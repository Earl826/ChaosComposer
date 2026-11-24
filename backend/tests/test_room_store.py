import json
from copy import deepcopy
from threading import Lock

import azure.functions as func
import pytest

import function_app
from function_app import app
from models import MAX_PLAYERS
from pattern_store import ConflictError, CosmosAccessError, CosmosStoreError
from player_service import LobbyError, StoredRoom, VersionConflict, validate_join
from room_store import CODE_ALPHABET, CODE_LENGTH, create_room, generate_room_code


class InMemoryRoomRepository:
    def __init__(self):
        self._rooms = {}
        self._lock = Lock()
        self._revision = 0

    def get_room(self, session_code):
        with self._lock:
            return deepcopy(self._rooms.get(session_code))

    def create_if_absent(self, room):
        with self._lock:
            code = room.state.session_code
            if code in self._rooms:
                raise ConflictError("A room with this code already exists.")
            self._revision += 1
            self._rooms[code] = StoredRoom(deepcopy(room.state), dict(room.token_hashes), str(self._revision))

    def save_if_unchanged(self, room):
        with self._lock:
            current = self._rooms.get(room.state.session_code)
            if current is None or current.etag != room.etag:
                raise VersionConflict()
            self._revision += 1
            self._rooms[room.state.session_code] = StoredRoom(
                deepcopy(room.state), dict(room.token_hashes), str(self._revision))


@pytest.fixture(scope="module")
def functions():
    app.functions_bindings = {}
    result = {f.get_function_name(): f for f in app.get_functions()}
    yield result
    app.functions_bindings = {}


@pytest.fixture
def repo(monkeypatch):
    store = InMemoryRoomRepository()
    monkeypatch.setattr(function_app, "get_room_repository", lambda: store)
    return store


def call(functions, name, *, method="GET", body=None, raw=None, code=None, token=None):
    payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
    request = func.HttpRequest(
        method=method, url="/api/sessions",
        headers={"X-Player-Token": token} if token else {},
        route_params={"session_code": code} if code else {},
        body=payload,
    )
    return functions[name].get_user_function()(request)


def create(functions, name="Alex", **extra):
    response = call(functions, "create_session", method="POST", body={"player_name": name, **extra})
    assert response.status_code == 201
    return json.loads(response.get_body())


def test_create_room(functions, repo):
    created = create(functions, "  Alex ")
    code = created["session_code"]
    assert len(code) == CODE_LENGTH and set(code) <= set(CODE_ALPHABET)
    assert created["player_id"] and created["player_token"]
    room = repo.get_room(code)
    assert room.state.status == "lobby"
    assert room.state.max_players == MAX_PLAYERS
    host = room.state.players[0]
    assert host.name == "Alex" and host.is_host is True and host.is_ready is False
    assert created["player_token"] not in json.dumps(room.token_hashes)  # only a hash is stored
    assert list(room.token_hashes) == [created["player_id"]]


def test_create_room_with_custom_capacity(functions, repo):
    created = create(functions, max_players=4)
    assert repo.get_room(created["session_code"]).state.max_players == 4


@pytest.mark.parametrize("body", [
    {}, {"player_name": ""}, {"player_name": "   "}, {"player_name": "x" * 25},
    {"player_name": "Alex", "max_players": 3}, {"player_name": "Alex", "max_players": 7},
    {"player_name": "Alex", "max_players": "six"}, {"player_name": "Alex", "unexpected": 1}, [],
])
def test_create_room_rejects_invalid_body(functions, repo, body):
    response = call(functions, "create_session", method="POST", body=body)
    assert response.status_code == 422
    assert json.loads(response.get_body())["code"] == "invalid_request"


@pytest.mark.parametrize("raw", [b"", b"not json"])
def test_create_room_rejects_missing_or_bad_json(functions, repo, raw):
    assert call(functions, "create_session", method="POST", raw=raw).status_code == 422


def test_storage_failure_returns_503(functions, monkeypatch):
    def broken():
        raise CosmosAccessError("denied")
    monkeypatch.setattr(function_app, "get_room_repository", broken)
    response = call(functions, "create_session", method="POST", body={"player_name": "Alex"})
    assert response.status_code == 503
    assert json.loads(response.get_body())["code"] == "storage_unavailable"


