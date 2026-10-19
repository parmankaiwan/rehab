"""Non-invasive FlexMap EMG hardware commissioning preflight.

This command enumerates serial devices and compares them with the local EMG
configuration.  It never opens a serial port, changes firmware, or prints
credentials.  A successful preflight only means that a candidate USB device is
present; it does not claim that valid EMG samples were received.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.emg.device_scanner import scan_serial_devices

SAFE_KEYS = {
    "FLEXMAP_EMG_PORT",
    "FLEXMAP_EMG_BAUD",
    "FLEXMAP_EMG_PROTOCOL",
    "FLEXMAP_EMG_CHANNELS",
    "FLEXMAP_EMG_RATE",
}


def load_safe_configuration(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in SAFE_KEYS:
            values[key] = value.strip().strip('"').strip("'")
    return values


def commissioning_preflight(
    configuration: dict[str, str], devices: list[dict[str, Any]]
) -> dict[str, Any]:
    preferred = configuration.get("FLEXMAP_EMG_PORT", "")
    usb_devices = [device for device in devices if device.get("is_usb")]
    preferred_device = next(
        (
            device
            for device in devices
            if str(device.get("port", "")).casefold() == preferred.casefold()
        ),
        None,
    )
    candidate = preferred_device if preferred_device and preferred_device.get("is_usb") else None
    if candidate is None and len(usb_devices) == 1:
        candidate = usb_devices[0]
    state = "USB_DEVICE_DETECTED" if candidate else "USB_DEVICE_NOT_DETECTED"
    return {
        "state": state,
        "configuration": configuration,
        "preferred_port_present": preferred_device is not None,
        "candidate": candidate,
        "usb_devices": usb_devices,
        "other_serial_devices": [device for device in devices if not device.get("is_usb")],
        "physical_samples_verified": False,
        "note": (
            "Candidate presence is not proof of firmware compatibility or EMG acquisition."
            if candidate
            else "Connect the ESP32 with a data-capable USB cable, then run this check again."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect FlexMap EMG configuration and USB serial presence")
    parser.add_argument("--require-device", action="store_true", help="Return exit code 2 when no USB candidate is detected")
    args = parser.parse_args()
    report = commissioning_preflight(
        load_safe_configuration(ROOT / ".env.agent"),
        scan_serial_devices(include_non_usb=True),
    )
    print(json.dumps(report, indent=2))
    return 2 if args.require_device and report["state"] != "USB_DEVICE_DETECTED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
