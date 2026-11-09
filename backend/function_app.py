"""MVP Azure Functions API stubs: editable 16-step patterns, not audio uploads.

All business endpoints intentionally return 501 until implemented.
OpenAPI metadata describes the TARGET contract, not implemented behaviour.
Requires existing azure-functions / azure-functions-openapi dependencies and
Pydantic 2.x. Keep models_mvp.py alongside this file.

Proposed rules: 4-6 ready players; frozen roster at start; one prompt per player;
first assignment excludes the prompt author; N composing rounds for N players;
auto-advance only after all contributions persist. No forced skip in this MVP.
Do not store authoritative game state in process globals: use persisted state
and conditional/atomic updates to protect concurrent advancement.
"""
import json
from copy import deepcopy
import azure.functions as func
from azure_functions_openapi.decorator import openapi
from azure_functions_openapi.openapi import get_openapi_json
from azure_functions_openapi.swagger_ui import render_swagger_ui
from models import (
    ErrorResponse, CreateSessionRequest, JoinSessionRequest, SessionCreated,
    PlayerCredentials, SessionState, ReadyRequest, StartGameRequest,
    SubmitPromptRequest, AssignmentResponse, SubmitPatternRequest,
    AdvanceRoundRequest, RevealResponse, NegotiateRequest, NegotiateResponse,
)
from pattern_store import (
    get_chain_repository,
    handle_get_assignment_http,
    handle_reveal_http,
    handle_submit_pattern_http,
    json_error,
)
from typing import Any, Literal
from pydantic import BaseModel

app = func.FunctionApp()

PLAYER_TOKEN = [{
    "name": "X-Player-Token", "in": "header", "required": True,
    "description": "Room-scoped player credential returned by create/join. Validate membership and permissions in the handler.",
    "schema": {"type": "string", "minLength": 1},
}]


def inline_schema(model):
    """Produce a self-contained schema for responses= status-code maps."""
    root = deepcopy(model.model_json_schema())
    definitions = root.pop("$defs", {})
    def expand(value):
        if isinstance(value, list):
            return [expand(item) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value and value["$ref"].startswith("#/$defs/"):
            name = value["$ref"].split("/")[-1]
            merged = deepcopy(definitions[name])
            merged.update({k: v for k, v in value.items() if k != "$ref"})
            return expand(merged)
        # Mapping discriminator is optional; its local refs would dangle after
        # inlining. Preserve propertyName and the discriminated oneOf branches.
        return {k: expand(v) for k, v in value.items() if k != "mapping"}
    return expand(root)


def documented_responses(model: type[BaseModel], success: int = 200, errors: tuple[int, ...] = ()):
    descriptions = {
        200: "Successful response", 201: "Created", 401: "Missing or invalid player token",
        403: "Caller is not permitted to perform this action", 404: "Room not found",
        409: "State, round, assignment or duplicate-request conflict",
        422: "Invalid request data", 501: "Stub only: endpoint not implemented yet",
    }
    result: dict[int | Literal["default"], Any] = {success: {"description": descriptions[success], "content": {
        "application/json": {"schema": inline_schema(model)}}}}
    for status in sorted(set(errors) | {501}):
        result[status] = {"description": descriptions[status], "content": {
            "application/json": {"schema": inline_schema(ErrorResponse)}}}
    return result


def not_implemented(name: str) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"code": "not_implemented", "detail": name}),
        status_code=501, mimetype="application/json",
    )


