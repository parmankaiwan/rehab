from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import flexmap_lifecycle as lifecycle


def test_env_parser_does_not_expand_or_print_secrets(tmp_path: Path):
    path = tmp_path / ".env"
    path.write_text("# comment\nTOKEN='private value'\nEMPTY=\n", encoding="utf-8")
    assert lifecycle._load_env(path) == {"TOKEN": "private value", "EMPTY": ""}


def test_instance_lock_prevents_duplicate_supervisor(tmp_path: Path):
    first = lifecycle.InstanceLock(tmp_path / "flexmap.lock")
    second = lifecycle.InstanceLock(tmp_path / "flexmap.lock")
    assert first.acquire() is True
    try:
        assert second.acquire() is False
    finally:
        first.release()
    assert second.acquire() is True
    second.release()


def test_hardware_reconnect_uses_bounded_command_file(tmp_path: Path, monkeypatch):
    command = tmp_path / "hardware-command.json"
    monkeypatch.setattr(lifecycle, "HARDWARE_COMMAND_PATH", command)
    supervisor = lifecycle.FlexMapSupervisor(open_browser=False)
    supervisor.children["hardware"] = SimpleNamespace(
        process=SimpleNamespace(poll=lambda: None, pid=123),
    )
    result = supervisor.command_hardware("emg")
    saved = json.loads(command.read_text(encoding="utf-8"))
    assert result == {"accepted": True, "target": "emg"}
    assert saved["action"] == "reconnect_emg"
    assert saved["id"]


def test_browser_camera_lease_releases_python_owner_and_restores_after_expiry(tmp_path: Path, monkeypatch):
    command = tmp_path / "hardware-command.json"
    monkeypatch.setattr(lifecycle, "HARDWARE_COMMAND_PATH", command)
    supervisor = lifecycle.FlexMapSupervisor(open_browser=False)
    assert supervisor.camera_lease("page-1", "acquire")["accepted"] is True
    assert json.loads(command.read_text(encoding="utf-8"))["action"] == "release_cv"
    supervisor.browser_lease_until = time.monotonic() - 1
    supervisor._expire_camera_lease()
    assert json.loads(command.read_text(encoding="utf-8"))["action"] == "reconnect_cv"


def test_second_browser_camera_owner_is_rejected(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(lifecycle, "HARDWARE_COMMAND_PATH", tmp_path / "hardware-command.json")
    supervisor = lifecycle.FlexMapSupervisor(open_browser=False)
    supervisor.camera_lease("page-1", "acquire")
    result = supervisor.camera_lease("page-2", "acquire")
    assert result["accepted"] is False
    assert result["owner"] == "browser"


def test_status_rejects_stale_hardware_as_live(tmp_path: Path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "hardware-status.json").write_text(
        json.dumps({"updated_at": time.time() - 60, "cv_process_running": True, "emg": {"state": "STREAMING", "latest_data_age_ms": 1}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(lifecycle, "RUNTIME_ROOT", runtime)
    monkeypatch.setattr(lifecycle, "_json_get", lambda url, **kwargs: {"application": "flexmap-api"} if url.endswith("/health") else {})
    supervisor = lifecycle.FlexMapSupervisor(open_browser=False)
    result = supervisor.status()
    assert result["cv"]["process_running"] is False
    assert result["cv"]["source"] == "UNAVAILABLE"
    assert result["cv"]["owner"] == "none"
    assert result["emg"]["signal_live"] is False
    assert result["emg"]["state"] == "DISCONNECTED"
    assert result["controls"]["reconnect_cv"] is False


def test_shutdown_targets_only_registered_children(monkeypatch):
    supervisor = lifecycle.FlexMapSupervisor(open_browser=False)
    stopped: list[str] = []
    supervisor.children = {
        name: SimpleNamespace(name=name) for name in ("backend", "frontend", "hardware")
    }
    monkeypatch.setattr(supervisor, "_terminate", lambda item: stopped.append(item.name))
    monkeypatch.setattr(supervisor, "_write_state", lambda: None)
    supervisor.shutdown()
    assert stopped == ["hardware", "frontend", "backend"]


def test_unrelated_flexmap_backend_is_never_adopted_as_owned(monkeypatch):
    monkeypatch.setattr(lifecycle, "_json_get", lambda *_args, **_kwargs: {"application": "flexmap-api"})
    supervisor = lifecycle.FlexMapSupervisor(open_browser=False)
    assert supervisor._existing_backend() is True
    assert "backend" not in supervisor.children


def test_watchdog_restarts_only_failed_owned_component(monkeypatch, tmp_path: Path):
    supervisor = lifecycle.FlexMapSupervisor(open_browser=False)
    supervisor.state = "RUNNING"
    closed: list[bool] = []
    supervisor.children["backend"] = SimpleNamespace(
        process=SimpleNamespace(poll=lambda: 1),
        log_handle=SimpleNamespace(close=lambda: closed.append(True)),
        started_at=time.monotonic() - 1,
    )
    supervisor.process_specs["backend"] = (["python", "-m", "backend.app"], tmp_path, {})
    supervisor.restart_after["backend"] = time.monotonic() - 1
    spawned: list[str] = []
    monkeypatch.setattr(supervisor, "_spawn", lambda name, *_args: spawned.append(name))
    supervisor._watchdog()
    assert spawned == ["backend"]
    assert closed
