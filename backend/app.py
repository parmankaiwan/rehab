from __future__ import annotations

import asyncio
import hmac
import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    # Environment variables still work without python-dotenv.
    pass

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .posture_stream import mjpeg_frames, store
from .schemas import EngineStatus, PostureSnapshot
from .video_store import raw_video_store, video_store
from .webrtc_video import RTCAnswer, RTCOffer, answer_offer, close_peers
from .master_dataset_api import router as master_dataset_router
from .emg.api import router as emg_router, ws_router as emg_ws_router, service as emg_service
from .emg.schemas import RemoteEmgBatch
from .sessions import router as sessions_router
from .patient_sessions import router as patient_sessions_router
from .acquisition import router as acquisition_router
from .ml import router as ml_router

app = FastAPI(title="FlexMap Posture Bridge", version="1.0.0")
origins = [value.strip() for value in os.getenv("FLEXMAP_CORS_ORIGINS", "http://localhost:3000").split(",") if value.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["GET", "POST"], allow_headers=["*"])
app.include_router(master_dataset_router)
app.include_router(emg_router)
app.include_router(emg_ws_router)
app.include_router(sessions_router)
app.include_router(patient_sessions_router)
app.include_router(acquisition_router)
app.include_router(ml_router)


def require_engine(request: Request) -> None:
    """Authenticate CV engine writes when a deployment token is configured."""
    expected = os.getenv("FLEXMAP_ENGINE_TOKEN", "")
    supplied = request.headers.get("x-flexmap-engine-token", "")
    if expected and not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="CV engine authorization required")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status", response_model=EngineStatus)
def status() -> dict:
    return store.status()


@app.post("/api/reset")
def reset() -> dict[str, bool]:
    store.reset()
    return {"success": True}


@app.post("/api/engine/snapshot", include_in_schema=False)
def receive_engine_snapshot(snapshot: PostureSnapshot, request: Request) -> dict[str, bool | int]:
    require_engine(request)
    store.update(snapshot)
    return {"success": True, "reset_generation": store.reset_generation}


@app.post("/api/engine/frame", include_in_schema=False)
async def receive_engine_frame(request: Request) -> dict[str, bool]:
    require_engine(request)
    frame = await request.body()
    if len(frame) < 4 or len(frame) > 2_000_000 or not frame.startswith(bytes((255, 216))):
        raise HTTPException(status_code=400, detail="Invalid JPEG frame")
    def number(name: str) -> float | None:
        value = request.headers.get(name)
        try:
            return float(value) if value is not None else None
        except ValueError:
            return None
    sequence = number("x-flexmap-frame-sequence")
    video_store.update(frame, sequence=int(sequence) if sequence is not None else None, source_timestamp=number("x-flexmap-source-timestamp"), annotated_timestamp=number("x-flexmap-annotated-timestamp"), jpeg_encode_ms=number("x-flexmap-jpeg-encode-ms"))
    return {"success": True}

@app.post("/api/engine/raw-frame", include_in_schema=False)
async def receive_engine_raw_frame(request: Request) -> dict[str, bool]:
    require_engine(request)
    frame = await request.body()
    if len(frame) < 4 or len(frame) > 2_000_000 or not frame.startswith(bytes((255, 216))):
        raise HTTPException(status_code=400, detail="Invalid JPEG frame")
    def number(name: str) -> float | None:
        try: return float(request.headers[name]) if name in request.headers else None
        except ValueError: return None
    sequence = number("x-flexmap-frame-sequence")
    capture_ns = number("x-flexmap-capture-timestamp-ns")
    raw_video_store.update(frame, sequence=int(sequence) if sequence is not None else None, source_timestamp=number("x-flexmap-source-timestamp"), jpeg_encode_ms=number("x-flexmap-jpeg-encode-ms"), capture_timestamp_ns=int(capture_ns) if capture_ns is not None else None)
    return {"success": True}

@app.post("/api/engine/status", include_in_schema=False)
def receive_engine_status(status: dict[str, bool | None], request: Request) -> dict[str, bool]:
    require_engine(request)
    store.set_engine_status(**status)
    return {"success": True}


@app.post("/api/engine/emg/batch", include_in_schema=False)
def receive_engine_emg_batch(batch: RemoteEmgBatch, request: Request) -> dict:
    require_engine(request)
    try:
        return emg_service.ingest_remote_batch(batch)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/webrtc/offer", response_model=RTCAnswer)
async def webrtc_offer(offer: RTCOffer) -> RTCAnswer:
    if not video_store.is_fresh():
        raise HTTPException(status_code=503, detail="Live annotated frame is unavailable")
    return await answer_offer(offer)


@app.get("/api/video/metrics")
def video_metrics() -> dict:
    return video_store.metrics()


@app.on_event("shutdown")
async def shutdown_webrtc() -> None:
    await close_peers()
    emg_service.disconnect()

@app.get("/video-feed")
def video_feed() -> StreamingResponse:
    if not video_store.is_fresh():
        raise HTTPException(status_code=503, detail="Annotated camera stream is not available")
    return StreamingResponse(mjpeg_frames(), media_type="multipart/x-mixed-replace; boundary=frame", headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache", "X-Accel-Buffering": "no"})


@app.websocket("/ws/posture")
async def posture_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    store.clients += 1
    rate = max(1.0, min(float(os.getenv("FLEXMAP_WS_HZ", "15")), 20.0))
    try:
        while True:
            snapshot = store.latest()
            if snapshot:
                await websocket.send_json(snapshot.model_dump(mode="json"))
            else:
                await websocket.send_json({"type": "waiting", "message": "Waiting for FlexMap CV engine"})
            await asyncio.sleep(1 / rate)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        store.clients = max(0, store.clients - 1)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app:app", host="127.0.0.1", port=8000, reload=False, access_log=False)
