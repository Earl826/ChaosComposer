from dataclasses import dataclass, field
from enum import Enum


class GamePhase(str, Enum):
    LOBBY = "lobby"
    PROMPT_SUBMISSION = "prompt_submission"
    COMPOSING = "composing"
    TRANSITIONING = "transitioning"
    FINISHED = "finished"


@dataclass
class GameState:
    id: str
    host_id: str

    phase: GamePhase = GamePhase.LOBBY
    round_index: int | None = None

    player_order: list[str] = field(default_factory=list)
    chain_ids: list[str] = field(default_factory=list)
    initial_assignments: dict[str, str] = field(default_factory=dict)
    prompt_chain_ids: dict[str, str] = field(default_factory=dict)
    submitted_player_ids: set[str] = field(default_factory=set)
    state_version: int = 0

    @property
    def total_rounds(self) -> int:
        if self.phase == GamePhase.LOBBY:
            return 0
        return len(self.player_order)

    @property
    def current_round(self) -> int:
        if self.round_index is None:
            return 0
        return self.round_index + 1

    