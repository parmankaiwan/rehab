import hashlib
import json
import time

import pytest

from backend.dataset_config import DatasetSettings
from backend.emg.firmware_service import FirmwareError, FirmwareService
from backend.emg.schemas import ChannelConfig, ConnectRequest
from backend.emg.service import EmgService


def settings(tmp_path):
    value = DatasetSettings(
        root=tmp_path / "vault", labels_path=tmp_path / "labels.json"
    )
    value.labels_path.write_text("{}")
    return value


def test_mock_connect_requires_and_passes_stream_verification(tmp_path):
    service = EmgService(settings(tmp_path))
    request = ConnectRequest(
        transport_type="MOCK",
        channels=[ChannelConfig(internal_id="channel_1", display_name="Channel 1")],
    )
    status = service.connect_verified(request)
    assert status["connection_state"] == "STREAMING"
    assert status["verification"] == "DATA_STREAM_VERIFIED"
    assert service.board_test()["passed"] is True
    service.disconnect()


def test_unknown_usb_identity_cannot_be_flashed(tmp_path):
    root = tmp_path / "firmware"
    root.mkdir()
    (root / "manifest.json").write_text(
        json.dumps({"schema_version": "1.0", "releases": []})
    )
    status = FirmwareService(root).status({"vid": "10C4", "pid": "EA60"})
    assert status["supported_board"] is False
    assert status["flash_enabled"] is False
    assert "could not be verified" in status["disabled_reason"]


def test_manifest_artifact_is_confined_and_hash_verified(tmp_path, monkeypatch):
    root = tmp_path / "firmware"
    root.mkdir()
    artifact = root / "trusted.bin"
    artifact.write_bytes(b"firmware")
    release = {
        "firmware_id": "flexmap-test",
        "version": "1.0.0",
        "board_family": "TEST",
        "expected_vid": "1234",
        "expected_pid": "5678",
        "artifact": "trusted.bin",
        "sha256": hashlib.sha256(b"firmware").hexdigest(),
        "flash_tool": "ESPTOOL",
    }
    (root / "manifest.json").write_text(
        json.dumps({"schema_version": "1.0", "releases": [release]})
    )
    monkeypatch.setattr(
        "backend.emg.firmware_service.shutil.which",
        lambda value: "esptool" if value == "esptool" else None,
    )
    service = FirmwareService(root)
    matched, path = service.validate_flash(
        {"vid": "1234", "pid": "5678"}, "flexmap-test"
    )
    assert matched["version"] == "1.0.0" and path == artifact
    artifact.write_bytes(b"tampered")
    with pytest.raises(FirmwareError, match="INTEGRITY"):
        service.validate_flash({"vid": "1234", "pid": "5678"}, "flexmap-test")
