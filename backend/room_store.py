"""Room (lobby) storage, logic and HTTP handlers.

Rooms share the gameState container with chains, in the room's own partition:
roomId = room code, id = "room", type = "room".
"""
import hashlib
import hmac
import logging
import re
import secrets
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable, Protocol
from uuid import uuid4

import azure.functions as func
from azure.core import MatchConditions
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from pydantic import ValidationError

from models import (
    MAX_PLAYERS, CreateSessionRequest, GameStatus, PlayerInfo,
    SessionCreated, SessionState, SessionStatus,
)
from pattern_store import (
    ConflictError, CosmosStoreError, NotFoundError, StaleChainError,
    cosmos_operation, get_chain_repository, json_error,
)

logger = logging.getLogger(__name__)

ROOM_DOC_ID = "room"
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I, O, 0, 1
CODE_LENGTH = 4
MAX_CODE_ATTEMPTS = 10
ROOM_CODE_PATTERN = re.compile(f"[{CODE_ALPHABET}]{{{CODE_LENGTH}}}")


class RoomRepository(Protocol):
    """save_room creates a room (no _etag) or replaces it only with the revision returned by a read."""
    def get_room(self, session_code: str) -> dict[str, Any] | None: ...
    def save_room(self, room: dict[str, Any]) -> None: ...


class InMemoryRoomRepository:
    """In-process storage for tests with the same conditional write contract."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._lock = Lock()
        self._revision = 0

    def get_room(self, session_code: str) -> dict[str, Any] | None:
        with self._lock:
            return deepcopy(self._store.get(session_code))

    def save_room(self, room: dict[str, Any]) -> None:
        code = room["roomId"]
        with self._lock:
            current = self._store.get(code, {})
            if current.get("_etag") != room.get("_etag"):
                if "_etag" not in room:
                    raise ConflictError("A room with this code already exists.")
                raise StaleChainError("The room changed since it was read.")
            self._revision += 1
            self._store[code] = {**deepcopy(room), "_etag": str(self._revision)}


class CosmosRoomRepository:
    """Cosmos DB repository using the /roomId partition key."""

    def __init__(self, container_client: Any) -> None:
        self._container = container_client

    def get_room(self, session_code: str) -> dict[str, Any] | None:
        with cosmos_operation():
            try:
                document = self._container.read_item(item=ROOM_DOC_ID, partition_key=session_code)
            except CosmosResourceNotFoundError as exc:
                if getattr(exc, "sub_status", None) not in (None, 0):
                    raise
                # A missing container can also surface as a 404, so confirm it exists.
                self._container.read()
                return None
        if document.get("type") != "room":
            return None
        return document

    def save_room(self, room: dict[str, Any]) -> None:
        if room.get("type") != "room" or room.get("id") != ROOM_DOC_ID or not room.get("roomId"):
            raise ValueError("Expected a room document with id 'room' and a roomId.")
        etag = room.get("_etag")
        body = {k: v for k, v in room.items() if k not in {"_etag", "_rid", "_self", "_attachments", "_ts"}}
        with cosmos_operation():
            if "_etag" not in room:
                try:
                    self._container.create_item(body=body, retry_write=0)
                except CosmosResourceExistsError:
                    raise ConflictError("A room with this code already exists.") from None
                return
            if not etag or etag == "*":
                raise CosmosStoreError("A conditional room replacement requires a valid ETag.")
            try:
                self._container.replace_item(
                    item=ROOM_DOC_ID, body=body, etag=etag,
                    match_condition=MatchConditions.IfNotModified, retry_write=0,
                )
            except CosmosAccessConditionFailedError:
                raise StaleChainError("The room changed since it was read.") from None


def get_room_repository() -> CosmosRoomRepository:
    """Reuse the chain repository's Cosmos container (same database and container)."""
    return CosmosRoomRepository(get_chain_repository()._container)


