"""Device drivers: Modbus RTU (RS-485), standard 0x55 stream (TTL/RS-232), simulator.

All three share :class:`BaseDevice`, which implements the WitMotion
configuration and calibration sequences on top of three primitives:
``read_registers``, ``write_register`` and ``poll``.

Example::

    from witmotion import ModbusDevice

    with ModbusDevice("COM8", baudrate=115200, address=0x50) as dev:
        s = dev.read_sample()
        print(s.roll, s.pitch, s.yaw)
"""

from __future__ import annotations

import math
import random
import threading
import time
from collections import deque
from datetime import datetime
from typing import Deque, Dict, List, Optional

from . import protocol as P
from .registers import (
    BAUD_CODES, BAUD_RATES, CAL_ACCEL, CAL_ANGLE_REFERENCE, CAL_HEADING_ZERO, CAL_MAG_START,
    CAL_NORMAL, FACTORY_RESET, LAST_REGISTER, POLL_COUNT, POLL_START, SAVE_CONFIG, UNLOCK_KEY,
    Reg, describe_config, encode_chip_time, info, u16,
)
from .sample import Sample, decode_sample

try:  # pyserial is only needed for real hardware
    import serial  # type: ignore
except ImportError:  # pragma: no cover
    serial = None  # type: ignore

CMD_DELAY = 0.1  # seconds between configuration commands (matches the WitMotion app)


class WitMotionError(Exception):
    """Communication with the sensor failed."""


