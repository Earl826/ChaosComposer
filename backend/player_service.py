
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