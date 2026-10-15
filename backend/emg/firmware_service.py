from __future__ import annotations

import hashlib
import json
import shutil
import threading
from pathlib import Path
from typing import Any


class FirmwareError(RuntimeError):
    pass


class FirmwareService:
    """Trusted, local-only firmware catalogue and board matching.

    This project currently contains no board firmware artifact. An empty manifest is
    intentional: it keeps flashing unavailable instead of guessing the CP210x host
    bridge's underlying microcontroller.
    """

    def __init__(self, root: Path | None = None):
        self.root = (root or Path(__file__).parent / "firmware").resolve()
        self.manifest_path = self.root / "manifest.json"
        self.lock = threading.Lock()

    def releases(self) -> list[dict[str, Any]]:
        data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if data.get("schema_version") != "1.0" or not isinstance(
            data.get("releases"), list
        ):
            raise FirmwareError("FIRMWARE MANIFEST IS INVALID")
        return data["releases"]

    def match(
        self, device: dict[str, Any], firmware_id: str | None = None
    ) -> dict[str, Any] | None:
        for release in self.releases():
            if firmware_id and release.get("firmware_id") != firmware_id:
                continue
            if (
                str(release.get("expected_vid", "")).upper()
                != str(device.get("vid", "")).upper()
            ):
                continue
            if (
                str(release.get("expected_pid", "")).upper()
                != str(device.get("pid", "")).upper()
            ):
                continue
            return release
        return None

    def artifact(self, release: dict[str, Any]) -> Path:
        relative = release.get("artifact")
        if not isinstance(relative, str) or not relative:
            raise FirmwareError("TRUSTED FIRMWARE ARTIFACT IS NOT CONFIGURED")
        path = (self.root / relative).resolve()
        if self.root not in path.parents or not path.is_file():
            raise FirmwareError("TRUSTED FIRMWARE ARTIFACT IS MISSING")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest.lower() != str(release.get("sha256", "")).lower():
            raise FirmwareError("FIRMWARE FILE FAILED INTEGRITY CHECK")
        return path

    @staticmethod
    def tool_status(release: dict[str, Any] | None) -> dict[str, Any]:
        tool = str((release or {}).get("flash_tool", "")).lower()
        executable = {
            "ESPTOOL": "esptool",
            "ARDUINO_CLI": "arduino-cli",
            "AVRDUDE": "avrdude",
        }.get(tool.upper())
        return {
            "name": executable,
            "available": bool(executable and shutil.which(executable)),
        }

    def status(self, device: dict[str, Any] | None = None) -> dict[str, Any]:
        release = self.match(device) if device else None
        tool = self.tool_status(release)
        reason = None
        if not device:
            reason = "Select a connected USB board."
        elif not release:
            reason = "Board type could not be verified. No trusted FlexMap firmware is configured for this USB identity."
        elif not tool["available"]:
            reason = f"Required flash tool {tool['name']} is not installed."
        return {
            "installed_version": None,
            "firmware_state": "UNKNOWN",
            "supported_board": bool(release),
            "release": release,
            "tool": tool,
            "flash_enabled": bool(release and tool["available"]),
            "disabled_reason": reason,
        }

    def validate_flash(
        self, device: dict[str, Any], firmware_id: str
    ) -> tuple[dict[str, Any], Path]:
        release = self.match(device, firmware_id)
        if not release:
            raise FirmwareError("UNSUPPORTED BOARD OR FIRMWARE")
        if not self.tool_status(release)["available"]:
            raise FirmwareError("REQUIRED FLASH TOOL IS NOT INSTALLED")
        return release, self.artifact(release)