class BaseDevice:
    """Common configuration / calibration logic."""

    protocol = "base"
    streaming = False  # True when the sensor pushes data (no polling needed)

    def __init__(self, port: str, baudrate: int = 115200, address: int = 0x50, timeout: float = 0.25):
        self.port = port
        self.baudrate = int(baudrate)
        self.address = int(address)
        self.timeout = float(timeout)
        self._lock = threading.RLock()

    # ---- primitives (overridden) ----------------------------------------- #
    def open(self) -> "BaseDevice":
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    @property
    def is_open(self) -> bool:
        raise NotImplementedError

    def read_registers(self, register: int, count: int) -> List[int]:
        raise NotImplementedError

    def write_register(self, register: int, value: int, expect_reply: bool = True) -> None:
        raise NotImplementedError

    def poll(self) -> Optional[Dict[int, int]]:
        """Return the latest register image, or None if nothing new arrived."""
        raise NotImplementedError

    def set_host_baudrate(self, baudrate: int) -> None:
        self.baudrate = int(baudrate)

    # ---- context manager ---------------------------------------------- #
    def __enter__(self) -> "BaseDevice":
        if not self.is_open:
            self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def describe(self) -> dict:
        return {"port": self.port, "baudrate": self.baudrate, "address": self.address, "protocol": self.protocol}

    # ---- reading -------------------------------------------------------- #
    def read_sample(self) -> Sample:
        image = self.poll()
        if image is None:
            raise WitMotionError("no data received")
        return decode_sample(image)

    def read_range(self, start: int, count: int, chunk: int = 48) -> Dict[int, int]:
        """Read ``count`` registers from ``start`` in chunks; returns ``{addr: value}``."""
        out: Dict[int, int] = {}
        addr = start
        end = start + count
        while addr < end:
            n = min(chunk, end - addr)
            for i, v in enumerate(self.read_registers(addr, n)):
                out[addr + i] = v
            addr += n
        return out

    def read_all_registers(self) -> Dict[int, int]:
        return self.read_range(0, LAST_REGISTER + 1)

    def read_config(self) -> dict:
        values = self.read_range(0x00, 0x30)
        values.update(self.read_range(Reg.MODDELAY, Reg.YREFPITCH - Reg.MODDELAY + 1))
        return describe_config(values)

    # ---- writing ------------------------------------------------------ #
    def unlock(self) -> None:
        self.write_register(Reg.KEY, UNLOCK_KEY)
        time.sleep(CMD_DELAY)

    def save(self) -> None:
        self.write_register(Reg.SAVE, SAVE_CONFIG)
        time.sleep(CMD_DELAY)

    def write_config(self, register: int, value: int, save: bool = True) -> None:
        """Unlock, write one register, and (optionally) save to flash."""
        with self._lock:
            self.unlock()
            self.write_register(register, value)
            time.sleep(CMD_DELAY)
            if save:
                self.save()

    def set_bandwidth(self, code: int) -> None:
        self.write_config(Reg.BANDWIDTH, _check_option(code, range(0, 7), "bandwidth code"))

    def set_algorithm(self, code: int) -> None:
        self.write_config(Reg.AXIS6, _check_option(code, (0, 1), "algorithm"))

    def set_orientation(self, code: int) -> None:
        self.write_config(Reg.ORIENT, _check_option(code, (0, 1), "orientation"))

    def set_baudrate(self, baudrate: int) -> None:
        """Change the sensor's baud rate, then follow it on the host side."""
        baudrate = int(baudrate)
        if baudrate not in BAUD_CODES:
            raise ValueError(f"unsupported baud rate {baudrate}; choose from {sorted(BAUD_CODES)}")
        old = self.baudrate
        with self._lock:
            self.unlock()
            self.write_register(Reg.BAUD, BAUD_CODES[baudrate], expect_reply=False)
            time.sleep(CMD_DELAY)
            self.write_register(Reg.SAVE, SAVE_CONFIG, expect_reply=False)
            time.sleep(CMD_DELAY * 2)
            self.set_host_baudrate(baudrate)
            time.sleep(CMD_DELAY)
            if not self._responds():
                self.set_host_baudrate(old)
                if self._responds():
                    raise WitMotionError(f"sensor did not switch to {baudrate} baud; still at {old}")
                raise WitMotionError(f"sensor stopped responding after baud change to {baudrate}")

    def set_address(self, address: int) -> None:
        """Change the Modbus/device address (0x00-0x7F)."""
        address = int(address)
        if not 0 <= address <= 0x7F:
            raise ValueError("device address must be 0x00-0x7F")
        old = self.address
        with self._lock:
            self.unlock()
            self.write_register(Reg.IICADDR, address, expect_reply=False)
            time.sleep(CMD_DELAY)
            self.write_register(Reg.SAVE, SAVE_CONFIG, expect_reply=False)
            time.sleep(CMD_DELAY * 2)
            self.address = address
            if not self._responds():
                self.address = old
                if self._responds():
                    raise WitMotionError(f"address change to 0x{address:02X} did not take effect")
                raise WitMotionError("sensor stopped responding after address change")

    def calibrate_accelerometer(self, seconds: float = 5.0) -> None:
        """Automatic accelerometer calibration. Keep the sensor level and still."""
        with self._lock:
            self.unlock()
            self.write_register(Reg.CALSW, CAL_ACCEL)
        time.sleep(seconds)  # release the lock so live data keeps flowing
        with self._lock:
            self.unlock()
            self.write_register(Reg.CALSW, CAL_NORMAL)
            time.sleep(CMD_DELAY)
            self.save()

    def start_mag_calibration(self) -> None:
        """Begin magnetometer calibration: rotate slowly through every axis, then stop."""
        with self._lock:
            self.unlock()
            self.write_register(Reg.CALSW, CAL_MAG_START)

    def stop_mag_calibration(self) -> None:
        with self._lock:
            self.unlock()
            self.write_register(Reg.CALSW, CAL_NORMAL)
            time.sleep(CMD_DELAY)
            self.save()

    def zero_heading(self) -> None:
        """Set the current yaw (Z angle) to zero."""
        with self._lock:
            self.unlock()
            self.write_register(Reg.CALSW, CAL_HEADING_ZERO)

    def set_angle_reference(self) -> None:
        """Make the current roll/pitch read as zero (stored in 0x79/0x7A)."""
        with self._lock:
            self.unlock()
            self.write_register(Reg.CALSW, CAL_ANGLE_REFERENCE)
            time.sleep(CMD_DELAY)
            self.save()

    def clear_angle_reference(self) -> None:
        with self._lock:
            self.unlock()
            self.write_register(Reg.XREFROLL, 0)
            time.sleep(CMD_DELAY)
            self.write_register(Reg.YREFPITCH, 0)
            time.sleep(CMD_DELAY)
            self.save()

    def sync_clock(self, when: Optional[datetime] = None) -> str:
        """Write the host clock to the sensor's on-chip RTC (registers 0x30-0x33)."""
        when = when or datetime.now()
        with self._lock:
            self.unlock()
            for reg, value in encode_chip_time(when).items():
                self.write_register(reg, value)
                time.sleep(0.02)
            self.save()
        return when.isoformat(sep=" ", timespec="milliseconds")

    def factory_reset(self) -> None:
        """Restore factory settings. Baud rate and address may change!"""
        with self._lock:
            self.unlock()
            self.write_register(Reg.SAVE, FACTORY_RESET, expect_reply=False)
            time.sleep(CMD_DELAY * 3)

    # ---- helpers ------------------------------------------------------ #
    def _responds(self) -> bool:
        for _ in range(3):
            try:
                self.read_registers(Reg.BAUD, 1)
                return True
            except (WitMotionError, P.ProtocolError):
                time.sleep(0.05)
        return False


