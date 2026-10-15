from __future__ import annotations
import csv, hashlib, json, math, queue, random, secrets, shutil, sqlite3, threading, time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from .schemas import BaselineRequest, ConnectRequest, RecordingRequest
from .signal_processing import EmgProcessingConfig, EmgProcessingPipeline
from .signal_quality import EmgSignalQualityMonitor
from .hardware_profiles import HardwareProfileStore, utcnow
from .device_scanner import scan_serial_devices
from .firmware_service import FirmwareService
from .serial_manager import SerialConnectionConfig, SerialManager
from .hardware_validation import (
    adc_validation,
    baseline_repeatability,
    channel_check,
    conversion_config,
    filter_response,
    host_pipeline_latency,
    powerline_validation,
    quick_check,
    timing_validation,
)
from ..dataset_config import DatasetSettings
from ..rehab_modules import RehabModuleRegistry


class EmgService:
    def __init__(self, settings: DatasetSettings):
        self.settings = settings
        self.registry = RehabModuleRegistry(settings.modules_path)
        self.lock = threading.RLock()
        self.samples = deque(maxlen=60000)
        self.processed_samples = deque(maxlen=10000)
        self.processing = EmgProcessingPipeline()
        self.processing_queue = queue.Queue(maxsize=5000)
        self.processing_worker = None
        self.signal_quality = EmgSignalQualityMonitor()
        self.display_signals = {"raw"}
        self.processing_lock = threading.RLock()
        self.sequence = 0
        self.invalid = 0
        self.connection_state = "DISCONNECTED"
        self.config = None
        self.stop_event = threading.Event()
        self.worker = None
        self.serial = None
        self.started_ns = None
        self.latest_ns = None
        self.tickets = {}
        self.record_state = "IDLE"
        self.recording_id = None
        self.review = None
        self.record_thread = None
        self.cancel_event = threading.Event()
        self.manual_stop_event = threading.Event()
        self.recording_started_ns = None
        self.recording_countdown_started_ns = None
        self.recording_request = None
        self.record_markers = []
        self.baseline_state = "IDLE"
        self.baseline_review = None
        self.hardware = HardwareProfileStore(settings.root)
        self._init_storage()
        self.operation_lock = threading.Lock()
        self.connection_error = None
        self.verification = "NOT_RUN"
        self.selected_device = None
        self.firmware = FirmwareService()
        self.serial_manager = SerialManager(self._add, self._serial_state)

    def _db(self):
        db = sqlite3.connect(self.settings.database_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _init_storage(self):
        self.settings.root.mkdir(parents=True, exist_ok=True)
        self.settings.temp_dir.mkdir(parents=True, exist_ok=True)
        for m in self.registry.modules:
            base = self.settings.rehab_dir / m.slug / "emg"
            (base / "recordings").mkdir(parents=True, exist_ok=True)
            (base / "baselines").mkdir(exist_ok=True)
            (base / "manifests").mkdir(exist_ok=True)
        with self._db() as db:
            db.executescript(
                """CREATE TABLE IF NOT EXISTS dataset_audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT,timestamp TEXT NOT NULL,recording_id TEXT,action TEXT NOT NULL,previous_value TEXT,new_value TEXT);CREATE TABLE IF NOT EXISTS emg_recordings(recording_id TEXT PRIMARY KEY,rehab_type TEXT NOT NULL,rehab_slug TEXT NOT NULL,subject_id TEXT NOT NULL,session_id TEXT,research_label TEXT NOT NULL,affected_side TEXT NOT NULL,created_at TEXT NOT NULL,duration_seconds REAL NOT NULL,sample_count INTEGER NOT NULL,channel_count INTEGER NOT NULL,measured_sample_rate_hz REAL,technical_quality TEXT NOT NULL,is_mock INTEGER NOT NULL,interrupted INTEGER NOT NULL,training_eligible INTEGER NOT NULL DEFAULT 0,excluded INTEGER NOT NULL DEFAULT 0,relative_path TEXT NOT NULL,storage_bytes INTEGER NOT NULL);CREATE INDEX IF NOT EXISTS idx_emg_rehab ON emg_recordings(rehab_type);CREATE INDEX IF NOT EXISTS idx_emg_rehab_label ON emg_recordings(rehab_type,research_label);CREATE INDEX IF NOT EXISTS idx_emg_subject ON emg_recordings(rehab_type,subject_id);"""
            )
        self._recover_orphans()
        self.generate_manifests()

    def _recover_orphans(self):
        for module in self.registry.modules:
            for folder in (
                self.settings.rehab_dir / module.slug / "emg" / "recordings"
            ).glob("EMG-*"):
                try:
                    meta = json.loads(
                        (folder / "metadata.json").read_text(encoding="utf-8")
                    )
                    relative = str(folder.relative_to(self.settings.root)).replace(
                        "\\", "/"
                    )
                    size = sum(
                        p.stat().st_size for p in folder.iterdir() if p.is_file()
                    )
                    values = (
                        meta["recording_id"],
                        meta["rehab_type"],
                        meta["rehab_slug"],
                        meta["subject_id"],
                        meta.get("session_id"),
                        meta["research_label"],
                        meta["affected_side"],
                        meta["created_at_utc"],
                        meta["duration_actual"],
                        meta["sample_count"],
                        meta["channel_count"],
                        meta.get("measured_sample_rate_hz"),
                        meta["technical_quality"],
                        int(meta.get("is_mock", False)),
                        int(meta.get("interrupted", False)),
                        0,
                        0,
                        relative,
                        size,
                    )
                    with self._db() as db:
                        db.execute(
                            "INSERT OR IGNORE INTO emg_recordings(recording_id,rehab_type,rehab_slug,subject_id,session_id,research_label,affected_side,created_at,duration_seconds,sample_count,channel_count,measured_sample_rate_hz,technical_quality,is_mock,interrupted,training_eligible,excluded,relative_path,storage_bytes) VALUES("
                            + ",".join("?" for _ in values)
                            + ")",
                            values,
                        )
                except Exception:
                    continue

    def processing_status(self):
        cfg = self.processing.config
        return {
            "enabled": cfg.enabled,
            "config": cfg.model_dump(),
            "processing_sample_rate_hz": cfg.processing_sample_rate_hz,
            "sample_rate_source": cfg.sample_rate_source,
            "processing_version": cfg.processing_version,
            "config_hash": cfg.hash,
            "error": self.processing.error,
            "processed_display_drop_count": self.processing.processed_display_drop_count,
            "processing_queue_depth": self.processing_queue.qsize(),
            "processing_queue_capacity": self.processing_queue.maxsize,
            "selected_representations": sorted(self.display_signals),
        }

    def processing_config(self):
        return self.processing_status()

    def apply_processing_config(self, cfg: EmgProcessingConfig):
        with self.processing_lock:
            self.processing.apply(cfg)
            self.processed_samples.clear()
        with self._db() as db:
            db.execute(
                "INSERT INTO dataset_audit_log(timestamp,recording_id,action,previous_value,new_value) VALUES(?,?,?,?,?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    None,
                    "EMG_PROCESSING_CONFIG_CHANGED",
                    None,
                    json.dumps(cfg.model_dump()),
                ),
            )
        return self.processing_status()

    def reset_processing(self):
        with self.processing_lock:
            self.processing.reset()
            self.processed_samples.clear()
        return self.processing_status()

    def select_display_signals(self, signals: list[str]):
        allowed = {"raw", "filtered", "rectified", "rms", "envelope"}
        chosen = set(signals)
        if not chosen or not chosen <= allowed or len(chosen) > 2:
            raise ValueError("Select one or two supported signal representations")
        self.display_signals = chosen
        return self.processing_status()

    def signal_quality_report(self):
        rate = (
            self.processing.config.processing_sample_rate_hz
            if self.processing.config.enabled
            else (self.config.expected_sample_rate_hz if self.config else None)
        )
        return self.signal_quality.report(
            rate, self.config.adc_bits if self.config else None
        )

    def start_baseline(self, req: BaselineRequest):
        if self.connection_state != "STREAMING":
            raise RuntimeError("NO LIVE SIGNAL")
        if self.baseline_state in ("COUNTDOWN", "RECORDING"):
            raise RuntimeError("A baseline is active")
        module = self.registry.by_id(req.rehab_type)
        self.baseline_state = "COUNTDOWN"
        self.baseline_review = None
        threading.Thread(target=self._baseline, args=(req, module), daemon=True).start()
        return self.baseline_status()

    def _baseline(self, req, module):
        time.sleep(3)
        start_ns = time.perf_counter_ns()
        start_seq = self.sequence
        self.baseline_state = "RECORDING"
        time.sleep(req.duration_seconds)
        stop_ns = time.perf_counter_ns()
        with self.lock:
            rows = [
                x
                for x in self.samples
                if start_seq < x["sequence_id"] and x["host_timestamp_ns"] <= stop_ns
            ]
        baseline_id = f"BASE-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{secrets.token_hex(2).upper()}"
        base = self.settings.rehab_dir / module.slug / "emg" / "baselines" / baseline_id
        base.mkdir(parents=True, exist_ok=False)
        fields = ["sequence_id", "host_timestamp_ns"] + [
            x.internal_id for x in self.config.channels
        ]
        with (base / "emg_raw.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "sequence_id": row["sequence_id"],
                        "host_timestamp_ns": row["host_timestamp_ns"],
                        **row["channels"],
                    }
                )
        pipeline = EmgProcessingPipeline(
            self.processing.config.model_copy(update={"enabled": True})
        )
        processed = pipeline.process_rows(rows)
        summary = {}
        for channel in [x.internal_id for x in self.config.channels]:
            rms = [x["channels"][channel]["rms"] for x in processed]
            raw = [x["channels"][channel]["raw"] for x in processed]
            summary[channel] = {
                "raw_mean": sum(raw) / len(raw) if raw else None,
                "rms_mean": sum(rms) / len(rms) if rms else None,
                "rms_std": float(__import__("numpy").std(rms)) if rms else None,
            }
        raw_hash = hashlib.sha256((base / "emg_raw.csv").read_bytes()).hexdigest()
        quality = self.signal_quality_report()
        meta = {
            "baseline_id": baseline_id,
            "rehab_type": req.rehab_type,
            "rehab_slug": module.slug,
            "subject_id": req.subject_id,
            "session_id": req.session_id,
            "collection_id": req.collection_id,
            "protocol_id": req.protocol_id,
            "protocol_version": req.protocol_version,
            "baseline_group_id": req.baseline_group_id,
            "baseline_number": req.baseline_number,
            "hardware_profile_id": req.hardware_profile_id,
            "hardware_profile_version": req.hardware_profile_version,
            "channel_map_snapshot": req.channel_map_snapshot,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": req.duration_seconds,
            "sample_count": len(rows),
            "raw_units": "ADC_COUNTS",
            "processing_config": self.processing.config.model_dump(),
            "processing_config_hash": self.processing.config.hash,
            "source_raw_sha256": raw_hash,
            "summary": summary,
            "notes": req.notes,
        }
        (base / "baseline_summary.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        (base / "signal_quality_report.json").write_text(
            json.dumps(quality, indent=2), encoding="utf-8"
        )
        with self._db() as db:
            db.execute(
                "INSERT INTO dataset_audit_log(timestamp,recording_id,action,previous_value,new_value) VALUES(?,?,?,?,?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    baseline_id,
                    "EMG_BASELINE_CREATED",
                    None,
                    json.dumps({"rehab_type": req.rehab_type}),
                ),
            )
        self.baseline_review = meta
        self.baseline_state = "COMPLETE"

    def baseline_status(self):
        return {"state": self.baseline_state, "baseline": self.baseline_review}

    def list_baselines(self):
        result = []
        for module in self.registry.modules:
            for path in sorted(
                (self.settings.rehab_dir / module.slug / "emg" / "baselines").glob(
                    "BASE-*"
                ),
                reverse=True,
            ):
                try:
                    result.append(
                        json.loads((path / "baseline_summary.json").read_text())
                    )
                except Exception:
                    pass
        return result

    def get_baseline(self, bid):
        for module in self.registry.modules:
            path = (
                self.settings.rehab_dir
                / module.slug
                / "emg"
                / "baselines"
                / bid
                / "baseline_summary.json"
            )
            if path.is_file():
                return json.loads(path.read_text())
        return None

    def reprocess(self, rid, cfg: EmgProcessingConfig, preferred=False):
        item = self.get(rid)
        if not item:
            raise FileNotFoundError(rid)
        base = self.settings.root / item["relative_path"]
        raw_path = base / "emg_raw.csv"
        before = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        rows = []
        with raw_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append(
                    {
                        "sequence_id": int(row["sequence_id"]),
                        "host_timestamp_ns": int(row["host_timestamp_ns"]),
                        "channels": {
                            key: float(value)
                            for key, value in row.items()
                            if key.startswith("channel_") and value not in ("", None)
                        },
                    }
                )
        config = cfg.model_copy(update={"enabled": True})
        pipeline = EmgProcessingPipeline(config)
        processed = pipeline.process_rows(rows)
        proc_id = f"PROC-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{secrets.token_hex(2).upper()}"
        out = base / "processing" / proc_id
        out.mkdir(parents=True)
        channel_ids = sorted(rows[0]["channels"]) if rows else []
        representations = ["filtered", "rectified", "rms", "envelope"]
        fields = ["sequence_id", "host_timestamp_ns"] + [
            f"{ch}_{rep}" for ch in channel_ids for rep in representations
        ]
        with (out / f"emg_processed_{proc_id}.csv").open(
            "w", newline="", encoding="utf-8"
        ) as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for sample in processed:
                row = {
                    "sequence_id": sample["sequence_id"],
                    "host_timestamp_ns": sample["host_timestamp_ns"],
                }
                for ch in channel_ids:
                    for rep in representations:
                        row[f"{ch}_{rep}"] = sample["channels"][ch][rep]
                writer.writerow(row)
        after = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        if before != after:
            raise RuntimeError("RAW IMMUTABILITY VIOLATION")
        run = {
            "processing_run_id": proc_id,
            "source_recording_id": rid,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_raw_sha256": before,
            "processing_config": config.model_dump(),
            "processing_config_hash": config.hash,
            "processing_pipeline_version": config.processing_version,
            "causal": True,
            "preferred_for_review": preferred,
            "sample_count": len(processed),
        }
        (out / "processing_run.json").write_text(
            json.dumps(run, indent=2), encoding="utf-8"
        )
        quality = EmgSignalQualityMonitor()
        [quality.accept(x["channels"]) for x in rows]
        (out / "signal_quality_report.json").write_text(
            json.dumps(
                quality.report(
                    config.processing_sample_rate_hz, item["metadata"].get("adc_bits")
                ),
                indent=2,
            ),
            encoding="utf-8",
        )
        with self._db() as db:
            db.execute(
                "INSERT INTO dataset_audit_log(timestamp,recording_id,action,previous_value,new_value) VALUES(?,?,?,?,?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    rid,
                    "EMG_RECORDING_REPROCESSED",
                    None,
                    json.dumps({"processing_run_id": proc_id, "raw_sha256": before}),
                ),
            )
        return run

    def processing_runs(self, rid):
        item = self.get(rid)
        if not item:
            return []
        result = []
        for path in sorted(
            (self.settings.root / item["relative_path"] / "processing").glob("PROC-*"),
            reverse=True,
        ):
            try:
                result.append(json.loads((path / "processing_run.json").read_text()))
            except Exception:
                pass
        return result

    def devices(self):
        try:
            from serial.tools import list_ports

            return [
                {
                    "port": p.device,
                    "description": p.description,
                    "hwid": p.hwid,
                    "usb_vid": f"{p.vid:04X}" if p.vid is not None else None,
                    "usb_pid": f"{p.pid:04X}" if p.pid is not None else None,
                    "serial_number": p.serial_number,
                    "manufacturer": p.manufacturer,
                }
                for p in list_ports.comports()
            ]
        except Exception:
            return []

    def connect(self, cfg: ConnectRequest):
        with self.lock:
            if self.connection_state != "DISCONNECTED":
                if (
                    self.config
                    and self.config.transport_type == cfg.transport_type
                    and self.config.serial_port == cfg.serial_port
                ):
                    return self.board_status()
                raise RuntimeError("ANOTHER SERIAL CONNECTION IS ACTIVE")
            self.config = cfg
            self.stop_event.clear()
            self.invalid = 0
            self.sequence = 0
            self.samples.clear()
            self.processed_samples.clear()
            self.signal_quality.reset()
            self.processing.reset()
            self.started_ns = time.perf_counter_ns()
            self.latest_ns = None
        if cfg.transport_type == "MOCK":
            self.connection_state = "CONNECTING"
            target = self._mock_loop
        else:
            devices = scan_serial_devices()
            self.selected_device = next(
                (
                    item
                    for item in devices
                    if item["port"].casefold() == str(cfg.serial_port).casefold()
                ),
                None,
            )
            if not self.selected_device:
                self.connection_state = "ERROR"
                self.connection_error = "PORT_NOT_FOUND"
                raise RuntimeError("PORT_NOT_FOUND")
            serial_config = SerialConnectionConfig(
                port=str(cfg.serial_port),
                baud_rate=cfg.baud_rate,
                protocol=cfg.protocol,
                expected_channels=len(cfg.channels),
            )
            self.processing_worker = threading.Thread(
                target=self._processing_loop, name="flexmap-emg-processing", daemon=True
            )
            self.processing_worker.start()
            self.serial_manager.connect(serial_config, self.selected_device)
            return self.board_status()
        self.processing_worker = threading.Thread(
            target=self._processing_loop, name="flexmap-emg-processing", daemon=True
        )
        self.processing_worker.start()
        self.worker = threading.Thread(
            target=target, name="flexmap-emg-reader", daemon=True
        )
        self.worker.start()
        self.connection_state = "STREAMING"
        return self.status()

    def _serial_state(self, state: str, error: str | None):
        self.connection_state = state
        self.connection_error = error
        self.verification = (
            "DATA_STREAM_VERIFIED" if state in ("STREAMING", "STALE") else "NOT_RUN"
        )

    def disconnect(self):
        self.stop_event.set()
        if self.config and self.config.transport_type == "USB_SERIAL":
            self.serial_manager.stop()
            if (
                self.processing_worker
                and self.processing_worker is not threading.current_thread()
            ):
                self.processing_worker.join(timeout=1)
            self.connection_state = "DISCONNECTED"
            return self.board_status()
        if self.serial:
            try:
                self.serial.close()
            except Exception:
                pass
        if self.worker and self.worker is not threading.current_thread():
            self.worker.join(timeout=1)
        if (
            self.processing_worker
            and self.processing_worker is not threading.current_thread()
        ):
            self.processing_worker.join(timeout=1)
        self.serial = None
        self.connection_state = "DISCONNECTED"
        return self.status()

    def connect_verified(self, cfg: ConnectRequest):
        if not self.operation_lock.acquire(blocking=False):
            raise RuntimeError("ANOTHER BOARD OPERATION IS IN PROGRESS")
        try:
            if (
                cfg.transport_type == "USB_SERIAL"
                and self.connection_state == "ERROR"
                and not self.serial_manager.status()["reader_alive"]
            ):
                self.disconnect()
            self.connection_error = None
            self.verification = "NOT_RUN"
            if cfg.transport_type == "USB_SERIAL":
                devices = scan_serial_devices(include_non_usb=True)
                self.selected_device = next(
                    (
                        x
                        for x in devices
                        if x["port"].casefold() == str(cfg.serial_port).casefold()
                    ),
                    None,
                )
                if not self.selected_device:
                    raise RuntimeError("BOARD DISCONNECTED")
                return self.connect(cfg)
            else:
                self.selected_device = {"port": "MOCK", "is_usb": False}
            self.connect(cfg)
            self.connection_state = "VERIFYING"
            deadline = time.monotonic() + 2
            while (
                self.sequence < 3
                and self.connection_state != "ERROR"
                and time.monotonic() < deadline
            ):
                time.sleep(0.02)
            if self.sequence < 3:
                reason = (
                    "WRONG SERIAL PROTOCOL" if self.invalid else "DEVICE NOT RESPONDING"
                )
                self.connection_error = reason
                self.disconnect()
                raise RuntimeError(reason + ". FIRMWARE MAY NEED FLASHING")
            self.verification = "DATA_STREAM_VERIFIED"
            self.connection_state = "STREAMING"
            return self.board_status()
        finally:
            self.operation_lock.release()

    def board_status(self):
        result = self.status()
        serial_status = (
            self.serial_manager.status()
            if self.config and self.config.transport_type == "USB_SERIAL"
            else None
        )
        if serial_status:
            result.update(
                {
                    "connection_state": serial_status["state"],
                    "serial_port": serial_status["port"],
                    "invalid_packets": serial_status["invalid_packets"],
                    "latest_data_age_ms": serial_status["latest_data_age_ms"],
                    "connected_since": serial_status["connected_since"],
                    "reconnect_state": (
                        serial_status["state"]
                        if serial_status["state"] == "RECONNECTING"
                        else None
                    ),
                }
            )
        result.update(
            {
                "connection_error": (
                    serial_status["last_error"]
                    if serial_status
                    else self.connection_error
                ),
                "verification": self.verification,
                "device": (
                    serial_status["device"] if serial_status else self.selected_device
                ),
                "protocol_version": None,
                "firmware": self.firmware.status(
                    self.selected_device
                    if self.selected_device and self.selected_device.get("is_usb")
                    else None
                ),
            }
        )
        return result

    def board_test(self):
        status = self.board_status()
        fresh = (
            status["latest_data_age_ms"] is not None
            and status["latest_data_age_ms"] < 2500
        )
        return {
            "passed": status["connection_state"] == "STREAMING"
            and status["verification"] == "DATA_STREAM_VERIFIED"
            and fresh,
            "checks": {
                "usb_present": bool(status["is_mock"] or status["device"]),
                "serial_open": bool(status["is_mock"] or self.serial_manager.serial),
                "protocol_valid": status["verification"] == "DATA_STREAM_VERIFIED",
                "channels": {
                    "passed": status["channel_count"] > 0,
                    "actual": status["channel_count"],
                },
                "fresh_samples": fresh,
                "sample_rate_hz": status["received_rate_hz"],
            },
            "note": "Communication only; muscle activation is not required.",
        }

    def serial_diagnostics(self):
        value = self.serial_manager.status()
        value["configured_source"] = "Master connection request"
        value["raw_values_modified"] = False
        return value

    def reconnect(self):
        if not self.config or self.config.transport_type != "USB_SERIAL":
            raise RuntimeError("NO_PHYSICAL_BOARD_CONFIGURED")
        config = self.config.model_copy()
        self.disconnect()
        return self.connect_verified(config)

    def _add(self, channels, device_seq=None, device_ts=None, valid=True):
        now = time.perf_counter_ns()
        with self.lock:
            self.sequence += 1
            self.latest_ns = now
            sample = {
                "sequence_id": self.sequence,
                "host_timestamp_ns": now,
                "server_timestamp_ns": now,
                "device_sequence_id": device_seq,
                "device_timestamp": device_ts,
                "channels": {f"channel_{i+1}": v for i, v in enumerate(channels)},
                "valid": valid,
            }
            self.samples.append(sample)
        self.signal_quality.accept(sample["channels"])
        try:
            self.processing_queue.put_nowait(sample)
        except queue.Full:
            self.processing.processed_display_drop_count += 1

    def _processing_loop(self):
        while not self.stop_event.is_set() or not self.processing_queue.empty():
            try:
                first = self.processing_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            batch = [first]
            for _ in range(255):
                try:
                    batch.append(self.processing_queue.get_nowait())
                except queue.Empty:
                    break
            with self.processing_lock:
                processed = self.processing.process_batch(batch)
            completed = time.perf_counter_ns()
            for item in processed:
                item["processing_completed_ns"] = completed
            self.processed_samples.extend(processed)

    def _mock_loop(self):
        rate = self.config.expected_sample_rate_hz
        period = 1 / rate
        next_t = time.perf_counter()
        rng = random.Random(17)
        while not self.stop_event.is_set():
            now = time.perf_counter()
            while next_t <= now:
                scenario = self.config.mock_scenario
                values = []
                for i in range(len(self.config.channels)):
                    value = (
                        2048
                        + 90
                        * math.sin(2 * math.pi * (70 + i * 11) * self.sequence / rate)
                        + rng.gauss(0, 4)
                    )
                    if scenario == "POWERLINE_50HZ":
                        value += 180 * math.sin(2 * math.pi * 50 * self.sequence / rate)
                    elif scenario == "POWERLINE_60HZ":
                        value += 180 * math.sin(2 * math.pi * 60 * self.sequence / rate)
                    elif scenario == "FLATLINE":
                        value = 2048
                    elif scenario == "CLIPPING":
                        value = (
                            0
                            if self.sequence % 2
                            else (2 ** (self.config.adc_bits or 12) - 1)
                        )
                    values.append(value)
                n = self.sequence
                device_seq = n
                device_ts = n * (1000 / rate)
                if scenario == "SEQUENCE_GAPS":
                    device_seq = n + n // 100
                elif scenario == "DUPLICATES" and n % 100 == 0:
                    device_seq = max(0, n - 1)
                elif scenario == "CLOCK_DRIFT":
                    device_ts *= 1.0002
                elif scenario == "JITTER":
                    device_ts += (rng.random() - 0.5) * 0.3
                if scenario == "10_BIT_NORMAL":
                    values = [min(1023, max(0, 512 + (v - 2048) / 4)) for v in values]
                elif scenario == "SIGNED_16_BIT":
                    values = [v - 2048 for v in values]
                elif scenario == "OUT_OF_RANGE":
                    values = [5000 if n % 50 == 0 else v for v in values]
                elif scenario == "LOW_DYNAMIC_RANGE":
                    values = [2048 + (v - 2048) * 0.01 for v in values]
                elif scenario == "VARIABLE":
                    values = [v + (n // 500) * 80 for v in values]
                elif scenario == "DRIFT":
                    values = [v + n * 0.02 for v in values]
                self._add(values, device_seq, device_ts)
                next_t += period
            time.sleep(0.001)

    def status(self):
        now = time.perf_counter_ns()
        with self.lock:
            first_sample = self.samples[0] if len(self.samples) >= 2 else None
            last_sample = self.samples[-1] if len(self.samples) >= 2 else None
        sample_span = (
            (last_sample["host_timestamp_ns"] - first_sample["host_timestamp_ns"])
            / 1e9
            if first_sample and last_sample
            else 0
        )
        rate = (len(self.samples) - 1) / sample_span if sample_span > 0 else 0
        age = (now - self.latest_ns) / 1e6 if self.latest_ns else None
        return {
            "type": "emg.status",
            "connection_state": self.connection_state,
            "transport_type": self.config.transport_type if self.config else None,
            "serial_port": self.config.serial_port if self.config else None,
            "baud_rate": self.config.baud_rate if self.config else None,
            "protocol": self.config.protocol if self.config else None,
            "channel_count": len(self.config.channels) if self.config else 0,
            "channels": (
                [x.model_dump() for x in self.config.channels] if self.config else []
            ),
            "received_rate_hz": rate,
            "adc_bits": self.config.adc_bits if self.config else None,
            "latest_data_age_ms": age,
            "valid_samples": self.sequence,
            "invalid_packets": self.invalid,
            "recorder_drops": 0,
            "is_mock": bool(self.config and self.config.transport_type == "MOCK"),
            "recording_state": self.record_state,
            "processing": self.processing_status(),
            "baseline_state": self.baseline_state,
            "mock_scenario": self.config.mock_scenario if self.config else None,
        }

    def batch(self, after=0, limit=500):
        with self.lock:
            rows = [x for x in self.samples if x["sequence_id"] > after][-limit:]
        base = rows[0]["host_timestamp_ns"] if rows else 0
        processed = {
            x["sequence_id"]: x
            for x in self.processed_samples
            if x["sequence_id"] > after
        }
        samples = []
        for x in rows:
            item = {**x, "t_ms": (x["host_timestamp_ns"] - base) / 1e6}
            if x["sequence_id"] in processed:
                item["processed"] = {
                    key: {
                        name: value
                        for name, value in values.items()
                        if name in self.display_signals
                    }
                    for key, values in processed[x["sequence_id"]]["channels"].items()
                }
            samples.append(item)
        return {
            "type": "emg.samples",
            "schema_version": "2.0",
            "samples": samples,
            "latest_sequence_id": rows[-1]["sequence_id"] if rows else after,
        }

    def issue_ticket(self):
        ticket = secrets.token_urlsafe(24)
        self.tickets[ticket] = time.time() + 60
        return ticket

    def consume_ticket(self, ticket):
        expiry = self.tickets.pop(ticket, None)
        return bool(expiry and expiry >= time.time())

    def start_recording(self, request: RecordingRequest):
        if self.connection_state != "STREAMING":
            raise RuntimeError("NO EMG DEVICE CONNECTED")
        module = self.registry.validate_emg_label(
            request.rehab_type, request.research_label
        )
        if self.record_state in ("COUNTDOWN", "RECORDING", "FINALIZING"):
            raise RuntimeError("An EMG recording is active")
        self.recording_id = self._new_id()
        self.record_state = "COUNTDOWN"
        self.review = None
        self.cancel_event.clear()
        self.manual_stop_event.clear()
        self.recording_started_ns = None
        self.recording_countdown_started_ns = time.perf_counter_ns()
        self.recording_request = request
        self.record_markers = []
        self.record_thread = threading.Thread(
            target=self._record, args=(request, module), daemon=True
        )
        self.record_thread.start()
        return self.recording_status()

    def _new_id(self):
        now = datetime.now(timezone.utc)
        with self._db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS emg_sequence(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL)"
            )
            n = db.execute(
                "INSERT INTO emg_sequence(created_at) VALUES(?)", (now.isoformat(),)
            ).lastrowid
        return f"EMG-{now:%Y%m%d}-{n:06d}"

    def _record(self, req, module):
        if self.cancel_event.wait(req.countdown_seconds):
            self.record_state = "DISCARDED"
            return
        start_ns = time.perf_counter_ns()
        start_seq = self.sequence
        start_invalid = self.invalid
        self.recording_started_ns = start_ns
        self.record_state = "RECORDING"
        interrupted = False
        end = start_ns + int(req.duration_seconds * 1e9)
        while time.perf_counter_ns() < end and not self.cancel_event.is_set() and not self.manual_stop_event.is_set():
            if self.connection_state not in ("STREAMING",):
                interrupted = True
                break
            time.sleep(0.01)
        stop_ns = time.perf_counter_ns()
        self.record_state = "FINALIZING"
        if self.cancel_event.is_set():
            self.record_state = "DISCARDED"
            return
        with self.lock:
            rows = [
                x
                for x in self.samples
                if start_seq < x["sequence_id"] and x["host_timestamp_ns"] <= stop_ns
            ]
        self.review = self._write_temp(
            req, module, rows, start_ns, stop_ns, interrupted, max(0, self.invalid - start_invalid)
        )
        self.record_state = "REVIEW"

    def _write_temp(self, req, module, rows, start_ns, stop_ns, interrupted, invalid_packets):
        rid = self.recording_id
        base = self.settings.temp_dir / rid
        base.mkdir(parents=True, exist_ok=False)
        fields = (
            [
                "sequence_id",
                "host_timestamp_ns",
                "relative_timestamp_ms",
                "device_sequence_id",
                "device_timestamp",
            ]
            + [x.internal_id for x in self.config.channels]
            + ["valid"]
        )
        with (base / "emg_raw.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for x in rows:
                w.writerow(
                    {
                        "sequence_id": x["sequence_id"],
                        "host_timestamp_ns": x["host_timestamp_ns"],
                        "relative_timestamp_ms": (x["host_timestamp_ns"] - start_ns)
                        / 1e6,
                        "device_sequence_id": x["device_sequence_id"],
                        "device_timestamp": x["device_timestamp"],
                        **x["channels"],
                        "valid": x["valid"],
                    }
                )
        duration = (stop_ns - start_ns) / 1e9
        rate = (
            (len(rows) - 1)
            / ((rows[-1]["host_timestamp_ns"] - rows[0]["host_timestamp_ns"]) / 1e9)
            if len(rows) > 1
            else 0
        )
        warnings = []
        if interrupted:
            warnings.append("DEVICE_DISCONNECTED_DURING_RECORDING")
        if not rows:
            warnings.append("NO_SAMPLES")
        if (
            rate
            and abs(rate - self.config.expected_sample_rate_hz)
            / self.config.expected_sample_rate_hz
            > 0.2
        ):
            warnings.append("SAMPLE_RATE_OUTSIDE_TOLERANCE")
        quality = (
            "INVALID"
            if not rows
            else (
                "LOW_QUALITY"
                if interrupted
                else "USABLE_WITH_WARNINGS" if warnings else "GOOD"
            )
        )
        profile_snapshot = (
            self.hardware.snapshot(req.hardware_profile_id, req.hardware_profile_version)
            if req.hardware_profile_id
            else None
        )
        meta = {
            **req.model_dump(),
            "hardware_profile_version": (
                profile_snapshot.get("profile_version") if profile_snapshot else None
            ),
            "hardware_profile_snapshot": profile_snapshot,
            "raw_representation": (
                profile_snapshot.get("raw_representation")
                if profile_snapshot
                else "LEGACY_UNSPECIFIED"
            ),
            "physical_unit_conversion": (
                conversion_config(profile_snapshot)
                if profile_snapshot
                else {"available": False, "reason": "NO_HARDWARE_PROFILE"}
            ),
            "recording_id": rid,
            "modality": "EMG",
            "dataset_schema_version": "3.0",
            "emg_schema_version": "1.0-integrated",
            "rehab_slug": module.slug,
            "label_source": "MASTER_MANUAL",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "duration_requested": req.duration_seconds,
            "duration_actual": duration,
            "transport_type": self.config.transport_type,
            "serial_port": self.config.serial_port,
            "baud_rate": self.config.baud_rate,
            "protocol": self.config.protocol,
            "channel_count": len(self.config.channels),
            "channel_map": {
                x.internal_id: x.model_dump(exclude={"internal_id"})
                for x in self.config.channels
            },
            "raw_units": "ADC_COUNTS",
            "adc_bits": self.config.adc_bits,
            "expected_sample_rate_hz": self.config.expected_sample_rate_hz,
            "measured_sample_rate_hz": rate,
            "sample_count": len(rows),
            "invalid_packet_count": invalid_packets,
            "recorder_drop_count": 0,
            "recording_start_timestamp_ns": start_ns,
            "recording_stop_timestamp_ns": stop_ns,
            "stop_reason": "MANUAL_STOP" if self.manual_stop_event.is_set() else "DEVICE_INTERRUPTION" if interrupted else "FIXED_DURATION_COMPLETE",
            "interrupted": interrupted,
            "is_mock": self.config.transport_type == "MOCK",
            "technical_quality": quality,
            "training_eligible": False,
            "processing_provenance": {
                "processing_pipeline_version": self.processing.config.processing_version,
                "processing_config_hash": self.processing.config.hash,
                "processing_config": self.processing.config.model_dump(),
                "processing_sample_rate_hz": self.processing.config.processing_sample_rate_hz,
                "sample_rate_source": self.processing.config.sample_rate_source,
                "raw_recording_processed": False,
            },
        }
        (base / "events.json").write_text(
            json.dumps(
                {
                    "recording_id": rid,
                    "events": [
                        {"event": "RECORDING_STARTED", "host_timestamp_ns": start_ns, "relative_timestamp_ms": 0},
                        *self.record_markers,
                        {"event": "RECORDING_ENDED", "host_timestamp_ns": stop_ns, "relative_timestamp_ms": (stop_ns-start_ns)/1e6},
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (base / "quality_report.json").write_text(
            json.dumps(
                {
                    "recording_id": rid,
                    "technical_quality": quality,
                    "measured_sample_rate_hz": rate,
                    "sample_count": len(rows),
                    "invalid_packet_count": invalid_packets,
                    "recorder_drop_count": 0,
                    "interrupted": interrupted,
                    "warnings": warnings,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (base / "metadata.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        acquisition_quality = {
            "recording_id": rid, "scope": "ACQUISITION", "connection_interrupted": interrupted,
            "configured_sample_rate_hz": self.config.expected_sample_rate_hz,
            "measured_host_receive_rate_hz": rate, "sample_count": len(rows),
            "invalid_packet_count": invalid_packets, "recorder_drop_count": 0,
            "warnings": warnings,
        }
        monitor = EmgSignalQualityMonitor()
        for row in rows:
            if row.get("valid", True): monitor.accept(row["channels"])
        signal_quality = monitor.report(rate or self.config.expected_sample_rate_hz, self.config.adc_bits)
        timestamps = [row["host_timestamp_ns"] for row in rows]
        sequence_ids = [row["sequence_id"] for row in rows]
        integrity = {
            "recording_id": rid, "scope": "INTEGRITY",
            "raw_file_present": (base / "emg_raw.csv").is_file(),
            "raw_sha256": hashlib.sha256((base / "emg_raw.csv").read_bytes()).hexdigest(),
            "timestamps_monotonic": all(right > left for left, right in zip(timestamps, timestamps[1:])),
            "duplicate_sequence_ids": len(sequence_ids) - len(set(sequence_ids)),
            "sample_count_matches": len(rows) == meta["sample_count"],
            "valid": bool(rows) and not interrupted and len(sequence_ids) == len(set(sequence_ids)),
        }
        meta["raw_sha256"] = integrity["raw_sha256"]
        (base / "metadata.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        (base / "acquisition_quality_report.json").write_text(json.dumps(acquisition_quality, indent=2), encoding="utf-8")
        (base / "signal_quality_report.json").write_text(json.dumps(signal_quality, indent=2), encoding="utf-8")
        (base / "integrity_report.json").write_text(json.dumps(integrity, indent=2), encoding="utf-8")
        art = {
            p.name: {
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "size_bytes": p.stat().st_size,
            }
            for p in base.iterdir()
            if p.is_file()
        }
        (base / "artifact_manifest.json").write_text(
            json.dumps({"recording_id": rid, "artifacts": art}, indent=2),
            encoding="utf-8",
        )
        return {
            "recording_id": rid,
            "metadata": meta,
            "quality_report": json.loads((base / "quality_report.json").read_text()),
            "acquisition_quality_report": acquisition_quality,
            "signal_quality_report": signal_quality,
            "integrity_report": integrity,
            "events": json.loads((base / "events.json").read_text())["events"],
            "files": [p.name for p in base.iterdir()],
        }

    def recording_status(self):
        now = time.perf_counter_ns()
        elapsed = (now - self.recording_started_ns) / 1e9 if self.recording_started_ns and self.record_state in ("RECORDING", "FINALIZING", "REVIEW") else 0
        requested = self.recording_request.duration_seconds if self.recording_request else 0
        countdown = max(0, (self.recording_request.countdown_seconds if self.recording_request else 0) - ((now - self.recording_countdown_started_ns) / 1e9 if self.recording_countdown_started_ns else 0)) if self.record_state == "COUNTDOWN" else 0
        return {
            "state": self.record_state,
            "recording_id": self.recording_id,
            "elapsed_seconds": elapsed,
            "remaining_seconds": max(0, requested - elapsed),
            "countdown_remaining": countdown,
            "manual_stop": bool(self.recording_request and self.recording_request.manual_stop),
            "review": self.review,
        }

    def stop_recording(self):
        if self.record_state != "RECORDING":
            raise RuntimeError("No EMG recording is active")
        self.manual_stop_event.set()
        return self.recording_status()

    def add_recording_marker(self, event_type, notes=""):
        if self.record_state != "RECORDING" or not self.recording_started_ns:
            raise RuntimeError("Markers require an active EMG recording")
        now = time.perf_counter_ns()
        marker = {"event": event_type, "event_id": f"MARK-{secrets.token_hex(6).upper()}", "host_timestamp_ns": now, "relative_timestamp_ms": (now-self.recording_started_ns)/1e6, "notes": notes}
        self.record_markers.append(marker)
        return marker

    def cancel(self):
        self.cancel_event.set()
        return self.recording_status()

    def save(self, rid, review_status="APPROVED", training_eligible=None, review_notes=""):
        if self.record_state != "REVIEW" or rid != self.recording_id:
            raise RuntimeError("Recording is not ready")
        meta = self.review["metadata"]
        source = self.settings.temp_dir / rid
        technically_eligible = bool(review_status in ("APPROVED", "APPROVED_WITH_WARNINGS") and not meta.get("is_mock") and not meta.get("interrupted") and not meta.get("validation_recording") and meta.get("technical_quality") != "INVALID")
        eligible = technically_eligible and (training_eligible is not False)
        meta.update({"review_status": review_status, "approved": review_status in ("APPROVED", "APPROVED_WITH_WARNINGS"), "training_eligible": eligible, "review_notes": review_notes, "reviewed_at": datetime.now(timezone.utc).isoformat()})
        (source / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        artifacts = {p.name: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "size_bytes": p.stat().st_size} for p in source.iterdir() if p.is_file() and p.name != "artifact_manifest.json"}
        (source / "artifact_manifest.json").write_text(json.dumps({"recording_id": rid, "artifacts": artifacts}, indent=2), encoding="utf-8")
        target = (
            self.settings.rehab_dir / meta["rehab_slug"] / "emg" / "recordings" / rid
        )
        if not (source / "emg_raw.csv").is_file() or meta["sample_count"] <= 0:
            raise ValueError("EMG RECORDING INTEGRITY ERROR")
        shutil.move(str(source), str(target))
        relative = str(target.relative_to(self.settings.root)).replace("\\", "/")
        size = sum(p.stat().st_size for p in target.iterdir())
        with self._db() as db:
            db.execute(
                "INSERT INTO emg_recordings VALUES(" + ",".join("?" for _ in range(19)) + ")",
                (
                    rid,
                    meta["rehab_type"],
                    meta["rehab_slug"],
                    meta["subject_id"],
                    meta.get("session_id"),
                    meta["research_label"],
                    meta["affected_side"],
                    meta["created_at_utc"],
                    meta["duration_actual"],
                    meta["sample_count"],
                    meta["channel_count"],
                    meta["measured_sample_rate_hz"],
                    meta["technical_quality"],
                    int(meta["is_mock"]),
                    int(meta["interrupted"]),
                    int(meta["training_eligible"]),
                    0,
                    relative,
                    size,
                ),
            )
            db.execute(
                "INSERT INTO dataset_audit_log(timestamp,recording_id,action,previous_value,new_value) VALUES(?,?,?,?,?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    rid,
                    "EMG_RECORDING_APPROVED" if meta["approved"] else "EMG_RECORDING_RETAINED_FOR_TRACEABILITY",
                    None,
                    json.dumps({"rehab_type": meta["rehab_type"], "modality": "EMG"}),
                ),
            )
        self.generate_manifests()
        self.record_state = "SAVED"
        return meta

    def discard(self, rid):
        if rid != self.recording_id:
            raise RuntimeError("Recording unavailable")
        shutil.rmtree(self.settings.temp_dir / rid, ignore_errors=True)
        self.record_state = "DISCARDED"
        return {"success": True}

    def delete_saved(self, rid):
        current = self.get(rid)
        if not current:
            raise FileNotFoundError(rid)
        path = (self.settings.root / current["relative_path"]).resolve()
        if not path.is_relative_to(self.settings.root.resolve()):
            raise ValueError("Unsafe EMG dataset path")
        with self._db() as db:
            db.execute(
                "INSERT INTO dataset_audit_log(timestamp,recording_id,action,previous_value,new_value) VALUES(?,?,?,?,?)",
                (utcnow(), rid, "EMG_RECORDING_DELETED", json.dumps(current), None),
            )
            db.execute("DELETE FROM emg_recordings WHERE recording_id=?", (rid,))
        shutil.rmtree(path)
        self.generate_manifests()
        return {"success": True, "recording_id": rid}

    def list(
        self,
        slug,
        label="",
        mock="",
        hardware_profile_id="",
        hardware_version=None,
        channel_count=None,
        processing_version="",
        quality_profile_id="",
        study_id="",
        collection_id="",
        protocol_id="",
        trial_id="",
    ):
        module = self.registry.by_slug(slug)
        clauses = ["rehab_type=?"]
        values = [module.id]
        if label:
            clauses.append("research_label=?")
            values.append(label)
        if mock in ("REAL", "MOCK"):
            clauses.append("is_mock=?")
            values.append(int(mock == "MOCK"))
        with self._db() as db:
            rows = [
                dict(x)
                for x in db.execute(
                    "SELECT * FROM emg_recordings WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY created_at DESC",
                    values,
                )
            ]
        if channel_count is not None:
            rows = [x for x in rows if x["channel_count"] == channel_count]
        if any(
            (
                hardware_profile_id,
                hardware_version,
                processing_version,
                quality_profile_id,
                study_id,
                collection_id,
                protocol_id,
                trial_id,
            )
        ):
            filtered = []
            for x in rows:
                try:
                    meta = json.loads(
                        (
                            self.settings.root / x["relative_path"] / "metadata.json"
                        ).read_text()
                    )
                except Exception:
                    continue
                if (
                    hardware_profile_id
                    and meta.get("hardware_profile_id") != hardware_profile_id
                ):
                    continue
                if (
                    hardware_version is not None
                    and meta.get("hardware_profile_version") != hardware_version
                ):
                    continue
                if (
                    processing_version
                    and meta.get("processing_provenance", {}).get(
                        "processing_pipeline_version"
                    )
                    != processing_version
                ):
                    continue
                if (
                    quality_profile_id
                    and meta.get("quality_profile_id") != quality_profile_id
                ):
                    continue
                if study_id and meta.get("study_id") != study_id: continue
                if collection_id and meta.get("collection_id") != collection_id: continue
                if protocol_id and meta.get("protocol_id") != protocol_id: continue
                if trial_id and meta.get("trial_id") != trial_id: continue
                x.update({key:meta.get(key) for key in ("study_id","collection_id","protocol_id","protocol_version","trial_id","trial_number","attempt_number","sync_status")})
                filtered.append(x)
            rows = filtered
        return rows

    def get(self, rid):
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM emg_recordings WHERE recording_id=?", (rid,)
            ).fetchone()
        if not row:
            return None
        x = dict(row)
        base = self.settings.root / x["relative_path"]
        x["metadata"] = json.loads((base / "metadata.json").read_text())
        x["quality_report"] = json.loads((base / "quality_report.json").read_text())
        x["files"] = [p.name for p in base.iterdir()]
        return x

    def stats(self, slug):
        rows = self.list(slug)
        research_rows = []
        engineering_validation = 0
        for row in rows:
            try:
                metadata = json.loads(
                    (self.settings.root / row["relative_path"] / "metadata.json").read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                metadata = {}
            if metadata.get("validation_recording"):
                engineering_validation += 1
            else:
                research_rows.append(row)
        rows = research_rows
        subjects = {x["subject_id"] for x in rows}
        labels = {}
        channels = {}
        sides = {}
        quality = {}
        for x in rows:
            for d, k in (
                (labels, x["research_label"]),
                (channels, str(x["channel_count"])),
                (sides, x["affected_side"]),
                (quality, x["technical_quality"]),
            ):
                d[k] = d.get(k, 0) + 1
        return {
            "total_recordings": len(rows),
            "total_duration_seconds": sum(x["duration_seconds"] for x in rows),
            "training_eligible": sum(x["training_eligible"] for x in rows),
            "unique_subjects": len(subjects),
            "label_counts": labels,
            "channel_count_distribution": channels,
            "side_counts": sides,
            "quality_counts": quality,
            "storage_bytes": sum(x["storage_bytes"] for x in rows),
            "mock_recordings": sum(x["is_mock"] for x in rows),
            "engineering_validation_recordings": engineering_validation,
        }

    def generate_manifests(self):
        fields = [
            "recording_id",
            "modality",
            "rehab_type",
            "rehab_slug",
            "subject_id",
            "session_id",
            "study_id",
            "collection_id",
            "protocol_id",
            "protocol_version",
            "trial_id",
            "trial_number",
            "attempt_number",
            "sync_status",
            "research_label",
            "affected_side",
            "created_at",
            "duration_seconds",
            "sample_count",
            "channel_count",
            "measured_sample_rate_hz",
            "technical_quality",
            "is_mock",
            "interrupted",
            "training_eligible",
            "relative_path",
        ]
        for module in self.registry.modules:
            rows = self.list(module.slug)
            base = self.settings.rehab_dir / module.slug / "emg" / "manifests"
            for name, training in [
                ("dataset_manifest.csv", False),
                ("training_manifest.csv", True),
            ]:
                with (base / name).open("w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=fields)
                    w.writeheader()
                    for x in rows:
                        if training and (not x["training_eligible"] or x["is_mock"]):
                            continue
                        row = {**x, "modality": "EMG", "created_at": x["created_at"]}
                        w.writerow({key: row.get(key) for key in fields})

    def create_hardware_profile(self, payload):
        result = self.hardware.create(payload)
        self._audit(
            result["hardware_profile_id"], "EMG_HARDWARE_PROFILE_CREATED", result
        )
        return result

    def version_hardware_profile(self, profile_id, payload):
        result = self.hardware.version(profile_id, payload)
        self._audit(profile_id, "EMG_HARDWARE_PROFILE_VERSIONED", result)
        return result

    def hardware_profiles(self, include_archived=False):
        return self.hardware.list(include_archived)

    def hardware_profile(self, profile_id):
        return self.hardware.get(profile_id)

    def archive_hardware_profile(self, profile_id):
        return self.hardware.archive(profile_id)

    def hardware_history(self, profile_id):
        return self.hardware.validation_history(profile_id)

    def create_quality_profile(self, payload):
        return self.hardware.save_quality_profile(payload)

    def _audit(self, recording_id, action, value):
        with self._db() as db:
            db.execute(
                "INSERT INTO dataset_audit_log(timestamp,recording_id,action,previous_value,new_value) VALUES(?,?,?,?,?)",
                (utcnow(), recording_id, action, None, json.dumps(value)),
            )

    def _profile_samples(self, profile_id):
        profile = self.hardware.get(profile_id)
        if not profile:
            raise KeyError(profile_id)
        with self.lock:
            rows = list(self.samples)
        return profile, rows

    def validate_timing(self, profile_id):
        profile, rows = self._profile_samples(profile_id)
        return timing_validation(
            rows,
            profile["expected_sample_rate_hz"],
            profile.get("device_timestamp_unit"),
            profile.get("device_sequence_modulus"),
        )

    def validate_adc(self, profile_id):
        profile, rows = self._profile_samples(profile_id)
        return adc_validation(rows, profile)

    def validate_channels(self, profile_id):
        profile, rows = self._profile_samples(profile_id)
        return channel_check(rows, profile)

    def validate_powerline(self, profile_id):
        profile, rows = self._profile_samples(profile_id)
        return powerline_validation(
            rows,
            profile["expected_sample_rate_hz"],
            profile.get("mains_frequency_hz") or 50,
        )

    def validate_filter(self, profile_id):
        profile = self.hardware.get(profile_id)
        if not profile:
            raise KeyError(profile_id)
        cfg = self.processing.config.model_copy(
            update={"processing_sample_rate_hz": profile["expected_sample_rate_hz"]}
        ).model_dump()
        return filter_response(cfg)

    def validate_latency(self):
        with self.lock:
            rows = list(self.processed_samples)
        return host_pipeline_latency(rows)

    def quick_signal_check(self, profile_id):
        profile, rows = self._profile_samples(profile_id)
        return quick_check(
            rows[-5000:],
            profile["expected_sample_rate_hz"],
            profile["channel_count"],
            profile,
        )

    def baseline_repeatability_report(self, profile_id, baseline_ids):
        profile = self.hardware.get(profile_id)
        if not profile:
            raise KeyError(profile_id)
        trials = []
        for bid in baseline_ids:
            value = self.get_baseline(bid)
            if not value:
                raise KeyError(bid)
            trials.append(value)
        result = baseline_repeatability(trials)
        result.update(
            {
                "hardware_profile_id": profile_id,
                "hardware_profile_version": profile["profile_version"],
            }
        )
        self._audit(profile_id, "EMG_BASELINE_REPEATABILITY_RUN", result)
        return result

    def generate_hardware_report(self, profile_id, notes=""):
        profile, rows = self._profile_samples(profile_id)
        started = utcnow()
        timing = timing_validation(
            rows,
            profile["expected_sample_rate_hz"],
            profile.get("device_timestamp_unit"),
            profile.get("device_sequence_modulus"),
        )
        adc = adc_validation(rows, profile)
        channels = channel_check(rows, profile)
        powerline = powerline_validation(
            rows,
            profile["expected_sample_rate_hz"],
            profile.get("mains_frequency_hz") or 50,
        )
        filters = filter_response(
            self.processing.config.model_copy(
                update={"processing_sample_rate_hz": profile["expected_sample_rate_hz"]}
            ).model_dump()
        )
        latency = self.validate_latency()
        warnings = timing["warnings"] + adc["warnings"] + filters["warnings"]
        report = {
            "hardware_profile_id": profile_id,
            "hardware_profile_version": profile["profile_version"],
            "hardware_profile_snapshot": profile,
            "started_at": started,
            "completed_at": utcnow(),
            "status": "COMPLETE WITH WARNINGS" if warnings else "COMPLETE",
            "timing": timing,
            "adc_range": adc,
            "physical_unit_conversion": conversion_config(profile),
            "channel_check": channels,
            "powerline": powerline,
            "filter_response": {
                "sample_rate_hz": filters["sample_rate_hz"],
                "nyquist_hz": filters["nyquist_hz"],
                "warnings": filters["warnings"],
                "scipy_version": filters["scipy_version"],
            },
            "host_pipeline_latency": latency,
            "warnings": warnings,
            "notes": notes,
            "software_version": "FlexMap EMG Phase 4",
            "technical_conclusion": (
                "TECHNICAL WARNINGS PRESENT"
                if warnings
                else "TECHNICAL VALIDATION COMPLETED"
            ),
            "limitations": [
                "Software validation does not establish electrical or clinical safety.",
                "Host latency excludes device and USB buffering.",
                "No clinical interpretation is performed.",
            ],
        }
        saved = self.hardware.save_validation(report)
        self._audit(
            profile_id,
            "EMG_VALIDATION_COMPLETED",
            {
                "validation_run_id": saved["validation_run_id"],
                "status": saved["status"],
            },
        )
        return saved

    def assign_hardware_profile(self, rid, profile_id):
        item = self.get(rid)
        if not item:
            raise FileNotFoundError(rid)
        profile = self.hardware.snapshot(profile_id)
        path = self.settings.root / item["relative_path"] / "metadata.json"
        meta = json.loads(path.read_text())
        previous = meta.get("hardware_profile_id")
        meta.update(
            {
                "hardware_profile_id": profile_id,
                "hardware_profile_version": profile["profile_version"],
                "hardware_profile_snapshot": profile,
                "hardware_profile_assignment": "MASTER_EXPLICIT_LEGACY_ASSIGNMENT",
            }
        )
        path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        self._audit(
            rid,
            "EMG_HARDWARE_PROFILE_ASSIGNED",
            {"previous": previous, "new": profile_id},
        )
        return meta

    def processing_waveform(self, rid, proc_id, max_points=2000):
        item = self.get(rid)
        if not item:
            return None
        directory = self.settings.root / item["relative_path"] / "processing" / proc_id
        csv_path = directory / f"emg_processed_{proc_id}.csv"
        if not csv_path.is_file():
            return None
        with csv_path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        stride = max(1, len(rows) // max(1, min(max_points, 5000)))
        return {
            "recording_id": rid,
            "processing_run_id": proc_id,
            "samples": rows[::stride][:5000],
        }

    def file(self, rid, name):
        if name not in {
            "emg_raw.csv",
            "metadata.json",
            "quality_report.json",
            "events.json",
            "artifact_manifest.json",
        }:
            raise FileNotFoundError(name)
        x = self.get(rid)
        if not x:
            raise FileNotFoundError(name)
        path = (self.settings.root / x["relative_path"] / name).resolve()
        base = (self.settings.root / x["relative_path"]).resolve()
        if path.parent != base or not path.is_file():
            raise FileNotFoundError(name)
        return path
