from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend import lifecycle_api


def request(host: str = "127.0.0.1"):
    return SimpleNamespace(client=SimpleNamespace(host=host))


def test_lifecycle_controls_are_disabled_without_local_supervisor(monkeypatch):
    monkeypatch.delenv("FLEXMAP_LOCAL_LIFECYCLE_ENABLED", raising=False)
    with pytest.raises(HTTPException) as exc:
        lifecycle_api._local_enabled(request())
    assert exc.value.status_code == 409


def test_lifecycle_controls_reject_non_loopback(monkeypatch):
    monkeypatch.setenv("FLEXMAP_LOCAL_LIFECYCLE_ENABLED", "true")
    with pytest.raises(HTTPException) as exc:
        lifecycle_api._local_enabled(request("10.0.0.2"))
    assert exc.value.status_code == 403


def test_lifecycle_requires_pinned_loopback_url_and_token(monkeypatch):
    monkeypatch.setenv("FLEXMAP_LOCAL_LIFECYCLE_ENABLED", "true")
    monkeypatch.setenv("FLEXMAP_LIFECYCLE_URL", "https://example.com")
    monkeypatch.setenv("FLEXMAP_LIFECYCLE_TOKEN", "secret")
    with pytest.raises(HTTPException) as exc:
        lifecycle_api._local_enabled(request())
    assert exc.value.status_code == 503


def test_lifecycle_accepts_configured_loopback_supervisor(monkeypatch):
    monkeypatch.setenv("FLEXMAP_LOCAL_LIFECYCLE_ENABLED", "true")
    monkeypatch.setenv("FLEXMAP_LIFECYCLE_URL", "http://127.0.0.1:8766")
    monkeypatch.setenv("FLEXMAP_LIFECYCLE_TOKEN", "secret")
    assert lifecycle_api._local_enabled(request()) == ("http://127.0.0.1:8766", "secret")


def test_shutdown_marks_active_recordings_interrupted_without_false_save(tmp_path, monkeypatch):
    journal = tmp_path / "interrupted-recordings.jsonl"
    cancelled: list[str] = []
    monkeypatch.setattr(lifecycle_api, "INTERRUPTION_JOURNAL", journal)
    monkeypatch.setattr(
        lifecycle_api,
        "recorder",
        SimpleNamespace(
            status=lambda: SimpleNamespace(state=SimpleNamespace(value="RECORDING"), recording_id="CV-123"),
            cancel=lambda: cancelled.append("CV"),
        ),
    )
    monkeypatch.setattr(
        lifecycle_api,
        "emg_service",
        SimpleNamespace(
            recording_status=lambda: {"state": "COUNTDOWN", "recording_id": "EMG-456"},
            cancel=lambda: cancelled.append("EMG"),
        ),
    )
    lifecycle_api.shutdown_requested.clear()
    lifecycle_api._journaled_interruptions.clear()
    try:
        interrupted = lifecycle_api.prepare_for_shutdown()
        event = json.loads(journal.read_text(encoding="utf-8"))
        assert interrupted == [
            {"modality": "CV", "recording_id": "CV-123"},
            {"modality": "EMG", "recording_id": "EMG-456"},
        ]
        assert cancelled == ["CV", "EMG"]
        assert event["status"] == "INTERRUPTED"
        assert event["recordings"] == interrupted
        assert "participant" not in event
    finally:
        lifecycle_api.shutdown_requested.clear()
        lifecycle_api._journaled_interruptions.clear()


def test_shutdown_during_idle_monitoring_creates_no_recording(tmp_path, monkeypatch):
    journal = tmp_path / "interrupted-recordings.jsonl"
    monkeypatch.setattr(lifecycle_api, "INTERRUPTION_JOURNAL", journal)
    monkeypatch.setattr(
        lifecycle_api,
        "recorder",
        SimpleNamespace(status=lambda: SimpleNamespace(state=SimpleNamespace(value="IDLE"), recording_id=None)),
    )
    monkeypatch.setattr(lifecycle_api, "emg_service", SimpleNamespace(recording_status=lambda: {"state": "IDLE"}))
    lifecycle_api.shutdown_requested.clear()
    lifecycle_api._journaled_interruptions.clear()
    try:
        assert lifecycle_api.prepare_for_shutdown() == []
        assert not journal.exists()
    finally:
        lifecycle_api.shutdown_requested.clear()
        lifecycle_api._journaled_interruptions.clear()