def generate_room_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_room(
    repo: RoomRepository,
    player_name: str,
    max_players: int = MAX_PLAYERS,
    code_factory: Callable[[], str] = generate_room_code,
) -> tuple[dict[str, Any], str]:
    """Create a lobby with the host as its first player. Returns (room, plaintext host token)."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).isoformat()
    host = {
        "player_id": uuid4().hex, "name": player_name, "token_hash": hash_token(token),
        "is_host": True, "is_ready": False, "joined_at": now,
    }
    for _ in range(MAX_CODE_ATTEMPTS):
        code = code_factory()
        room = {
            "id": ROOM_DOC_ID, "roomId": code, "type": "room", "session_code": code,
            "status": GameStatus.lobby.value, "state_version": 0,
            "current_round": 0, "total_rounds": 0, "max_players": max_players,
            "players": [host], "prompted_player_ids": [], "submitted_player_ids": [],
            "created_at": now,
        }
        try:
            repo.save_room(room)  # fails if this code already exists
        except ConflictError:
            continue
        return room, token
    raise CosmosStoreError("Could not allocate a unique room code.")


def normalize_room_code(code: str) -> str:
    return (code or "").strip().upper()


def load_room(repo: RoomRepository, session_code: str) -> dict[str, Any]:
    code = normalize_room_code(session_code)
    if not ROOM_CODE_PATTERN.fullmatch(code):
        raise NotFoundError(f"Room '{session_code}' not found.")
    room = repo.get_room(code)
    if room is None:
        raise NotFoundError(f"Room '{code}' not found.")
    return room


def find_player_by_token(room: dict[str, Any], token: str) -> dict[str, Any] | None:
    digest = hash_token(token)
    for player in room["players"]:
        if hmac.compare_digest(player["token_hash"], digest):
            return player
    return None


def room_is_full(room: dict[str, Any]) -> bool:
    return len(room["players"]) >= room["max_players"]


def ensure_room_has_capacity(room: dict[str, Any]) -> None:
    """For the join endpoint: raises ConflictError (409) if nobody else can join."""
    if room["status"] != GameStatus.lobby.value:
        raise ConflictError("Room is no longer accepting players.")
    if room_is_full(room):
        raise ConflictError("Room is full.")


def room_to_state(room: dict[str, Any]) -> SessionState:
    """Member-visible view. Built field by field so token hashes can never leak."""
    return SessionState(
        session_code=room["session_code"], status=room["status"],
        state_version=room["state_version"], max_players=room["max_players"],
        current_round=room["current_round"], total_rounds=room["total_rounds"],
        players=[
            PlayerInfo(player_id=p["player_id"], name=p["name"], is_host=p["is_host"], is_ready=p["is_ready"])
            for p in room["players"]
        ],
        prompted_player_ids=list(room["prompted_player_ids"]),
        submitted_player_ids=list(room["submitted_player_ids"]),
    )


def room_to_status(room: dict[str, Any]) -> SessionStatus:
    return SessionStatus(
        session_code=room["session_code"], status=room["status"],
        player_count=len(room["players"]), max_players=room["max_players"],
        is_full=room_is_full(room),
    )


def _json(model: Any, status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(model.model_dump_json(), status_code=status_code, mimetype="application/json")


def _storage_error(exc: CosmosStoreError) -> func.HttpResponse:
    logger.warning("Room storage failed: %s", exc)
    return json_error("storage_unavailable", "Game storage is unavailable.", 503)


def _validation_detail(exc: ValueError) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(part) for part in e['loc']) or 'body'}: {e['msg']}" for e in exc.errors()
        )
    return "Request body must be valid JSON."


def handle_create_room_http(req: func.HttpRequest, repo_factory: Callable[[], RoomRepository]) -> func.HttpResponse:
    """POST /api/sessions"""
    try:
        body = CreateSessionRequest.model_validate(req.get_json())
    except ValueError as exc:  # bad JSON or ValidationError
        return json_error("invalid_request", _validation_detail(exc), 422)
    try:
        room, token = create_room(repo_factory(), body.player_name, body.max_players)
    except CosmosStoreError as exc:
        return _storage_error(exc)
    host = room["players"][0]
    return _json(
        SessionCreated(session_code=room["session_code"], player_id=host["player_id"], player_token=token),
        201,
    )


def handle_get_room_http(
    req: func.HttpRequest, repo_factory: Callable[[], RoomRepository], session_code: str
) -> func.HttpResponse:
    """GET /api/sessions/{session_code} (members only)"""
    token = req.headers.get("X-Player-Token")
    if not token:
        return json_error("unauthorized", "Missing X-Player-Token header.", 401)
    try:
        room = load_room(repo_factory(), session_code)
    except NotFoundError as exc:
        return json_error("not_found", str(exc), 404)
    except CosmosStoreError as exc:
        return _storage_error(exc)
    if find_player_by_token(room, token) is None:
        return json_error("forbidden", "You are not a member of this room.", 403)
    return _json(room_to_state(room))


def handle_room_status_http(repo_factory: Callable[[], RoomRepository], session_code: str) -> func.HttpResponse:
    """GET /api/sessions/{session_code}/status (public, no roster)"""
    try:
        room = load_room(repo_factory(), session_code)
    except NotFoundError as exc:
        return json_error("not_found", str(exc), 404)
    except CosmosStoreError as exc:
        return _storage_error(exc)
    return _json(room_to_status(room))
