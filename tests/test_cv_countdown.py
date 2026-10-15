import threading
from types import SimpleNamespace

import pytest

from backend.cv_recording_service import CvRecordingService
from backend.dataset_models import RecordingConfiguration, RecordingState


def configuration(seconds=3, **changes):
    values = dict(
        rehab_type="REACHING",
        subject_id="P001",
        category="REACHING",
        label="reach",
        duration_seconds=10,
        countdown_seconds=seconds,
        consent_recorded=True,
    )
    values.update(changes)
    return RecordingConfiguration(**values)


def countdown_service(snapshot):
    service = CvRecordingService.__new__(CvRecordingService)
    service.posture_store = SimpleNamespace(latest=lambda: snapshot)
    service.raw_store = SimpleNamespace(is_fresh=lambda: True)
    service.annotated_store = SimpleNamespace(is_fresh=lambda: True)
    service._cancel = threading.Event()
    service._countdown_started = None
    return service


def test_cv_countdown_accepts_only_three_or_five_seconds():
    assert configuration(3).countdown_seconds == 3
    assert configuration(5).countdown_seconds == 5
    with pytest.raises(ValueError):
        configuration(4)


def test_countdown_cancels_when_tracking_is_lost_and_restarts_from_full_value():
    snapshot = SimpleNamespace(connected=True, tracking_quality="LOST")
    service = countdown_service(snapshot)
    assert service._wait_for_countdown(5) == "TRACKING_LOST"


def test_manual_cancel_interrupts_countdown_without_recording():
    snapshot = SimpleNamespace(connected=True, tracking_quality="GOOD")
    service = countdown_service(snapshot)
    service._cancel.set()
    assert service._wait_for_countdown(3) == "CANCELLED"


def test_countdown_completes_only_with_usable_tracking():
    snapshot = SimpleNamespace(connected=True, tracking_quality="GOOD")
    service = countdown_service(snapshot)
    assert service._wait_for_countdown(.01) == "READY"


def test_countdown_stops_if_the_existing_camera_stream_becomes_stale():
    snapshot = SimpleNamespace(connected=True, tracking_quality="GOOD")
    service = countdown_service(snapshot)
    service.raw_store = SimpleNamespace(is_fresh=lambda: False)
    assert service._wait_for_countdown(5) == "TRACKING_LOST"


def test_manual_stop_uses_a_finalize_signal_not_the_discard_signal():
    service = CvRecordingService.__new__(CvRecordingService)
    service._lock = threading.RLock()
    service._state = RecordingState.RECORDING
    service._configuration = configuration(3, manual_stop=True)
    service._stop = threading.Event()
    service._cancel = threading.Event()
    service._started_monotonic = None
    service._recording_start_timestamp_ns = 123
    service._countdown_started = None
    service._recording_id = "CV-1"
    service._frame_count = service._pose_count = 0
    service._error = service._review = None
    service.settings = SimpleNamespace(countdown_seconds=3)
    service.stop()
    assert service._stop.is_set()
    assert not service._cancel.is_set()
