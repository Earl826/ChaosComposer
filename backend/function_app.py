import json

import azure.functions as func
from azure_functions_openapi.decorator import openapi
from azure_functions_openapi.openapi import get_openapi_json
from azure_functions_openapi.swagger_ui import render_swagger_ui

from models import (
    ClipLink,
    CreateSessionRequest,
    JoinSessionRequest,
    NegotiateResponse,
    PlayerCredentials,
    RevealResponse,
    SessionCreated,
    SessionState,
    SubmitClipRequest,
    UploadLink,
    UploadLinkRequest,
)

app = func.FunctionApp()


def not_implemented(name: str) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"code": "not_implemented", "detail": name}),
        status_code=501,
        mimetype="application/json",
    )


@app.route(route="openapi.json", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def openapi_json(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(get_openapi_json(), mimetype="application/json")


@app.route(route="docs", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def swagger_ui(req: func.HttpRequest) -> func.HttpResponse:
    return render_swagger_ui()


@openapi(
    summary="Create a room",
    description=(
        "Create a room and make the caller its host. "
        "201: room created. 422: name is blank or longer than 24 characters."
    ),
    requests=CreateSessionRequest,
    responses=SessionCreated,
    tags=["sessions"],
)
@app.route(route="sessions", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def create_session(req: func.HttpRequest) -> func.HttpResponse:
    return not_implemented("create_session")


@openapi(
    summary="Join a room",
    description=(
        "Join a room that is still in the lobby. "
        "201: joined. 404: no room with this code. 409: the game has already started."
    ),
    requests=JoinSessionRequest,
    responses=PlayerCredentials,
    tags=["sessions"],
)
@app.route(route="sessions/{session_code}/players", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def join_session(req: func.HttpRequest) -> func.HttpResponse:
    return not_implemented("join_session")


@openapi(
    summary="Get room state",
    description=(
        "Clients call this on load and when a live update arrives. "
        "200: current status, round, players and submissions. 404: no room with this code."
    ),
    responses=SessionState,
    tags=["sessions"],
)
@app.route(route="sessions/{session_code}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_session(req: func.HttpRequest) -> func.HttpResponse:
    return not_implemented("get_session")


@openapi(
    summary="Start the game",
    description=(
        "Start round 1. Host only, using the X-Player-Token header. "
        "200: game started, status is recording. 403: caller is not the host. "
        "404: no room with this code. 409: fewer than 4 or more than 6 players."
    ),
    responses=SessionState,
    tags=["game"],
)
@app.route(route="sessions/{session_code}/start", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def start_game(req: func.HttpRequest) -> func.HttpResponse:
    return not_implemented("start_game")


@openapi(
    summary="Request a clip upload link",
    description=(
        "Get a short-lived SAS link to upload one clip directly to Blob Storage. "
        "200: upload link issued. 404: no room with this code. "
        "409: no round is open for uploads."
    ),
    requests=UploadLinkRequest,
    responses=UploadLink,
    tags=["game"],
)
@app.route(route="sessions/{session_code}/uploads", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def create_upload_link(req: func.HttpRequest) -> func.HttpResponse:
    return not_implemented("create_upload_link")


@openapi(
    summary="Confirm a clip for the current round",
    description=(
        "Record that this player's clip has uploaded. The server advances the round "
        "when everyone has submitted. 200: accepted, returns the updated room. "
        "404: no room with this code. 409: round is closed, or the player already submitted."
    ),
    requests=SubmitClipRequest,
    responses=SessionState,
    tags=["game"],
)
@app.route(route="sessions/{session_code}/submissions", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def submit_clip(req: func.HttpRequest) -> func.HttpResponse:
    return not_implemented("submit_clip")


@openapi(
    summary="Get the clip to build on",
    description=(
        "Returns the previous contributor's clip. The original prompt is never returned. "
        "200: short-lived read link to the clip. 404: no room with this code. "
        "409: round not started, or no clip available for this player."
    ),
    responses=ClipLink,
    tags=["game"],
)
@app.route(route="sessions/{session_code}/clip", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_clip(req: func.HttpRequest) -> func.HttpResponse:
    return not_implemented("get_clip")


@openapi(
    summary="Advance the round (host only)",
    description=(
        "Close the current round for absent players so the game does not stall. "
        "200: next round started. 403: caller is not the host. 409: round is not open."
    ),
    responses=SessionState,
    tags=["game"],
)
@app.route(route="sessions/{session_code}/advance", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def advance_round(req: func.HttpRequest) -> func.HttpResponse:
    return not_implemented("advance_round")


@openapi(
    summary="Reveal all chains",
    description=(
        "Every chain with its original prompt, each stage, and its final mix. "
        "200: all chains in round order. 404: no room with this code. "
        "409: the game has not finished."
    ),
    responses=RevealResponse,
    tags=["game"],
)
@app.route(route="sessions/{session_code}/reveal", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def reveal(req: func.HttpRequest) -> func.HttpResponse:
    return not_implemented("reveal")


@openapi(
    summary="Get SignalR connection details",
    description="Returns the URL and access token the browser needs for live updates. 200: connection details issued.",
    responses=NegotiateResponse,
    tags=["realtime"],
)
@app.route(route="negotiate", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def negotiate(req: func.HttpRequest) -> func.HttpResponse:
    return not_implemented("negotiate")