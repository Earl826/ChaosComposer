import json
import os
from contextlib import contextmanager
from copy import deepcopy
from threading import Lock
from urllib.parse import urlsplit
from uuid import UUID

from azure.core import MatchConditions
import azure.functions as func
from azure.core.exceptions import AzureError, ClientAuthenticationError, ServiceRequestError, ServiceResponseError
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosClientTimeoutError,
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from azure.identity import AzureCliCredential, ManagedIdentityCredential
from pydantic import ValidationError
from typing import Any, Protocol
from models import MusicalPattern, PatternAssignment, PromptAssignment, SubmitPatternRequest, StageResult, ChainResult, RevealResponse, ErrorResponse, AssignmentResponse

ALLOWED_INSTRUMENTS = {"kick", "snare", "hihat", "clap", "tom", "bass", "synth", "piano"}

class ConflictError(Exception):
    """Raised when a submission is a duplicate or is out of order and conflicts (HTTP 409)."""

class StaleChainError(ConflictError):
    """The chain changed after it was read."""


class NotFoundError(Exception):
    """Raised when a requested chain does not exist (HTTP 404)."""


class CosmosStoreError(Exception):
    """Cosmos failed to complete a storage operation."""


class CosmosConfigurationError(CosmosStoreError):
    """Cosmos settings are missing or invalid."""


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
    """Save creates a chain or replaces it only with the revision returned by a read."""
    def get_chain(self, session_code: str, chain_id: str) -> dict[str, Any] | None: ...
    def save_chain(self, chain_doc: dict[str, Any]) -> None: ...
    def list_chains_for_session(self, session_code: str) -> list[dict[str, Any]]: ...

