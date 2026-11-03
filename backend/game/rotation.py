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
        raise ValueError("Round number must be between 1 and the player count.")
 
    initial_chains = [ initial_assignments[player] for player in player_order ]

    round_assignments = {}
    for i in range(0, len(player_order)):
        chain_index = (i + round_number) % len(player_order)
        assigned_chain = initial_chains[chain_index]
        round_assignments[player_order[i]] = assigned_chain

    return round_assignments
