import time
from collections import deque

from backend.emg.serial_manager import SerialConnectionConfig, SerialManager


class FakeSerial:
    def __init__(self, lines):
        self.lines = deque(lines)
        self.closed = False

    def readline(self):
        if self.closed:
            raise OSError("device removed")
        if self.lines:
            return self.lines.popleft()
        time.sleep(0.005)
        return b""

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        pass

    def close(self):
        self.closed = True


def wait_for(manager, state, timeout=0.5):
    deadline = time.monotonic() + timeout
    while manager.state != state and time.monotonic() < deadline:
        time.sleep(0.005)
    return manager.state


def manager_with(lines, config):
    samples, states = [], []
    manager = SerialManager(
        lambda values, seq, timestamp: samples.append(values),
        lambda state, error: states.append((state, error)),
    )
    manager._matching_device = lambda: {
        "port": "COM7",
        "vid": "1234",
        "pid": "5678",
        "serial_number": "ABC",
        "is_usb": True,
    }
    manager._open = lambda port: FakeSerial(lines)
    manager.connect(
        config,
        {
            "port": "COM7",
            "vid": "1234",
            "pid": "5678",
            "serial_number": "ABC",
            "is_usb": True,
        },
    )
    return manager, samples, states


def config(**values):
    return SerialConnectionConfig(
        port="COM7",
        baud_rate=115200,
        protocol="CSV_CHANNELS",
        expected_channels=2,
        boot_wait_s=0,
        first_data_timeout_s=0.08,
        stale_timeout_s=0.04,
        verification_packets=3,
        **values
    )


def test_boot_text_and_malformed_lines_do_not_prevent_verification():
    manager, samples, states = manager_with(
        [b"ESP-ROM:boot\r\n", b"bad,data\n", b"1,2\n", b"2,3\r\n", b"3,4\n"], config()
    )
    assert wait_for(manager, "STREAMING") == "STREAMING"
    diagnostics = manager.status()
    assert len(samples) == 3
    assert diagnostics["rejection_categories"]["BOOT_TEXT"] == 1
    assert diagnostics["rejection_categories"]["NON_NUMERIC"] == 1
    assert [item[0] for item in states][:6] == [
        "DEVICE_DETECTED",
        "OPENING_PORT",
        "PORT_OPEN",
        "WAITING_FOR_DEVICE",
        "WAITING_FOR_DATA",
        "VERIFYING_STREAM",
    ]
    manager.stop()


def test_no_data_fails_with_specific_error_and_closes_reader():
    manager, _, _ = manager_with([], config())
    assert wait_for(manager, "ERROR") == "ERROR"
    assert manager.last_error == "NO_DATA_RECEIVED"
    manager.stop()
    assert not manager.status()["reader_alive"]


def test_wrong_channel_count_is_categorized():
    manager, _, _ = manager_with([b"512\n"] * 8, config())
    assert wait_for(manager, "ERROR") == "ERROR"
    assert manager.status()["rejection_categories"]["WRONG_CHANNEL_COUNT"] >= 1
    manager.stop()


def test_stale_stream_recovers_when_valid_data_resumes():
    serial = FakeSerial([b"1,2\n", b"2,3\n", b"3,4\n"])
    samples, states = [], []
    manager = SerialManager(
        lambda values, seq, timestamp: samples.append(values),
        lambda state, error: states.append(state),
    )
    manager._matching_device = lambda: {
        "port": "COM7",
        "vid": "1234",
        "pid": "5678",
        "serial_number": "ABC",
        "is_usb": True,
    }
    manager._open = lambda port: serial
    manager.connect(
        config(),
        {
            "port": "COM7",
            "vid": "1234",
            "pid": "5678",
            "serial_number": "ABC",
            "is_usb": True,
        },
    )
    assert wait_for(manager, "STREAMING") == "STREAMING"
    assert wait_for(manager, "STALE") == "STALE"
    serial.lines.extend([b"4,5\n"])
    assert wait_for(manager, "STREAMING") == "STREAMING"
    manager.stop()
