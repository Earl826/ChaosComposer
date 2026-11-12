import pytest
from game.rotation import get_round_assignments, create_initial_assignments


@pytest.fixture
def four_player_game():
    players = ["A", "B", "C", "D"]
    assignments = {
        "A": "chain_2",
        "B": "chain_3",
        "C": "chain_4",
        "D": "chain_1",
    }
    return players, assignments


@pytest.mark.parametrize(
    "round_index, expected",
    [
        (
            0,
            {
                "A": "chain_2",
                "B": "chain_3",
                "C": "chain_4",
                "D": "chain_1",
            },
        ),
        (
            1,
            {
                "A": "chain_3",
                "B": "chain_4",
                "C": "chain_1",
                "D": "chain_2",
            },
        ),
        (
            2,
            {
                "A": "chain_4",
                "B": "chain_1",
                "C": "chain_2",
                "D": "chain_3",
            },
        ),
        (
            3,
            {
                "A": "chain_1",
                "B": "chain_2",
                "C": "chain_3",
                "D": "chain_4",
            },
        ),
    ],
)
def test_expected_assignments_for_each_round(
    four_player_game, round_index, expected
):
    players, assignments = four_player_game

    result = get_round_assignments(players, assignments, round_index)

    assert result == expected


@pytest.mark.parametrize("player_count", [4, 5, 6])
def test_every_player_receives_every_chain_exactly_once(player_count):
    players = [f"player_{i}" for i in range(player_count)]
    assignments = {
        player: f"chain_{i}"
        for i, player in enumerate(players)
    }

    rounds = [
        get_round_assignments(players, assignments, round_index)
        for round_index in range(player_count)
    ]

    assert rounds[0] == assignments

    for result in rounds:
        assert set(result) == set(players)

        assert len(result.values()) == player_count
        assert set(result.values()) == set(assignments.values())

    for player in players:
        received = [result[player] for result in rounds]

        assert len(set(received)) == player_count
        assert set(received) == set(assignments.values())

    for previous, current in zip(rounds, rounds[1:]):
        next_players = players[1:] + players[:1]

        for player, next_player in zip(players, next_players):
            assert current[player] == previous[next_player]


def test_player_order_controls_rotation_not_dictionary_order():
    players = ["C", "A", "D", "B"]

    assignments = {
        "A": "chain_2",
        "B": "chain_3",
        "C": "chain_4",
        "D": "chain_1",
    }

    result = get_round_assignments(players, assignments, 1)

    assert result == {
        "C": "chain_2",
        "A": "chain_1",
        "D": "chain_3",
        "B": "chain_4",
    }


def test_chain_ids_are_opaque_strings():
    players = ["A", "B", "C", "D"]
    assignments = {
        "A": "melody-blue",
        "B": "uuid-xyz",
        "C": "drums",
        "D": "chain_99",
    }

    result = get_round_assignments(players, assignments, 1)

    assert result == {
        "A": "uuid-xyz",
        "B": "drums",
        "C": "chain_99",
        "D": "melody-blue",
    }


def test_calls_do_not_mutate_inputs_or_depend_on_previous_calls(
    four_player_game,
):
    players, assignments = four_player_game
    original_players = players.copy()
    original_assignments = assignments.copy()

    first_result = get_round_assignments(players, assignments, 2)

    get_round_assignments(players, assignments, 3)
    get_round_assignments(players, assignments, 0)

    repeated_result = get_round_assignments(players, assignments, 2)

    assert first_result == repeated_result
    assert players == original_players
    assert assignments == original_assignments


def test_result_is_not_the_original_assignment_dictionary(four_player_game):
    players, assignments = four_player_game

    result = get_round_assignments(players, assignments, 0)
    result["A"] = "changed"

    assert assignments["A"] == "chain_2"


@pytest.mark.parametrize("player_count", [0, 1, 2, 3, 7, 8])
def test_rejects_unsupported_player_counts(player_count):
    players = [f"player_{i}" for i in range(player_count)]
    assignments = {
        player: f"chain_{i}"
        for i, player in enumerate(players)
    }

    with pytest.raises(ValueError):
        get_round_assignments(players, assignments, 0)


