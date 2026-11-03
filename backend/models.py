from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class RoundStatus(str, Enum):
    lobby = "lobby"          # players are joining
    recording = "recording"  # a round is open for uploads
    mixing = "mixing"        # game ended, mixes being built
    finished = "finished"    # mixes ready for reveal


class ErrorResponse(BaseModel):
    code: str = Field(..., examples=["session_not_found"])
    detail: str = Field(..., examples=["No session with code K7QX"])


class CreateSessionRequest(BaseModel):
    player_name: str = Field(..., min_length=1, max_length=24, examples=["Ana"])


class JoinSessionRequest(BaseModel):
    player_name: str = Field(..., min_length=1, max_length=24, examples=["Ben"])


class PlayerCredentials(BaseModel):
    player_id: str
    player_token: str = Field(..., description="Send as the X-Player-Token header on later requests.")


class SessionCreated(PlayerCredentials):
    session_code: str = Field(..., min_length=4, max_length=4, examples=["K7QX"])


class PlayerInfo(BaseModel):
    player_id: str
    name: str
    is_host: bool


class SessionState(BaseModel):
    session_code: str
    status: RoundStatus
    current_round: int = Field(..., ge=0)
    players: list[PlayerInfo]
    submitted_player_ids: list[str] = Field(..., description="Players who have submitted this round.")


class UploadLinkRequest(BaseModel):
    content_type: str = Field(..., examples=["audio/webm"])
    size_bytes: int = Field(..., gt=0, le=5_000_000)


class UploadLink(BaseModel):
    upload_url: str
    blob_name: str = Field(..., description="Send this back in the submissions call.")
    expires_at: datetime


class SubmitClipRequest(BaseModel):
    blob_name: str
    duration_seconds: float = Field(..., gt=0, le=60)


class ClipLink(BaseModel):
    """The prompt is never included. Players hear only the audio."""

    chain_id: str
    round: int = Field(..., ge=0)
    read_url: str
    expires_at: datetime


class StageResult(BaseModel):
    round: int = Field(..., ge=0)
    player_name: str
    clip_url: str


class ChainResult(BaseModel):
    chain_id: str
    original_prompt: str
    stages: list[StageResult]
    final_mix_url: str


class RevealResponse(BaseModel):
    session_code: str
    chains: list[ChainResult]


class NegotiateResponse(BaseModel):
    url: str
    access_token: str