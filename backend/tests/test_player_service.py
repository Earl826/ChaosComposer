import pytest

from models import GameStatus, PlayerInfo, SessionState
from player_service import LobbyError, validate_join


@pytest.fixture
def room():
    return SessionState(
        session_code="K7QX",
        status=GameStatus.lobby,
        state_version=0,
        current_round=0,
        total_rounds=0,
        players=[],
        prompted_player_ids=[],
        submitted_player_ids=[],
    )


def test_valid_join(room):
    assert validate_join(room, "  Ben  ") == "Ben"


def test_duplicate_name(room):
    room.players.append(
        PlayerInfo(
            player_id="p1",
            name="Ben",
            is_host=True,
            is_ready=False,
        )
    )

    with pytest.raises(LobbyError) as exc:
        validate_join(room, "ben")

    assert exc.value.status_code == 409


def test_full_room(room):
    room.players = [
        PlayerInfo(
            player_id=f"p{i}",
            name=f"Player{i}",
            is_host=(i == 0),
            is_ready=False,
        )
        for i in range(6)
    ]

    with pytest.raises(LobbyError) as exc:
        validate_join(room, "Extra")

    assert exc.value.status_code == 409


def test_game_already_started(room):
    room.status = GameStatus.composing

    with pytest.raises(LobbyError) as exc:
        validate_join(room, "Ben")

    assert exc.value.status_code == 409


@pytest.mark.parametrize("name", ["", " ", "a" * 25, None])
def test_invalid_name(room, name):
    with pytest.raises(LobbyError) as exc:
        validate_join(room, name)

    assert exc.value.status_code == 422
