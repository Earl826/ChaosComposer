import pytest

from game.lifecycle import (
    begin_round_transition,
    complete_round_transition,
    get_player_assignment,
    record_player_submission,
    start_composing,
    start_game,
)
from game.state import GamePhase, GameState


def make_lobby_game(player_count: int = 4) -> GameState:
    players = [f"player_{i}" for i in range(player_count)]
    return GameState(
        id="game_1",
        host_id="player_0",
        player_order=players,
    )


def make_prompt_ready_game(player_count: int = 4) -> GameState:
    game = make_lobby_game(player_count)
    start_game(game, "player_0")
    game.prompt_chain_ids = {
        player_id: f"chain_{i}" for i, player_id in enumerate(game.player_order)
    }
    return game


def make_composing_game(player_count: int = 4) -> GameState:
    game = make_prompt_ready_game(player_count)
    start_composing(game)
    return game


# --- GameState properties ---


def test_game_state_defaults_and_round_properties():
    game = make_lobby_game(4)
    assert game.phase == GamePhase.LOBBY
    assert game.round_index is None
    assert game.current_round == 0
    assert game.total_rounds == 0
    assert game.state_version == 0
    assert game.submitted_player_ids == set()

    start_game(game, "player_0")
    assert game.current_round == 0
    assert game.total_rounds == 4

    game.prompt_chain_ids = {p: f"chain_{i}" for i, p in enumerate(game.player_order)}
    start_composing(game)
    assert game.round_index == 0
    assert game.current_round == 1
    assert game.total_rounds == 4


# --- start_game ---


@pytest.mark.parametrize("player_count", [4, 5, 6])
def test_start_game_with_valid_player_count(player_count):
    game = make_lobby_game(player_count)
    start_game(game, "player_0")
    assert game.phase == GamePhase.PROMPT_SUBMISSION
    assert game.state_version == 1


def test_start_game_rejects_non_host():
    game = make_lobby_game(4)
    with pytest.raises(PermissionError):
        start_game(game, "player_1")
    assert game.phase == GamePhase.LOBBY
    assert game.state_version == 0


@pytest.mark.parametrize("player_count", [0, 1, 2, 3, 7])
def test_start_game_rejects_invalid_player_count(player_count):
    game = make_lobby_game(player_count)
    with pytest.raises(ValueError):
        start_game(game, "player_0")
    assert game.phase == GamePhase.LOBBY
    assert game.state_version == 0


def test_start_game_rejects_duplicate_players():
    game = GameState(
        id="game_1",
        host_id="player_0",
        player_order=["player_0", "player_1", "player_2", "player_2"],
    )
    with pytest.raises(ValueError):
        start_game(game, "player_0")
    assert game.phase == GamePhase.LOBBY


@pytest.mark.parametrize(
    "phase",
    [
        GamePhase.PROMPT_SUBMISSION,
        GamePhase.COMPOSING,
        GamePhase.TRANSITIONING,
        GamePhase.FINISHED,
    ],
)
def test_start_game_rejects_non_lobby_phase(phase):
    game = make_lobby_game(4)
    game.phase = phase
    with pytest.raises(ValueError):
        start_game(game, "player_0")
    assert game.phase == phase


# --- start_composing ---


@pytest.mark.parametrize("player_count", [4, 5, 6])
def test_start_composing_assigns_different_player_prompt_in_round_1(player_count):
    game = make_prompt_ready_game(player_count)
    game.submitted_player_ids.add("stale_player")
    prev_version = game.state_version

    start_composing(game)

    assert game.phase == GamePhase.COMPOSING
    assert game.round_index == 0
    assert game.current_round == 1
    assert game.submitted_player_ids == set()
    assert game.state_version == prev_version + 1
    assert set(game.initial_assignments.values()) == set(game.chain_ids)

    for player_id in game.player_order:
        assigned_chain = get_player_assignment(game, player_id)
        assert assigned_chain != game.prompt_chain_ids[player_id]


