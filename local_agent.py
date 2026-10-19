"""Single-owner local CV and EMG hardware agent for FlexMap."""
from __future__ import annotations

import contextlib
import http.client
import json
import os
import signal
import subprocess
import threading
import time
import urllib.parse
from collections import deque
from pathlib import Path

from backend.emg.device_scanner import scan_serial_devices
from backend.emg.serial_manager import SerialConnectionConfig, SerialManager

ROOT = Path(__file__).resolve().parent
CV_ROOT = ROOT.parent / "CV part"
RUNTIME_ROOT = ROOT / "data" / "runtime"
STATUS_PATH = RUNTIME_ROOT / "hardware-status.json"
COMMAND_PATH = RUNTIME_ROOT / "hardware-command.json"
AGENT_LOCK_PATH = RUNTIME_ROOT / "hardware-agent.lock"


class AgentLock:
    def __init__(self) -> None:
        self.handle = None

    def acquire(self) -> bool:
        RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
        self.handle = AGENT_LOCK_PATH.open("a+b")
        if AGENT_LOCK_PATH.stat().st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.handle.close()
            self.handle = None
            return False

    def release(self) -> None:
        if not self.handle:
            return
        with contextlib.suppress(OSError):
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


def load_env() -> None:
    path = ROOT / ".env.agent"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class EmgPublisher:
    def __init__(self) -> None:
        self.base = urllib.parse.urlsplit(os.environ["FLEXMAP_WEB_BACKEND"].rstrip("/"))
        self.token = os.environ["FLEXMAP_ENGINE_TOKEN"]
        self.samples = deque(maxlen=5000)
        self.lock = threading.Lock()
        self.device: dict = {}
        self.port = ""
        self.manager = SerialManager(self.on_sample, self.on_state)
        self.last_error = ""
        self.next_connect_at = 0.0
        self.retry_index = 0

    def on_sample(self, values, device_seq=None, device_ts=None, valid=True) -> None:
        with self.lock:
            self.samples.append({"values": values, "device_sequence_id": device_seq, "device_timestamp": device_ts, "valid": valid})

    def on_state(self, state, error) -> None:
        if error and error != self.last_error:
            print(f"EMG {state}: {error}", flush=True)
            self.last_error = error
        if state == "STREAMING":
            self.retry_index = 0

    def _backoff(self) -> None:
        delays = (1, 2, 5, 10, 20, 30)
        self.next_connect_at = time.monotonic() + delays[min(self.retry_index, len(delays) - 1)]
        self.retry_index += 1

    def ensure_connected(self) -> None:
        if self.manager.status()["reader_alive"] or time.monotonic() < self.next_connect_at:
            return
        devices = scan_serial_devices(include_non_usb=True)
        preferred = os.getenv("FLEXMAP_EMG_PORT", "").strip()
        device = next((item for item in devices if item["port"].casefold() == preferred.casefold()), None) if preferred else next((item for item in devices if item.get("is_usb")), None)
        if not device:
            self._backoff()
            return
        self.device, self.port = device, device["port"]
        config = SerialConnectionConfig(
            port=self.port,
            baud_rate=int(os.getenv("FLEXMAP_EMG_BAUD", "115200")),
            protocol=os.getenv("FLEXMAP_EMG_PROTOCOL", "CSV_CHANNELS"),
            expected_channels=int(os.getenv("FLEXMAP_EMG_CHANNELS", "1")),
        )
        self.manager.connect(config, device)
        print(f"EMG CONNECTING: {self.port}", flush=True)

    def reconnect(self) -> None:
        self.manager.stop()
        self.device, self.port, self.last_error = {}, "", ""
        self.retry_index = 0
        self.next_connect_at = 0

    def publish(self) -> None:
        with self.lock:
            rows = [self.samples.popleft() for _ in range(min(250, len(self.samples)))]
        if not rows:
            return
        payload = json.dumps(
            {
                "source_port": self.port,
                "baud_rate": int(os.getenv("FLEXMAP_EMG_BAUD", "115200")),
                "protocol": os.getenv("FLEXMAP_EMG_PROTOCOL", "CSV_CHANNELS"),
                "expected_sample_rate_hz": float(os.getenv("FLEXMAP_EMG_RATE", "1000")),
                "channel_count": int(os.getenv("FLEXMAP_EMG_CHANNELS", "1")),
                "device": self.device,
                "samples": rows,
            }, separators=(",", ":"),
        ).encode()
        connection_type = http.client.HTTPSConnection if self.base.scheme == "https" else http.client.HTTPConnection
        connection = connection_type(self.base.hostname, self.base.port or (443 if self.base.scheme == "https" else 80), timeout=5)
        try:
            connection.request("POST", f"{self.base.path.rstrip('/')}/api/engine/emg/batch", payload, {"Content-Type": "application/json", "X-FlexMap-Engine-Token": self.token})
            response = connection.getresponse()
            response.read()
            if response.status >= 400:
                raise OSError(f"EMG backend returned {response.status}")
        except Exception:
            with self.lock:
                self.samples.extendleft(reversed(rows))
            raise
        finally:
            connection.close()

    def stop(self) -> None:
        self.manager.stop()


