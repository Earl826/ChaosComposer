"""Room creation and status.

A room is stored as {"id": "room", "roomId": code, "type": "room",
"state": SessionState, "token_hashes": {player_id: abc123}}
"""
import hashlib
import logging
import re
import secrets
from typing import Callable, Protocol
from uuid import uuid4

import azure.functions as func
from pydantic import ValidationError

from models import (
    MAX_PLAYERS, CreateSessionRequest, GameStatus, PlayerInfo,
    SessionCreated, SessionState, SessionStatus,
)
from pattern_store import ConflictError, CosmosStoreError, json_error
from player_service import StoredRoom

logger = logging.getLogger(__name__)

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I, O, 0, 1
CODE_LENGTH = 4
MAX_CODE_ATTEMPTS = 10
ROOM_CODE_PATTERN = re.compile(f"[{CODE_ALPHABET}]{{{CODE_LENGTH}}}")


class RoomCreator(Protocol):
    """The slice of the room repository that creation and status need."""
    def get_room(self, session_code: str) -> StoredRoom | None: ...
    def create_if_absent(self, room: StoredRoom) -> None: ...


def generate_room_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_room(
    repo: RoomCreator,
    player_name: str,
    max_players: int = MAX_PLAYERS,
    code_factory: Callable[[], str] = generate_room_code,
) -> tuple[StoredRoom, str]:
    """Create a lobby with the host as its first player. Returns (room, plaintext host token)."""
    token = secrets.token_urlsafe(32)
    host = PlayerInfo(player_id=uuid4().hex, name=player_name, is_host=True, is_ready=False)
    for _ in range(MAX_CODE_ATTEMPTS):
        code = code_factory()
        room = StoredRoom(
            state=SessionState(
                session_code=code, status=GameStatus.lobby, state_version=0,
                max_players=max_players, current_round=0, total_rounds=0,
                players=[host], prompted_player_ids=[], submitted_player_ids=[],
            ),
            token_hashes={host.player_id: hash_token(token)},
            etag="",
        )
        try:
            repo.create_if_absent(room)
        except ConflictError:
            continue
        return room, token
    raise CosmosStoreError("Could not allocate a unique room code.")


def normalize_room_code(code: str) -> str:
    return (code or "").strip().upper()


def room_is_full(state: SessionState) -> bool:
    return len(state.players) >= state.max_players


def state_to_status(state: SessionState) -> SessionStatus:
    return SessionStatus(
        session_code=state.session_code, status=state.status,
        player_count=len(state.players), max_players=state.max_players,
        is_full=room_is_full(state),
    )


def _json(model, status_code: int = 200) -> func.HttpResponse:
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


def handle_create_room_http(req: func.HttpRequest, repo_factory: Callable[[], RoomCreator]) -> func.HttpResponse:
    """POST /api/sessions"""
    try:
        body = CreateSessionRequest.model_validate(req.get_json())
    except ValueError as exc:  # bad JSON or ValidationError
        return json_error("invalid_request", _validation_detail(exc), 422)
    try:
        room, token = create_room(repo_factory(), body.player_name, body.max_players)
    except CosmosStoreError as exc:
        return _storage_error(exc)
    host = room.state.players[0]
    return _json(
        SessionCreated(session_code=room.state.session_code, player_id=host.player_id, player_token=token),
        201,
    )


def handle_room_status_http(repo_factory: Callable[[], RoomCreator], session_code: str) -> func.HttpResponse:
    """GET /api/sessions/{session_code}/status (public, no roster)"""
    code = normalize_room_code(session_code)
    if not ROOM_CODE_PATTERN.fullmatch(code):
        return json_error("not_found", f"Room '{session_code}' not found.", 404)
    try:
        room = repo_factory().get_room(code)
    except CosmosStoreError as exc:
        return _storage_error(exc)
    if room is None:
        return json_error("not_found", f"Room '{code}' not found.", 404)
    return _json(state_to_status(room.state))