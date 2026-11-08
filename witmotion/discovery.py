"""Find WitMotion sensors on serial ports."""

from __future__ import annotations

import time
from typing import Callable, Iterable, List, Optional, Sequence

from . import protocol as P
from .registers import POLL_COUNT, POLL_START

try:
    import serial  # type: ignore
    from serial.tools import list_ports as _list_ports  # type: ignore
except ImportError:  # pragma: no cover
    serial = None  # type: ignore
    _list_ports = None  # type: ignore

# USB-serial bridges WitMotion ships with its USB-485 / USB-TTL adapters.
USB_SERIAL_VIDS = {
    0x1A86: "WCH CH34x",
    0x10C4: "Silicon Labs CP210x",
    0x0403: "FTDI",
    0x067B: "Prolific PL2303",
}

# Most likely first: WT901C-485 ships at 9600; 115200 is the common re-configured rate.
DEFAULT_BAUDS = (115200, 9600, 230400, 460800, 921600, 57600, 38400, 19200, 4800)


def list_ports() -> List[dict]:
    if _list_ports is None:
        return []
    out = []
    for p in sorted(_list_ports.comports(), key=lambda p: p.device):
        out.append({
            "device": p.device,
            "description": p.description,
            "manufacturer": p.manufacturer,
            "vid": p.vid,
            "pid": p.pid,
            "serial_number": p.serial_number,
            "bridge": USB_SERIAL_VIDS.get(p.vid or -1),
            "likely": (p.vid in USB_SERIAL_VIDS),
        })
    return out


def _probe_modbus(ser, address: int, timeout: float = 0.12) -> Optional[List[int]]:
    req = P.modbus_read_request(address, POLL_START, POLL_COUNT)
    n = P.modbus_read_response_length(POLL_COUNT)
    ser.reset_input_buffer()
    ser.write(req)
    deadline = time.monotonic() + timeout + n * 10.0 / ser.baudrate
    buf = bytearray()
    while time.monotonic() < deadline and len(buf) < n + 16:
        buf += ser.read(n)
        for i in range(len(buf) - n + 1):
            if buf[i] == address and buf[i + 1] == P.MODBUS_READ:
                try:
                    return P.parse_modbus_read_response(bytes(buf[i:i + n]), address, POLL_COUNT)
                except P.ProtocolError:
                    continue
    return None


def _probe_standard(ser, listen: float = 0.35) -> int:
    """Count valid 0x55 frames heard without transmitting anything."""
    parser = P.StandardFrameParser()
    ser.reset_input_buffer()
    deadline = time.monotonic() + listen
    count = 0
    while time.monotonic() < deadline:
        count += len(parser.feed(ser.read(512)))
        if count >= 3:
            break
    return count


def scan(
    ports: Optional[Iterable[str]] = None,
    bauds: Sequence[int] = DEFAULT_BAUDS,
    addresses: Sequence[int] = (0x50,),
    all_ports: bool = False,
    progress: Optional[Callable[[str], None]] = None,
) -> List[dict]:
    """Probe ports for WitMotion sensors.

    By default only USB-serial bridges are probed (Bluetooth and modem ports are
    skipped). For each baud rate the port is first *listened to* for a 0x55
    stream, then sent a harmless Modbus read of the data registers.
    """
    if serial is None:
        raise RuntimeError("pyserial is not installed")
    if ports is None:
        ports = [p["device"] for p in list_ports() if all_ports or p["likely"]]
    found: List[dict] = []
    for port in ports:
        try:
            ser = serial.Serial(port, bauds[0], timeout=0.03, write_timeout=0.5)
        except (serial.SerialException, OSError, ValueError) as exc:
            if progress:
                progress(f"{port}: cannot open ({exc})")
            continue
        try:
            hit = None
            for baud in bauds:
                ser.baudrate = baud
                time.sleep(0.02)
                if progress:
                    progress(f"{port} @ {baud}")
                frames = _probe_standard(ser)
                if frames >= 3:
                    hit = {"port": port, "baudrate": baud, "protocol": "standard", "address": None}
                    break
                for addr in addresses:
                    if _probe_modbus(ser, addr) is not None:
                        hit = {"port": port, "baudrate": baud, "protocol": "modbus", "address": addr}
                        break
                if hit:
                    break
            if hit:
                found.append(hit)
                if progress:
                    progress(f"found {hit}")
        except (serial.SerialException, OSError) as exc:
            if progress:
                progress(f"{port}: {exc}")
        finally:
            ser.close()
    return found
