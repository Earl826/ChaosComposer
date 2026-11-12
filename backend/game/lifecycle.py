from .state import GameState, GamePhase
from .rotation import create_initial_assignments, get_round_assignments


MIN_PLAYERS = 4
MAX_PLAYERS = 6


def start_game(game: GameState, requesting_player_id: str) -> None:
    if game.phase != GamePhase.LOBBY:
        raise ValueError("Game can only be started from the lobby")

    if requesting_player_id != game.host_id:
        raise PermissionError("Only the host can start the game")

    if not MIN_PLAYERS <= len(game.player_order) <= MAX_PLAYERS:
        raise ValueError("Game requires between 4 and 6 players")

    if len(set(game.player_order)) != len(game.player_order):
        raise ValueError("Player IDs have to be unique")

    game.phase = GamePhase.PROMPT_SUBMISSION
    game.state_version += 1


def start_composing(game: GameState) -> None:
    if game.phase != GamePhase.PROMPT_SUBMISSION:
        raise ValueError("Game can only progress to composing if in prompt submission")

    if not(bool(game.player_order and set(game.prompt_chain_ids) == set(game.player_order))):
        raise ValueError("Not everyone has submitted their prompt yet")

    if len(set(game.prompt_chain_ids.values())) != len(game.prompt_chain_ids):
        raise ValueError("Not a unique chain per player")
    
    chain_ids = [
        game.prompt_chain_ids[player_id] for player_id in game.player_order
    ]

    rotated_chain_ids = chain_ids[1:] + chain_ids[:1]

    initial_assignments = create_initial_assignments(
        game.player_order,
        rotated_chain_ids
    )

    game.chain_ids = chain_ids
    game.initial_assignments = initial_assignments
    game.round_index = 0

    game.submitted_player_ids.clear()
    game.phase = GamePhase.COMPOSING
    game.state_version += 1


def get_player_assignment(game: GameState, player_id: str) -> str:
    if game.phase != GamePhase.COMPOSING or game.round_index is None:
        raise ValueError("To get player assignments, game must be in composing phase")

    if player_id not in game.initial_assignments:
        raise ValueError("Referenced player not in game")

    round_assignments = get_round_assignments(game.player_order, game.initial_assignments, game.round_index)
    return round_assignments[player_id]


def record_player_submission(game: GameState, player_id: str) -> bool:
    if game.phase != GamePhase.COMPOSING:
        raise ValueError("Can only record player submission if game in composing phase")
    if player_id not in game.player_order:
        raise ValueError("Referenced player not in game")
    if player_id in game.submitted_player_ids:
        raise ValueError("Referenced player already submitted")

    game.submitted_player_ids.add(player_id)
    game.state_version += 1

    if len(game.player_order) == len(game.submitted_player_ids):
        return True
    return False
    

def begin_round_transition(
    game: GameState, 
    expected_round: int | None = None,
    expected_state_version: int | None = None
) -> None:
    if game.phase != GamePhase.COMPOSING or game.round_index is None:
        raise ValueError("Game must be in composing phase to begin round transition")

    if expected_round is not None and expected_round != game.current_round:
        raise ValueError("Expected round was provided and does not match the game state's current round")

    if expected_state_version is not None and expected_state_version != game.state_version:
        raise ValueError("Expected state version was provided and is stale")

    if set(game.submitted_player_ids) != set(game.player_order):
        raise ValueError("Not all players submitted a composition")

    game.phase = GamePhase.TRANSITIONING
    game.state_version += 1


def complete_round_transition(
        game: GameState,
        expected_state_version: int | None = None
) -> None:
    if game.phase != GamePhase.TRANSITIONING or game.round_index is None:
        raise ValueError("Game must be in transitioning phase to complete a round transition")

    if expected_state_version is not None and expected_state_version != game.state_version:
        raise ValueError("Expected state version was provided and is stale")

    game.submitted_player_ids.clear()

    if game.current_round >= game.total_rounds:
        game.phase = GamePhase.FINISHED
    else:
        game.round_index += 1
        game.phase = GamePhase.COMPOSING

    game.state_version += 1
    
    