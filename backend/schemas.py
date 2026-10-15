from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PostureState(str, Enum):
    GREEN = "GREEN"
    ORANGE = "ORANGE"
    RED = "RED"
    GREY = "GREY"


class ComponentSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")
    state: PostureState
    value: Optional[float] = None
    units: Optional[str] = None
    confidence: Optional[float] = None
    display_name: Optional[str] = None


class DisplayLandmark(BaseModel):
    x: float
    y: float
    z: Optional[float] = None
    visibility: Optional[float] = None
    presence: Optional[float] = None
    valid: bool = True


class PostureSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")
    timestamp: float
    capture_frame_id: Optional[int] = None
    capture_timestamp_ns: Optional[int] = None
    connected: bool = True
    tracking_quality: str = "UNKNOWN"
    overall_state: PostureState
    ready: bool
    ready_progress: float = Field(default=0.0, ge=0.0, le=1.0)
    ready_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    baseline_captured: bool = False
    ready_stage: Optional[str] = None
    landmarks: dict[str, DisplayLandmark] = Field(default_factory=dict)
    components: dict[str, ComponentSnapshot] = Field(default_factory=dict)
    feedback: list[str] = Field(default_factory=list, max_length=2)
    confidence: Optional[float] = None
    fps: Optional[float] = None
    # Existing exercise-engine output forwarded by the CV bridge.
    exercise_snapshot: Optional[dict] = None


class EngineStatus(BaseModel):
    cv_engine: str
    pose_model: Optional[bool] = None
    hand_model: Optional[bool] = None
    camera: Optional[bool] = None
    websocket_clients: int
    last_update: Optional[float] = None