@pytest.mark.parametrize(
    "phase",
    [
        GamePhase.LOBBY,
        GamePhase.COMPOSING,
        GamePhase.TRANSITIONING,
        GamePhase.FINISHED,
    ],
)
def test_start_composing_rejects_wrong_phase(phase):
    game = make_prompt_ready_game(4)
    game.phase = phase
    with pytest.raises(ValueError):
        start_composing(game)


def test_start_composing_rejects_empty_player_order():
    game = GameState(id="game_1", host_id="player_0", phase=GamePhase.PROMPT_SUBMISSION)
    with pytest.raises(ValueError):
        start_composing(game)


def test_start_composing_rejects_missing_or_mismatched_prompts():
    game = make_prompt_ready_game(4)
    del game.prompt_chain_ids["player_3"]
    with pytest.raises(ValueError):
        start_composing(game)

    game.prompt_chain_ids["unknown_player"] = "chain_3"
    with pytest.raises(ValueError):
        start_composing(game)


def test_start_composing_rejects_duplicate_chain_ids():
    game = make_prompt_ready_game(4)
    game.prompt_chain_ids["player_3"] = game.prompt_chain_ids["player_0"]
    with pytest.raises(ValueError):
        start_composing(game)


# --- get_player_assignment ---


@pytest.mark.parametrize(
    "phase",
    [
        GamePhase.LOBBY,
        GamePhase.PROMPT_SUBMISSION,
        GamePhase.TRANSITIONING,
        GamePhase.FINISHED,
    ],
)
def test_get_player_assignment_rejects_non_composing_phase(phase):
    game = make_composing_game(4)
    game.phase = phase
    with pytest.raises(ValueError):
        get_player_assignment(game, "player_0")


def test_get_player_assignment_rejects_missing_round_index_or_unknown_player():
    game = make_composing_game(4)
    with pytest.raises(ValueError):
        get_player_assignment(game, "outsider")

    game.round_index = None
    with pytest.raises(ValueError):
        get_player_assignment(game, "player_0")


# --- record_player_submission ---


def test_record_player_submission_tracks_progress_and_detects_completion():
    game = make_composing_game(4)
    base_version = game.state_version

    assert record_player_submission(game, "player_0") is False
    assert record_player_submission(game, "player_1") is False
    assert record_player_submission(game, "player_2") is False
    assert game.state_version == base_version + 3
    assert game.submitted_player_ids == {"player_0", "player_1", "player_2"}

    assert record_player_submission(game, "player_3") is True
    assert game.state_version == base_version + 4
    assert game.submitted_player_ids == set(game.player_order)


def test_record_player_submission_rejects_duplicate_submission():
    game = make_composing_game(4)
    record_player_submission(game, "player_0")
    version_after_first = game.state_version

    with pytest.raises(ValueError):
        record_player_submission(game, "player_0")
    assert game.state_version == version_after_first


def test_record_player_submission_rejects_unknown_player():
    game = make_composing_game(4)
    with pytest.raises(ValueError):
        record_player_submission(game, "outsider")


@pytest.mark.parametrize(
    "phase",
    [
        GamePhase.LOBBY,
        GamePhase.PROMPT_SUBMISSION,
        GamePhase.TRANSITIONING,
        GamePhase.FINISHED,
    ],
)
def test_record_player_submission_rejects_non_composing_phase(phase):
    game = make_composing_game(4)
    game.phase = phase
    with pytest.raises(ValueError):
        record_player_submission(game, "player_0")


# --- begin_round_transition & complete_round_transition ---


def test_begin_round_transition_requires_all_submissions():
    game = make_composing_game(4)
    for player_id in game.player_order[:-1]:
        record_player_submission(game, player_id)

    with pytest.raises(ValueError):
        begin_round_transition(game)
    assert game.phase == GamePhase.COMPOSING


def test_begin_round_transition_rejects_wrong_phase_or_missing_round_index():
    game = make_composing_game(4)
    for player_id in game.player_order:
        record_player_submission(game, player_id)

    game.round_index = None
    with pytest.raises(ValueError):
        begin_round_transition(game)

    game.round_index = 0
    for phase in (
        GamePhase.LOBBY,
        GamePhase.PROMPT_SUBMISSION,
        GamePhase.TRANSITIONING,
        GamePhase.FINISHED,
    ):
        game.phase = phase
        with pytest.raises(ValueError):
            begin_round_transition(game)


