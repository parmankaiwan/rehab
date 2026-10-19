"""Windows lifecycle supervisor for the local FlexMap application.

This process is the only authority allowed to start and stop a local FlexMap
session.  It tracks exact child PIDs, exposes an authenticated loopback control
socket, and never scans for or terminates arbitrary Python/Node processes.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
CV_ROOT = ROOT.parent / "CV part"
RUNTIME_ROOT = ROOT / "data" / "runtime"
LOCK_PATH = RUNTIME_ROOT / "flexmap.lock"
STATE_PATH = RUNTIME_ROOT / "lifecycle.json"
HARDWARE_COMMAND_PATH = RUNTIME_ROOT / "hardware-command.json"
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = 8766


def _load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _json_get(url: str, timeout: float = 1.5, headers: dict[str, str] | None = None) -> dict[str, Any] | None:
    try:
        request = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            value = json.loads(response.read().decode("utf-8"))
            return value if isinstance(value, dict) else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def _wait_json(url: str, predicate, timeout: float) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = _json_get(url)
        if value is not None and predicate(value):
            return value
        time.sleep(0.25)
    return None


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.25)
        return connection.connect_ex(("127.0.0.1", port)) == 0


class InstanceLock:
    def __init__(self, path: Path = LOCK_PATH) -> None:
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0)
        if self.handle.tell() == 0 and self.path.stat().st_size == 0:
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
        self.handle = None


@dataclass
class ManagedProcess:
    name: str
    process: subprocess.Popen
    log_handle: Any
    command: list[str]
    started_at: float


class FlexMapSupervisor:
    def __init__(self, *, open_browser: bool = True, start_hardware: bool = True) -> None:
        self.open_browser = open_browser
        self.start_hardware = start_hardware
        self.token = secrets.token_urlsafe(32)
        self.stop_event = threading.Event()
        self.state = "PREFLIGHT"
        self.started_at = time.time()
        self.children: dict[str, ManagedProcess] = {}
        self.process_specs: dict[str, tuple[list[str], Path, dict[str, str]]] = {}
        self.restart_attempts: dict[str, int] = {}
        self.restart_after: dict[str, float] = {}
        self.errors: list[str] = []
        self.server: ThreadingHTTPServer | None = None
        self.lock = InstanceLock()
        self._mutex = threading.RLock()
        self.browser_lease_id = ""
        self.browser_lease_until = 0.0
        self.root_env = _load_env(ROOT / ".env")
        self.agent_env = _load_env(ROOT / ".env.agent")
        self.web_env = _load_env(WEB_ROOT / ".env.local")

    def _base_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(self.root_env)
        master = self.root_env.get("FLEXMAP_MASTER_INTERNAL_TOKEN") or self.web_env.get("MASTER_INTERNAL_TOKEN")
        engine = self.root_env.get("FLEXMAP_ENGINE_TOKEN") or self.agent_env.get("FLEXMAP_ENGINE_TOKEN")
        if master:
            env["FLEXMAP_MASTER_INTERNAL_TOKEN"] = master
        if engine:
            env["FLEXMAP_ENGINE_TOKEN"] = engine
        env.update(
            FLEXMAP_LIFECYCLE_URL=f"http://{CONTROL_HOST}:{CONTROL_PORT}",
            FLEXMAP_LIFECYCLE_TOKEN=self.token,
            FLEXMAP_LOCAL_LIFECYCLE_ENABLED="true",
            FLEXMAP_BACKEND_URL="http://127.0.0.1:8000",
        )
        return env

    def preflight(self) -> None:
        if not (ROOT / "backend" / "app.py").is_file():
            raise RuntimeError("FastAPI application was not found")
        if not (WEB_ROOT / "package.json").is_file():
            raise RuntimeError("Next.js application was not found")
        if not shutil.which("node") or not shutil.which("npm"):
            raise RuntimeError("Node.js and npm are required")
        try:
            __import__("fastapi")
            __import__("uvicorn")
        except ImportError as exc:
            raise RuntimeError(f"Python dependency is missing: {exc.name}") from exc
        if not self.root_env.get("FLEXMAP_MASTER_INTERNAL_TOKEN") and not self.web_env.get("MASTER_INTERNAL_TOKEN"):
            self.errors.append("Master data token is unavailable; authenticated research pages will remain unavailable")
        supabase_secret = self.root_env.get("FLEXMAP_SUPABASE_SECRET_KEY") or self.root_env.get("SUPABASE_SERVICE_ROLE_KEY")
        if not self.root_env.get("FLEXMAP_SUPABASE_URL") or not supabase_secret:
            self.errors.append("Supabase configuration is incomplete; live monitoring can continue without cloud storage")
        if self.start_hardware:
            cv_python = CV_ROOT / ".venv" / "Scripts" / "python.exe"
            if not cv_python.is_file() or not (CV_ROOT / "main.py").is_file():
                self.errors.append("CV runtime unavailable; website and backend will still start")
            if not self.agent_env.get("FLEXMAP_ENGINE_TOKEN") and not self.root_env.get("FLEXMAP_ENGINE_TOKEN"):
                self.errors.append("Hardware token missing; CV and EMG agent will not start")

    def _spawn(self, name: str, command: list[str], cwd: Path, env: dict[str, str]) -> ManagedProcess:
        log_dir = RUNTIME_ROOT / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log = (log_dir / f"{name}.log").open("a", encoding="utf-8", buffering=1)
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        item = ManagedProcess(name, process, log, command, time.monotonic())
        self.children[name] = item
        self.process_specs[name] = (list(command), cwd, env.copy())
        self._write_state()
        return item

    def _existing_backend(self) -> bool:
        health = _json_get("http://127.0.0.1:8000/health")
        return bool(health and health.get("application") == "flexmap-api")

    def _existing_frontend(self) -> bool:
        identity = _json_get("http://127.0.0.1:3000/api/lifecycle-identity")
        return bool(identity and identity.get("application") == "flexmap-web")

    def start_services(self) -> None:
        env = self._base_env()
        self.state = "STARTING_BACKEND"
        self._write_state()
        if self._existing_backend():
            self.errors.append("Using independently started FlexMap backend; it will not be stopped by this launcher")
        else:
            if _port_in_use(8000):
                raise RuntimeError("Port 8000 is occupied by a service that is not the FlexMap API; it was not terminated")
            self._spawn("backend", [sys.executable, "-m", "backend.app"], ROOT, env)
        if not _wait_json("http://127.0.0.1:8000/health", lambda v: v.get("application") == "flexmap-api", 35):
            raise RuntimeError("FastAPI did not become ready on port 8000")

        self.state = "STARTING_FRONTEND"
        self._write_state()
        if self._existing_frontend():
            self.errors.append("Using independently started FlexMap frontend; it will not be stopped by this launcher")
        else:
            if _port_in_use(3000):
                raise RuntimeError("Port 3000 is occupied by a service that is not FlexMap; it was not terminated")
            npm = shutil.which("npm") or "npm"
            command = [npm, "run", "dev"]
            if os.name == "nt":
                command = [os.environ.get("ComSpec", "cmd.exe"), "/d", "/s", "/c", "npm run dev"]
            self._spawn("frontend", command, WEB_ROOT, env)
        if not _wait_json("http://127.0.0.1:3000/api/lifecycle-identity", lambda v: v.get("application") == "flexmap-web", 60):
            raise RuntimeError("Next.js did not become ready on port 3000")

        self.state = "INITIALIZING_DEVICES"
        self._write_state()
        token = env.get("FLEXMAP_ENGINE_TOKEN")
        if self.start_hardware and token and not self.children.get("hardware"):
            hardware_env = env.copy()
            hardware_env.update(self.agent_env)
            hardware_env["FLEXMAP_WEB_BACKEND"] = "http://127.0.0.1:8000"
            hardware_env["FLEXMAP_ENGINE_TOKEN"] = token
            self._spawn("hardware", [sys.executable, "local_agent.py"], ROOT, hardware_env)

        self.state = "RUNNING"
        self._write_state()
        if self.open_browser:
            webbrowser.open("http://localhost:3000/master")

    def _child_status(self, name: str) -> dict[str, Any]:
        item = self.children.get(name)
        if not item:
            return {"managed": False, "running": False, "pid": None}
        return {"managed": True, "running": item.process.poll() is None, "pid": item.process.pid}

    def status(self) -> dict[str, Any]:
        hardware: dict[str, Any] = {}
        hardware_path = RUNTIME_ROOT / "hardware-status.json"
        with contextlib.suppress(OSError, ValueError):
            candidate = json.loads(hardware_path.read_text(encoding="utf-8"))
            if time.time() - float(candidate.get("updated_at", 0)) < 3:
                hardware = candidate
        backend_health = _json_get("http://127.0.0.1:8000/health")
        frontend_health = _json_get("http://127.0.0.1:3000/api/lifecycle-identity")
        video = _json_get("http://127.0.0.1:8000/api/video/metrics") or {}
        frame_age = video.get("backend_frame_age_ms")
        cv_fresh = isinstance(frame_age, (int, float)) and frame_age < 2500
        emg = hardware.get("emg") if isinstance(hardware.get("emg"), dict) else {}
        emg_live = emg.get("state") == "STREAMING" and (emg.get("latest_data_age_ms") or 1e9) < 2500
        browser_owner = self.browser_lease_until > time.monotonic()
        hardware_agent = self._child_status("hardware")
        camera_owner = "browser" if browser_owner else "local_agent" if hardware_agent["running"] else "none"
        camera_source = "BROWSER_MEDIAPIPE" if browser_owner else "PYTHON_ENGINE" if hardware_agent["running"] else "UNAVAILABLE"
        return {
            "deployment": "LOCAL_WINDOWS",
            "application": self.state,
            "started_at": self.started_at,
            "backend": {**self._child_status("backend"), "ready": bool(backend_health)},
            "frontend": {**self._child_status("frontend"), "ready": bool(frontend_health)},
            "hardware_agent": hardware_agent,
            "cv": {
                "process_running": bool(hardware.get("cv_process_running")),
                "camera_live": cv_fresh,
                "source": camera_source,
                "owner": camera_owner,
                "error": hardware.get("cv_error"),
            },
            "emg": {
                "agent_running": hardware_agent["running"],
                "board_connected": emg.get("state") == "STREAMING",
                "signal_live": emg_live,
                "state": emg.get("state", "DISCONNECTED"),
                "port": emg.get("port"),
                "latest_data_age_ms": emg.get("latest_data_age_ms"),
                "error": emg.get("last_error"),
            },
            "supabase": {"state": self._supabase_state()},
            "errors": list(self.errors),
            "controls": {
                "reconnect_cv": hardware_agent["running"],
                "reconnect_emg": hardware_agent["running"],
                "exit": True,
            },
        }

    def _supabase_state(self) -> str:
        token = self._base_env().get("FLEXMAP_MASTER_INTERNAL_TOKEN")
        if not token:
            return "UNAVAILABLE"
        value = _json_get(
            "http://127.0.0.1:8000/api/master/storage/status",
            timeout=3,
            headers={"X-FlexMap-Master-Token": token},
        )
        return str(value.get("state", "UNAVAILABLE")) if value else "UNAVAILABLE"

    def command_hardware(self, target: str) -> dict[str, Any]:
        if target not in {"cv", "emg"}:
            raise ValueError("Unsupported reconnect target")
        if not self._child_status("hardware")["running"]:
            return {"accepted": False, "message": "Hardware agent is not running"}
        payload = {"id": secrets.token_hex(12), "action": f"reconnect_{target}", "created_at": time.time()}
        temp = HARDWARE_COMMAND_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(payload), encoding="utf-8")
        temp.replace(HARDWARE_COMMAND_PATH)
        return {"accepted": True, "target": target}

    def camera_lease(self, lease_id: str, action: str) -> dict[str, Any]:
        if not lease_id or len(lease_id) > 100:
            raise ValueError("A bounded camera lease ID is required")
        with self._mutex:
            if action in {"acquire", "renew"}:
                if self.browser_lease_id and self.browser_lease_id != lease_id and self.browser_lease_until > time.monotonic():
                    return {"accepted": False, "owner": "browser", "message": "Camera is already leased by another FlexMap page"}
                first = self.browser_lease_until <= time.monotonic()
                self.browser_lease_id = lease_id
                self.browser_lease_until = time.monotonic() + 5
                if first:
                    self._write_hardware_action("release_cv")
                return {"accepted": True, "owner": "browser", "expires_seconds": 5}
            if action == "release" and self.browser_lease_id == lease_id:
                self.browser_lease_id = ""
                self.browser_lease_until = 0
                self._write_hardware_action("reconnect_cv")
                return {"accepted": True, "owner": "local_agent"}
        return {"accepted": False, "owner": "local_agent"}

    def _write_hardware_action(self, action: str) -> None:
        payload = {"id": secrets.token_hex(12), "action": action, "created_at": time.time()}
        temp = HARDWARE_COMMAND_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(payload), encoding="utf-8")
        temp.replace(HARDWARE_COMMAND_PATH)

    def _expire_camera_lease(self) -> None:
        with self._mutex:
            if self.browser_lease_id and self.browser_lease_until <= time.monotonic():
                self.browser_lease_id = ""
                self.browser_lease_until = 0
                self._write_hardware_action("reconnect_cv")

    def _watchdog(self) -> None:
        if self.state != "RUNNING":
            return
        for name, item in list(self.children.items()):
            if item.process.poll() is None:
                if time.monotonic() - item.started_at >= 30:
                    self.restart_attempts[name] = 0
                continue
            with contextlib.suppress(OSError):
                item.log_handle.close()
            attempt = self.restart_attempts.get(name, 0)
            if attempt >= 5:
                message = f"{name} stopped repeatedly; automatic restart is paused"
                if message not in self.errors:
                    self.errors.append(message)
                continue
            deadline = self.restart_after.get(name)
            if deadline is None:
                self.restart_after[name] = time.monotonic() + (1, 2, 5, 10, 20)[attempt]
                continue
            if time.monotonic() < deadline:
                continue
            command, cwd, env = self.process_specs[name]
            self.restart_attempts[name] = attempt + 1
            self.restart_after.pop(name, None)
            self._spawn(name, command, cwd, env)

    def _write_state(self) -> None:
        RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
        value = {
            "application": self.state,
            "supervisor_pid": os.getpid(),
            "control_url": f"http://{CONTROL_HOST}:{CONTROL_PORT}",
            "children": {name: item.process.pid for name, item in self.children.items()},
            "updated_at": time.time(),
        }
        temp = STATE_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
        temp.replace(STATE_PATH)

    def start_control_server(self) -> None:
        supervisor = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:
                return

            def _authorized(self) -> bool:
                return secrets.compare_digest(self.headers.get("X-FlexMap-Lifecycle-Token", ""), supervisor.token)

            def _send(self, status: int, body: dict[str, Any]) -> None:
                encoded = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(encoded)

            def do_GET(self) -> None:
                if not self._authorized():
                    self._send(403, {"error": "authorization required"})
                elif self.path == "/status":
                    self._send(200, supervisor.status())
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self) -> None:
                if not self._authorized():
                    self._send(403, {"error": "authorization required"})
                    return
                if self.path == "/stop":
                    self._send(202, {"accepted": True})
                    threading.Thread(target=supervisor.stop_event.set, daemon=True).start()
                elif self.path in {"/reconnect/cv", "/reconnect/emg"}:
                    self._send(202, supervisor.command_hardware(self.path.rsplit("/", 1)[-1]))
                elif self.path == "/camera/lease":
                    try:
                        length = min(int(self.headers.get("Content-Length", "0")), 4096)
                        payload = json.loads(self.rfile.read(length) or b"{}")
                        self._send(200, supervisor.camera_lease(str(payload.get("lease_id", "")), str(payload.get("action", ""))))
                    except (ValueError, json.JSONDecodeError) as exc:
                        self._send(400, {"accepted": False, "message": str(exc)})
                else:
                    self._send(404, {"error": "not found"})

        self.server = ThreadingHTTPServer((CONTROL_HOST, CONTROL_PORT), Handler)
        threading.Thread(target=self.server.serve_forever, name="flexmap-lifecycle-control", daemon=True).start()

    def _terminate(self, item: ManagedProcess, timeout: float = 8) -> None:
        if item.process.poll() is not None:
            item.log_handle.close()
            return
        with contextlib.suppress(OSError):
            if os.name == "nt":
                item.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                item.process.terminate()
        try:
            item.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Exact owned process tree only. Never target by image name.
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(item.process.pid), "/T", "/F"], capture_output=True, check=False)
            else:
                item.process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                item.process.wait(timeout=3)
        item.log_handle.close()

    def shutdown(self) -> None:
        self.state = "STOPPING"
        self._write_state()
        # Hardware first so camera and serial resources are released before API shutdown.
        for name in ("hardware", "frontend", "backend"):
            item = self.children.get(name)
            if item:
                self._terminate(item)
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        self.state = "STOPPED"
        self._write_state()

    def run(self) -> int:
        if not self.lock.acquire():
            print("FlexMap is already managed. Opening the existing application.")
            if self.open_browser:
                webbrowser.open("http://localhost:3000/master")
            return 0
        try:
            self.preflight()
            HARDWARE_COMMAND_PATH.unlink(missing_ok=True)
            self.start_control_server()
            self.start_services()
            print("FlexMap is ready at http://localhost:3000/master")
            print("Use Exit FlexMap in System Diagnostics, or press Ctrl+C here.")
            while not self.stop_event.wait(0.5):
                self._expire_camera_lease()
                self._watchdog()
            return 0
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            self.errors.append(str(exc))
            self.state = "ERROR"
            self._write_state()
            print(f"FlexMap startup failed: {exc}", file=sys.stderr)
            return 1
        finally:
            self.shutdown()
            self.lock.release()


def request_existing(path: str) -> bool:
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        url = str(state["control_url"]).rstrip("/") + path
        # The token is intentionally not persisted. Commands are available through
        # the authenticated FastAPI bridge; this CLI only reports managed state.
        print(f"Use the authenticated Master System page to request {path}.")
        return bool(url)
    except (OSError, ValueError, KeyError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the local FlexMap application")
    parser.add_argument("command", choices=("start", "status"), nargs="?", default="start")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-hardware", action="store_true", help="Start web services without camera/serial owners")
    args = parser.parse_args()
    if args.command == "status":
        if not STATE_PATH.is_file():
            print("FlexMap is not managed")
            return 1
        print(STATE_PATH.read_text(encoding="utf-8"))
        return 0
    return FlexMapSupervisor(open_browser=not args.no_browser, start_hardware=not args.no_hardware).run()


if __name__ == "__main__":
    raise SystemExit(main())