def test_get_room_details_for_member(functions, repo):
    created = create(functions)
    response = call(functions, "get_session", code=created["session_code"], token=created["player_token"])
    state = json.loads(response.get_body())
    assert response.status_code == 200
    assert state["session_code"] == created["session_code"]
    assert state["status"] == "lobby"
    assert state["max_players"] == MAX_PLAYERS
    assert state["players"] == [
        {"player_id": created["player_id"], "name": "Alex", "is_host": True, "is_ready": False}
    ]
    body = response.get_body().decode()
    assert created["player_token"] not in body and "token_hash" not in body


@pytest.mark.parametrize("token", [None, "wrong"])
def test_get_room_rejects_missing_or_wrong_token(functions, repo, token):
    created = create(functions)
    response = call(functions, "get_session", code=created["session_code"], token=token)
    assert response.status_code == 401


def test_get_unknown_room(functions, repo):
    assert call(functions, "get_session", code="ZZZZ", token="x").status_code == 404


def test_room_status_is_public(functions, repo):
    created = create(functions)
    response = call(functions, "get_session_status", code=created["session_code"].lower())
    assert response.status_code == 200
    assert json.loads(response.get_body()) == {
        "session_code": created["session_code"], "status": "lobby",
        "player_count": 1, "max_players": MAX_PLAYERS, "is_full": False,
    }


@pytest.mark.parametrize("code", ["ZZZZ", "ab", "0000", "TOOLONG"])
def test_room_status_unknown_or_malformed_room(functions, repo, code):
    assert call(functions, "get_session_status", code=code).status_code == 404


def test_generated_codes_avoid_ambig_chars():
    for _ in range(500):
        code = generate_room_code()
        assert len(code) == CODE_LENGTH
        assert set(code) <= set(CODE_ALPHABET)
        assert not set(code) & set("0O1I")


def test_code_collision_is_retried(repo):
    codes = iter(["AAAA", "AAAA", "BBBB"])
    first, _ = create_room(repo, "Alex", code_factory=lambda: next(codes))
    second, _ = create_room(repo, "Bob", code_factory=lambda: next(codes))
    assert (first.state.session_code, second.state.session_code) == ("AAAA", "BBBB")


def test_code_allocation_gives_up_after_too_many_clashes(repo):
    create_room(repo, "Alex", code_factory=lambda: "AAAA")
    with pytest.raises(CosmosStoreError):
        create_room(repo, "Bob", code_factory=lambda: "AAAA")


def test_room_capacity_follows_max_players(repo):
    room, _ = create_room(repo, "Alex", 4)
    for name in ("Bob", "Cob", "Dob"):
        validate_join(room.state, name)
        room.state.players.append(room.state.players[0].model_copy(update={"name": name, "is_host": False}))
    with pytest.raises(LobbyError, match="full"):
        validate_join(room.state, "Ed")


def test_cosmos_create_if_absent_writes_room_doc():
    from unittest.mock import MagicMock
    from cosmos_room_repository import CosmosRoomRepository
    container = MagicMock()
    room, _ = create_room(InMemoryRoomRepository(), "Alex", code_factory=lambda: "AAAA")
    CosmosRoomRepository(container).create_if_absent(room)
    body = container.create_item.call_args.kwargs["body"]
    assert body["id"] == "room" and body["roomId"] == "AAAA" and body["type"] == "room"
    assert body["state"]["max_players"] == MAX_PLAYERS
    assert list(body["token_hashes"]) == [room.state.players[0].player_id]


def test_cosmos_create_if_absent_maps_duplicate_to_conflict():
    from unittest.mock import MagicMock
    from azure.cosmos.exceptions import CosmosResourceExistsError
    from cosmos_room_repository import CosmosRoomRepository
    container = MagicMock()
    container.create_item.side_effect = CosmosResourceExistsError(status_code=409, message="exists")
    room, _ = create_room(InMemoryRoomRepository(), "Alex", code_factory=lambda: "AAAA")
    with pytest.raises(ConflictError):
        CosmosRoomRepository(container).create_if_absent(room)