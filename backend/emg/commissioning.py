from __future__ import annotations

import hashlib
import json
import os
import statistics
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .device_scanner import scan_serial_devices
from .hardware_validation import channel_check, timing_validation
from .schemas import RecordingRequest

TEST_IDS = (
    "usb_detection",
    "serial_connection",
    "stream",
    "channels",
    "baseline",
    "fixed_trial",
    "manual_trial",
    "event_markers",
    "review",
    "retry",
    "interruption",
    "reconnect",
    "long_run",
    "dataset",
    "raw_integrity",
    "processing",
    "training_eligibility",
)
RUN_STATES = {
    "NOT_STARTED",
    "RUNNING",
    "INCOMPLETE",
    "COMPLETE",
    "COMPLETE_WITH_WARNINGS",
    "FAILED",
}
TEST_STATES = {"NOT_RUN", "RUNNING", "PASS", "WARNING", "FAIL"}
PASSING_TEST_STATES = {"PASS", "WARNING"}
TEST_PREREQUISITES = {
    "serial_connection": ("usb_detection",),
    "stream": ("serial_connection",),
    "channels": ("stream",),
    "baseline": ("channels",),
    "fixed_trial": ("baseline",),
    "manual_trial": ("fixed_trial",),
    "review": ("manual_trial", "event_markers"),
    "interruption": ("review",),
    "reconnect": ("interruption",),
    "retry": ("reconnect",),
    "long_run": ("retry",),
    "dataset": ("long_run", "review"),
    "raw_integrity": ("dataset",),
    "processing": ("raw_integrity",),
    "training_eligibility": ("processing",),
}
EVIDENCE_NAMES = {
    "usb_detection": "connection_test.json",
    "serial_connection": "serial_connection_test.json",
    "channels": "channel_test.json",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ValidationRunCreate(BaseModel):
    hardware_profile_id: str
    hardware_profile_version: Optional[int] = Field(default=None, ge=1)
    selected_port: str = Field(default="", max_length=100)
    baud_rate: Optional[int] = Field(default=None, ge=1200, le=3_000_000)
    serial_protocol: Optional[str] = Field(default=None, max_length=80)
    notes: str = Field(default="", max_length=2000)


class ValidationTestRequest(BaseModel):
    duration_seconds: float = Field(default=30, ge=1, le=900)
    baseline_ids: list[str] = Field(default_factory=list, max_length=10)
    recording_id: Optional[str] = None
    prior_recording_id: Optional[str] = None
    rehab_type: str = "REACHING"
    research_label: str = "full_trial"
    notes: str = Field(default="", max_length=1000)


class ValidationReviewRequest(BaseModel):
    decision: Literal["APPROVE", "APPROVE_WITH_WARNINGS", "RETRY", "DISCARD"]
    notes: str = Field(default="Engineering validation recording", max_length=1000)


class EmgHardwareValidationStore:
    """Persistent commissioning coordinator; never owns serial or opens a device."""

    def __init__(self, root: Path, service):
        self.root = root / "emg_validation"
        self.root.mkdir(parents=True, exist_ok=True)
        self.service = service
        self.lock = threading.RLock()

    def _folder(self, run_id: str) -> Path:
        if not run_id.startswith("VAL-"):
            raise KeyError("Validation run not found")
        folder = (self.root / run_id).resolve()
        if self.root.resolve() not in folder.parents:
            raise KeyError("Validation run not found")
        return folder

    def _read(self, run_id: str) -> dict:
        path = self._folder(run_id) / "validation.json"
        if not path.is_file():
            raise KeyError("Validation run not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, run: dict, evidence: Optional[tuple[str, dict]] = None) -> dict:
        folder = self._folder(run["validation_run_id"])
        folder.mkdir(parents=True, exist_ok=True)
        run["updated_at"] = utcnow()
        temp = folder / "validation.tmp"
        temp.write_text(json.dumps(run, indent=2), encoding="utf-8")
        temp.replace(folder / "validation.json")
        if evidence:
            name, payload = evidence
            filename = EVIDENCE_NAMES.get(name, f"{name}_test.json")
            (folder / filename).write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
        return run

    def create(self, request: ValidationRunCreate) -> dict:
        with self.lock:
            profile = self.service.hardware.snapshot(
                request.hardware_profile_id, request.hardware_profile_version
            )
            if profile.get("is_mock"):
                raise ValueError(
                    "Physical commissioning cannot use a mock hardware profile"
                )
            usb_devices = scan_serial_devices()
            selected_usb = next(
                (
                    device
                    for device in usb_devices
                    if device.get("port", "").casefold()
                    == request.selected_port.casefold()
                ),
                None,
            )
            if not request.selected_port or not selected_usb:
                raise ValueError(
                    "HARDWARE NOT DETECTED: select a connected USB serial device"
                )
            status = self.service.status()
            device = selected_usb
            if hasattr(device, "model_dump"):
                device = device.model_dump()
            run_id = f"VAL-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{os.urandom(2).hex().upper()}"
            run = {
                "schema_version": "1.0",
                "validation_run_id": run_id,
                "hardware_profile_id": profile["hardware_profile_id"],
                "hardware_profile_version": profile["profile_version"],
                "hardware_profile_snapshot": profile,
                "device_identity": device,
                "started_at": utcnow(),
                "completed_at": None,
                "status": "RUNNING",
                "selected_port": request.selected_port
                or status.get("serial_port")
                or "",
                "baud_rate": request.baud_rate
                or status.get("baud_rate")
                or profile.get("serial_baud_rate"),
                "serial_protocol": request.serial_protocol
                or status.get("protocol")
                or profile.get("protocol"),
                "expected_channels": profile.get("channel_count"),
                "configured_sample_rate_hz": profile.get("expected_sample_rate_hz"),
                "real_hardware": True,
                "tests": {
                    test_id: {
                        "state": "NOT_RUN",
                        "started_at": None,
                        "completed_at": None,
                        "metrics": {},
                        "warnings": [],
                        "failures": [],
                    }
                    for test_id in TEST_IDS
                },
                "warnings": [],
                "failures": [],
                "software_version": "flexmap-emg-commissioning-1.0",
                "notes": request.notes,
            }
            return self._write(run)

    def list(self, profile_id: str = "") -> list[dict]:
        result = []
        for path in sorted(self.root.glob("VAL-*/validation.json"), reverse=True):
            try:
                run = json.loads(path.read_text(encoding="utf-8"))
                if not profile_id or run["hardware_profile_id"] == profile_id:
                    result.append(self._sync(run))
            except (OSError, ValueError, KeyError):
                continue
        return result

    def get(self, run_id: str) -> dict:
        with self.lock:
            return self._sync(self._read(run_id))

    def _finish_test(
        self,
        run: dict,
        test_id: str,
        state: str,
        metrics: dict,
        warnings=None,
        failures=None,
    ) -> dict:
        if state not in TEST_STATES:
            raise ValueError("Invalid validation test state")
        test = run["tests"][test_id]
        test.update(
            state=state,
            completed_at=utcnow(),
            metrics=metrics,
            warnings=warnings or [],
            failures=failures or [],
        )
        run["warnings"] = sorted(
            {
                warning
                for item in run["tests"].values()
                for warning in item.get("warnings", [])
            }
        )
        run["failures"] = sorted(
            {
                failure
                for item in run["tests"].values()
                for failure in item.get("failures", [])
            }
        )
        return self._write(run, (test_id, test))

    @staticmethod
    def _status_result(condition: bool, warning: bool = False) -> str:
        return (
            "PASS" if condition and not warning else "WARNING" if condition else "FAIL"
        )

    def start_test(
        self, run_id: str, test_id: str, request: ValidationTestRequest
    ) -> dict:
        if test_id not in TEST_IDS:
            raise KeyError("Unknown validation test")
        with self.lock:
            run = self._sync(self._read(run_id))
            if run["status"] != "RUNNING":
                raise ValueError("Validation run is not active")
            prerequisites = TEST_PREREQUISITES.get(test_id, ())
            blocked = [
                required
                for required in prerequisites
                if run["tests"][required]["state"] not in PASSING_TEST_STATES
            ]
            if test_id == "event_markers":
                blocked = (
                    []
                    if run["tests"]["manual_trial"]["state"] == "RUNNING"
                    else ["manual_trial_running"]
                )
            if blocked:
                raise ValueError(
                    "Complete required commissioning step(s) first: "
                    + ", ".join(blocked)
                )
            test = run["tests"][test_id]
            if test["state"] == "RUNNING":
                return run
            test.update(
                state="RUNNING",
                started_at=utcnow(),
                completed_at=None,
                metrics={},
                warnings=[],
                failures=[],
            )
            status = self.service.status()
            if test_id == "usb_detection":
                devices = scan_serial_devices()
                selected = next(
                    (
                        d
                        for d in devices
                        if d.get("is_usb")
                        and d.get("port", "").casefold()
                        == run["selected_port"].casefold()
                    ),
                    None,
                )
                if selected:
                    run["device_identity"] = selected
                metrics = {"detected_devices": devices, "selected_device": selected}
                return self._finish_test(
                    run,
                    test_id,
                    "PASS" if selected else "FAIL",
                    metrics,
                    failures=[] if selected else ["SELECTED_USB_DEVICE_NOT_DETECTED"],
                )
            if test_id == "serial_connection":
                diagnostics = self.service.serial_diagnostics()
                channel_match = status.get("channel_count") == run["expected_channels"]
                passed = (
                    status.get("connection_state") == "STREAMING"
                    and diagnostics.get("valid_packets", 0) > 1
                    and diagnostics.get("bytes_received", 0) > 0
                    and channel_match
                )
                metrics = {
                    "port": status.get("serial_port"),
                    "baud_rate": status.get("baud_rate"),
                    "protocol": status.get("protocol"),
                    "bytes_received": diagnostics.get("bytes_received", 0),
                    "valid_packets": diagnostics.get("valid_packets", 0),
                    "invalid_packets": diagnostics.get("invalid_packets", 0),
                    "first_valid_packet_latency_ms": diagnostics.get(
                        "first_valid_packet_latency_ms"
                    ),
                    "expected_channel_count": run["expected_channels"],
                    "actual_channel_count": status.get("channel_count"),
                    "channel_count_matches": channel_match,
                }
                return self._finish_test(
                    run,
                    test_id,
                    "PASS" if passed else "FAIL",
                    metrics,
                    failures=[] if passed else ["MULTIPLE_VALID_PACKETS_NOT_CONFIRMED"],
                )
            if test_id in {"stream", "long_run"}:
                if status.get("connection_state") != "STREAMING" or status.get(
                    "is_mock"
                ):
                    return self._finish_test(
                        run, test_id, "FAIL", {}, failures=["REAL_EMG_STREAM_REQUIRED"]
                    )
                test["runtime"] = {
                    "start_monotonic_ns": time.monotonic_ns(),
                    "start_process_ns": time.process_time_ns(),
                    "start_sequence": self.service.sequence,
                    "start_valid_samples": status.get("valid_samples", 0),
                    "start_invalid_packets": status.get("invalid_packets", 0),
                    "start_recorder_drops": status.get("recorder_drops", 0),
                    "start_processing_drops": status.get("processing", {}).get(
                        "processed_display_drop_count", 0
                    ),
                    "duration_seconds": request.duration_seconds,
                    "max_queue_depth": status.get("processing", {}).get(
                        "processing_queue_depth", 0
                    ),
                    "stale_events": 0,
                }
                return self._write(run)
            if test_id == "channels":
                rows = list(self.service.samples)
                report = channel_check(rows, run["hardware_profile_snapshot"])
                configured = self.service.config.channels if self.service.config else []
                for channel in configured:
                    result = report.get("channels", {}).get(channel.internal_id, {})
                    result.update(
                        display_name=channel.display_name,
                        muscle_label=channel.muscle_label,
                        body_side=channel.body_side,
                    )
                failed = any(
                    value.get("technical_state") in {"MISSING", "INVALID FORMAT"}
                    for value in report.get("channels", {}).values()
                )
                warnings = report.get("warnings", [])
                return self._finish_test(
                    run,
                    test_id,
                    "FAIL" if failed else "WARNING" if warnings else "PASS",
                    report,
                    warnings=warnings,
                    failures=["REQUIRED_CHANNEL_VALIDATION_FAILED"] if failed else [],
                )
            if test_id == "baseline":
                ids = request.baseline_ids
                baselines = [self.service.get_baseline(value) for value in ids]
                baselines = [value for value in baselines if value]
                if len(baselines) < 3:
                    return self._finish_test(
                        run,
                        test_id,
                        "FAIL",
                        {"baseline_ids": ids},
                        failures=["THREE_REAL_BASELINES_REQUIRED"],
                    )
                repeatability = self.service.baseline_repeatability_report(
                    run["hardware_profile_id"], ids
                )
                warnings = repeatability.get("warnings", []) + [
                    warning
                    for value in repeatability.get("channels", {}).values()
                    for warning in value.get("warnings", [])
                ]
                return self._finish_test(
                    run,
                    test_id,
                    "WARNING" if warnings else "PASS",
                    {
                        "baseline_ids": ids,
                        "baselines": baselines,
                        "repeatability": repeatability,
                    },
                    warnings=warnings,
                )
            if test_id in {"fixed_trial", "manual_trial"}:
                if status.get("connection_state") != "STREAMING" or status.get(
                    "is_mock"
                ):
                    return self._finish_test(
                        run, test_id, "FAIL", {}, failures=["REAL_EMG_STREAM_REQUIRED"]
                    )
                module = self.service.registry.by_id(request.rehab_type)
                self.service.registry.validate_emg_label(
                    request.rehab_type, request.research_label
                )
                baseline_metrics = run["tests"]["baseline"].get("metrics", {})
                baseline_ids = baseline_metrics.get("baseline_ids", [])
                recording = self.service.start_recording(
                    RecordingRequest(
                        rehab_type=module.id,
                        subject_id="TEST-HARDWARE",
                        research_label=request.research_label,
                        duration_seconds=request.duration_seconds,
                        countdown_seconds=3,
                        manual_stop=test_id == "manual_trial",
                        affected_side="N/A",
                        session_id=run_id,
                        study_id="EMG-HARDWARE-VALIDATION",
                        protocol_id="TEST_EMG_HARDWARE_VALIDATION",
                        protocol_version=1,
                        trial_id=f"{run_id}-{test_id}",
                        trial_number=1,
                        attempt_number=1,
                        notes=request.notes,
                        hardware_profile_id=run["hardware_profile_id"],
                        hardware_profile_version=run["hardware_profile_version"],
                        channel_map_snapshot={
                            "channels": [
                                channel.model_dump()
                                for channel in self.service.config.channels
                            ]
                        },
                        consent_recorded=True,
                        baseline_id=baseline_ids[0] if baseline_ids else None,
                        baseline_group_id=f"{run_id}-BASELINES",
                        validation_recording=True,
                        validation_run_id=run_id,
                    )
                )
                test["runtime"] = {
                    "recording_id": recording.get("recording_id"),
                    "requested_duration_seconds": request.duration_seconds,
                    "manual_stop": test_id == "manual_trial",
                }
                return self._write(run)
            if test_id == "event_markers":
                recording = self.service.recording_status()
                if recording.get("state") != "RECORDING":
                    return self._finish_test(
                        run,
                        test_id,
                        "FAIL",
                        {},
                        failures=["ACTIVE_MANUAL_RECORDING_REQUIRED"],
                    )
                markers = [
                    self.service.add_recording_marker(event, "Commissioning marker")
                    for event in ("MOVEMENT_STARTED", "TARGET_REACHED", "SENSOR_ISSUE")
                ]
                return self._finish_test(
                    run,
                    test_id,
                    "PASS",
                    {"recording_id": recording.get("recording_id"), "markers": markers},
                )
            if test_id == "interruption":
                if status.get("connection_state") != "STREAMING":
                    return self._finish_test(
                        run,
                        test_id,
                        "FAIL",
                        {},
                        failures=["START_WITH_STREAMING_BOARD"],
                    )
                test["runtime"] = {
                    "armed_at_monotonic_ns": time.monotonic_ns(),
                    "was_streaming": True,
                    "recording_id": self.service.recording_id,
                }
                return self._write(run)
            if test_id == "reconnect":
                test["runtime"] = {
                    "previous_port": run.get("selected_port"),
                    "started_disconnected": status.get("connection_state")
                    != "STREAMING",
                }
                return self._write(run)
            if test_id == "retry":
                prior = (
                    self.service.get(request.prior_recording_id)
                    if request.prior_recording_id and hasattr(self.service, "get")
                    else None
                )
                replacement = (
                    self.service.get(request.recording_id)
                    if request.recording_id and hasattr(self.service, "get")
                    else None
                )
                prior_meta = (prior or {}).get("metadata", {})
                replacement_meta = (replacement or {}).get("metadata", {})
                trace_checked = bool(prior and replacement)
                same_trial = (
                    prior_meta.get("trial_id") == replacement_meta.get("trial_id")
                    if trace_checked
                    else None
                )
                attempt_increased = (
                    replacement_meta.get("attempt_number", 0)
                    > prior_meta.get("attempt_number", 0)
                    if trace_checked
                    else None
                )
                metrics = {
                    "prior_recording_id": request.prior_recording_id,
                    "new_recording_id": request.recording_id,
                    "same_trial_id": same_trial,
                    "attempt_number_increased": attempt_increased,
                    "recording_trace_checked": trace_checked,
                }
                passed = bool(
                    request.prior_recording_id
                    and request.recording_id
                    and request.prior_recording_id != request.recording_id
                    and (not trace_checked or same_trial and attempt_increased)
                )
                return self._finish_test(
                    run,
                    test_id,
                    "PASS" if passed else "FAIL",
                    metrics,
                    failures=(
                        [] if passed else ["DISTINCT_ATTEMPT_RECORDING_IDS_REQUIRED"]
                    ),
                )
            return self._recording_test(run, test_id, request.recording_id)

    def _recording_test(
        self, run: dict, test_id: str, recording_id: Optional[str]
    ) -> dict:
        if not recording_id:
            return self._finish_test(
                run, test_id, "FAIL", {}, failures=["RECORDING_ID_REQUIRED"]
            )
        item = self.service.get(recording_id)
        if not item:
            return self._finish_test(
                run,
                test_id,
                "FAIL",
                {"recording_id": recording_id},
                failures=["RECORDING_NOT_FOUND"],
            )
        meta = item.get("metadata", {})
        if test_id == "dataset":
            passed = bool(
                meta.get("validation_recording")
                and meta.get("validation_run_id") == run["validation_run_id"]
            )
            return self._finish_test(
                run,
                test_id,
                "PASS" if passed else "FAIL",
                {
                    "recording_id": recording_id,
                    "relative_path": item.get("relative_path"),
                    "metadata": meta,
                },
                failures=[] if passed else ["VALIDATION_DATASET_REGISTRATION_MISMATCH"],
            )
        if test_id == "raw_integrity":
            raw = self.service.file(recording_id, "emg_raw.csv")
            digest = hashlib.sha256(raw.read_bytes()).hexdigest()
            expected = (
                meta.get("raw_sha256")
                or meta.get("source_raw_sha256")
                or item.get("integrity_report", {}).get("raw_sha256")
            )
            passed = bool(expected and digest == expected)
            return self._finish_test(
                run,
                test_id,
                "PASS" if passed else "FAIL",
                {
                    "recording_id": recording_id,
                    "calculated_sha256": digest,
                    "stored_sha256": expected,
                    "identical": passed,
                },
                failures=[] if passed else ["RAW_SHA256_MISMATCH"],
            )
        if test_id == "processing":
            before = hashlib.sha256(
                self.service.file(recording_id, "emg_raw.csv").read_bytes()
            ).hexdigest()
            processing = self.service.reprocess(
                recording_id, self.service.processing.config, preferred=False
            )
            after = hashlib.sha256(
                self.service.file(recording_id, "emg_raw.csv").read_bytes()
            ).hexdigest()
            passed = before == after
            return self._finish_test(
                run,
                test_id,
                "PASS" if passed else "FAIL",
                {
                    "recording_id": recording_id,
                    "processing_run": processing,
                    "raw_sha256_before": before,
                    "raw_sha256_after": after,
                },
                failures=[] if passed else ["RAW_CHANGED_DURING_PROCESSING"],
            )
        if test_id == "training_eligibility":
            passed = (
                meta.get("validation_recording") is True
                and meta.get("training_eligible") is False
            )
            return self._finish_test(
                run,
                test_id,
                "PASS" if passed else "FAIL",
                {
                    "recording_id": recording_id,
                    "validation_recording": meta.get("validation_recording"),
                    "training_eligible": meta.get("training_eligible"),
                    "is_mock": meta.get("is_mock"),
                    "interrupted": meta.get("interrupted"),
                },
                failures=(
                    [] if passed else ["VALIDATION_RECORDING_ELIGIBILITY_POLICY_FAILED"]
                ),
            )
        return self._finish_test(
            run, test_id, "FAIL", {}, failures=["UNSUPPORTED_RECORDING_TEST"]
        )

    def stop_manual(self, run_id: str) -> dict:
        self.service.stop_recording()
        return self.get(run_id)

    def review_recording(self, run_id: str, request: ValidationReviewRequest) -> dict:
        with self.lock:
            run = self._sync(self._read(run_id))
            recording = self.service.recording_status()
            rid = recording.get("recording_id")
            if recording.get("state") != "REVIEW" or not rid:
                raise ValueError("Validation recording is not ready for review")
            if request.decision == "DISCARD":
                self.service.discard(rid)
            elif request.decision == "RETRY":
                self.service.save(rid, "RETRY_REQUIRED", False, request.notes)
            else:
                status = (
                    "APPROVED_WITH_WARNINGS"
                    if request.decision == "APPROVE_WITH_WARNINGS"
                    else "APPROVED"
                )
                self.service.save(rid, status, False, request.notes)
            test_id = "review"
            state = "WARNING" if request.decision == "APPROVE_WITH_WARNINGS" else "PASS"
            return self._finish_test(
                run,
                test_id,
                state,
                {
                    "recording_id": rid,
                    "decision": request.decision,
                    "training_eligible": False,
                },
            )

    def _sync(self, run: dict) -> dict:
        changed = False
        status = self.service.status()
        for test_id in ("stream", "long_run"):
            test = run["tests"][test_id]
            if test["state"] == "RUNNING":
                runtime = test["runtime"]
                runtime["max_queue_depth"] = max(
                    runtime.get("max_queue_depth", 0),
                    status.get("processing", {}).get("processing_queue_depth", 0),
                )
                if status.get("connection_state") != "STREAMING":
                    runtime["stale_events"] = runtime.get("stale_events", 0) + 1
                elapsed = (time.monotonic_ns() - runtime["start_monotonic_ns"]) / 1e9
                test["progress"] = min(1, elapsed / runtime["duration_seconds"])
                if elapsed >= runtime["duration_seconds"]:
                    rows = [
                        row
                        for row in self.service.samples
                        if row["sequence_id"] > runtime["start_sequence"]
                    ]
                    timing = (
                        timing_validation(
                            rows,
                            run["configured_sample_rate_hz"],
                            run["hardware_profile_snapshot"].get(
                                "device_timestamp_unit"
                            ),
                        )
                        if len(rows) > 1
                        else {}
                    )
                    valid = (
                        status.get("valid_samples", 0) - runtime["start_valid_samples"]
                    )
                    invalid = (
                        status.get("invalid_packets", 0)
                        - runtime["start_invalid_packets"]
                    )
                    wall = max(elapsed, 0.001)
                    cpu_seconds = (
                        time.process_time_ns() - runtime["start_process_ns"]
                    ) / 1e9
                    metrics = {
                        "wall_duration_seconds": elapsed,
                        "total_samples": max(
                            0, self.service.sequence - runtime["start_sequence"]
                        ),
                        "valid_samples": max(0, valid),
                        "invalid_packets": max(0, invalid),
                        "effective_host_receive_rate_hz": max(0, valid) / wall,
                        "configured_sample_rate_hz": run["configured_sample_rate_hz"],
                        "device_sample_rate_hz_estimated": timing.get(
                            "device_sample_rate_hz_estimated"
                        ),
                        "timing_clock_source": timing.get("sampling_clock_source"),
                        "median_interval_ms": timing.get("median_interval_ms"),
                        "p95_interval_ms": timing.get("p95_interval_ms"),
                        "p99_interval_ms": timing.get("p99_interval_ms"),
                        "maximum_gap_ms": timing.get("max_interval_ms"),
                        "device_sequence_gap_count": timing.get(
                            "device_sequence_gap_count"
                        ),
                        "estimated_missing_samples": timing.get(
                            "estimated_missing_samples"
                        ),
                        "stale_events": runtime.get("stale_events", 0),
                        "recorder_drops": status.get("recorder_drops", 0)
                        - runtime["start_recorder_drops"],
                        "processing_drops": status.get("processing", {}).get(
                            "processed_display_drop_count", 0
                        )
                        - runtime["start_processing_drops"],
                        "processing_queue_max": runtime.get("max_queue_depth", 0),
                        "processing_queue_capacity": status.get("processing", {}).get(
                            "processing_queue_capacity"
                        ),
                        "sample_buffer_occupancy": len(self.service.samples),
                        "sample_buffer_capacity": self.service.samples.maxlen,
                        "cpu_percent_single_process_average": 100 * cpu_seconds / wall,
                        "memory_working_set_bytes": self._memory_bytes(),
                    }
                    warnings = timing.get("warnings", [])
                    state = (
                        "FAIL"
                        if valid <= 1
                        else "WARNING" if warnings or invalid else "PASS"
                    )
                    self._finish_test(
                        run,
                        test_id,
                        state,
                        metrics,
                        warnings=warnings,
                        failures=[] if valid > 1 else ["INSUFFICIENT_REAL_SAMPLES"],
                    )
                    changed = True
        for test_id in ("fixed_trial", "manual_trial"):
            test = run["tests"][test_id]
            if test["state"] == "RUNNING":
                recording = self.service.recording_status()
                if recording.get("state") == "REVIEW" and recording.get(
                    "recording_id"
                ) == test.get("runtime", {}).get("recording_id"):
                    review = recording.get("review") or {}
                    meta = review.get("metadata", {})
                    files = set(review.get("files", []))
                    required = {
                        "emg_raw.csv",
                        "metadata.json",
                        "quality_report.json",
                        "signal_quality_report.json",
                        "integrity_report.json",
                        "artifact_manifest.json",
                    }
                    passed = (
                        required <= files
                        and meta.get("sample_count", 0) > 0
                        and meta.get("validation_recording") is True
                    )
                    metrics = {
                        "recording_id": recording["recording_id"],
                        "requested_duration_seconds": test["runtime"][
                            "requested_duration_seconds"
                        ],
                        "actual_duration_seconds": meta.get("duration_actual"),
                        "stop_reason": meta.get("stop_reason"),
                        "sample_count": meta.get("sample_count"),
                        "measured_host_receive_rate_hz": meta.get(
                            "measured_sample_rate_hz"
                        ),
                        "raw_sha256": meta.get("raw_sha256"),
                        "files": sorted(files),
                        "markers": review.get("events", []),
                    }
                    self._finish_test(
                        run,
                        test_id,
                        "PASS" if passed else "FAIL",
                        metrics,
                        failures=(
                            []
                            if passed
                            else ["VALIDATION_RECORDING_FINALIZATION_FAILED"]
                        ),
                    )
                    changed = True
        interruption = run["tests"]["interruption"]
        if (
            interruption["state"] == "RUNNING"
            and status.get("connection_state") != "STREAMING"
        ):
            recording_status = getattr(self.service, "recording_status", None)
            recording = recording_status() if recording_status else {}
            metrics = {
                "detected_connection_state": status.get("connection_state"),
                "recording_state": recording.get("state", "NOT_RECORDING"),
                "recording_id": recording.get("recording_id"),
                "fastapi_alive": True,
            }
            self._finish_test(run, "interruption", "PASS", metrics)
            changed = True
        reconnect = run["tests"]["reconnect"]
        if (
            reconnect["state"] == "RUNNING"
            and status.get("connection_state") == "STREAMING"
        ):
            metrics = {
                "previous_port": reconnect.get("runtime", {}).get("previous_port"),
                "current_port": status.get("serial_port"),
                "com_port_changed": bool(
                    reconnect.get("runtime", {}).get("previous_port")
                    and reconnect["runtime"]["previous_port"]
                    != status.get("serial_port")
                ),
                "valid_samples": status.get("valid_samples"),
                "received_rate_hz": status.get("received_rate_hz"),
            }
            self._finish_test(
                run,
                "reconnect",
                "PASS" if status.get("valid_samples", 0) > 1 else "WARNING",
                metrics,
                warnings=(
                    []
                    if status.get("valid_samples", 0) > 1
                    else ["RECONNECTED_WITHOUT_MULTIPLE_VALID_SAMPLES"]
                ),
            )
            changed = True
        if changed:
            return self._read(run["validation_run_id"])
        return self._write(run)

    @staticmethod
    def _memory_bytes() -> Optional[int]:
        try:
            import psutil

            return psutil.Process(os.getpid()).memory_info().rss
        except Exception:
            return None

    def complete(self, run_id: str) -> dict:
        with self.lock:
            run = self._sync(self._read(run_id))
            if run.get("completed_at"):
                return run
            states = [test["state"] for test in run["tests"].values()]
            if "RUNNING" in states:
                raise ValueError("A validation test is still running")
            run["status"] = (
                "INCOMPLETE"
                if "NOT_RUN" in states
                else "FAILED"
                if "FAIL" in states
                else "COMPLETE_WITH_WARNINGS"
                if "WARNING" in states
                else "COMPLETE"
            )
            run["completed_at"] = utcnow()
            report = {
                **run,
                "firmware": (
                    self.service.board_status().get("firmware")
                    if hasattr(self.service, "board_status")
                    else None
                ),
                "known_limitations": [
                    "Host receive rate is not asserted to be exact ADC sampling rate.",
                    "Software commissioning does not establish electrical safety or electrode placement.",
                ],
                "final_technical_status": (
                    "INCOMPLETE"
                    if run["status"] == "INCOMPLETE"
                    else "FAIL"
                    if run["status"] == "FAILED"
                    else (
                        "PASS_WITH_WARNINGS"
                        if run["status"] == "COMPLETE_WITH_WARNINGS"
                        else "PASS"
                    )
                ),
                "scope_statement": "THIS IS TECHNICAL ACQUISITION VALIDATION, NOT CLINICAL VALIDATION.",
                "physical_safety_statement": "Software commissioning does not establish electrical safety for a human-connected prototype.",
            }
            folder = self._folder(run_id)
            (folder / "final_report.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
            (folder / "emg_hardware_validation_report.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
            if run["status"] in {"COMPLETE", "COMPLETE_WITH_WARNINGS"}:
                self.service.hardware.save_validation(report)
            return self._write(run)

    def profile_validation(
        self, profile_id: str, version: Optional[int] = None
    ) -> dict:
        profile = self.service.hardware.snapshot(profile_id, version)
        history = self.list(profile_id)
        completed = next(
            (
                run
                for run in history
                if run["status"] in {"COMPLETE", "COMPLETE_WITH_WARNINGS"}
            ),
            None,
        )
        return {
            "hardware_profile_id": profile_id,
            "hardware_profile_version": profile["profile_version"],
            "validated": bool(
                completed
                and completed["hardware_profile_version"] == profile["profile_version"]
            ),
            "last_validation": completed,
            "configuration_matches": bool(
                completed
                and completed["hardware_profile_version"] == profile["profile_version"]
            ),
            "warning": (
                None
                if completed
                and completed["hardware_profile_version"] == profile["profile_version"]
                else "CURRENT HARDWARE CONFIGURATION DIFFERS FROM LAST VALIDATION"
            ),
        }

    def evidence_path(self, run_id: str, name: str) -> Path:
        allowed = {
            "validation.json",
            "connection_test.json",
            "serial_connection_test.json",
            "stream_test.json",
            "channel_test.json",
            "baseline_test.json",
            "fixed_trial_test.json",
            "manual_trial_test.json",
            "event_markers_test.json",
            "review_test.json",
            "retry_test.json",
            "interruption_test.json",
            "reconnect_test.json",
            "long_run_test.json",
            "dataset_test.json",
            "raw_integrity_test.json",
            "processing_test.json",
            "training_eligibility_test.json",
            "final_report.json",
            "emg_hardware_validation_report.json",
        }
        if name not in allowed:
            raise FileNotFoundError(name)
        path = self._folder(run_id) / name
        if not path.is_file():
            raise FileNotFoundError(name)
        return path
