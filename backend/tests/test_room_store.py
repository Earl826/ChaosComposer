import json

import azure.functions as func
import pytest

import function_app
from function_app import app
from models import MAX_PLAYERS
from pattern_store import ConflictError, CosmosAccessError, CosmosStoreError
from room_store import (
    CODE_ALPHABET, CODE_LENGTH, InMemoryRoomRepository, create_room,
    ensure_room_has_capacity, generate_room_code,
)


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
    assert room["status"] == "lobby"
    assert room["max_players"] == MAX_PLAYERS
    assert room["players"][0]["name"] == "Alex"
    assert room["players"][0]["is_host"] is True
    assert created["player_token"] not in json.dumps(room)


def test_create_room_with_custom_capacity(functions, repo):
    created = create(functions, max_players=4)
    assert repo.get_room(created["session_code"])["max_players"] == 4


@pytest.mark.parametrize("body", [
    {}, {"player_name": ""}, {"player_name": "   "}, {"player_name": "x" * 25},
    {"player_name": "Alex", "max_players": 3}, {"player_name": "Alex", "max_players": 7},
    {"player_name": "Alex", "max_players": "four"}, {"player_name": "Alex", "unexpected": 1}, [],
])
def test_create_room_rejects_invalid_body(functions, repo, body):
    response = call(functions, "create_session", method="POST", body=body)
    assert response.status_code == 422
    assert json.loads(response.get_body())["code"] == "invalid_request"


@pytest.mark.parametrize("raw", [b"", b"not json"])
def test_create_room_rejects_missing_or_bad_json(functions, repo, raw):
    response = call(functions, "create_session", method="POST", raw=raw)
    assert response.status_code == 422


def test_storage_failure(functions, monkeypatch):
    def broken():
        raise CosmosAccessError("denied")
    monkeypatch.setattr(function_app, "get_room_repository", broken)
    response = call(functions, "create_session", method="POST", body={"player_name": "Alex"})
    assert response.status_code == 503
    assert json.loads(response.get_body())["code"] == "storage_unavailable"


def test_get_room_details_for_member(functions, repo):
    created = create(functions)
    response = call(functions, "get_session", code=created["session_code"].lower(), token=created["player_token"])
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


def test_get_room_requires_token(functions, repo):
    created = create(functions)
    assert call(functions, "get_session", code=created["session_code"]).status_code == 401


def test_get_room_rejects_non_member(functions, repo):
    created = create(functions)
    assert call(functions, "get_session", code=created["session_code"], token="wrong").status_code == 403


@pytest.mark.parametrize("code", ["ZZZZ", "ab", "0000", "TOOLONG"])
def test_get_unknown_or_malformed_room_returns_404(functions, repo, code):
    assert call(functions, "get_session", code=code, token="x").status_code == 404


def test_room_status_is_public(functions, repo):
    created = create(functions)
    response = call(functions, "get_session_status", code=created["session_code"])
    assert response.status_code == 200
    assert json.loads(response.get_body()) == {
        "session_code": created["session_code"], "status": "lobby",
        "player_count": 1, "max_players": MAX_PLAYERS, "is_full": False,
    }


def test_room_status_unknown_room(functions, repo):
    assert call(functions, "get_session_status", code="ZZZZ").status_code == 404


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
    assert (first["session_code"], second["session_code"]) == ("AAAA", "BBBB")


def test_code_allocation_gives_up_after_too_many_clashes(repo):
    create_room(repo, "Alex", code_factory=lambda: "AAAA")
    with pytest.raises(CosmosStoreError):
        create_room(repo, "Bob", code_factory=lambda: "AAAA")


def test_capacity_checks(repo):
    room, _ = create_room(repo, "Alex", 4)
    ensure_room_has_capacity(room)  # 1 of 4 players: fine
    room["players"] += [{"player_id": f"p{i}"} for i in range(3)]
    with pytest.raises(ConflictError, match="full"):
        ensure_room_has_capacity(room)
    room["players"].pop()
    room["status"] = "composing"
    with pytest.raises(ConflictError, match="no longer"):
        ensure_room_has_capacity(room)
