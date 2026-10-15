from pathlib import Path
import time
import pytest
from backend.patient_sessions import PatientSessionCreate, PatientSessionStore
from backend.rehab_modules import RehabModuleRegistry

REGISTRY = RehabModuleRegistry(Path(__file__).parents[1] / "config" / "rehab_modules.json")

@pytest.fixture
def sessions(tmp_path): return PatientSessionStore(tmp_path / "sessions.db", REGISTRY)

def request(): return PatientSessionCreate(exercise_id="reaching", rehab_type="REACHING")

def test_create_and_active_recovery(sessions):
    item=sessions.create(request())
    assert item["session_id"].startswith("PATIENT-")
    assert sessions.active()["session_id"]==item["session_id"]
    assert item["completed_repetitions"] is None

def test_records_browser_pose_source_without_changing_default(sessions):
    browser = PatientSessionCreate(exercise_id="reaching", rehab_type="REACHING", source="BROWSER_MEDIAPIPE")
    assert sessions.create(browser)["source"] == "BROWSER_MEDIAPIPE"

def test_prevents_duplicate_active_session(sessions):
    first=sessions.create(request())
    with pytest.raises(RuntimeError,match=first["session_id"]): sessions.create(request())

def test_start_pause_resume_end_and_summary(sessions):
    sid=sessions.create(request())["session_id"]
    assert sessions.start(sid)["status"]=="ACTIVE"
    time.sleep(.02)
    paused=sessions.pause(sid); assert paused["status"]=="PAUSED" and paused["active_duration"]>0
    time.sleep(.02)
    resumed=sessions.resume(sid); assert resumed["status"]=="ACTIVE" and resumed["paused_duration"]>0
    ended=sessions.end(sid); assert ended["status"]=="ENDED" and ended["ended_at"]
    assert sessions.active() is None

def test_invalid_transitions_and_unknown_session(sessions):
    sid=sessions.create(request())["session_id"]
    with pytest.raises(ValueError): sessions.pause(sid)
    with pytest.raises(KeyError): sessions.start("PATIENT-UNKNOWN")

def test_persists_across_store_restart(sessions):
    sid=sessions.create(request())["session_id"]
    sessions.start(sid); sessions.pause(sid)
    restarted=PatientSessionStore(sessions.database_path,REGISTRY)
    assert restarted.active()["session_id"]==sid
    assert restarted.active()["status"]=="PAUSED"
