import csv
import json
from types import SimpleNamespace

from backend.cv_recording_service import CvRecordingService


def test_structured_package_preserves_frame_pose_rate_and_nulls(tmp_path):
    service = CvRecordingService.__new__(CvRecordingService)
    rid = "REC-20260907-000001"
    frame_index = [
        {"recording_id": rid, "capture_frame_id": i, "capture_timestamp_ns": i * 1_000_000,
         "relative_time_ms": float(i), "wall_time_utc": None, "raw_video_frame_index": i - 1,
         "annotated_video_frame_index": i - 1, "pose_result_available": i % 2 == 0,
         "pose_result_id": i // 2 if i % 2 == 0 else None, "tracking_state": "GOOD" if i % 2 == 0 else None,
         "recording_state": "RECORDING"}
        for i in range(1, 5)
    ]
    frames = [
        {"frame_id": i, "capture_timestamp_ns": i * 1_000_000, "timestamp_ms": i,
         "tracking_quality": "GOOD", "landmarks": {"RIGHT_WRIST": {"x": .5, "y": .4, "z": None,
         "visibility": .9, "presence": None, "valid": True}}}
        for i in (2, 4)
    ]
    measurements = [
        {"frame_id": i, "timestamp_ms": i, "tracking_quality": "GOOD", "overall_posture_state": "GREEN",
         "ready": True, "ready_progress": 1.0, "ready_stage": "READY", "feedback": [],
         "exercise_snapshot": None, "trunk_upright": {"value": None, "units": "degrees", "state": "GREY"}}
        for i in (2, 4)
    ]
    config = SimpleNamespace(session_id="SESSION-1", exercise_id=None, store_raw_video=True)
    service._write_structured_artifacts(tmp_path, rid, config, frames, frame_index, measurements, [], .1, 4, 4, 0)

    with (tmp_path / "frame_index.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4
    assert sum(row["pose_result_available"] == "True" for row in rows) == 2
    assert rows[0]["pose_result_id"] == ""
    with (tmp_path / "kinematics.csv").open(newline="", encoding="utf-8") as handle:
        kinematics = list(csv.DictReader(handle))
    assert "trunk_upright" not in kinematics[0]  # unavailable is not fabricated as zero
    assert json.loads((tmp_path / "rep_events.json").read_text())["authoritative"] is False
    assert not (tmp_path / "calibration.json").exists()


def test_integrity_detects_orphan_pose_reference(tmp_path):
    config = SimpleNamespace(store_raw_video=False)
    report = CvRecordingService._integrity_report(
        tmp_path, "REC-20260907-000002",
        [{"capture_frame_id": 1}, {"capture_frame_id": 2}],
        [{"frame_id": 3}], config,
    )
    assert report["status"] == "FAIL"
    assert "ORPHAN_POSE_FRAME_REFERENCE" in report["errors"]
