# HTTP handlers for player and lobby operations

import azure.functions as func
from pydantic import ValidationError

from models import JoinSessionRequest, ReadyRequest
from pattern_store import CosmosStoreError, json_error
from player_service import (
    LobbyError,
    RoomRepository,
    authenticate_player,
    join_player,
    leave_player,
    set_player_ready,
)


def respond(operation, success_status=200):
    """Convert service results and expected failures to HTTP."""
    try:
        result = operation()
        return func.HttpResponse(
            result.model_dump_json(),
            status_code=success_status,
            mimetype="application/json",
        )
    except LobbyError as exc:
        code = {
            401: "unauthorized",
            404: "not_found",
            409: "conflict",
            422: "invalid_request",
        }.get(exc.status_code, "request_failed")
        return json_error(code, str(exc), exc.status_code)
    except CosmosStoreError:
        return json_error(
            "storage_unavailable",
            "Room storage is unavailable.",
            503,
        )


def parse_body(req, model):
    """Validate a JSON request against the API model."""
    try:
        return model.model_validate(req.get_json())
    except (ValueError, ValidationError):
        return None


def handle_join_http(req, repo: RoomRepository, session_code):
    body = parse_body(req, JoinSessionRequest)

    if body is None:
        return json_error(
            "invalid_request", "Invalid player name or JSON.", 422
        )

    return respond(
        lambda: join_player(repo, session_code, body.player_name),
        success_status=201,
    )


def handle_get_lobby_http(req, repo: RoomRepository, session_code):
    def operation():
        stored = repo.get_room(session_code)
        if stored is None:
            raise LobbyError(404, "Room not found")

        authenticate_player(
            stored, req.headers.get("X-Player-Token", "")
        )
        return stored.state

    return respond(operation)


def handle_ready_http(req, repo: RoomRepository, session_code):
    body = parse_body(req, ReadyRequest)

    if body is None:
        return json_error(
            "invalid_request", "Invalid readiness request.", 422
        )

    return respond(
        lambda: set_player_ready(
            repo,
            session_code,
            req.headers.get("X-Player-Token", ""),
            body.is_ready,
        )
    )


def handle_leave_http(req, repo: RoomRepository, session_code):
    return respond(
        lambda: leave_player(
            repo,
            session_code,
            req.headers.get("X-Player-Token", ""),
        )
    )