def test_rejects_duplicate_player_ids():
    players = ["A", "B", "C", "A"]
    assignments = {
        "A": "chain_1",
        "B": "chain_2",
        "C": "chain_3",
    }

    with pytest.raises(ValueError, match="Player IDs must be unique"):
        get_round_assignments(players, assignments, 0)


@pytest.mark.parametrize(
    "assignments",
    [
        {},
        {
            "A": "chain_1",
            "B": "chain_2",
            "C": "chain_3",
        },
        {
            "A": "chain_1",
            "B": "chain_2",
            "C": "chain_3",
            "D": "chain_4",
            "E": "chain_5",
        },
        {
            "A": "chain_1",
            "B": "chain_2",
            "C": "chain_3",
            "E": "chain_4",
        },
    ],
)
def test_rejects_assignments_that_do_not_match_players(assignments):
    players = ["A", "B", "C", "D"]

    with pytest.raises(ValueError, match="match the players exactly"):
        get_round_assignments(players, assignments, 0)


@pytest.mark.parametrize(
    "chains",
    [
        ["chain_1", "chain_1", "chain_3", "chain_4"],
        ["chain_1", "chain_1", "chain_1", "chain_1"],
    ],
)
def test_rejects_duplicate_initial_chains(chains):
    players = ["A", "B", "C", "D"]
    assignments = dict(zip(players, chains))

    with pytest.raises(ValueError, match="different chain"):
        get_round_assignments(players, assignments, 0)


@pytest.mark.parametrize("player_count", [4, 5, 6])
def test_rejects_round_indices_outside_game(player_count):
    players = [f"player_{i}" for i in range(player_count)]
    assignments = {
        player: f"chain_{i}"
        for i, player in enumerate(players)
    }

    for invalid_round in [-10, -1, player_count, player_count + 1, 100]:
        with pytest.raises(ValueError):
            get_round_assignments(players, assignments, invalid_round)


@pytest.mark.parametrize("player_count", [4, 5, 6])
def test_assigns_each_player_to_corresponding_chain(player_count):
    players = [f"player_{i}" for i in range(player_count)]
    chains = [f"chain_{i}" for i in range(player_count)]

    result = create_initial_assignments(players, chains)

    expected = {
        f"player_{i}": f"chain_{i}"
        for i in range(player_count)
    }
    assert result == expected


def test_uses_supplied_order_not_sorted_order():
    players = ["player_c", "player_a", "player_b"]
    chains = ["chain_2", "chain_3", "chain_1"]

    result = create_initial_assignments(players, chains)

    assert result == {
        "player_c": "chain_2",
        "player_a": "chain_3",
        "player_b": "chain_1",
    }


def test_empty_lists_return_empty_dictionary():
    assert create_initial_assignments([], []) == {}


def test_single_player_and_chain():
    assert create_initial_assignments(
        ["player_1"], ["chain_1"]
    ) == {"player_1": "chain_1"}


def test_does_not_modify_input_lists():
    players = ["player_b", "player_a"]
    chains = ["chain_2", "chain_1"]
    original_players = players.copy()
    original_chains = chains.copy()

    create_initial_assignments(players, chains)

    assert players == original_players
    assert chains == original_chains


# Invalid edge cases: mismatched lengths in both directions.
@pytest.mark.parametrize(
    "players, chains",
    [
        (["player_1", "player_2"], ["chain_1"]),
        (["player_1"], ["chain_1", "chain_2"]),
        ([], ["chain_1"]),
        (["player_1"], []),
    ],
    ids=[
        "more-players-than-chains",
        "more-chains-than-players",
        "no-players",
        "no-chains",
    ],
)
def test_rejects_mismatched_lengths(players, chains):
    with pytest.raises(
        ValueError,
        match="Each player must have exactly one chain",
    ):
        create_initial_assignments(players, chains)


def test_rejects_duplicate_player_ids():
    players = ["player_1", "player_2", "player_1"]
    chains = ["chain_1", "chain_2", "chain_3"]

    with pytest.raises(ValueError, match="Player IDs must be unique"):
        create_initial_assignments(players, chains)


def test_rejects_duplicate_chain_ids():
    players = ["player_1", "player_2", "player_3"]
    chains = ["chain_1", "chain_2", "chain_1"]

    with pytest.raises(ValueError, match="Chain IDs must be unique"):
        create_initial_assignments(players, chains)