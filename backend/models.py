"""Proposed MVP API models. Requires Pydantic 2.x.

These are contracts, not persistence models. Runtime handlers must validate requests.
Pattern format and instrument identifiers must be agreed with the sequencer owner.
"""
from enum import Enum
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=24)]
PromptText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Identifier = Annotated[str, StringConstraints(min_length=1)]

class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class ErrorResponse(APIModel):
    code: str
    detail: str

class GameStatus(str, Enum):
    lobby = "lobby"
    prompt_submission = "prompt_submission"
    composing = "composing"
    transitioning = "transitioning"
    finished = "finished"

class CreateSessionRequest(APIModel):
    player_name: Name

class JoinSessionRequest(APIModel):
    player_name: Name

class PlayerCredentials(APIModel):
    player_id: Identifier
    player_token: str = Field(description="Secret token sent in X-Player-Token. Never include in shared room state.")

class SessionCreated(PlayerCredentials):
    session_code: str = Field(min_length=4, max_length=4)

class PlayerInfo(APIModel):
    player_id: Identifier
    name: str
    is_host: bool
    is_ready: bool

class SessionState(APIModel):
    session_code: str
    status: GameStatus
    state_version: int = Field(ge=0, description="Monotonic revision for conditional state-changing requests.")
    current_round: int = Field(ge=0, description="0 before composing; composing rounds are numbered 1..total_rounds.")
    total_rounds: int = Field(ge=0, description="0 before start; frozen player count after start.")
    players: list[PlayerInfo]
    prompted_player_ids: list[str]
    submitted_player_ids: list[str] = Field(description="Accepted, persisted contributions for the current composing round only.")

class ReadyRequest(APIModel):
    is_ready: bool

class StartGameRequest(APIModel):
    expected_state_version: int = Field(ge=0)

class SubmitPromptRequest(APIModel):
    prompt: PromptText

class PatternTrack(APIModel):
    instrument: Identifier = Field(description="Agreed sequencer instrument ID, e.g. kick. No audio file required.")
    steps: list[bool] = Field(min_length=16, max_length=16, description="One on/off value for each of the 16 steps.")

class MusicalPattern(APIModel):
    schema_version: Literal["1.0"] = "1.0"
    tempo: float = Field(ge=30, le=300, description="BPM; proposed bounds to agree with the team.")
    step_count: Literal[16] = 16
    tracks: list[PatternTrack] = Field(min_length=1, max_length=16, description="Proposed percussion-only MVP format. Instrument IDs must be unique.")

class PromptAssignment(APIModel):
    kind: Literal["prompt"] = "prompt"
    chain_id: Identifier
    round: Literal[1] = 1
    prompt: str

class PatternAssignment(APIModel):
    kind: Literal["pattern"] = "pattern"
    chain_id: Identifier
    round: int = Field(ge=2)
    previous_version_id: Identifier
    pattern: MusicalPattern

class AssignmentResponse(APIModel):
    assignment: Annotated[Union[PromptAssignment, PatternAssignment], Field(discriminator="kind")]

class SubmitPatternRequest(APIModel):
    chain_id: Identifier
    expected_round: int = Field(ge=1)
    submission_id: Identifier = Field(description="Client-generated unique ID retained across retries; conflicting reuse is rejected.")
    pattern: MusicalPattern

class AdvanceRoundRequest(APIModel):
    expected_round: int = Field(ge=1)
    expected_state_version: int = Field(ge=0)

class StageResult(APIModel):
    version_id: Identifier
    round: int = Field(ge=1)
    player_id: Identifier
    player_name: str
    pattern: MusicalPattern

class ChainResult(APIModel):
    chain_id: Identifier
    original_prompt: str
    stages: list[StageResult]
    final_version_id: Identifier

class RevealResponse(APIModel):
    session_code: str
    chains: list[ChainResult]

class NegotiateRequest(APIModel):
    session_code: Identifier

class NegotiateResponse(APIModel):
    url: str
    access_token: str
