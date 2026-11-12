def get_round_assignments(
        player_order: list[str],
        initial_assignments: dict[str, str],
        round_number: int
) -> dict[str, str]:
    player_count = len(player_order)

    if not 4 <= player_count <= 6:
        raise ValueError("The game requires 4–6 players.")

    if len(set(player_order)) != player_count:
        raise ValueError("Player IDs must be unique.")

    if set(initial_assignments) != set(player_order):
        raise ValueError("Initial assignments must match the players exactly.")

    if len(set(initial_assignments.values())) != player_count:
        raise ValueError("Each player must start with a different chain.")

    if not 0 <= round_number < player_count:
        raise ValueError("Round number must be between 0 and the player count - 1.")
 
    initial_chains = [ initial_assignments[player] for player in player_order ]

    round_assignments = {}
    for i in range(0, len(player_order)):
        chain_index = (i + round_number) % len(player_order)
        assigned_chain = initial_chains[chain_index]
        round_assignments[player_order[i]] = assigned_chain

    return round_assignments


def create_initial_assignments(
        player_order: list[str],
        chain_ids: list[str],
) -> dict[str, str]:
    if len(player_order) != len(chain_ids):
        raise ValueError("Each player must have exactly one chain.")

    if len(set(player_order)) != len(player_order):
        raise ValueError("Player IDs must be unique.")

    if len(set(chain_ids)) != len(chain_ids):
        raise ValueError("Chain IDs must be unique.")

    return dict(zip(player_order, chain_ids))