def _check_option(value, allowed, what) -> int:
    value = int(value)
    if value not in allowed:
        raise ValueError(f"invalid {what}: {value}")
    return value


# --------------------------------------------------------------------------- #
# Serial-backed devices
# --------------------------------------------------------------------------- #

class _SerialDevice(BaseDevice):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ser = None

    def open(self) -> "BaseDevice":
        if serial is None:
            raise WitMotionError("pyserial is not installed: pip install pyserial")
        with self._lock:
            if self._ser is not None:
                return self
            try:
                self._ser = serial.Serial(self.port, self.baudrate, timeout=0.02, write_timeout=1.0)
            except (serial.SerialException, OSError, ValueError) as exc:
                raise WitMotionError(f"cannot open {self.port}: {exc}") from exc
            time.sleep(0.05)
            self._ser.reset_input_buffer()
        return self

    def close(self) -> None:
        with self._lock:
            if self._ser is not None:
                try:
                    self._ser.close()
                finally:
                    self._ser = None

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def set_host_baudrate(self, baudrate: int) -> None:
        with self._lock:
            super().set_host_baudrate(baudrate)
            if self._ser is not None:
                self._ser.baudrate = self.baudrate
                time.sleep(0.02)
                self._ser.reset_input_buffer()

    def _require(self):
        if self._ser is None:
            raise WitMotionError("device is not open")
        return self._ser

    def _write(self, data: bytes) -> None:
        ser = self._require()
        try:
            ser.write(data)
        except (serial.SerialException, OSError) as exc:
            raise WitMotionError(f"write failed on {self.port}: {exc}") from exc

    def _read(self, n: int) -> bytes:
        ser = self._require()
        try:
            return ser.read(n)
        except (serial.SerialException, OSError) as exc:
            raise WitMotionError(f"read failed on {self.port}: {exc}") from exc


