"""HTTP + Server-Sent-Events front end for the sensor engine (stdlib only)."""

from __future__ import annotations

import json
import logging
import queue
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlsplit

from . import discovery
from .device import PROTOCOLS, WitMotionError
from .engine import SensorEngine
from .registers import (
    ALGORITHMS, BANDWIDTHS, BAUD_RATES, CALSW_MODES, ORIENTATIONS, REGISTERS,
)

log = logging.getLogger("witmotion.server")

WEB_DIR = Path(__file__).resolve().parent / "web"
MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".json": "application/json",
}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class WitServer(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets two servers share a port; don't.
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, address, engine: SensorEngine, allow_remote: bool = False):
        super().__init__(address, Handler)
        self.engine = engine
        self.allow_remote = allow_remote
        self.stopping = threading.Event()
        self._scan_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server: WitServer
    server_version = "WitMotion"

    # ---- plumbing ------------------------------------------------------ #
    def log_message(self, fmt, *args):  # quieter than the default stderr spam
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _host_ok(self) -> bool:
        """Reject DNS-rebinding / cross-site requests unless remote access is enabled."""
        if self.server.allow_remote:
            return True
        host = (self.headers.get("Host") or "").strip()
        if host.startswith("["):
            host = host[1:host.find("]")] if "]" in host else host
        else:
            host = host.rsplit(":", 1)[0]
        return host.lower() in LOCAL_HOSTS

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin or self.server.allow_remote:
            return True
        return (urlsplit(origin).hostname or "").lower() in LOCAL_HOSTS

    def _send(self, status: int, body: bytes, ctype: str, extra: Optional[dict] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, status: int = 200) -> None:
        self._send(status, json.dumps(obj, default=str).encode("utf-8"), "application/json")

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def _body(self) -> dict:
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            raise PermissionError("Content-Type must be application/json")
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1_000_000:
            raise ValueError("request too large")
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw or b"{}")
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    # ---- GET ----------------------------------------------------------- #
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._host_ok():
            return self._error(403, "forbidden host")
        path = urlsplit(self.path).path
        engine = self.server.engine
        try:
            if path == "/api/status":
                return self._json(engine.status())
            if path == "/api/ports":
                return self._json(discovery.list_ports())
            if path == "/api/sample":
                return self._json(engine.latest.to_dict() if engine.latest else None)
            if path == "/api/meta":
                return self._json(_meta())
            if path == "/api/recordings":
                return self._json({"directory": str(engine.recorder.directory.resolve()),
                                   "files": engine.recorder.list(),
                                   "status": engine.recorder.status()})
            if path == "/api/settings":
                return self._json(engine.load_settings())
            if path == "/api/stream":
                return self._stream()
            if path.startswith("/recordings/"):
                return self._download(unquote(path[len("/recordings/"):]))
            if path.startswith("/api/"):
                return self._error(404, "not found")
            return self._static(path)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _static(self, path: str) -> None:
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (WEB_DIR / unquote(rel)).resolve()
        try:
            target.relative_to(WEB_DIR)
        except ValueError:
            return self._error(404, "not found")
        if not target.is_file():
            return self._error(404, "not found")
        ctype = MIME.get(target.suffix.lower(), "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)

    def _download(self, name: str) -> None:
        p = self.server.engine.recorder.path_for(name)
        if p is None:
            return self._error(404, "no such recording")
        self._send(200, p.read_bytes(), "text/csv; charset=utf-8",
                   {"Content-Disposition": f'attachment; filename="{p.name}"'})

    def _sse(self, event: str, data) -> None:
        msg = f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n".encode("utf-8")
        self.wfile.write(msg)

    def _stream(self) -> None:
        engine = self.server.engine
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q = engine.subscribe()
        try:
            self._sse("status", engine.status())
            if engine.latest is not None:
                self._sse("sample", engine.latest.to_dict())
            self.wfile.flush()
            last_status = time.monotonic()
            while not self.server.stopping.is_set():
                try:
                    kind, payload = q.get(timeout=0.5)
                    self._sse(kind, payload)
                    # Drain anything else that is already queued, then flush once.
                    while True:
                        try:
                            kind, payload = q.get_nowait()
                        except queue.Empty:
                            break
                        self._sse(kind, payload)
                except queue.Empty:
                    pass
                if time.monotonic() - last_status >= 1.0:
                    self._sse("status", engine.status())
                    last_status = time.monotonic()
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            engine.unsubscribe(q)

    # ---- POST ---------------------------------------------------------- #
    def do_POST(self):
        if not self._host_ok() or not self._origin_ok():
            return self._error(403, "forbidden origin")
        path = urlsplit(self.path).path
        engine = self.server.engine
        try:
            body = self._body()
            if path == "/api/connect":
                proto = body.get("protocol", "modbus")
                if proto not in PROTOCOLS:
                    raise ValueError(f"unknown protocol {proto!r}")
                return self._json(engine.connect(
                    port=str(body.get("port") or ("SIMULATOR" if proto == "simulated" else "")),
                    baudrate=int(body.get("baudrate", 115200)),
                    address=_int(body.get("address", 0x50)),
                    protocol=proto,
                    rate_hz=float(body.get("rate_hz", engine.rate_hz)),
                ))
            if path == "/api/disconnect":
                return self._json(engine.disconnect())
            if path == "/api/scan":
                return self._json(self._scan(body))
            if path == "/api/command":
                action = str(body.pop("action", ""))
                return self._json(engine.command(action, body))
            if path == "/api/record/start":
                if engine.device is None:
                    raise WitMotionError("connect a sensor before recording")
                return self._json(engine.recorder.start(body.get("name")))
            if path == "/api/record/stop":
                return self._json(engine.recorder.stop())
            return self._error(404, "not found")
        except PermissionError as exc:
            return self._error(415, str(exc))
        except (ValueError, KeyError, TypeError) as exc:
            return self._error(400, f"bad request: {exc}")
        except WitMotionError as exc:
            return self._error(409, str(exc))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as exc:  # noqa: BLE001
            log.exception("unhandled error")
            return self._error(500, f"{type(exc).__name__}: {exc}")

    def _scan(self, body: dict) -> dict:
        engine = self.server.engine
        if not self.server._scan_lock.acquire(blocking=False):
            raise WitMotionError("a scan is already running")
        try:
            busy_port = engine.device.port if engine.device else None
            ports = body.get("ports")
            if ports is None:
                ports = [p["device"] for p in discovery.list_ports()
                         if body.get("all_ports") or p["likely"]]
            ports = [p for p in ports if p != busy_port]
            bauds = [int(b) for b in body.get("bauds") or discovery.DEFAULT_BAUDS]
            addresses = [_int(a) for a in body.get("addresses") or [0x50]]
            found = discovery.scan(ports, bauds, addresses)
            return {"scanned": ports, "found": found, "skipped": busy_port}
        finally:
            self.server._scan_lock.release()


def _int(v) -> int:
    if isinstance(v, str):
        return int(v.strip(), 0)
    return int(v)


def _meta() -> dict:
    return {
        "registers": [r.to_dict() for r in REGISTERS.values()],
        "baud_rates": sorted(BAUD_RATES.values()),
        "bandwidths": BANDWIDTHS,
        "algorithms": ALGORITHMS,
        "orientations": ORIENTATIONS,
        "calsw": CALSW_MODES,
        "protocols": sorted(PROTOCOLS),
    }


def make_server(engine: SensorEngine, host: str = "127.0.0.1", port: int = 8765) -> WitServer:
    allow_remote = host not in LOCAL_HOSTS
    return WitServer((host, port), engine, allow_remote=allow_remote)


def serve_forever(server: WitServer) -> None:
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.stopping.set()
        server.server_close()
