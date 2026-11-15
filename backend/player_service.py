import hashlib
import secrets
import uuid
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

        # Update our local copy, not the stored document.
        stored.state.players.append(prepared.info)
        stored.token_hashes[
            prepared.info.player_id
        ] = prepared.token_hash

        stored.state.state_version += 1

        try:
            repository.save_if_unchanged(stored)
        except VersionConflict:
            # Another request updated the room.
            # Read the latest state and revalidate.
            continue

        # Credentials are returned only after successful persistence.
        return prepared.credentials

    raise LobbyError(409, "Room changed during joining")

