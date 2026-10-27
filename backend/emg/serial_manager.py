from __future__ import annotations

import logging
import math
import threading
import time
from collections import Counter, deque
from dataclasses import asdict, dataclass
from typing import Any, Callable, Literal

from .device_scanner import scan_serial_devices
from .parser import parse_serial_line

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SerialConnectionConfig:
    port: str
    baud_rate: int
    protocol: str
    expected_channels: int
    bytesize: int = 8
    parity: str = "N"
    stopbits: float = 1
    read_timeout_s: float = 0.1
    write_timeout_s: float = 0.5
    xonxoff: bool = False
    rtscts: bool = False
    dsrdtr: bool = False
    dtr: Literal["UNCHANGED", "HIGH", "LOW"] = "UNCHANGED"
    rts: Literal["UNCHANGED", "HIGH", "LOW"] = "UNCHANGED"
    boot_wait_s: float = 1.5
    first_data_timeout_s: float = 5.0
    stale_timeout_s: float = 2.5
    verification_packets: int = 5
    max_line_bytes: int = 512


class SerialManager:
    """The sole owner of the website runtime's physical serial.Serial object."""

    def __init__(
        self,
        on_sample: Callable[..., None],
        on_state: Callable[[str, str | None], None],
    ):
        self.on_sample = on_sample
        self.on_state = on_state
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.serial: Any = None
        self.config: SerialConnectionConfig | None = None
        self.device: dict[str, Any] | None = None
        self.state = "DISCONNECTED"
        self.last_error: str | None = None
        self.raw_lines: deque[str] = deque(maxlen=30)
        self.events: deque[dict[str, Any]] = deque(maxlen=80)
        self.rejections: Counter[str] = Counter()
        self.bytes_received = 0
        self.lines_received = 0
        self.valid_packets = 0
        self.latest_valid_ns: int | None = None
        self.latest_packet: dict[str, Any] | None = None
        self.connected_since: float | None = None

    def _set_state(self, state: str, error: str | None = None) -> None:
        self.state, self.last_error = state, error
        self.events.append({"timestamp": time.time(), "state": state, "message": error})
        log.info(
            "EMG serial state=%s port=%s error=%s",
            state,
            self.config.port if self.config else None,
            error,
        )
        self.on_state(state, error)

    def connect(
        self, config: SerialConnectionConfig, device: dict[str, Any]
    ) -> dict[str, Any]:
        with self.lock:
            if self.thread and self.thread.is_alive():
                if (
                    self.config
                    and self.config.port.casefold() == config.port.casefold()
                ):
                    return self.status()
                raise RuntimeError("ANOTHER SERIAL CONNECTION IS ACTIVE")
            self.config, self.device = config, dict(device)
            self.stop_event.clear()
            self.raw_lines.clear()
            self.events.clear()
            self.rejections.clear()
            self.bytes_received = self.lines_received = self.valid_packets = 0
            self.latest_valid_ns = None
            self.latest_packet = None
            self.connected_since = None
            self._set_state("DEVICE_DETECTED")
            self.thread = threading.Thread(
                target=self._run, name="flexmap-emg-serial-manager", daemon=True
            )
            self.thread.start()
            return self.status()

    def stop(self) -> None:
        self.stop_event.set()
        with self.lock:
            if self.serial:
                try:
                    self.serial.close()
                except Exception:
                    pass
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
        with self.lock:
            self.serial = None
        self._set_state("DISCONNECTED")

    def _matching_device(self) -> dict[str, Any] | None:
        devices = scan_serial_devices()
        original = self.device or {}
        serial_number = original.get("serial_number")
        if serial_number:
            match = next(
                (
                    item
                    for item in devices
                    if item.get("serial_number") == serial_number
                    and item.get("vid") == original.get("vid")
                    and item.get("pid") == original.get("pid")
                ),
                None,
            )
            if match:
                return match
        same_identity = [
            item
            for item in devices
            if item.get("vid") == original.get("vid")
            and item.get("pid") == original.get("pid")
        ]
        if len(same_identity) == 1:
            return same_identity[0]
        return next(
            (
                item
                for item in devices
                if item["port"].casefold() == str(original.get("port", "")).casefold()
            ),
            None,
        )

    def _open(self, port: str) -> Any:
        import serial

        cfg = self.config
        assert cfg
        try:
            handle = serial.Serial(
                port=port,
                baudrate=cfg.baud_rate,
                bytesize=cfg.bytesize,
                parity=cfg.parity,
                stopbits=cfg.stopbits,
                timeout=cfg.read_timeout_s,
                write_timeout=cfg.write_timeout_s,
                xonxoff=cfg.xonxoff,
                rtscts=cfg.rtscts,
                dsrdtr=cfg.dsrdtr,
            )
            if cfg.dtr != "UNCHANGED":
                handle.dtr = cfg.dtr == "HIGH"
            if cfg.rts != "UNCHANGED":
                handle.rts = cfg.rts == "HIGH"
            return handle
        except PermissionError as exc:
            raise RuntimeError("ACCESS_DENIED") from exc
        except serial.SerialException as exc:
            message = str(exc).lower()
            category = (
                "PORT_IN_USE"
                if "access is denied" in message or "permission" in message
                else (
                    "PORT_NOT_FOUND"
                    if "cannot find" in message or "not found" in message
                    else "PORT_OPEN_FAILED"
                )
            )
            raise RuntimeError(category) from exc

    def _run(self) -> None:
        reconnect_delays = (1, 1, 2, 2, 5)
        attempt = 0
        while not self.stop_event.is_set():
            match = self._matching_device()
            if not match:
                self._set_state(
                    "RECONNECTING" if attempt else "ERROR", "BOARD_DISCONNECTED"
                )
                self.stop_event.wait(
                    reconnect_delays[min(attempt, len(reconnect_delays) - 1)]
                )
                attempt += 1
                continue
            try:
                self._set_state("OPENING_PORT")
                self.serial = self._open(match["port"])
                self.device = match
                self._set_state("PORT_OPEN")
                self._set_state("WAITING_FOR_DEVICE")
                if self.stop_event.wait(self.config.boot_wait_s):
                    break
                try:
                    self.serial.reset_input_buffer()
                    self.serial.reset_output_buffer()
                except Exception:
                    pass
                self._set_state("WAITING_FOR_DATA")
                self.connected_since = time.time()
                attempt = 0
                outcome = self._read_loop()
                if outcome == "STOPPED":
                    break
            except RuntimeError as exc:
                self._set_state("ERROR", str(exc))
                if str(exc) in {
                    "PORT_IN_USE",
                    "ACCESS_DENIED",
                    "NO_DATA_RECEIVED",
                    "POSSIBLE_BAUD_OR_PROTOCOL_MISMATCH",
                }:
                    break
            except Exception as exc:
                self._set_state("RECONNECTING", "SERIAL_IO_ERROR")
                log.warning("EMG serial read failed: %s", exc)
            finally:
                with self.lock:
                    if self.serial:
                        try:
                            self.serial.close()
                        except Exception:
                            pass
                    self.serial = None
            if not self.stop_event.is_set():
                self._set_state("RECONNECTING", self.last_error or "BOARD_DISCONNECTED")
                self.stop_event.wait(
                    reconnect_delays[min(attempt, len(reconnect_delays) - 1)]
                )
                attempt += 1
        if self.stop_event.is_set():
            self._set_state("DISCONNECTED")

    def _reject(self, category: str, preview: str = "") -> None:
        self.rejections[category] += 1
        if preview:
            self.raw_lines.append(preview[: self.config.max_line_bytes])

    def _read_loop(self) -> str:
        started = time.monotonic()
        verified = False
        while not self.stop_event.is_set():
            raw = self.serial.readline()
            now_ns = time.perf_counter_ns()
            if not raw:
                if (
                    not verified
                    and time.monotonic() - started >= self.config.first_data_timeout_s
                ):
                    if self.bytes_received and not self.valid_packets:
                        raise RuntimeError("POSSIBLE_BAUD_OR_PROTOCOL_MISMATCH")
                    raise RuntimeError("NO_DATA_RECEIVED")
                if (
                    verified
                    and self.latest_valid_ns
                    and (now_ns - self.latest_valid_ns) / 1e9
                    >= self.config.stale_timeout_s
                ):
                    self._set_state("STALE", "EMG_SIGNAL_STALE")
                continue
            self.bytes_received += len(raw)
            self.lines_received += 1
            if len(raw) > self.config.max_line_bytes:
                self._reject("TOO_LONG")
                continue
            try:
                line = raw.decode("utf-8", errors="strict").strip("\r\n")
            except UnicodeDecodeError:
                self._reject("DECODE_ERROR", raw.decode("utf-8", errors="replace"))
                continue
            preview = "".join(ch for ch in line if ch.isprintable())
            self.raw_lines.append(preview)
            if not preview.strip():
                self._reject("EMPTY")
                continue
            lower = preview.lower()
            if lower.startswith(("rst:", "boot:", "esp-rom:", "ready")):
                self._reject("BOOT_TEXT")
                continue
            parsed = parse_serial_line(
                preview, self.config.protocol, self.config.expected_channels
            )
            if parsed is None:
                fields = preview.split(",")
                if any(not self._number(field) for field in fields):
                    reason = "NON_NUMERIC"
                elif len(fields) < self.config.expected_channels:
                    reason = "WRONG_CHANNEL_COUNT"
                else:
                    reason = "WRONG_FIELD_COUNT"
                self._reject(reason)
                continue
            seq, timestamp, values = parsed
            self.valid_packets += 1
            self.latest_valid_ns = now_ns
            self.latest_packet = {
                "sequence": seq,
                "timestamp": timestamp,
                "channels": values,
            }
            self.on_sample(values, seq, timestamp)
            if not verified:
                self._set_state("VERIFYING_STREAM")
                if self.valid_packets >= self.config.verification_packets:
                    verified = True
                    self._set_state("STREAMING")
            elif self.state == "STALE":
                self._set_state("STREAMING")
        return "STOPPED"

    @staticmethod
    def _number(value: str) -> bool:
        try:
            return math.isfinite(float(value))
        except ValueError:
            return False

    def status(self) -> dict[str, Any]:
        age = (
            (time.perf_counter_ns() - self.latest_valid_ns) / 1e6
            if self.latest_valid_ns
            else None
        )
        return {
            "state": self.state,
            "port": (
                self.device.get("port")
                if self.device
                else self.config.port if self.config else None
            ),
            "device": self.device,
            "config": asdict(self.config) if self.config else None,
            "bytes_received": self.bytes_received,
            "lines_received": self.lines_received,
            "valid_packets": self.valid_packets,
            "invalid_packets": sum(self.rejections.values()),
            "rejection_categories": dict(self.rejections),
            "latest_raw_line": self.raw_lines[-1] if self.raw_lines else None,
            "latest_raw_lines": list(self.raw_lines),
            "latest_valid_packet": self.latest_packet,
            "latest_data_age_ms": age,
            "connected_since": self.connected_since,
            "last_error": self.last_error,
            "events": list(self.events),
            "reader_alive": bool(self.thread and self.thread.is_alive()),
        }
