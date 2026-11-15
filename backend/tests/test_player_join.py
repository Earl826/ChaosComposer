from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Lock
from player_service import set_player_ready
from player_service import leave_player
import hashlib

import pytest

from models import GameStatus, PlayerInfo, SessionState
from player_service import (
    StoredRoom,
    VersionConflict,
    LobbyError,
    join_player,
)


class FakeRoomRepository:
    """Thread-safe fake supporting conditional room updates."""

    def __init__(self, state=None):
        self.lock = Lock()
        self.fail_next = False
        self.room = (
            StoredRoom(
                state=deepcopy(state),
                token_hashes={},
                etag="1",
            )
            if state is not None else None
        )

    def get_room(self, session_code):
        with self.lock:
            if self.room is None:
                return None
            if self.room.state.session_code != session_code:
                return None
            return deepcopy(self.room)

    def save_if_unchanged(self, room):
        with self.lock:
            if self.fail_next:
                self.fail_next = False
                raise VersionConflict()

            if self.room is None or self.room.etag != room.etag:
                raise VersionConflict()

            saved = deepcopy(room)
            saved.etag = str(int(self.room.etag) + 1)
            self.room = saved

    
    def delete_if_unchanged(self, room):
        with self.lock:
            if self.fail_next:
                self.fail_next = False
                raise VersionConflict()

            if self.room is None or self.room.etag != room.etag:
                raise VersionConflict()

            self.room = None



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


def test_join_persists_player(room):
    repo = FakeRoomRepository(room)

    credentials = join_player(repo, "K7QX", "Ben")
    saved = repo.get_room("K7QX")

    assert len(saved.state.players) == 1
    assert saved.state.players[0].name == "Ben"
    assert saved.state.state_version == 1

    expected_hash = hashlib.sha256(
        credentials.player_token.encode()
    ).hexdigest()

    assert saved.token_hashes[credentials.player_id] == expected_hash

    # Public room state must not expose authentication secrets.
    assert "player_token" not in saved.state.model_dump_json()


def test_join_nonexistent_room():
    repo = FakeRoomRepository()

    with pytest.raises(LobbyError) as exc:
        join_player(repo, "MISSING", "Ben")

    assert exc.value.status_code == 404


def test_simultaneous_joins_last_slot(room):
    room.players = [
        PlayerInfo(
            player_id=f"p{i}",
            name=f"Player{i}",
            is_host=(i == 0),
            is_ready=False,
        )
        for i in range(5)
    ]

    repo = FakeRoomRepository(room)

    def attempt(name):
        try:
            join_player(repo, "K7QX", name)
            return 201
        except LobbyError as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ["Alice", "Bob"]))

    assert sorted(results) == [201, 409]
    assert len(repo.get_room("K7QX").state.players) == 6


def test_retries_after_version_conflict(room):
    repo = FakeRoomRepository(room)
    repo.fail_next = True

    join_player(repo, "K7QX", "Ben")

    saved = repo.get_room("K7QX")
    assert len(saved.state.players) == 1
    assert saved.state.players[0].name == "Ben"


def test_player_can_become_ready(room):
    repo = FakeRoomRepository(room)
    credentials = join_player(repo, "K7QX", "Ben")

    state = set_player_ready(
        repo, "K7QX", credentials.player_token, True
    )

    assert state.players[0].is_ready is True
    assert state.state_version == 2


def test_player_can_become_unready(room):
    repo = FakeRoomRepository(room)
    credentials = join_player(repo, "K7QX", "Ben")

    set_player_ready(
        repo, "K7QX", credentials.player_token, True
    )
    state = set_player_ready(
        repo, "K7QX", credentials.player_token, False
    )

    assert state.players[0].is_ready is False


def test_repeated_ready_request_is_idempotent(room):
    repo = FakeRoomRepository(room)
    credentials = join_player(repo, "K7QX", "Ben")

    first = set_player_ready(
        repo, "K7QX", credentials.player_token, True
    )
    original_version = first.state_version

    second = set_player_ready(
        repo, "K7QX", credentials.player_token, True
    )

    assert second.state_version == original_version


def test_invalid_token_cannot_change_readiness(room):
    repo = FakeRoomRepository(room)
    join_player(repo, "K7QX", "Ben")

    with pytest.raises(LobbyError) as exc:
        set_player_ready(repo, "K7QX", "fake-token", True)

    assert exc.value.status_code == 401
    assert repo.get_room("K7QX").state.players[0].is_ready is False


def test_readiness_rejected_after_game_starts(room):
    repo = FakeRoomRepository(room)
    credentials = join_player(repo, "K7QX", "Ben")

    repo.room.state.status = GameStatus.composing

    with pytest.raises(LobbyError) as exc:
        set_player_ready(
            repo, "K7QX", credentials.player_token, True
        )

    assert exc.value.status_code == 409


def test_ready_retries_after_version_conflict(room):
    repo = FakeRoomRepository(room)
    credentials = join_player(repo, "K7QX", "Ben")

    repo.fail_next = True

    state = set_player_ready(
        repo, "K7QX", credentials.player_token, True
    )

    assert state.players[0].is_ready is True
    assert repo.get_room("K7QX").state.players[0].is_ready is True


def test_non_host_can_leave(room):
    repo = FakeRoomRepository(room)

    host = join_player(repo, "K7QX", "Ana")
    guest = join_player(repo, "K7QX", "Ben")

    repo.room.state.players[0].is_host = True

    state = leave_player(
        repo, "K7QX", guest.player_token
    )

    assert len(state.players) == 1
    assert state.players[0].player_id == host.player_id
    assert state.players[0].is_host is True


def test_host_leaving_transfers_ownership(room):
    repo = FakeRoomRepository(room)

    host = join_player(repo, "K7QX", "Ana")
    second = join_player(repo, "K7QX", "Ben")
    join_player(repo, "K7QX", "Charlie")

    repo.room.state.players[0].is_host = True

    state = leave_player(
        repo, "K7QX", host.player_token
    )

    assert len(state.players) == 2
    assert state.players[0].player_id == second.player_id
    assert state.players[0].is_host is True
    assert state.players[1].is_host is False


def test_last_player_leaving_deletes_room(room):
    repo = FakeRoomRepository(room)

    player = join_player(repo, "K7QX", "Ana")

    state = leave_player(
        repo, "K7QX", player.player_token
    )

    assert state.players == []
    assert repo.get_room("K7QX") is None


def test_invalid_token_cannot_remove_player(room):
    repo = FakeRoomRepository(room)
    join_player(repo, "K7QX", "Ana")

    with pytest.raises(LobbyError) as exc:
        leave_player(repo, "K7QX", "invalid-token")

    assert exc.value.status_code == 401
    assert len(repo.get_room("K7QX").state.players) == 1


def test_cannot_leave_after_game_starts(room):
    repo = FakeRoomRepository(room)
    player = join_player(repo, "K7QX", "Ana")

    repo.room.state.status = GameStatus.composing

    with pytest.raises(LobbyError) as exc:
        leave_player(repo, "K7QX", player.player_token)

    assert exc.value.status_code == 409


def test_leave_retries_after_conflict(room):
    repo = FakeRoomRepository(room)

    join_player(repo, "K7QX", "Ana")
    guest = join_player(repo, "K7QX", "Ben")

    repo.fail_next = True

    state = leave_player(
        repo, "K7QX", guest.player_token
    )

    assert len(state.players) == 1
    assert state.players[0].name == "Ana"
