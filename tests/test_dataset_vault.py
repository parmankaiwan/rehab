from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import app
from backend.dataset_config import DatasetSettings
from backend.dataset_vault import DatasetVault


def settings(tmp_path: Path) -> DatasetSettings:
    labels = tmp_path / "labels.json"
    labels.write_text('{"STARTING_POSTURE":["acceptable_start"]}', encoding="utf-8")
    return DatasetSettings(root=tmp_path / "vault", labels_path=labels, countdown_seconds=0)


def make_temp(vault: DatasetVault, recording_id: str) -> None:
    folder = vault.temp_path(recording_id); folder.mkdir()
    landmarks = {"recording_id": recording_id, "frames": [{"frame_id": i, "timestamp_ms": i * 50, "tracking_quality": "GOOD", "landmarks": {"LEFT_SHOULDER": {"x": .3, "y": .2, "z": -.1, "visibility": .99, "valid": True}}} for i in range(30)]}
    measurements = {"recording_id": recording_id, "samples": [{"frame_id": i, "timestamp_ms": i * 75, "tracking_quality": "GOOD", "ready": True} for i in range(20)]}
    metadata = {"recording_id": recording_id, "subject_id": "P001", "category": "STARTING_POSTURE", "label": "acceptable_start", "affected_side": "RIGHT", "view": "Front", "notes": "", "session_id": "S1", "exercise_id": "E1", "trial_number": 1, "store_raw_video": True, "consent_recorded": True, "created_at": "2026-08-27T00:00:00+00:00", "duration_actual_seconds": 1.5, "frame_count": 30, "pose_result_count": 20, "tracking_good_ratio": 1.0, "tracking_poor_ratio": 0.0, "tracking_lost_ratio": 0.0}
    (folder / "landmarks.json").write_text(json.dumps(landmarks), encoding="utf-8")
    (folder / "landmarks.csv").write_text("recording_id,frame_id\n", encoding="utf-8")
    (folder / "measurements.json").write_text(json.dumps(measurements), encoding="utf-8")
    (folder / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (folder / "preview.jpg").write_bytes(b"jpeg")
    (folder / "video.mp4").write_bytes(b"mp4")


def test_vault_saves_thirty_frames_twenty_pose_results_and_survives_restart(tmp_path):
    config = settings(tmp_path); vault = DatasetVault(config); recording_id = vault.new_recording_id()
    make_temp(vault, recording_id); vault.save_temp(recording_id)
    restarted = DatasetVault(config); record = restarted.get(recording_id)
    assert record and record["frame_count"] == 30 and record["pose_result_count"] == 20
    assert len(record["metadata"]["recording_id"]) > 0
    assert (config.manifest_path).is_file()


def test_relabel_keeps_original_label_and_audit(tmp_path):
    config = settings(tmp_path); config.labels_path.write_text('{"STARTING_POSTURE":["acceptable_start","lean_left"]}', encoding="utf-8")
    vault = DatasetVault(config); recording_id = vault.new_recording_id(); make_temp(vault, recording_id); vault.save_temp(recording_id)
    updated = vault.update(recording_id, category="STARTING_POSTURE", label="lean_left", notes="reviewed")
    assert updated["label"] == "lean_left" and updated["original_label"] == "acceptable_start"


def test_master_dataset_api_rejects_missing_token(monkeypatch):
    monkeypatch.setenv("FLEXMAP_MASTER_INTERNAL_TOKEN", "test-internal-token")
    response = TestClient(app).get("/api/master/dataset/stats")
    assert response.status_code == 403


def test_recording_service_never_owns_video_capture():
    source = Path("backend/cv_recording_service.py").read_text(encoding="utf-8")
    assert "VideoCapture" not in source