def test_begin_round_transition_rejects_stale_round_or_state_version_including_zero():
    game = make_composing_game(4)
    for player_id in game.player_order:
        record_player_submission(game, player_id)

    # Falsy 0 must still be caught as a mismatch
    with pytest.raises(ValueError):
        begin_round_transition(game, expected_round=0)
    with pytest.raises(ValueError):
        begin_round_transition(game, expected_round=2)
    with pytest.raises(ValueError):
        begin_round_transition(game, expected_state_version=0)
    with pytest.raises(ValueError):
        begin_round_transition(game, expected_state_version=game.state_version + 1)

    # Matching values succeed and duplicate call is rejected
    expected_round = game.current_round
    expected_version = game.state_version
    begin_round_transition(
        game,
        expected_round=expected_round,
        expected_state_version=expected_version,
    )
    assert game.phase == GamePhase.TRANSITIONING
    assert game.state_version == expected_version + 1

    with pytest.raises(ValueError):
        begin_round_transition(
            game,
            expected_round=expected_round,
            expected_state_version=expected_version,
        )


def test_complete_round_transition_guards_and_duplicate_rejection():
    game = make_composing_game(4)
    with pytest.raises(ValueError):
        complete_round_transition(game)

    for player_id in game.player_order:
        record_player_submission(game, player_id)
    begin_round_transition(game)

    # Falsy 0 and wrong version rejected
    with pytest.raises(ValueError):
        complete_round_transition(game, expected_state_version=0)
    with pytest.raises(ValueError):
        complete_round_transition(game, expected_state_version=game.state_version - 1)

    game.round_index = None
    with pytest.raises(ValueError):
        complete_round_transition(game)

    game.round_index = 0
    valid_version = game.state_version
    complete_round_transition(game, expected_state_version=valid_version)
    assert game.phase == GamePhase.COMPOSING
    assert game.current_round == 2
    assert game.submitted_player_ids == set()
    assert game.state_version == valid_version + 1

    # Duplicate completion call rejected
    with pytest.raises(ValueError):
        complete_round_transition(game, expected_state_version=valid_version)


# --- Full end-to-end game cycle ---


@pytest.mark.parametrize("player_count", [4, 5, 6])
def test_full_game_lifecycle_rotates_all_chains_once_and_finishes(player_count):
    game = make_lobby_game(player_count)
    start_game(game, "player_0")
    assert game.phase == GamePhase.PROMPT_SUBMISSION

    game.prompt_chain_ids = {
        player_id: f"chain_{i}" for i, player_id in enumerate(game.player_order)
    }
    start_composing(game)
    assert game.phase == GamePhase.COMPOSING

    seen_chains_by_player: dict[str, list[str]] = {
        player_id: [] for player_id in game.player_order
    }

    for round_num in range(1, player_count + 1):
        assert game.phase == GamePhase.COMPOSING
        assert game.current_round == round_num

        for idx, player_id in enumerate(game.player_order):
            chain_id = get_player_assignment(game, player_id)
            seen_chains_by_player[player_id].append(chain_id)
            all_done = record_player_submission(game, player_id)
            assert all_done is (idx == player_count - 1)

        begin_round_transition(
            game,
            expected_round=round_num,
            expected_state_version=game.state_version,
        )
        assert game.phase == GamePhase.TRANSITIONING

        complete_round_transition(
            game,
            expected_state_version=game.state_version,
        )

        if round_num < player_count:
            assert game.phase == GamePhase.COMPOSING
            assert game.current_round == round_num + 1
        else:
            assert game.phase == GamePhase.FINISHED

    # Every player worked on every chain once, starting with someone else's and ending on their own
    all_chains = set(game.chain_ids)
    for player_id, visited in seen_chains_by_player.items():
        assert len(visited) == player_count
        assert set(visited) == all_chains
        assert visited[0] != game.prompt_chain_ids[player_id]
        assert visited[-1] == game.prompt_chain_ids[player_id]