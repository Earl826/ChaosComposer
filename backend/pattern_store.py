import json
import os
from contextlib import contextmanager
import azure.functions as func
from azure.core.exceptions import AzureError, ClientAuthenticationError, ServiceRequestError, ServiceResponseError
from azure.cosmos.exceptions import CosmosClientTimeoutError, CosmosHttpResponseError, CosmosResourceNotFoundError
from pydantic import ValidationError
from typing import Any, Protocol
from models import MusicalPattern, PatternAssignment, PromptAssignment, SubmitPatternRequest, StageResult, ChainResult, RevealResponse, ErrorResponse, AssignmentResponse

ALLOWED_INSTRUMENTS = {"kick", "snare", "hihat", "clap", "tom", "bass", "synth", "piano"}

class ConflictError(Exception):
    """Raised when a submission is a duplicate or is out of order and conflicts (HTTP 409)."""

class NotFoundError(Exception):
    """Raised when a requested chain does not exist (HTTP 404)."""


class CosmosStoreError(Exception):
    """Cosmos failed to complete a storage operation."""


class CosmosAccessError(CosmosStoreError):
    """The configured identity could not access Cosmos DB."""


class CosmosUnavailableError(CosmosStoreError):
    """Cosmos DB could not complete the request due to a service or network failure."""


@contextmanager
def cosmos_operation():
    """Translate SDK failures into operator messages that are safe to log."""
    try:
        yield
    except ClientAuthenticationError:
        raise CosmosAccessError("Cosmos authentication failed. Check the configured Entra credential.") from None
    except (ServiceRequestError, ServiceResponseError, CosmosClientTimeoutError):
        raise CosmosUnavailableError("Could not reach Cosmos DB. Check connectivity and retry.") from None
    except CosmosHttpResponseError as exc:
        if exc.status_code in (401, 403):
            raise CosmosAccessError(
                "Cosmos access denied. Check the identity's Cosmos DB for NoSQL data-plane role and network access."
            ) from None
        if exc.status_code in (408, 429) or exc.status_code >= 500:
            raise CosmosUnavailableError(f"Cosmos DB is temporarily unavailable (HTTP {exc.status_code}).") from None
        if exc.status_code == 404:
            raise CosmosStoreError("Cosmos resource lookup failed. Check the configured database and container.") from None
        raise CosmosStoreError(f"Cosmos DB rejected the operation (HTTP {exc.status_code}).") from None
    except AzureError:
        raise CosmosStoreError("The Azure SDK could not complete the Cosmos operation.") from None


def validate_musical_pattern(pattern: MusicalPattern) -> None:
    """Enforces unique instrument tracks and allowed instrument IDs."""
    seen_instruments: set[str] = set()
    for track in pattern.tracks:
        instrument_lower = track.instrument.lower().strip()
        if instrument_lower not in ALLOWED_INSTRUMENTS:
            raise ValueError(f"Unsupported instrument '{track.instrument}'. Allowed: {sorted(ALLOWED_INSTRUMENTS)}")
        if instrument_lower in seen_instruments:
            raise ValueError(f"Duplicate instrument track '{track.instrument}'. Instrument IDs must be unique.")
        seen_instruments.add(instrument_lower)

class ChainRepository(Protocol):
    """Interface so the code works locally in Phase 1 and with Cosmos DB in Phase 2."""
    def get_chain(self, session_code: str, chain_id: str) -> dict[str, Any] | None: ...
    def save_chain(self, chain_doc: dict[str, Any]) -> None: ...
    def list_chains_for_session(self, session_code: str) -> list[dict[str, Any]]: ...

class InMemoryChainRepository:
    """Local storage for testing before Azure is wired up."""
    def __init__(self) -> None:
        self._store: dict[tuple[str, str], dict[str, Any]] = {}

    def get_chain(self, session_code: str, chain_id: str) -> dict[str, Any] | None:
        return self._store.get((session_code, chain_id))

    def save_chain(self, chain_doc: dict[str, Any]) -> None:
        key = (chain_doc["session_code"], chain_doc["id"])
        self._store[key] = chain_doc

    def list_chains_for_session(self, session_code: str) -> list[dict[str, Any]]:
        chains = [
            doc for (s_code, _), doc in self._store.items()
            if s_code == session_code
        ]
        return sorted(chains, key=lambda d: d["id"])