class ModbusDevice(_SerialDevice):
    """RS-485 WitMotion sensor speaking Modbus RTU (e.g. WT901C-485)."""

    protocol = "modbus"
    streaming = False

    def __init__(self, port: str, baudrate: int = 115200, address: int = 0x50,
                 timeout: float = 0.25, retries: int = 2):
        super().__init__(port, baudrate, address, timeout)
        self.retries = retries
        self.stats = {"requests": 0, "failures": 0}

    def _transact(self, request: bytes, func: int, reply_len: int) -> bytes:
        """Send ``request`` and return the first well-formed reply frame."""
        ser = self._require()
        try:
            ser.reset_input_buffer()
        except (serial.SerialException, OSError) as exc:
            raise WitMotionError(f"{self.port}: {exc}") from exc
        self._write(request)
        self.stats["requests"] += 1
        deadline = time.monotonic() + self.timeout
        buf = bytearray()
        while time.monotonic() < deadline:
            chunk = self._read(max(1, reply_len - len(buf)))
            if chunk:
                buf += chunk
            frame = _find_reply(buf, self.address, func, reply_len)
            if frame is not None:
                return frame
        self.stats["failures"] += 1
        if not buf:
            raise WitMotionError(f"no reply from 0x{self.address:02X} on {self.port} @ {self.baudrate}")
        raise P.ProtocolError(f"incomplete or invalid reply: {bytes(buf).hex(' ')}")

    def read_registers(self, register: int, count: int) -> List[int]:
        request = P.modbus_read_request(self.address, register, count)
        reply_len = P.modbus_read_response_length(count)
        last: Optional[Exception] = None
        with self._lock:
            for _ in range(self.retries + 1):
                try:
                    frame = self._transact(request, P.MODBUS_READ, reply_len)
                    return P.parse_modbus_read_response(frame, self.address, count)
                except (WitMotionError, P.ProtocolError) as exc:
                    last = exc
                    if "exception code" in str(exc) or not self.is_open:
                        break
        raise WitMotionError(str(last))

    def write_register(self, register: int, value: int, expect_reply: bool = True) -> None:
        request = P.modbus_write_request(self.address, register, value)
        with self._lock:
            if not expect_reply:
                self._require().reset_input_buffer()
                self._write(request)
                time.sleep(0.03)
                return
            last: Optional[Exception] = None
            for _ in range(self.retries + 1):
                try:
                    frame = self._transact(request, P.MODBUS_WRITE_SINGLE, 8)
                    P.parse_modbus_write_response(frame, self.address, register, value)
                    return
                except (WitMotionError, P.ProtocolError) as exc:
                    last = exc
            raise WitMotionError(f"write 0x{register:02X}={value}: {last}")

    def poll(self) -> Optional[Dict[int, int]]:
        values = self.read_registers(POLL_START, POLL_COUNT)
        return {POLL_START + i: v for i, v in enumerate(values)}


def _find_reply(buf: bytearray, address: int, func: int, reply_len: int) -> Optional[bytes]:
    """Locate a valid Modbus reply in ``buf`` (tolerates echo/garbage before it)."""
    i = 0
    while i + 4 < len(buf):
        if buf[i] == address:
            if buf[i + 1] == func and len(buf) - i >= reply_len:
                cand = bytes(buf[i:i + reply_len])
                if P.check_modbus_crc(cand):
                    return cand
            elif buf[i + 1] == (func | 0x80) and len(buf) - i >= 5:
                cand = bytes(buf[i:i + 5])
                if P.check_modbus_crc(cand):
                    return cand
        i += 1
    return None


class StandardDevice(_SerialDevice):
    """TTL / RS-232 WitMotion sensor streaming 0x55 frames (e.g. WT901C-TTL/-232)."""

    protocol = "standard"
    streaming = True

    def __init__(self, port: str, baudrate: int = 9600, address: int = 0x50, timeout: float = 0.5):
        super().__init__(port, baudrate, address, timeout)
        self._parser = P.StandardFrameParser()
        self._image: Dict[int, int] = {}
        self._replies: Deque[tuple] = deque(maxlen=16)

    def _pump(self, max_wait: float) -> bool:
        """Read whatever is available (waiting up to ``max_wait``); True if data frames arrived."""
        ser = self._require()
        deadline = time.monotonic() + max_wait
        got = False
        while True:
            try:
                waiting = ser.in_waiting
            except (serial.SerialException, OSError) as exc:
                raise WitMotionError(f"{self.port}: {exc}") from exc
            chunk = self._read(waiting or 1)
            if chunk:
                for ftype, payload in self._parser.feed(chunk):
                    if ftype == P.STD_REGISTER_REPLY:
                        self._replies.append(P.std_payload_values(payload))
                    else:
                        regs = P.STD_FRAME_REGISTERS.get(ftype)
                        if regs:
                            for reg, val in zip(regs, P.std_payload_values(payload)):
                                if reg is not None:
                                    self._image[reg] = val
                            got = True
            if got or self._replies or time.monotonic() >= deadline:
                return got

    def poll(self) -> Optional[Dict[int, int]]:
        with self._lock:
            got = self._pump(self.timeout)
            return dict(self._image) if got else None

    def read_registers(self, register: int, count: int) -> List[int]:
        out: List[int] = []
        with self._lock:
            reg = register
            while len(out) < count:
                self._replies.clear()
                self._write(P.std_read_command(reg))
                deadline = time.monotonic() + self.timeout
                while not self._replies and time.monotonic() < deadline:
                    self._pump(0.05)
                if not self._replies:
                    raise WitMotionError(f"no register reply for 0x{reg:02X} on {self.port}")
                out.extend(self._replies.popleft())
                reg += 4
        return out[:count]

    def write_register(self, register: int, value: int, expect_reply: bool = True) -> None:
        with self._lock:
            self._write(P.std_command(register, value))
            time.sleep(0.02)