def launch_cv() -> subprocess.Popen | None:
    if os.getenv("FLEXMAP_AUTOSTART_CV", "true").lower() != "true":
        return None
    python = CV_ROOT / ".venv" / "Scripts" / "python.exe"
    main_path = CV_ROOT / "main.py"
    if not python.exists() or not main_path.exists():
        print("CV runtime not found", flush=True)
        return None
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    return subprocess.Popen([str(python), str(main_path)], cwd=str(CV_ROOT), env=os.environ.copy(), creationflags=flags)


def stop_process(process: subprocess.Popen | None) -> None:
    if not process or process.poll() is not None:
        return
    with contextlib.suppress(OSError):
        process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
    try:
        process.wait(timeout=6)
    except subprocess.TimeoutExpired:
        process.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=2)


def write_status(cv: subprocess.Popen | None, emg: EmgPublisher, cv_error: str = "") -> None:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    status = emg.manager.status()
    value = {
        "agent_pid": os.getpid(),
        "cv_process_running": bool(cv and cv.poll() is None),
        "cv_pid": cv.pid if cv and cv.poll() is None else None,
        "cv_error": cv_error or None,
        "emg": {key: status[key] for key in ("state", "port", "latest_data_age_ms", "last_error", "valid_packets", "invalid_packets")},
        "updated_at": time.time(),
    }
    temp = STATUS_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temp.replace(STATUS_PATH)


def main() -> None:
    load_env()
    os.environ.setdefault("FLEXMAP_WEB_BACKEND", "https://flexmap-rehab-api-parmankaiwan.onrender.com")
    if not os.getenv("FLEXMAP_ENGINE_TOKEN"):
        raise SystemExit("FLEXMAP_ENGINE_TOKEN is missing from .env.agent")
    instance_lock = AgentLock()
    if not instance_lock.acquire():
        raise SystemExit("A FlexMap hardware agent already owns the camera/serial lifecycle")
    stop = threading.Event()

    def request_stop(*_args) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    with contextlib.suppress(AttributeError):
        signal.signal(signal.SIGBREAK, request_stop)

    cv = launch_cv()
    cv_error = ""
    cv_retry_at = 0.0
    cv_retry_index = 0
    cv_enabled = os.getenv("FLEXMAP_AUTOSTART_CV", "true").lower() == "true"
    emg = EmgPublisher()
    last_command = ""
    last_status = 0.0
    try:
        while not stop.is_set():
            if cv and cv.poll() is not None:
                cv_error = f"CV process exited with code {cv.returncode}"
                cv = None
                delays = (2, 5, 10, 20, 30)
                cv_retry_at = time.monotonic() + delays[min(cv_retry_index, len(delays) - 1)]
                cv_retry_index += 1
            if cv is None and cv_enabled and time.monotonic() >= cv_retry_at:
                cv = launch_cv()
                if cv:
                    cv_error = ""
            if COMMAND_PATH.is_file():
                with contextlib.suppress(OSError, ValueError):
                    command = json.loads(COMMAND_PATH.read_text(encoding="utf-8"))
                    if command.get("id") and command["id"] != last_command:
                        last_command = command["id"]
                        if command.get("action") == "reconnect_cv":
                            cv_enabled = True
                            stop_process(cv)
                            cv = launch_cv()
                            cv_error = ""
                            cv_retry_index = 0
                        elif command.get("action") == "reconnect_emg":
                            emg.reconnect()
                        elif command.get("action") == "release_cv":
                            cv_enabled = False
                            stop_process(cv)
                            cv = None
                            cv_error = "Camera ownership handed to browser"
            try:
                emg.ensure_connected()
                emg.publish()
            except Exception as exc:
                print(f"AGENT RETRYING: {exc}", flush=True)
                emg._backoff()
            if time.monotonic() - last_status >= 0.5:
                write_status(cv, emg, cv_error)
                last_status = time.monotonic()
            stop.wait(0.04)
    finally:
        emg.stop()
        stop_process(cv)
        write_status(None, emg, "Agent stopped")
        instance_lock.release()


if __name__ == "__main__":
    main()
