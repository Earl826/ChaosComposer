import json
from datetime import datetime, timedelta, timezone
import pytest
from azure.functions import Out

from game.lifecycle import (
    begin_round_transition,
    complete_round_transition,
    get_player_assignment,
    record_player_submission,
    start_composing,
    start_game,
)
from game.realtime import (
    build_group_add_message,
    build_state_changed_message,
    emit_signalr_messages,
)
from game.state import GamePhase, GameState


class DummySignalROut(Out[str]):
    """Captures JSON payloads written to an Azure Functions SignalR output binding."""

    def __init__(self) -> None:
        self.payloads: list[list[dict]] = []

    def set(self, val: str) -> None:
        self.payloads.append(json.loads(val))

    def get(self) -> str:
        return json.dumps(self.payloads[-1]) if self.payloads else "[]"


@pytest.mark.parametrize("player_count", [4, 5, 6])
def test_full_single_cycle_progression_and_broadcasts(player_count: int) -> None:
    players = [f"p{i}" for i in range(player_count)]
    game = GameState(id="ROOM", host_id=players[0], player_order=list(players))
    out = DummySignalROut()

    # 1. Lobby -> Prompt Submission
    start_game(game, requesting_player_id=players[0])
    assert game.phase == GamePhase.PROMPT_SUBMISSION
    assert game.round_deadline is not None
    emit_signalr_messages(out, [build_state_changed_message(game, "prompt_submission_started")])

    # 2. Submit all prompts -> Round 1 Composing
    expected_prompt_submitters: list[str] = []
    for pid in players:
        game.prompt_chain_ids[pid] = f"chain_{pid}"
        expected_prompt_submitters.append(pid)

        prompt_event = build_state_changed_message(game, "prompt_submitted")
        emit_signalr_messages(out, [prompt_event])
        arg = prompt_event["arguments"][0]
        assert arg["status"] == "prompt_submission"
        assert arg["submitted_player_ids"] == expected_prompt_submitters
        assert arg["submitted_count"] == len(expected_prompt_submitters)

    start_composing(game)
    assert game.phase == GamePhase.COMPOSING
    assert game.current_round == 1
    assert game.total_rounds == player_count

    composing_event = build_state_changed_message(game, "composing_started")
    emit_signalr_messages(out, [composing_event])
    assert composing_event["arguments"][0]["submitted_player_ids"] == []
    assert composing_event["arguments"][0]["submitted_count"] == 0

    # Verify Round 1 never assigns a player their own prompt chain
    for pid in players:
        assert get_player_assignment(game, pid) != f"chain_{pid}"

    # Track every chain each player touches across all rounds
    visited_by_player: dict[str, list[str]] = {pid: [] for pid in players}

    # 3. Run all N composing rounds in lockstep
    for round_num in range(1, player_count + 1):
        assert game.current_round == round_num
        assert game.round_deadline is not None

        expected_round_submitters: list[str] = []
        for idx, pid in enumerate(players):
            assigned_chain = get_player_assignment(game, pid)
            visited_by_player[pid].append(assigned_chain)

            all_done = record_player_submission(game, pid)
            expected_round_submitters.append(pid)
            assert all_done is (idx == player_count - 1)

            if not all_done:
                pattern_event = build_state_changed_message(game, "pattern_submitted")
                emit_signalr_messages(out, [pattern_event])
                arg = pattern_event["arguments"][0]
                assert arg["status"] == "composing"
                assert arg["submitted_player_ids"] == expected_round_submitters
                assert arg["submitted_count"] == len(expected_round_submitters)

        # Auto-advance once final active player submits
        events = []
        begin_round_transition(game)
        assert game.phase == GamePhase.TRANSITIONING
        assert game.round_deadline is None
        events.append(build_state_changed_message(game, "round_transitioning"))

        complete_round_transition(game)
        reason = "game_finished" if game.phase == GamePhase.FINISHED else "round_advanced"
        events.append(build_state_changed_message(game, reason))
        emit_signalr_messages(out, events)

    # 4. Verify single-cycle completion invariants
    assert game.phase == GamePhase.FINISHED
    expected_chains = {f"chain_{pid}" for pid in players}
    for pid, chains in visited_by_player.items():
        assert len(chains) == player_count
        assert set(chains) == expected_chains  # Every player worked on every chain once

    # Verify SignalR broadcasts targeted the room group and ended in 'finished'
    flattened = [msg for batch in out.payloads for msg in batch]
    assert all(msg["groupName"] == "ROOM" for msg in flattened)
    assert flattened[-1]["arguments"][0]["status"] == "finished"


def test_deadline_enforcement_and_timeout_advancement() -> None:
    players = ["p0", "p1", "p2", "p3"]
    game = GameState(id="TIME", host_id="p0", player_order=players)
    start_game(game, "p0")
    for pid in players:
        game.prompt_chain_ids[pid] = f"chain_{pid}"
    start_composing(game)

    # Simulate p0 submitting on time, then the deadline expiring
    assert record_player_submission(game, "p0") is False
    game.round_deadline = datetime.now(timezone.utc) - timedelta(seconds=1)

    # Late submission from p1 must be rejected
    with pytest.raises(ValueError, match="deadline has passed"):
        record_player_submission(game, "p1")

    # Server timer can still advance the round once deadline has passed
    begin_round_transition(game)
    assert game.phase == GamePhase.TRANSITIONING
    complete_round_transition(game)
    assert game.phase == GamePhase.COMPOSING
    assert game.current_round == 2


def test_group_add_message_format() -> None:
    msg = build_group_add_message("ABCD", "p1")
    assert msg == {"userId": "p1", "groupName": "ABCD", "action": "add"}