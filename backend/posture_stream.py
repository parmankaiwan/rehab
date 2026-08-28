from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Optional

from .schemas import ComponentSnapshot, PostureSnapshot, PostureState
from .video_store import video_store


class PostureStateStore:
    """Thread-safe boundary between the existing CV loop and web delivery."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshot: Optional[PostureSnapshot] = None
        self._frame: Optional[bytes] = None
        self._frame_updated_at: Optional[float] = None
        self._engine_status: dict[str, Optional[bool]] = {
            "pose_model": None, "hand_model": None, "camera": None
        }
        self._reset_callback: Optional[Callable[[], None]] = None
        self.clients = 0
        self.reset_generation = 0

    def update(self, snapshot: PostureSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot.model_copy(deep=True)

    def latest(self) -> Optional[PostureSnapshot]:
        with self._lock:
            return self._snapshot.model_copy(deep=True) if self._snapshot else None

    def update_frame(self, jpeg: bytes) -> None:
        with self._lock:
            self._frame = bytes(jpeg)
            self._frame_updated_at = time.monotonic()

    def latest_frame(self) -> Optional[bytes]:
        with self._lock:
            return self._frame

    def frame_is_fresh(self, stale_after: float = 2.5) -> bool:
        with self._lock:
            return self._frame_updated_at is not None and time.monotonic() - self._frame_updated_at <= stale_after

    def set_engine_status(self, **values: Optional[bool]) -> None:
        with self._lock:
            for key in self._engine_status:
                if key in values:
                    self._engine_status[key] = values[key]

    def status(self) -> dict[str, Any]:
        with self._lock:
            latest = self._snapshot
            return {
                "cv_engine": "running" if latest and latest.connected else "waiting",
                **self._engine_status,
                "websocket_clients": self.clients,
                "last_update": latest.timestamp if latest else None,
            }

    def register_reset(self, callback: Callable[[], None]) -> None:
        self._reset_callback = callback

    def reset(self) -> None:
        self.reset_generation += 1
        if self._reset_callback:
            self._reset_callback()
        with self._lock:
            self._snapshot = None


store = PostureStateStore()


def snapshot_from_posture_data(data: Any, *, ready_progress: float = 0.0, fps: Optional[float] = None) -> PostureSnapshot:
    """Serialize engine output without making classification decisions."""
    criteria = getattr(data, "criteria", {})
    components: dict[str, ComponentSnapshot] = {}
    for key, item in criteria.items():
        state = getattr(getattr(item, "status", "GREY"), "value", getattr(item, "status", "GREY"))
        components[key] = ComponentSnapshot(
            state=PostureState(state), value=getattr(item, "value", None),
            units=getattr(item, "units", None), confidence=getattr(item, "confidence", None),
            display_name=getattr(item, "display_name", None),
        )
    overall = getattr(getattr(data, "posture_state", "GREY"), "value", getattr(data, "posture_state", "GREY"))
    quality = getattr(getattr(data, "tracking_quality", "UNKNOWN"), "value", getattr(data, "tracking_quality", "UNKNOWN"))
    ready = bool(getattr(data, "green_allowed", False))
    return PostureSnapshot(
        timestamp=time.time(),
        tracking_quality=str(quality), overall_state=PostureState(overall), ready=ready,
        ready_progress=1.0 if ready else ready_progress,
        components=components, feedback=list(getattr(data, "corrections", ()))[:2], fps=fps,
    )


async def mjpeg_frames(interval: float = 1 / 30):
    last: Optional[bytes] = None
    while True:
        if not video_store.is_fresh():
            return
        packet = video_store.latest()
        frame = packet.jpeg if packet else None
        if frame and frame != last:
            last = frame
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        await asyncio.sleep(interval)