class InMemoryChainRepository:
    """In-process storage for tests with the same conditional write contract."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = Lock()
        self._revision = 0

    def get_chain(self, session_code: str, chain_id: str) -> dict[str, Any] | None:
        with self._lock:
            return deepcopy(self._store.get((session_code, chain_id)))

    def save_chain(self, chain_doc: dict[str, Any]) -> None:
        key = (chain_doc["session_code"], chain_doc["id"])
        with self._lock:
            current = self._store.get(key, {})
            if current.get("_etag") != chain_doc.get("_etag"):
                if "_etag" not in chain_doc:
                    raise ConflictError("A chain with this ID already exists in the room.")
                raise StaleChainError("The chain changed during submission.")
            self._revision += 1
            self._store[key] = {**deepcopy(chain_doc), "_etag": str(self._revision)}

    def list_chains_for_session(self, session_code: str) -> list[dict[str, Any]]:
        with self._lock:
            chains = [deepcopy(doc) for (room, _), doc in self._store.items() if room == session_code]
        return sorted(chains, key=lambda d: d["id"])



class CosmosChainRepository:
    """Cosmos DB repository using the /roomId partition key."""

    def __init__(self, container_client: Any) -> None:
        self._container = container_client

    def check_ready(self) -> None:
        """Verify authenticated access to the expected Cosmos container metadata."""
        with cosmos_operation():
            properties = self._container.read()
        if properties.get("partitionKey", {}).get("paths") != ["/roomId"]:
            raise CosmosConfigurationError("The Cosmos container must use /roomId as its partition key.")

    def get_chain(
        self, session_code: str, chain_id: str
    ) -> dict[str, Any] | None:
        with cosmos_operation():
            try:
                document = self._container.read_item(item=chain_id, partition_key=session_code)
            except CosmosResourceNotFoundError as exc:
                if getattr(exc, "sub_status", None) not in (None, 0):
                    raise
                # A missing container can also surface as a 404 during a point read.
                self._container.read()
                return None
        if document.get("type") != "chain":
            return None
        if not document.get("_etag") or document["_etag"] == "*":
            raise CosmosStoreError("Cosmos returned a chain without a valid ETag.")
        return document

    def save_chain(self, chain_doc: dict[str, Any]) -> None:
        if (
            chain_doc.get("type") != "chain"
            or not chain_doc.get("session_code")
            or chain_doc.get("roomId") != chain_doc["session_code"]
        ):
            raise ValueError("Expected a chain document with roomId matching session_code.")

        etag = chain_doc.get("_etag")
        body = {
            name: value for name, value in chain_doc.items()
            if name not in {"_etag", "_rid", "_self", "_attachments", "_ts"}
        }
        with cosmos_operation():
            if "_etag" not in chain_doc:
                try:
                    self._container.create_item(body=body, retry_write=0)
                except CosmosResourceExistsError:
                    raise ConflictError("A chain with this ID already exists in the room.") from None
                return

            if not etag or etag == "*":
                raise CosmosStoreError("A conditional chain replacement requires a valid ETag.")
            try:
                self._container.replace_item(
                    item=body["id"],
                    body=body,
                    etag=etag,
                    match_condition=MatchConditions.IfNotModified,
                    retry_write=0,
                )
            except CosmosAccessConditionFailedError:
                raise StaleChainError("The chain changed during submission.") from None

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
    incoming_pattern = request.pattern.model_dump()
    new_version = {
        "version_id": f"{request.chain_id}_v{request.expected_round}",
        "submission_id": request.submission_id,
        "round": request.expected_round,
        "player_id": player_id,
        "player_name": player_name,
        "pattern": incoming_pattern,
    }
    for attempt in range(3):
        chain_doc = repo.get_chain(session_code, request.chain_id)
        if chain_doc is None:
            raise NotFoundError(f"Chain '{request.chain_id}' not found in session '{session_code}'.")
        versions: list[dict[str, Any]] = chain_doc["versions"]
        for existing in versions:
            if existing["submission_id"] == request.submission_id:
                if (
                    existing["player_id"] == player_id
                    and existing["round"] == request.expected_round
                    and existing["pattern"] == incoming_pattern
                ):
                    return existing
                raise ConflictError("Conflicting reuse of submission_id with different data.")

        expected_next_round = len(versions) + 1
        if request.expected_round < expected_next_round:
            raise ConflictError(f"Round {request.expected_round} already has a submission for chain '{request.chain_id}'.")
        if request.expected_round > expected_next_round:
            raise ConflictError(f"Expected round {expected_next_round}, got {request.expected_round}.")

        chain_doc["versions"] = [*versions, new_version]
        try:
            repo.save_chain(chain_doc)
        except StaleChainError:
            if attempt == 2:
                raise
        else:
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

def required_cosmos_setting(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise CosmosConfigurationError(f"Missing required app setting {name}.")
    return value


def _create_cosmos_repository() -> CosmosChainRepository:
    endpoint = required_cosmos_setting("COSMOS_ENDPOINT")
    database_name = required_cosmos_setting("COSMOS_DATABASE_NAME")
    container_name = required_cosmos_setting("COSMOS_CHAINS_CONTAINER")
    auth_mode = required_cosmos_setting("COSMOS_AUTH_MODE")
    try:
        url = urlsplit(endpoint)
        valid_endpoint = (
            url.scheme == "https"
            and url.hostname is not None
            and url.username is None
            and url.port is None
            and url.path in ("", "/")
            and not (url.query or url.fragment)
            and not any(character.isspace() for character in endpoint)
        )
    except ValueError:
        valid_endpoint = False
    if not valid_endpoint:
        raise CosmosConfigurationError("COSMOS_ENDPOINT must be a plain HTTPS account URL.")

    if auth_mode == "managed_identity":
        client_id = required_cosmos_setting("AZURE_CLIENT_ID")
        try:
            UUID(client_id)
        except ValueError:
            raise CosmosConfigurationError("AZURE_CLIENT_ID must be the managed identity's client ID.") from None
    elif auth_mode != "azure_cli" or os.environ.get("WEBSITE_SITE_NAME"):
        raise CosmosConfigurationError(
            "Set COSMOS_AUTH_MODE to managed_identity on Azure or azure_cli for local development."
        )

    with cosmos_operation():
        if auth_mode == "managed_identity":
            credential = ManagedIdentityCredential(client_id=client_id)
        else:
            credential = AzureCliCredential()
        client = CosmosClient(endpoint, credential=credential)
        container = client.get_database_client(database_name).get_container_client(container_name)
        return CosmosChainRepository(container)


_cosmos_repository: CosmosChainRepository | None = None
_cosmos_repository_lock = Lock()


def get_chain_repository() -> CosmosChainRepository:
    """Create and reuse one Cosmos client per worker after successful initialization."""
    global _cosmos_repository
    with _cosmos_repository_lock:
        if _cosmos_repository is None:
            _cosmos_repository = _create_cosmos_repository()
        return _cosmos_repository

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
