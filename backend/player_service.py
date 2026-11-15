import hashlib
import secrets
import uuid
import hmac
from typing import Protocol
from dataclasses import dataclass
from models import PlayerInfo, PlayerCredentials
from pydantic import ValidationError
from models import GameStatus, JoinSessionRequest, SessionState


class LobbyError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message)


def validate_join(room: SessionState, player_name: str) -> str:
    """Validate whether a player can join an existing room."""

    try:
        request = JoinSessionRequest.model_validate(
            {"player_name": player_name}
        )
    except ValidationError as exc:
        raise LobbyError(422, "Invalid player name") from exc

    name = request.player_name

    if room.status != GameStatus.lobby:
        raise LobbyError(409, "Game has already started")

    if any(p.name.casefold() == name.casefold()
           for p in room.players):
        raise LobbyError(409, "Player name already exists")

    if len(room.players) >= 6:
        raise LobbyError(409, "Room is full")

    return name


@dataclass(frozen=True)
class PreparedPlayer:
    info: PlayerInfo
    credentials: PlayerCredentials
    token_hash: str


def prepare_player(
    room: SessionState, player_name: str
) -> PreparedPlayer:
    """Prepare a validated player without saving them yet."""

    name = validate_join(room, player_name)

    player_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    info = PlayerInfo(
        player_id=player_id,
        name=name,
        is_host=False,
        is_ready=False,
    )

    credentials = PlayerCredentials(
        player_id=player_id,
        player_token=token,
    )

    return PreparedPlayer(
        info=info,
        credentials=credentials,
        token_hash=token_hash,
    )


@dataclass
class StoredRoom:
    """Room data, including private authentication information."""
    state: SessionState
    token_hashes: dict[str, str]
    etag: str


class VersionConflict(Exception):
    """The room changed before our update could be saved."""


class RoomRepository(Protocol):
    def get_room(self, session_code: str) -> StoredRoom | None:
        ...

    def save_if_unchanged(self, room: StoredRoom) -> None:
        ...

    def delete_if_unchanged(self, room: StoredRoom) -> None:
        ...


def join_player(
    repository: RoomRepository,
    session_code: str,
    player_name: str,
) -> PlayerCredentials:
    """Join a room with optimistic concurrency and bounded retries."""

    for _ in range(8):
        stored = repository.get_room(session_code)

        if stored is None:
            raise LobbyError(404, "Room not found")

        prepared = prepare_player(stored.state, player_name)

        stored.state.players.append(prepared.info)
        stored.token_hashes[
            prepared.info.player_id
        ] = prepared.token_hash

        stored.state.state_version += 1

        try:
            repository.save_if_unchanged(stored)
        except VersionConflict:
            continue
        return prepared.credentials

    raise LobbyError(409, "Room changed during joining")


def authenticate_player(
    stored: StoredRoom,
    player_token: str,
) -> PlayerInfo:
    """Identify a player using their secret room token."""

    if not isinstance(player_token, str) or not player_token:
        raise LobbyError(401, "Missing or invalid player token")

    provided_hash = hashlib.sha256(
        player_token.encode("utf-8")
    ).hexdigest()

    for player in stored.state.players:
        saved_hash = stored.token_hashes.get(player.player_id)

        if saved_hash and hmac.compare_digest(
            saved_hash, provided_hash
        ):
            return player

    raise LobbyError(401, "Missing or invalid player token")


def set_player_ready(
    repository: RoomRepository,
    session_code: str,
    player_token: str,
    is_ready: bool,
) -> SessionState:
    """Set a player's readiness with concurrency protection."""

    if type(is_ready) is not bool:
        raise LobbyError(422, "is_ready must be a boolean")

    for _ in range(8):
        stored = repository.get_room(session_code)

        if stored is None:
            raise LobbyError(404, "Room not found")

        player = authenticate_player(stored, player_token)

        if stored.state.status != GameStatus.lobby:
            raise LobbyError(409, "Readiness can only change in lobby")

        if player.is_ready == is_ready:
            return stored.state

        player.is_ready = is_ready
        stored.state.state_version += 1

        try:
            repository.save_if_unchanged(stored)
            return stored.state
        except VersionConflict:
            continue

    raise LobbyError(409, "Room changed during readiness update")


def leave_player(
    repository: RoomRepository,
    session_code: str,
    player_token: str,
) -> SessionState:
    """Remove an authenticated player from a lobby."""

    for _ in range(8):
        stored = repository.get_room(session_code)

        if stored is None:
            raise LobbyError(404, "Room not found")

        player = authenticate_player(stored, player_token)

        if stored.state.status != GameStatus.lobby:
            raise LobbyError(409, "Cannot leave after game starts")

        # removing only the authenticated player
        stored.state.players = [
            p for p in stored.state.players
            if p.player_id != player.player_id
        ]

        # Revoke authentication token
        stored.token_hashes.pop(player.player_id, None)

        # if the host leaves, transfer ownership to the earliest remaining player
        if player.is_host and stored.state.players:
            stored.state.players[0].is_host = True

        stored.state.state_version += 1

        try:
            if not stored.state.players:
                repository.delete_if_unchanged(stored)
            else:
                repository.save_if_unchanged(stored)

            return stored.state

        except VersionConflict:
            # if another request changed the room reload and revalidate before retrying.
            continue

    raise LobbyError(409, "Room changed during leave")
