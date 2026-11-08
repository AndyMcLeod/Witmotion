"""The sensor engine: owns the device, polls it in a thread, fans samples out."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Dict, Optional, Set

from . import __version__
from . import protocol as P
from .device import BaseDevice, WitMotionError, create_device, register_table
from .recorder import Recorder
from .registers import BAUD_RATES, LAST_REGISTER
from .sample import Sample, decode_sample

log = logging.getLogger("witmotion.engine")

MAX_RATE_HZ = 200.0


class SensorEngine:
    def __init__(self, data_dir: Path = Path("witmotion-data"),
                 device_factory: Callable[..., BaseDevice] = create_device):
        self.data_dir = Path(data_dir)
        self.recorder = Recorder(self.data_dir / "recordings")
        self._factory = device_factory
        self._device: Optional[BaseDevice] = None
        self._conn_lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._subs: Set[queue.Queue] = set()
        self._subs_lock = threading.Lock()
        self.latest: Optional[Sample] = None
        self.rate_hz = 50.0
        self.state = "disconnected"
        self.busy: Optional[str] = None
        self._seq = 0
        self._times: deque = deque(maxlen=200)
        self._reset_stats()

    # ------------------------------------------------------------------ #
    # connection
    # ------------------------------------------------------------------ #
    def _reset_stats(self) -> None:
        self.stats = {"samples": 0, "errors": 0, "consecutive_errors": 0, "last_error": None,
                      "connected_at": None}
        self._times.clear()

    @property
    def device(self) -> Optional[BaseDevice]:
        return self._device

    def connect(self, port: str, baudrate: int = 115200, address: int = 0x50,
                protocol: str = "modbus", rate_hz: float = 50.0) -> dict:
        with self._conn_lock:
            self.disconnect()
            dev = self._factory(protocol, port, int(baudrate), int(address))
            dev.open()
            try:
                self._verify(dev)
            except Exception:
                dev.close()
                raise
            self._device = dev
            self.set_rate(rate_hz)
            self._reset_stats()
            self.stats["connected_at"] = time.time()
            self.state = "connected"
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="witmotion-poll", daemon=True)
            self._thread.start()
            self._save_settings()
            log.info("connected: %s", dev.describe())
        self._publish("status", self.status())
        return self.status()

    def _verify(self, dev: BaseDevice) -> None:
        if dev.streaming:
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                if dev.poll() is not None:
                    return
            raise WitMotionError(f"no WitMotion data stream on {dev.port} @ {dev.baudrate} baud")
        try:
            dev.poll()
        except (WitMotionError, P.ProtocolError) as exc:
            raise WitMotionError(
                f"no reply from address 0x{dev.address:02X} on {dev.port} @ {dev.baudrate} baud ({exc})"
            ) from exc

    def disconnect(self) -> dict:
        with self._conn_lock:
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=3.0)
                self._thread = None
            if self._device is not None:
                try:
                    self._device.close()
                finally:
                    self._device = None
                was = True
            else:
                was = False
            self.state = "disconnected"
        if was:
            self._publish("status", self.status())
        return self.status()

    def set_rate(self, rate_hz: float) -> None:
        rate = float(rate_hz)
        if not 0.1 <= rate <= MAX_RATE_HZ:
            raise ValueError(f"rate must be between 0.1 and {MAX_RATE_HZ} Hz")
        self.rate_hz = rate

    # ------------------------------------------------------------------ #
    # polling loop
    # ------------------------------------------------------------------ #
    def _run(self) -> None:
        dev = self._device
        assert dev is not None
        next_t = time.monotonic()
        last_data = time.monotonic()
        while not self._stop.is_set():
            try:
                if not dev.is_open:
                    dev.open()
                image = dev.poll()
            except (WitMotionError, P.ProtocolError, OSError) as exc:
                self._on_error(dev, exc)
                continue
            now = time.monotonic()
            if image is None:  # streaming device, nothing new yet
                if now - last_data > 2.0:
                    self._set_state("no-response")
                continue
            last_data = now
            sample = decode_sample(image, seq=self._seq)
            self._seq += 1
            self.latest = sample
            self.stats["samples"] += 1
            self.stats["consecutive_errors"] = 0
            self._times.append(now)
            self._set_state("connected")
            try:
                self.recorder.write(sample)
            except OSError as exc:
                log.error("recording failed: %s", exc)
                self.recorder.stop()
            self._publish("sample", sample.to_dict())
            if not dev.streaming:
                period = 1.0 / self.rate_hz
                next_t += period
                delay = next_t - time.monotonic()
                if delay > 0:
                    # time.sleep is high-resolution on Windows (3.11+); Event.wait rounds
                    # up to the ~15.6 ms system tick, which would cap the poll rate.
                    if delay < 0.1:
                        time.sleep(delay)
                    else:
                        self._stop.wait(delay)
                elif delay < -period:
                    next_t = time.monotonic()  # fell behind by more than a period; resync

    def _on_error(self, dev: BaseDevice, exc: Exception) -> None:
        self.stats["errors"] += 1
        self.stats["consecutive_errors"] += 1
        self.stats["last_error"] = str(exc)
        n = self.stats["consecutive_errors"]
        if n >= 3:
            self._set_state("no-response")
        msg = str(exc).lower()
        if "failed on" in msg or "cannot open" in msg or "not open" in msg or isinstance(exc, OSError):
            # Port vanished (USB unplugged?) -- close and retry opening once a second.
            try:
                dev.close()
            except Exception:  # noqa: BLE001
                pass
            self._stop.wait(1.0)
        else:
            self._stop.wait(min(1.0, 0.05 * n))

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self._publish("status", self.status())

    def measured_rate(self) -> float:
        times = list(self._times)
        if len(times) < 2:
            return 0.0
        recent = [t for t in times if times[-1] - t <= 2.0]
        if len(recent) < 2 or recent[-1] == recent[0]:
            return 0.0
        return (len(recent) - 1) / (recent[-1] - recent[0])

    # ------------------------------------------------------------------ #
    # pub/sub
    # ------------------------------------------------------------------ #
    def subscribe(self, maxsize: int = 512) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=maxsize)
        with self._subs_lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._subs_lock:
            self._subs.discard(q)

    def _publish(self, kind: str, payload) -> None:
        with self._subs_lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait((kind, payload))
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait((kind, payload))
                except (queue.Empty, queue.Full):
                    pass

    # ------------------------------------------------------------------ #
    # status / settings
    # ------------------------------------------------------------------ #
    def status(self) -> dict:
        dev = self._device
        return {
            "version": __version__,
            "state": self.state,
            "connection": dev.describe() if dev else None,
            "rate_hz": self.rate_hz,
            "measured_hz": round(self.measured_rate(), 1),
            "stats": dict(self.stats),
            "recording": self.recorder.status(),
            "busy": self.busy,
        }

    @property
    def settings_path(self) -> Path:
        return self.data_dir / "settings.json"

    def load_settings(self) -> dict:
        try:
            return json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_settings(self) -> None:
        dev = self._device
        if dev is None:
            return
        settings = self.load_settings()
        settings["last_connection"] = {**dev.describe(), "rate_hz": self.rate_hz}
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        except OSError as exc:
            log.warning("could not save settings: %s", exc)

    # ------------------------------------------------------------------ #
    # commands
    # ------------------------------------------------------------------ #
    def _require(self) -> BaseDevice:
        dev = self._device
        if dev is None:
            raise WitMotionError("not connected")
        return dev

    def command(self, action: str, params: Optional[Dict] = None) -> dict:
        """Run a named device command (used by the HTTP API and CLI)."""
        params = params or {}
        if action == "set_rate":
            self.set_rate(params["rate_hz"])
            self._save_settings()
            return {"rate_hz": self.rate_hz}
        dev = self._require()
        handlers: Dict[str, Callable[[], object]] = {
            "read_config": dev.read_config,
            "save": dev.save,
            "factory_reset": dev.factory_reset,
            "calibrate_accel": lambda: dev.calibrate_accelerometer(float(params.get("seconds", 5.0))),
            "mag_start": dev.start_mag_calibration,
            "mag_stop": dev.stop_mag_calibration,
            "zero_heading": dev.zero_heading,
            "angle_reference": dev.set_angle_reference,
            "clear_angle_reference": dev.clear_angle_reference,
            "sync_clock": dev.sync_clock,
            "set_bandwidth": lambda: dev.set_bandwidth(int(params["value"])),
            "set_algorithm": lambda: dev.set_algorithm(int(params["value"])),
            "set_orientation": lambda: dev.set_orientation(int(params["value"])),
            "set_baudrate": lambda: dev.set_baudrate(int(params["value"])),
            "set_address": lambda: dev.set_address(int(params["value"])),
            "read_registers": lambda: register_table(
                dev.read_range(int(params.get("start", 0)),
                               min(int(params.get("count", LAST_REGISTER + 1)), 0x100))),
            "write_register": lambda: self._write_raw(dev, params),
        }
        if action not in handlers:
            raise ValueError(f"unknown action {action!r}")
        if self.busy:
            raise WitMotionError(f"device busy: {self.busy}")
        self.busy = action
        self._publish("status", self.status())
        try:
            result = handlers[action]()
        except P.ProtocolError as exc:
            raise WitMotionError(str(exc)) from exc
        finally:
            self.busy = None
            self._publish("status", self.status())
        if action in ("set_baudrate", "set_address"):
            self._save_settings()
        return {"ok": True, "action": action, "result": result}

    @staticmethod
    def _write_raw(dev: BaseDevice, params: Dict) -> dict:
        addr = int(params["addr"])
        value = int(params["value"])
        if not 0 <= addr <= 0xFF:
            raise ValueError("register address must be 0x00-0xFF")
        if not -0x8000 <= value <= 0xFFFF:
            raise ValueError("value must fit in 16 bits")
        dev.write_config(addr, value, save=bool(params.get("save", False)))
        time.sleep(0.05)
        try:
            readback = dev.read_registers(addr, 1)[0]
        except (WitMotionError, P.ProtocolError):
            readback = None
        return {"addr": addr, "written": value, "readback": readback}


def baud_choices() -> list:
    return sorted(BAUD_RATES.values())