class CosmosChainRepository:
    """Cosmos DB repository using the /roomId partition key."""

    def __init__(self, container_client: Any) -> None:
        self._container = container_client

    def get_chain(
        self, session_code: str, chain_id: str
    ) -> dict[str, Any] | None:
        with cosmos_operation():
            try:
                document = self._container.read_item(item=chain_id, partition_key=session_code)
            except CosmosResourceNotFoundError as exc:
                if exc.sub_status not in (None, 0):
                    raise
                # A missing container can also surface as a 404 during a point read.
                self._container.read()
                return None
        return document if document.get("type") == "chain" else None

    def save_chain(self, chain_doc: dict[str, Any]) -> None:
        if (
            chain_doc.get("type") != "chain"
            or not chain_doc.get("session_code")
            or chain_doc.get("roomId") != chain_doc["session_code"]
        ):
            raise ValueError("Expected a chain document with roomId matching session_code.")

        with cosmos_operation():
            self._container.upsert_item(body=chain_doc)

    def list_chains_for_session(
        self, session_code: str
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT * FROM c "
            "WHERE c.roomId = @roomId "
            "AND c.type = 'chain' "
            "ORDER BY c.id"
        )

        with cosmos_operation():
            return list(self._container.query_items(
                query=query,
                parameters=[{"name": "@roomId", "value": session_code}],
                partition_key=session_code,
            ))


def create_chain_document(repo: ChainRepository, session_code: str, chain_id: str, original_prompt: str) -> dict[str, Any]:
    """Creates a new musical chain matching sample_chain_doc.json."""
    chain_doc = {
        "id": chain_id,
        "roomId": session_code,
        "type": "chain",
        "session_code": session_code,
        "original_prompt": original_prompt,
        "versions": [],
    }
    repo.save_chain(chain_doc)
    return chain_doc

def record_pattern_submission(repo: ChainRepository, session_code: str, player_id: str, player_name: str, request: SubmitPatternRequest) -> dict[str, Any]:
    """Checks and adds a new pattern version without overwriting previous versions."""
    validate_musical_pattern(request.pattern)
    chain_doc = repo.get_chain(session_code, request.chain_id)
    if chain_doc is None:
        raise NotFoundError(f"Chain '{request.chain_id}' not found in session '{session_code}'.")
    versions: list[dict[str, Any]] = chain_doc["versions"]
    incoming_pattern_dict = request.pattern.model_dump()
    for existing in versions:
        if existing["submission_id"] == request.submission_id:
            if (existing["player_id"] == player_id and existing["round"] == request.expected_round and existing["pattern"] == incoming_pattern_dict):
                return existing
            raise ConflictError("Conflicting reuse of submission_id with different data.")
        if existing["round"] == request.expected_round:
            raise ConflictError(f"Round {request.expected_round} already has a submission for chain '{request.chain_id}'.")
    expected_next_round = len(versions) + 1
    if request.expected_round != expected_next_round:
        raise ConflictError(f"Expected round {expected_next_round}, got {request.expected_round}.")
    new_version = {
        "version_id": f"{request.chain_id}_v{request.expected_round}",
        "submission_id": request.submission_id,
        "round": request.expected_round,
        "player_id": player_id,
        "player_name": player_name,
        "pattern": incoming_pattern_dict,
    }
    versions.append(new_version)
    repo.save_chain(chain_doc)
    return new_version

def get_chain_assignment_for_round(repo: ChainRepository, session_code: str, chain_id: str, current_round: int) -> PromptAssignment | PatternAssignment:
    """Returns the prompt in Round 1, or ONLY the previous round's pattern in Rounds 2 and after."""
    chain_doc = repo.get_chain(session_code, chain_id)
    if chain_doc is None:
        raise NotFoundError(f"Chain '{chain_id}' not found in session '{session_code}'.")
    if current_round == 1:
        return PromptAssignment(chain_id=chain_id, round=1, prompt=chain_doc["original_prompt"])
    versions = chain_doc["versions"]
    if len(versions) < current_round - 1:
        raise ConflictError(f"Round {current_round - 1} pattern has not been submitted yet.")
    previous_version = versions[current_round - 2]
    return PatternAssignment(chain_id=chain_id, round=current_round, previous_version_id=previous_version["version_id"], pattern=MusicalPattern.model_validate(previous_version["pattern"]))

