from typing import Any, Protocol
from models import MusicalPattern

ALLOWED_INSTRUMENTS = {"kick", "snare", "hihat", "clap", "tom", "bass", "synth", "piano"}

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
        items = list(
            self._container.query_items(
                query=query,
                parameters=[{"name": "@session_code", "value": session_code}],
                partition_key=session_code,
            )
        )
        return items


