import hashlib
import secrets
import uuid
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
