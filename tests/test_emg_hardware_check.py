from pathlib import Path

from scripts.check_emg_hardware import commissioning_preflight, load_safe_configuration


def test_preflight_loads_only_non_secret_emg_configuration(tmp_path: Path):
    env = tmp_path / ".env.agent"
    env.write_text(
        "FLEXMAP_ENGINE_TOKEN=do-not-expose\n"
        "FLEXMAP_EMG_PORT=COM9\n"
        "FLEXMAP_EMG_BAUD=115200\n",
        encoding="utf-8",
    )
    assert load_safe_configuration(env) == {
        "FLEXMAP_EMG_PORT": "COM9",
        "FLEXMAP_EMG_BAUD": "115200",
    }


def test_preflight_does_not_treat_bluetooth_port_as_esp32():
    report = commissioning_preflight(
        {"FLEXMAP_EMG_PORT": "COM9"},
        [{"port": "COM3", "is_usb": False, "description": "Bluetooth serial"}],
    )
    assert report["state"] == "USB_DEVICE_NOT_DETECTED"
    assert report["candidate"] is None
    assert report["physical_samples_verified"] is False


def test_preflight_selects_configured_usb_device_without_claiming_samples():
    board = {"port": "COM9", "is_usb": True, "vid": 0x10C4, "pid": 0xEA60}
    report = commissioning_preflight({"FLEXMAP_EMG_PORT": "COM9"}, [board])
    assert report["state"] == "USB_DEVICE_DETECTED"
    assert report["candidate"] == board
    assert report["physical_samples_verified"] is False