def get_session_reveal(repo: ChainRepository, session_code: str) -> RevealResponse:
    """Retrieves all chains and their full version history in round order for the final reveal."""
    chain_docs = repo.list_chains_for_session(session_code)
    if not chain_docs:
        raise NotFoundError(f"No chains found for session '{session_code}'.")
    chain_results: list[ChainResult] = []
    for doc in chain_docs:
        versions = doc["versions"]
        if not versions:
            raise ConflictError(f"Chain '{doc['id']}' has no saved versions to reveal.")
        stages = [
            StageResult(version_id=v["version_id"], round=v["round"], player_id=v["player_id"], player_name=v["player_name"], pattern=MusicalPattern.model_validate(v["pattern"]))
            for v in sorted(versions, key=lambda x: x["round"])
        ]
        chain_results.append(ChainResult(chain_id=doc["id"], original_prompt=doc["original_prompt"], stages=stages, final_version_id=stages[-1].version_id))
    return RevealResponse(session_code=session_code, chains=chain_results)

_DEFAULT_MEMORY_REPO = InMemoryChainRepository()

def get_chain_repository() -> ChainRepository:
    """Returns CosmosChainRepository if Azure is setup, otherwise InMemoryChainRepository."""
    conn_str = os.environ.get("COSMOS_CONNECTION_STRING")
    db_name = os.environ.get("COSMOS_DATABASE_NAME", "musicgame")
    container_name = os.environ.get("COSMOS_CHAINS_CONTAINER", "chains")
    if conn_str:
        from azure.cosmos import CosmosClient
        client = CosmosClient.from_connection_string(conn_str)
        database = client.get_database_client(db_name)
        container = database.get_container_client(container_name)
        return CosmosChainRepository(container)
    return _DEFAULT_MEMORY_REPO

def json_error(code: str, detail: str, status_code: int) -> func.HttpResponse:
    """Gets an ErrorResponse to match models.py and function_app.py."""
    body = ErrorResponse(code=code, detail=detail).model_dump_json()
    return func.HttpResponse(body, status_code=status_code, mimetype="application/json")

def handle_submit_pattern_http(req: func.HttpRequest, repo: ChainRepository, session_code: str, player_id: str, player_name: str) -> func.HttpResponse:
    """HTTP wrapper for POST /api/sessions/{session_code}/submissions."""
    try:
        raw_body = req.get_json()
        submit_req = SubmitPatternRequest.model_validate(raw_body)
        saved_version = record_pattern_submission(repo=repo, session_code=session_code, player_id=player_id, player_name=player_name, request=submit_req)
        return func.HttpResponse(json.dumps(saved_version), status_code=200, mimetype="application/json")
    except (ValueError, ValidationError) as exc:
        return json_error("invalid_pattern", str(exc), 422)
    except NotFoundError as exc:
        return json_error("not_found", str(exc), 404)
    except ConflictError as exc:
        return json_error("conflict", str(exc), 409)
    except CosmosStoreError:
        return json_error("storage_unavailable", "Game storage is unavailable.", 503)

def handle_get_assignment_http(repo: ChainRepository, session_code: str, chain_id: str, current_round: int) -> func.HttpResponse:
    """HTTP wrapper for GET /api/sessions/{session_code}/assignment."""
    try:
        assignment = get_chain_assignment_for_round(repo=repo, session_code=session_code, chain_id=chain_id, current_round=current_round)
        response_model = AssignmentResponse(assignment=assignment)
        return func.HttpResponse(response_model.model_dump_json(), status_code=200, mimetype="application/json")
    except NotFoundError as exc:
        return json_error("not_found", str(exc), 404)
    except ConflictError as exc:
        return json_error("conflict", str(exc), 409)
    except CosmosStoreError:
        return json_error("storage_unavailable", "Game storage is unavailable.", 503)

def handle_reveal_http(repo: ChainRepository, session_code: str) -> func.HttpResponse:
    """HTTP wrapper for GET /api/sessions/{session_code}/reveal."""
    try:
        reveal_data = get_session_reveal(repo=repo, session_code=session_code)
        return func.HttpResponse(reveal_data.model_dump_json(), status_code=200, mimetype="application/json")
    except NotFoundError as exc:
        return json_error("not_found", str(exc), 404)
    except ConflictError as exc:
        return json_error("conflict", str(exc), 409)
    except CosmosStoreError:
        return json_error("storage_unavailable", "Game storage is unavailable.", 503)
