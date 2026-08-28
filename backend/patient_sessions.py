from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .dataset_config import dataset_settings
from .posture_stream import store as posture_store
from .rehab_modules import RehabModuleRegistry

ACTIVE_STATES = ("CREATED", "SETUP", "READY", "ACTIVE", "PAUSED")
TERMINAL_STATES = ("COMPLETED", "ENDED", "ERROR")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PatientSessionCreate(BaseModel):
    exercise_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]{1,63}$")
    rehab_type: str = Field(min_length=1, max_length=64)
    affected_side: Literal["LEFT", "RIGHT", "UNKNOWN", "N/A"] | None = None


class PatientSessionStore:
    def __init__(self, database_path: Path, registry: RehabModuleRegistry):
        self.database_path = database_path
        self.registry = registry
        self.lock = threading.RLock()
        self._initialize()

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _initialize(self) -> None:
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS patient_exercise_sessions (
                session_id TEXT PRIMARY KEY, exercise_id TEXT NOT NULL, rehab_type TEXT NOT NULL,
                affected_side TEXT, created_at TEXT NOT NULL, started_at TEXT, paused_at TEXT,
                ended_at TEXT, status TEXT NOT NULL, active_started_at TEXT,
                active_seconds REAL NOT NULL DEFAULT 0, paused_seconds REAL NOT NULL DEFAULT 0,
                pause_started_at TEXT, target_repetitions INTEGER, completed_repetitions INTEGER,
                attempt_count INTEGER, ready INTEGER NOT NULL DEFAULT 0, tracking_state TEXT NOT NULL,
                exercise_phase TEXT, source TEXT NOT NULL DEFAULT 'FLEXMAP_CV')""")

    def _new_id(self, db: sqlite3.Connection) -> str:
        day = utc_now().strftime("%Y%m%d")
        prefix = f"PATIENT-{day}-"
        row = db.execute("SELECT session_id FROM patient_exercise_sessions WHERE session_id LIKE ? ORDER BY session_id DESC LIMIT 1", (prefix + "%",)).fetchone()
        sequence = int(row[0].rsplit("-", 1)[-1]) + 1 if row else 1
        return f"{prefix}{sequence:04d}"

    def _serialize(self, row: sqlite3.Row) -> dict:
        item = dict(row)
        now = utc_now()
        active = float(item["active_seconds"])
        paused = float(item["paused_seconds"])
        if item["status"] == "ACTIVE" and item["active_started_at"]:
            active += max(0, (now - datetime.fromisoformat(item["active_started_at"])).total_seconds())
        if item["status"] == "PAUSED" and item["pause_started_at"]:
            paused += max(0, (now - datetime.fromisoformat(item["pause_started_at"])).total_seconds())
        end = datetime.fromisoformat(item["ended_at"]) if item["ended_at"] else now
        total = max(0, (end - datetime.fromisoformat(item["created_at"])).total_seconds())
        item.update(ready=bool(item["ready"]), active_duration=round(active, 3),
                    paused_duration=round(paused, 3), elapsed_duration=round(total, 3))
        item.pop("active_started_at", None); item.pop("pause_started_at", None)
        item.pop("active_seconds", None); item.pop("paused_seconds", None)
        return item

    def get(self, session_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM patient_exercise_sessions WHERE session_id=?", (session_id,)).fetchone()
        return self._serialize(row) if row else None

    def active(self) -> dict | None:
        placeholders = ",".join("?" for _ in ACTIVE_STATES)
        with self._db() as db:
            row = db.execute(f"SELECT * FROM patient_exercise_sessions WHERE status IN ({placeholders}) ORDER BY created_at DESC LIMIT 1", ACTIVE_STATES).fetchone()
        return self._serialize(row) if row else None

    def create(self, request: PatientSessionCreate) -> dict:
        module = self.registry.by_id(request.rehab_type)
        if not module.enabled or module.slug != request.exercise_id:
            raise ValueError("Exercise does not match an enabled rehabilitation module")
        with self.lock, self._db() as db:
            existing = db.execute("SELECT session_id FROM patient_exercise_sessions WHERE status IN ('CREATED','SETUP','READY','ACTIVE','PAUSED') LIMIT 1").fetchone()
            if existing:
                raise RuntimeError(existing["session_id"])
            session_id = self._new_id(db); now = utc_now().isoformat()
            snapshot = posture_store.latest(); ready = bool(snapshot and snapshot.ready)
            tracking = snapshot.tracking_quality if snapshot else "UNAVAILABLE"
            db.execute("INSERT INTO patient_exercise_sessions(session_id,exercise_id,rehab_type,affected_side,created_at,status,ready,tracking_state) VALUES(?,?,?,?,?,?,?,?)",
                       (session_id, request.exercise_id, module.id, request.affected_side, now, "READY" if ready else "SETUP", int(ready), tracking))
        return self.get(session_id)  # type: ignore[return-value]

    def _transition(self, session_id: str, action: str) -> dict:
        with self.lock, self._db() as db:
            row = db.execute("SELECT * FROM patient_exercise_sessions WHERE session_id=?", (session_id,)).fetchone()
            if not row: raise KeyError(session_id)
            status = row["status"]; now = utc_now(); stamp = now.isoformat()
            if action == "start":
                if status not in ("CREATED", "SETUP", "READY"): raise ValueError(f"Cannot start a {status} session")
                db.execute("UPDATE patient_exercise_sessions SET status='ACTIVE',started_at=COALESCE(started_at,?),active_started_at=?,paused_at=NULL,pause_started_at=NULL WHERE session_id=?", (stamp, stamp, session_id))
            elif action == "pause":
                if status != "ACTIVE": raise ValueError(f"Cannot pause a {status} session")
                active = float(row["active_seconds"]) + max(0, (now - datetime.fromisoformat(row["active_started_at"])).total_seconds())
                db.execute("UPDATE patient_exercise_sessions SET status='PAUSED',paused_at=?,pause_started_at=?,active_started_at=NULL,active_seconds=? WHERE session_id=?", (stamp, stamp, active, session_id))
            elif action == "resume":
                if status != "PAUSED": raise ValueError(f"Cannot resume a {status} session")
                paused = float(row["paused_seconds"]) + max(0, (now - datetime.fromisoformat(row["pause_started_at"])).total_seconds())
                db.execute("UPDATE patient_exercise_sessions SET status='ACTIVE',active_started_at=?,pause_started_at=NULL,paused_seconds=? WHERE session_id=?", (stamp, paused, session_id))
            elif action == "end":
                if status in TERMINAL_STATES: raise ValueError(f"Cannot end a {status} session")
                active = float(row["active_seconds"]); paused = float(row["paused_seconds"])
                if status == "ACTIVE" and row["active_started_at"]: active += max(0, (now - datetime.fromisoformat(row["active_started_at"])).total_seconds())
                if status == "PAUSED" and row["pause_started_at"]: paused += max(0, (now - datetime.fromisoformat(row["pause_started_at"])).total_seconds())
                db.execute("UPDATE patient_exercise_sessions SET status='ENDED',ended_at=?,active_started_at=NULL,pause_started_at=NULL,active_seconds=?,paused_seconds=? WHERE session_id=?", (stamp, active, paused, session_id))
            else: raise ValueError("Unknown session action")
        return self.get(session_id)  # type: ignore[return-value]

    def start(self, session_id: str) -> dict: return self._transition(session_id, "start")
    def pause(self, session_id: str) -> dict: return self._transition(session_id, "pause")
    def resume(self, session_id: str) -> dict: return self._transition(session_id, "resume")
    def end(self, session_id: str) -> dict: return self._transition(session_id, "end")


settings = dataset_settings()
session_store = PatientSessionStore(settings.database_path, RehabModuleRegistry(settings.modules_path))
router = APIRouter(prefix="/api/patient/sessions", tags=["Patient Sessions"])

def found(session_id: str) -> dict:
    item = session_store.get(session_id)
    if not item: raise HTTPException(404, "Patient session not found")
    return item

@router.post("")
def create_session(request: PatientSessionCreate):
    try: return session_store.create(request)
    except RuntimeError as exc: raise HTTPException(409, {"message":"A patient session is already in progress", "session_id":str(exc)}) from exc
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc

@router.get("/active")
def active_session(): return session_store.active()

@router.get("/{session_id}")
def get_session(session_id: str): return found(session_id)

def action(session_id: str, name: str):
    try: return getattr(session_store, name)(session_id)
    except KeyError as exc: raise HTTPException(404, "Patient session not found") from exc
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc

@router.post("/{session_id}/start")
def start_session(session_id: str): return action(session_id, "start")
@router.post("/{session_id}/pause")
def pause_session(session_id: str): return action(session_id, "pause")
@router.post("/{session_id}/resume")
def resume_session(session_id: str): return action(session_id, "resume")
@router.post("/{session_id}/end")
def end_session(session_id: str): return action(session_id, "end")
@router.get("/{session_id}/summary")
def session_summary(session_id: str): return found(session_id)
