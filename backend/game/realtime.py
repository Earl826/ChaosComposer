import json
from typing import Any
import azure.functions as func
from .state import GameState, GamePhase

SIGNALR_HUB_NAME = "gamehub"


def build_group_add_message(session_code: str, player_id: str) -> dict[str, Any]:
    return {
        "userId": player_id,
        "groupName": session_code,
        "action": "add",
    }


def build_state_changed_message(game: GameState, reason: str) -> dict[str, Any]:
    """Builds a room-scoped state notification matching the OpenAPI privacy rules."""
    if game.phase == GamePhase.PROMPT_SUBMISSION:
        submitted_ids = sorted(game.prompt_chain_ids.keys())
    elif game.phase == GamePhase.COMPOSING:
        submitted_ids = sorted(game.submitted_player_ids)
    else:
        submitted_ids = []

    return {
        "groupName": game.id,
        "target": "stateChanged",
        "arguments": [
            {
                "session_code": game.id,
                "status": game.phase.value,
                "state_version": game.state_version,
                "current_round": game.current_round,
                "total_rounds": game.total_rounds,
                "round_deadline": (
                    game.round_deadline.isoformat()
                    if game.round_deadline is not None
                    else None
                ),
                "submitted_player_ids": submitted_ids,
                "submitted_count": len(submitted_ids),
                "player_count": len(game.player_order),
                "reason": reason,
            }
        ],
    }


def emit_signalr_messages(
    signalr_out: func.Out[str],
    messages: list[dict[str, Any]],
) -> None:
    if messages:
        signalr_out.set(json.dumps(messages))