# --------------------------------------------------------------------------- #
# Simulator
# --------------------------------------------------------------------------- #

def _i16(v: float) -> int:
    return max(-32768, min(32767, int(round(v))))


class SimulatedDevice(BaseDevice):
    """A fake WT901C-485 for trying the UI without hardware."""

    protocol = "simulated"
    streaming = False

    def __init__(self, port: str = "SIMULATOR", baudrate: int = 115200, address: int = 0x50, timeout: float = 0.25):
        super().__init__(port, baudrate, address, timeout)
        self._open = False
        self._t0 = time.monotonic()
        self._yaw_offset = 0.0
        self._ref = (0.0, 0.0)
        self._calsw = 0
        self._regs: Dict[int, int] = {
            Reg.RSW: 30, Reg.RRATE: 13, Reg.BAUD: BAUD_CODES.get(self.baudrate, 6), Reg.IICADDR: address,
            Reg.BANDWIDTH: 4, Reg.GYRORANGE: 3, Reg.ACCRANGE: 3, Reg.ORIENT: 0, Reg.AXIS6: 0,
            Reg.FILTK: 30, Reg.VERSION1: 0x48C0, Reg.VERSION2: 0x000A, Reg.MODDELAY: 3000,
            Reg.MAGRANGX: 500, Reg.MAGRANGY: 500, Reg.MAGRANGZ: 500,
        }

    def open(self) -> "BaseDevice":
        self._open = True
        return self

    def close(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def _synth(self) -> None:
        t = time.monotonic() - self._t0
        n = lambda s: random.gauss(0.0, s)  # noqa: E731
        roll = 4.0 * math.sin(0.45 * t) + 1.5 * math.sin(1.7 * t) + n(0.01) - self._ref[0]
        pitch = 3.0 * math.sin(0.31 * t + 1.0) + n(0.01) - self._ref[1]
        yaw = ((15.0 * t + 40.0 * math.sin(0.1 * t) - self._yaw_offset + 180.0) % 360.0) - 180.0
        r, p, y = map(math.radians, (roll, pitch, yaw))
        ax = -math.sin(p) + n(0.002)
        ay = math.sin(r) * math.cos(p) + n(0.002)
        az = math.cos(r) * math.cos(p) + n(0.002)
        groll = 4.0 * 0.45 * math.cos(0.45 * t) + 1.5 * 1.7 * math.cos(1.7 * t)
        gpitch = 3.0 * 0.31 * math.cos(0.31 * t + 1.0)
        gyaw = 15.0 + 4.0 * math.cos(0.1 * t)
        hx, hy, hz = 1350 * math.cos(-y), 1350 * math.sin(-y), -8450
        cr, sr = math.cos(r / 2), math.sin(r / 2)
        cp, sp = math.cos(p / 2), math.sin(p / 2)
        cy, sy = math.cos(y / 2), math.sin(y / 2)
        q = (cr * cp * cy + sr * sp * sy, sr * cp * cy - cr * sp * sy,
             cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy)
        now = datetime.now()
        self._regs.update(encode_chip_time(now))
        self._regs.update({
            Reg.AX: _i16(ax / (16 / 32768)), Reg.AY: _i16(ay / (16 / 32768)), Reg.AZ: _i16(az / (16 / 32768)),
            Reg.GX: _i16(groll / (2000 / 32768)), Reg.GY: _i16(gpitch / (2000 / 32768)),
            Reg.GZ: _i16(gyaw / (2000 / 32768)),
            Reg.HX: _i16(hx + n(4)), Reg.HY: _i16(hy + n(4)), Reg.HZ: _i16(hz + n(4)),
            Reg.ROLL: _i16(roll / (180 / 32768)), Reg.PITCH: _i16(pitch / (180 / 32768)),
            Reg.YAW: _i16(yaw / (180 / 32768)),
            Reg.TEMP: _i16((22.0 + 0.3 * math.sin(0.02 * t)) * 100),
            Reg.Q0: _i16(q[0] * 32768), Reg.Q1: _i16(q[1] * 32768),
            Reg.Q2: _i16(q[2] * 32768), Reg.Q3: _i16(q[3] * 32768),
            Reg.CALSW: self._calsw,
        })
        # Keep the image consistent with u16 storage for unsigned regs
        for reg in (Reg.YYMM, Reg.DDHH, Reg.MMSS):
            v = self._regs[reg]
            self._regs[reg] = v - 0x10000 if v > 0x7FFF else v

    def read_registers(self, register: int, count: int) -> List[int]:
        if not self._open:
            raise WitMotionError("simulator is not open")
        time.sleep(0.004)
        self._synth()
        return [self._regs.get(register + i, 0) for i in range(count)]

    def write_register(self, register: int, value: int, expect_reply: bool = True) -> None:
        if not self._open:
            raise WitMotionError("simulator is not open")
        value = u16(value)
        signed = value - 0x10000 if value > 0x7FFF else value
        if register == Reg.CALSW:
            self._calsw = signed
            if signed == CAL_HEADING_ZERO:
                self._synth()
                self._yaw_offset += self._regs[Reg.YAW] * 180 / 32768
                self._calsw = 0
            elif signed == CAL_ANGLE_REFERENCE:
                self._synth()
                self._ref = (self._ref[0] + self._regs[Reg.ROLL] * 180 / 32768,
                             self._ref[1] + self._regs[Reg.PITCH] * 180 / 32768)
                self._regs[Reg.XREFROLL] = _i16(self._ref[0] / (180 / 32768))
                self._regs[Reg.YREFPITCH] = _i16(self._ref[1] / (180 / 32768))
                self._calsw = 0
            return
        if register == Reg.XREFROLL:
            self._ref = (signed * 180 / 32768, self._ref[1])
        if register == Reg.YREFPITCH:
            self._ref = (self._ref[0], signed * 180 / 32768)
        if register == Reg.BAUD and signed in BAUD_RATES:
            self.baudrate = BAUD_RATES[signed]
        if register == Reg.IICADDR:
            self.address = signed
        if register in (Reg.SAVE, Reg.KEY):
            return
        self._regs[register] = signed

    def set_host_baudrate(self, baudrate: int) -> None:
        self.baudrate = int(baudrate)

    def poll(self) -> Optional[Dict[int, int]]:
        values = self.read_registers(POLL_START, POLL_COUNT)
        return {POLL_START + i: v for i, v in enumerate(values)}


# --------------------------------------------------------------------------- #

PROTOCOLS = {
    "modbus": ModbusDevice,
    "standard": StandardDevice,
    "simulated": SimulatedDevice,
}


def create_device(protocol: str, port: str, baudrate: int = 115200, address: int = 0x50) -> BaseDevice:
    try:
        cls = PROTOCOLS[protocol]
    except KeyError:
        raise ValueError(f"unknown protocol {protocol!r}; choose from {sorted(PROTOCOLS)}") from None
    return cls(port, baudrate=baudrate, address=address)


def register_table(values: Dict[int, int]) -> List[dict]:
    """Rows for the register browser: raw, hex, scaled value and description."""
    rows = []
    for addr in sorted(values):
        raw = values[addr]
        meta = info(addr)
        scaled = meta.scaled(raw)
        rows.append({
            "addr": addr,
            "name": meta.name,
            "label": meta.label,
            "raw": raw,
            "hex": f"0x{u16(raw):04X}",
            "value": None if scaled is None else round(scaled, 5),
            "unit": meta.unit,
            "text": meta.describe(raw),
            "writable": meta.writable,
        })
    return rows
