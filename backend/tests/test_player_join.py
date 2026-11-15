from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Lock
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