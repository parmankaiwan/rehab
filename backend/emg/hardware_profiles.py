from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


IDENTITY_FIELDS = ("usb_vid", "usb_pid", "device_serial_number")
VALIDATING_FIELDS = {
    "expected_sample_rate_hz", "adc_bits", "adc_min_count", "adc_max_count",
    "analog_frontend_gain", "protocol", "raw_representation",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class HardwareProfileStore:
    """Append-only profile versions and validation artifacts on the dataset volume."""

    def __init__(self, root: Path):
        self.root = root / "emg_hardware"
        self.profiles = self.root / "profiles"
        self.validations = self.root / "validations"
        self.quality_profiles = self.root / "quality_profiles"
        for path in (self.profiles, self.validations, self.quality_profiles):
            path.mkdir(parents=True, exist_ok=True)
        mock_path = self.profiles / "HWP-MOCK-12BIT" / "v1.json"
        if not mock_path.is_file():
            self._write("HWP-MOCK-12BIT", 1, {"display_name":"MOCK HARDWARE - Deterministic 12-bit","transport_type":"MOCK","protocol":"SYNTHETIC","channel_count":2,"expected_sample_rate_hz":1000,"device_timestamp_supported":True,"device_timestamp_unit":"MILLISECONDS","device_sequence_supported":True,"adc_bits":12,"adc_min_count":0,"adc_max_count":4095,"raw_representation":"ADC_COUNTS_UNSIGNED","mains_frequency_hz":50,"is_mock":True,"notes":"MOCK DATA ONLY; never represents physical hardware validation."})

    def _profile_path(self, profile_id: str, version: int) -> Path:
        return self.profiles / profile_id / f"v{version}.json"

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile_id = payload.get("hardware_profile_id") or f"HWP-{secrets.token_hex(4).upper()}"
        if (self.profiles / profile_id).exists():
            raise ValueError("Hardware profile already exists")
        return self._write(profile_id, 1, payload)

    def version(self, profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get(profile_id)
        if not current:
            raise KeyError(profile_id)
        return self._write(profile_id, current["profile_version"] + 1, payload, current)

    def _write(self, profile_id: str, version: int, payload: dict[str, Any], prior: dict[str, Any] | None = None) -> dict[str, Any]:
        now = utcnow()
        data = {
            **payload,
            "schema_version": "1.0",
            "hardware_profile_id": profile_id,
            "profile_version": version,
            "created_at": prior.get("created_at", now) if prior else now,
            "updated_at": now,
            "archived": bool(payload.get("archived", False)),
        }
        path = self._profile_path(profile_id, version)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data

    def get(self, profile_id: str, version: int | None = None) -> dict[str, Any] | None:
        folder = self.profiles / profile_id
        if not folder.is_dir():
            return None
        paths = sorted(folder.glob("v*.json"), key=lambda p: int(p.stem[1:]))
        path = self._profile_path(profile_id, version) if version else (paths[-1] if paths else None)
        return json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else None

    def list(self, include_archived: bool = False) -> list[dict[str, Any]]:
        result = [self.get(path.name) for path in self.profiles.iterdir() if path.is_dir()]
        return sorted([x for x in result if x and (include_archived or not x.get("archived"))], key=lambda x: x["updated_at"], reverse=True)

    def snapshot(self, profile_id: str, version: int | None = None) -> dict[str, Any]:
        profile = self.get(profile_id, version)
        if not profile:
            raise KeyError(profile_id)
        return json.loads(json.dumps(profile))

    def archive(self, profile_id: str) -> dict[str, Any]:
        current = self.get(profile_id)
        if not current:
            raise KeyError(profile_id)
        return self.version(profile_id, {**current, "archived": True})

    def save_validation(self, report: dict[str, Any]) -> dict[str, Any]:
        run_id = report.get("validation_run_id") or f"VAL-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{secrets.token_hex(2).upper()}"
        data = {**report, "schema_version": "1.0", "validation_run_id": run_id}
        folder = self.validations / data["hardware_profile_id"] / run_id
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "hardware_validation_report.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data

    def validation_report_path(self, profile_id: str, run_id: str) -> Path:
        if not profile_id.startswith("HWP-") or not run_id.startswith("VAL-"):
            raise FileNotFoundError(run_id)
        path = (self.validations / profile_id / run_id / "hardware_validation_report.json").resolve()
        base = self.validations.resolve()
        if base not in path.parents or not path.is_file():
            raise FileNotFoundError(run_id)
        return path
    def validation_history(self, profile_id: str) -> list[dict[str, Any]]:
        folder = self.validations / profile_id
        if not folder.is_dir():
            return []
        values = []
        current = self.get(profile_id)
        for path in sorted(folder.glob("VAL-*/hardware_validation_report.json"), reverse=True):
            data = json.loads(path.read_text(encoding="utf-8"))
            data["matches_current_profile"] = bool(current and data.get("hardware_profile_version") == current["profile_version"])
            values.append(data)
        return values

    def save_quality_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        qid = payload.get("quality_profile_id") or f"QSP-{secrets.token_hex(4).upper()}"
        folder = self.quality_profiles / qid
        versions = sorted(folder.glob("v*.json"), key=lambda p: int(p.stem[1:])) if folder.is_dir() else []
        version = int(versions[-1].stem[1:]) + 1 if versions else 1
        data = {**payload, "schema_version": "1.0", "quality_profile_id": qid, "version": version, "created_at": utcnow()}
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"v{version}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data
