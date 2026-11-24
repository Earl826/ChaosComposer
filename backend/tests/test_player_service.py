import pytest
import hashlib

from models import GameStatus, PlayerInfo, SessionState
from player_service import LobbyError, validate_join
from player_service import LobbyError, validate_join, prepare_player


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


def test_prepare_player_creates_credentials(room):
    result = prepare_player(room, "  Ben  ")

    assert result.info.name == "Ben"
    assert result.info.is_ready is False
    assert result.info.is_host is False
    assert result.info.player_id

    assert result.credentials.player_id == result.info.player_id
    assert result.credentials.player_token

    expected_hash = hashlib.sha256(
        result.credentials.player_token.encode("utf-8")
    ).hexdigest()

    assert result.token_hash == expected_hash

    # Secret credentials must not appear in public player info.
    assert "player_token" not in result.info.model_dump()
    assert room.players == []


def test_prepared_players_have_unique_credentials(room):
    first = prepare_player(room, "Alice")
    second = prepare_player(room, "Bob")

    assert first.info.player_id != second.info.player_id

    assert (
        first.credentials.player_token
        != second.credentials.player_token
    )
