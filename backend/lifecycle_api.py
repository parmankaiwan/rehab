"""Authenticated bridge from the Master UI to the local Windows supervisor."""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from .master_dataset_api import recorder, require_master
from .emg.api import service as emg_service

router = APIRouter(prefix="/api/master/lifecycle", tags=["Local lifecycle"], dependencies=[Depends(require_master)])
shutdown_requested = threading.Event()
_interruption_lock = threading.Lock()
_journaled_interruptions: set[tuple[str, str | None]] = set()
INTERRUPTION_JOURNAL = Path(__file__).resolve().parent.parent / "data" / "runtime" / "interrupted-recordings.jsonl"


def prepare_for_shutdown() -> list[dict[str, str | None]]:
    """Stop active acquisition without ever presenting a partial trial as saved."""
    shutdown_requested.set()
    interrupted: list[dict[str, str | None]] = []
    cv_status = recorder.status()
    if cv_status.state.value in {"CONFIGURED", "COUNTDOWN", "RECORDING"}:
        key = ("CV", cv_status.recording_id)
        if key not in _journaled_interruptions:
            interrupted.append({"modality": key[0], "recording_id": key[1]})
            _journaled_interruptions.add(key)
        try:
            recorder.cancel()
        except RuntimeError:
            pass
    emg_status = emg_service.recording_status()
    if emg_status.get("state") in {"CONFIGURED", "COUNTDOWN", "RECORDING"}:
        key = ("EMG", emg_status.get("recording_id"))
        if key not in _journaled_interruptions:
            interrupted.append({"modality": key[0], "recording_id": key[1]})
            _journaled_interruptions.add(key)
        emg_service.cancel()
    if interrupted:
        journal = INTERRUPTION_JOURNAL
        journal.parent.mkdir(parents=True, exist_ok=True)
        event = {"status": "INTERRUPTED", "timestamp_utc": datetime.now(timezone.utc).isoformat(), "recordings": interrupted}
        with _interruption_lock, journal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")
    return interrupted


def _local_enabled(request: Request) -> tuple[str, str]:
    if os.getenv("FLEXMAP_LOCAL_LIFECYCLE_ENABLED", "").lower() != "true":
        raise HTTPException(409, "Lifecycle controls are available only in the local FlexMap application")
    if not request.client or request.client.host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(403, "Lifecycle controls require a loopback request")
    url = os.getenv("FLEXMAP_LIFECYCLE_URL", "")
    token = os.getenv("FLEXMAP_LIFECYCLE_TOKEN", "")
    if not url.startswith("http://127.0.0.1:") or not token:
        raise HTTPException(503, "Local FlexMap supervisor is unavailable")
    return url.rstrip("/"), token


def _supervisor(request: Request, path: str, method: str = "GET", payload: dict | None = None) -> dict:
    url, token = _local_enabled(request)
    outbound = urllib.request.Request(
        url + path,
        method=method,
        headers={"X-FlexMap-Lifecycle-Token": token, "Content-Type": "application/json"},
        data=json.dumps(payload or {}).encode("utf-8") if method == "POST" else None,
    )
    try:
        with urllib.request.urlopen(outbound, timeout=5) as response:
            value = json.loads(response.read().decode("utf-8"))
            return value if isinstance(value, dict) else {"status": "UNKNOWN"}
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise HTTPException(503, "Local FlexMap supervisor is unavailable") from exc


@router.get("/status")
def lifecycle_status(request: Request):
    if os.getenv("FLEXMAP_LOCAL_LIFECYCLE_ENABLED", "").lower() != "true":
        # Capability discovery is not an exceptional condition. Hosted and
        # independently started services deliberately have no process controls.
        return {"available": False, "deployment": "HOSTED_OR_INDEPENDENT", "application": "UNMANAGED", "controls": {"reconnect_cv": False, "reconnect_emg": False, "exit": False}}
    return _supervisor(request, "/status")


@router.post("/reconnect/{target}")
def lifecycle_reconnect(target: str, request: Request):
    if target not in {"cv", "emg"}:
        raise HTTPException(404, "Unknown hardware subsystem")
    return _supervisor(request, f"/reconnect/{target}", "POST")


@router.post("/camera-lease")
async def lifecycle_camera_lease(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict) or payload.get("action") not in {"acquire", "renew", "release"}:
        raise HTTPException(422, "Invalid camera lease action")
    return _supervisor(request, "/camera/lease", "POST", {"lease_id": payload.get("lease_id"), "action": payload["action"]})


@router.post("/stop")
def lifecycle_stop(request: Request):
    # Reject unavailable/non-loopback controls before cancelling any recording
    # or setting shutdown_requested. A rejected request must have no side effects.
    _local_enabled(request)
    interrupted = prepare_for_shutdown()
    result = _supervisor(request, "/stop", "POST")
    return {**result, "state": "STOPPING", "interrupted_recordings": interrupted}
