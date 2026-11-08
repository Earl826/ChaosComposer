from typing import Any, Protocol
from models import MusicalPattern, PatternAssignment, PromptAssignment, SubmitPatternRequest, StageResult, ChainResult, RevealResponse

ALLOWED_INSTRUMENTS = {"kick", "snare", "hihat", "clap", "tom", "bass", "synth", "piano"}

class ConflictError(Exception):
    """Raised when a submission is a duplicate or is out of order and conflicts (HTTP 409)."""

class NotFoundError(Exception):
    """Raised when a requested chain does not exist (HTTP 404)."""

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
    """Drop-in Azure Cosmos DB repository (partition key: /session_code)."""
    def __init__(self, container_client: Any) -> None:
        self._container = container_client

    def get_chain(self, session_code: str, chain_id: str) -> dict[str, Any] | None:
        try:
            return self._container.read_item(item=chain_id, partition_key=session_code)
        except Exception:
            return None

    def save_chain(self, chain_doc: dict[str, Any]) -> None:
        self._container.upsert_item(body=chain_doc)

    def list_chains_for_session(self, session_code: str) -> list[dict[str, Any]]:
        query = "SELECT * FROM c WHERE c.session_code = @session_code ORDER BY c.id"
        items = list(self._container.query_items(query=query, parameters=[{"name": "@session_code", "value": session_code}], partition_key=session_code,))
        return items

def create_chain_document(repo: ChainRepository, session_code: str, chain_id: str, original_prompt: str) -> dict[str, Any]:
    """Creates a new musical chain matching sample_chain_doc.json."""
    chain_doc = {
        "id": chain_id,
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