@app.route(route="openapi.json", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def openapi_json(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(get_openapi_json(), mimetype="application/json")


@app.route(route="docs", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def swagger_ui(req: func.HttpRequest) -> func.HttpResponse:
    return render_swagger_ui()


@app.route(route='sessions', methods=['POST'], auth_level=func.AuthLevel.ANONYMOUS)
@openapi(
    summary='Create a room',
    description='Create a lobby and its host player; return a unique four-character room code and secret player credentials. Trim and validate names. Host readiness starts false.',
    route='/api/sessions', method='post',
    requests=CreateSessionRequest,
    responses=documented_responses(SessionCreated, success=201, errors=(422,)),
    tags=['sessions'],
)
def create_session(req: func.HttpRequest) -> func.HttpResponse:
    return not_implemented('create_session')


@app.route(route='sessions/{session_code}/players', methods=['POST'], auth_level=func.AuthLevel.ANONYMOUS)
@openapi(
    summary='Join a room',
    description='Join only in lobby, with capacity at most six. Issue a new unique player ID and token; display names are not identity. Reject duplicate normalized display names for this proposed MVP.',
    route='/api/sessions/{session_code}/players', method='post',
    requests=JoinSessionRequest,
    responses=documented_responses(PlayerCredentials, success=201, errors=(404, 409, 422)),
    tags=['players'],
)
def join_session(req: func.HttpRequest) -> func.HttpResponse:
    return not_implemented('join_session')


@app.route(route='sessions/{session_code}', methods=['GET'], auth_level=func.AuthLevel.ANONYMOUS)
@openapi(
    summary='Get room state',
    description='Return member-visible status, roster, readiness, round and submission progress. Never return player tokens, original prompts or musical histories here.',
    route='/api/sessions/{session_code}', method='get',
    parameters=PLAYER_TOKEN,
    responses=documented_responses(SessionState, success=200, errors=(401, 403, 404)),
    tags=['sessions'],
)
def get_session(req: func.HttpRequest) -> func.HttpResponse:
    return not_implemented('get_session')


@app.route(route='sessions/{session_code}/players/me/ready', methods=['PUT'], auth_level=func.AuthLevel.ANONYMOUS)
@openapi(
    summary='Set my lobby readiness',
    description='Idempotently set the authenticated player readiness. Lobby only. No client-supplied player identity.',
    route='/api/sessions/{session_code}/players/me/ready', method='put',
    parameters=PLAYER_TOKEN,
    requests=ReadyRequest,
    responses=documented_responses(SessionState, success=200, errors=(401, 403, 404, 409, 422)),
    tags=['players'],
)
def set_ready(req: func.HttpRequest) -> func.HttpResponse:
    return not_implemented('set_ready')


@app.route(route='sessions/{session_code}/players/me', methods=['DELETE'], auth_level=func.AuthLevel.ANONYMOUS)
@openapi(
    summary='Leave the lobby',
    description='Remove the authenticated player only while in lobby. If the host leaves, transfer host to the earliest remaining joiner; return its empty lobby snapshot and delete an empty room. Active-game leaving is out of scope; roster remains frozen.',
    route='/api/sessions/{session_code}/players/me', method='delete',
    parameters=PLAYER_TOKEN,
    responses=documented_responses(SessionState, success=200, errors=(401, 403, 404, 409)),
    tags=['players'],
)
def leave_session(req: func.HttpRequest) -> func.HttpResponse:
    return not_implemented('leave_session')


@app.route(route='sessions/{session_code}/start', methods=['POST'], auth_level=func.AuthLevel.ANONYMOUS)
@openapi(
    summary='Start prompt submission (host only)',
    description='Require lobby, 4-6 players, all ready and matching expected_state_version. Freeze player order and total_rounds=N; enter prompt_submission with current_round=0. Conditional persistence must reject concurrent or stale starts.',
    route='/api/sessions/{session_code}/start', method='post',
    parameters=PLAYER_TOKEN,
    requests=StartGameRequest,
    responses=documented_responses(SessionState, success=200, errors=(401, 403, 404, 409, 422)),
    tags=['game'],
)
def start_game(req: func.HttpRequest) -> func.HttpResponse:
    return not_implemented('start_game')


@app.route(route='sessions/{session_code}/prompts', methods=['POST'], auth_level=func.AuthLevel.ANONYMOUS)
@openapi(
    summary='Submit my starting prompt',
    description='Accept one prompt per frozen player during prompt_submission. Exact retries return current state; changed duplicate prompts conflict. After all prompts persist, create N chains, assign each player a different player original prompt, and atomically enter composing round 1. Later rotations visit every chain once per player. Never expose other original prompts in room state.',
    route='/api/sessions/{session_code}/prompts', method='post',
    parameters=PLAYER_TOKEN,
    requests=SubmitPromptRequest,
    responses=documented_responses(SessionState, success=200, errors=(401, 403, 404, 409, 422)),
    tags=['prompts'],
)
def submit_prompt(req: func.HttpRequest) -> func.HttpResponse:
    return not_implemented('submit_prompt')


@app.route(route='sessions/{session_code}/assignment', methods=['GET'], auth_level=func.AuthLevel.ANONYMOUS)
@openapi(
    summary='Get my current chain input',
    description='Composing only. Return kind=prompt and assigned text in round 1; return kind=pattern, previous_version_id and the previous saved pattern in rounds 2..N. Never return original prompts or full history in later rounds. Resolve assignment from authenticated player identity.',
    route='/api/sessions/{session_code}/assignment', method='get',
    parameters=PLAYER_TOKEN,
    responses=documented_responses(AssignmentResponse, success=200, errors=(401, 403, 404, 409)),
    tags=['game'],
)
def get_assignment(req: func.HttpRequest) -> func.HttpResponse:
    player_token = req.headers.get("X-Player-Token", "").strip()
    if not player_token:
        return json_error("unauthorized", "Missing X-Player-Token header.", 401)

    session_code = req.route_params.get("session_code", "")
    chain_id = req.params.get("chain_id", "chain_1")
    try:
        current_round = int(req.params.get("round", "1"))
    except ValueError:
        return json_error("invalid_round", "Round parameter must be an integer.", 422)

    return handle_get_assignment_http(
        repo=get_chain_repository(),
        session_code=session_code,
        chain_id=chain_id,
        current_round=current_round,
    )

@app.route(route='sessions/{session_code}/submissions', methods=['POST'], auth_level=func.AuthLevel.ANONYMOUS)
@openapi(
    summary='Submit my musical pattern',
    description='Validate token, composing state, expected_round and assigned chain_id. Validate pattern and unique instrument IDs; persist an immutable contribution before counting it accepted. Same submission_id with identical content returns current state without another contribution; conflicting reuse or a second contribution conflicts. Retried accepted submissions remain idempotent after round advancement. Once all N contributions persist, advance exactly once, rotate assignments, clear current submission progress, or finish after round N. Use atomic/conditional persistence; never trust client identity.',
    route='/api/sessions/{session_code}/submissions', method='post',
    parameters=PLAYER_TOKEN,
    requests=SubmitPatternRequest,
    responses=documented_responses(SessionState, success=200, errors=(401, 403, 404, 409, 422)),
    tags=['patterns'],
)
def submit_pattern(req: func.HttpRequest) -> func.HttpResponse:
    player_token = req.headers.get("X-Player-Token", "").strip()
    if not player_token:
        return json_error("unauthorized", "Missing X-Player-Token header.", 401)

    session_code = req.route_params.get("session_code", "")
    player_name = req.headers.get("X-Player-Name", player_token)

    return handle_submit_pattern_http(
        req=req,
        repo=get_chain_repository(),
        session_code=session_code,
        player_id=player_token,
        player_name=player_name,
    )

@app.route(route='sessions/{session_code}/advance', methods=['POST'], auth_level=func.AuthLevel.ANONYMOUS)
@openapi(
    summary='Advance a completed round (host only)',
    description='Optional recovery endpoint, not a forced skip. Require composing, matching expected_round and expected_state_version, and all N contributions persisted. Advance exactly once or finish after round N. Reject stale/duplicate advancement; do not invent missing versions. Normal submissions auto-advance, so clients usually do not call this.',
    route='/api/sessions/{session_code}/advance', method='post',
    parameters=PLAYER_TOKEN,
    requests=AdvanceRoundRequest,
    responses=documented_responses(SessionState, success=200, errors=(401, 403, 404, 409, 422)),
    tags=['game'],
)
def advance_round(req: func.HttpRequest) -> func.HttpResponse:
    return not_implemented('advance_round')


@app.route(route='sessions/{session_code}/reveal', methods=['GET'], auth_level=func.AuthLevel.ANONYMOUS)
@openapi(
    summary='Reveal completed musical chains',
    description='Finished only, room members only. Return every original prompt and immutable pattern stage in ascending round order, plus final_version_id. No rendered audio mix is required.',
    route='/api/sessions/{session_code}/reveal', method='get',
    parameters=PLAYER_TOKEN,
    responses=documented_responses(RevealResponse, success=200, errors=(401, 403, 404, 409)),
    tags=['game'],
)
def reveal(req: func.HttpRequest) -> func.HttpResponse:
    player_token = req.headers.get("X-Player-Token", "").strip()
    if not player_token:
        return json_error("unauthorized", "Missing X-Player-Token header.", 401)

    session_code = req.route_params.get("session_code", "")
    return handle_reveal_http(
        repo=get_chain_repository(),
        session_code=session_code,
    )

@app.route(route='negotiate', methods=['POST'], auth_level=func.AuthLevel.ANONYMOUS)
@openapi(
    summary='Get room-scoped SignalR connection details',
    description='Optional live-update transport. Authenticate player membership in requested room and scope delivery server-side to that room. Publish only state-change notifications, never tokens, hidden prompts or musical histories. Clients refetch state/assignment; polling remains a valid MVP alternative.',
    route='/api/negotiate', method='post',
    parameters=PLAYER_TOKEN,
    requests=NegotiateRequest,
    responses=documented_responses(NegotiateResponse, success=200, errors=(401, 403, 404, 422)),
    tags=['realtime'],
)
def negotiate(req: func.HttpRequest) -> func.HttpResponse:
    return not_implemented('negotiate')
