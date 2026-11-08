"""Wire-level protocol helpers for WitMotion sensors.

Two framings are used across the WitMotion product line:

* **Modbus RTU** (RS-485 models such as the WT901C-485). The host polls; the
  sensor answers. Registers are 16-bit big-endian, signed for measurement data.
* **WitMotion standard protocol** (TTL / RS-232 models such as WT901C-TTL and
  WT901C-232). The sensor streams 11-byte frames that start with ``0x55`` and
  end with an 8-bit sum checksum. Commands are 5-byte ``FF AA reg lo hi``.

Both expose the same register map (see :mod:`witmotion.registers`), so the rest
of the engine works on a common "register image" of ``{address: int16}``.
"""

from __future__ import annotations

import struct
from typing import Dict, Iterable, List, Optional, Tuple


class ProtocolError(Exception):
    """A frame was malformed, truncated, or failed its checksum."""


# --------------------------------------------------------------------------- #
# Modbus RTU
# --------------------------------------------------------------------------- #

def _build_crc_table() -> List[int]:
    table = []
    for byte in range(256):
        crc = byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
        table.append(crc)
    return table


_CRC_TABLE = _build_crc_table()

MODBUS_READ = 0x03
MODBUS_WRITE_SINGLE = 0x06


def crc16_modbus(data: Iterable[int]) -> int:
    """CRC-16/MODBUS (poly 0xA001 reflected, init 0xFFFF)."""
    crc = 0xFFFF
    for b in data:
        crc = (crc >> 8) ^ _CRC_TABLE[(crc ^ b) & 0xFF]
    return crc


def _append_crc(frame: bytes) -> bytes:
    crc = crc16_modbus(frame)
    return frame + bytes((crc & 0xFF, crc >> 8))


def _check_address(address: int) -> None:
    if not 0 <= address <= 0xFF:
        raise ValueError(f"Modbus address out of range: {address}")


def modbus_read_request(address: int, register: int, count: int) -> bytes:
    """Build a function-0x03 'read holding registers' request."""
    _check_address(address)
    if not 0 <= register <= 0xFFFF:
        raise ValueError(f"register out of range: {register}")
    if not 1 <= count <= 125:
        raise ValueError(f"count must be 1..125, got {count}")
    return _append_crc(struct.pack(">BBHH", address, MODBUS_READ, register, count))


def modbus_write_request(address: int, register: int, value: int) -> bytes:
    """Build a function-0x06 'write single register' request."""
    _check_address(address)
    if not 0 <= register <= 0xFFFF:
        raise ValueError(f"register out of range: {register}")
    if not -0x8000 <= value <= 0xFFFF:
        raise ValueError(f"value does not fit in 16 bits: {value}")
    return _append_crc(struct.pack(">BBHH", address, MODBUS_WRITE_SINGLE, register, value & 0xFFFF))


def modbus_read_response_length(count: int) -> int:
    """Length in bytes of a well-formed reply to a read of ``count`` registers."""
    return 5 + 2 * count


def check_modbus_crc(frame: bytes) -> bool:
    if len(frame) < 4:
        return False
    return crc16_modbus(frame[:-2]) == (frame[-2] | (frame[-1] << 8))


def parse_modbus_read_response(frame: bytes, address: int, count: int) -> List[int]:
    """Validate a read reply and return the register values as signed int16."""
    if len(frame) >= 5 and frame[1] == (MODBUS_READ | 0x80) and check_modbus_crc(frame[:5]):
        raise ProtocolError(f"Modbus exception code {frame[2]} from device 0x{frame[0]:02X}")
    expected = modbus_read_response_length(count)
    if len(frame) < expected:
        raise ProtocolError(f"short reply: got {len(frame)} of {expected} bytes")
    frame = frame[:expected]
    if not check_modbus_crc(frame):
        raise ProtocolError("CRC mismatch")
    if frame[0] != address:
        raise ProtocolError(f"reply from address 0x{frame[0]:02X}, expected 0x{address:02X}")
    if frame[1] != MODBUS_READ:
        raise ProtocolError(f"unexpected function code 0x{frame[1]:02X}")
    if frame[2] != 2 * count:
        raise ProtocolError(f"byte count {frame[2]} != {2 * count}")
    return list(struct.unpack(f">{count}h", frame[3:3 + 2 * count]))


def parse_modbus_write_response(frame: bytes, address: int, register: int, value: int) -> None:
    """A function-0x06 reply echoes the request; raise if it doesn't."""
    if len(frame) >= 5 and frame[1] == (MODBUS_WRITE_SINGLE | 0x80) and check_modbus_crc(frame[:5]):
        raise ProtocolError(f"Modbus exception code {frame[2]} from device 0x{frame[0]:02X}")
    expected = modbus_write_request(address, register, value)
    if bytes(frame[:8]) != expected:
        raise ProtocolError(f"write echo mismatch: {bytes(frame[:8]).hex(' ')}")


# --------------------------------------------------------------------------- #
# WitMotion standard (0x55) protocol
# --------------------------------------------------------------------------- #

STD_HEADER = 0x55
STD_FRAME_LEN = 11
STD_REGISTER_REPLY = 0x5F

# Which registers each streamed frame type carries (4 little-endian int16 each).
STD_FRAME_REGISTERS: Dict[int, Tuple[Optional[int], ...]] = {
    0x50: (0x30, 0x31, 0x32, 0x33),  # chip time
    0x51: (0x34, 0x35, 0x36, 0x40),  # acceleration + temperature
    0x52: (0x37, 0x38, 0x39, None),  # angular velocity (+ voltage on some models)
    0x53: (0x3D, 0x3E, 0x3F, 0x2E),  # angle + firmware version
    0x54: (0x3A, 0x3B, 0x3C, 0x40),  # magnetic field + temperature
    0x55: (0x41, 0x42, 0x43, 0x44),  # D0-D3 port status
    0x56: (0x45, 0x46, 0x47, 0x48),  # pressure + height
    0x57: (0x49, 0x4A, 0x4B, 0x4C),  # longitude + latitude
    0x58: (0x4D, 0x4E, 0x4F, 0x50),  # GPS height, heading, ground speed
    0x59: (0x51, 0x52, 0x53, 0x54),  # quaternion
    0x5A: (0x55, 0x56, 0x57, 0x58),  # satellites + DOP
}


def std_command(register: int, value: int) -> bytes:
    """``FF AA reg lo hi`` -- write ``value`` to ``register``."""
    if not 0 <= register <= 0xFF:
        raise ValueError(f"register out of range: {register}")
    value &= 0xFFFF
    return bytes((0xFF, 0xAA, register, value & 0xFF, value >> 8))


def std_read_command(register: int) -> bytes:
    """Ask a streaming sensor to reply with a 0x5F frame of 4 registers."""
    return std_command(0x27, register)


def std_checksum(frame: bytes) -> int:
    return sum(frame[:10]) & 0xFF


class StandardFrameParser:
    """Incremental parser for the 11-byte ``0x55`` frame stream.

    Feed it arbitrary chunks from the serial port; it resynchronises on noise.
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self.bad_frames = 0

    def feed(self, data: bytes) -> List[Tuple[int, bytes]]:
        """Return ``[(frame_type, 8-byte payload), ...]`` for each valid frame."""
        self._buf += data
        frames: List[Tuple[int, bytes]] = []
        buf = self._buf
        while len(buf) >= STD_FRAME_LEN:
            if buf[0] != STD_HEADER:
                idx = buf.find(STD_HEADER, 1)
                if idx < 0:
                    buf.clear()
                    break
                del buf[:idx]
                continue
            if std_checksum(buf) == buf[10]:
                frames.append((buf[1], bytes(buf[2:10])))
                del buf[:STD_FRAME_LEN]
            else:
                self.bad_frames += 1
                del buf[:1]
        # Keep the buffer bounded if the line is pure noise.
        if len(buf) > 4096:
            del buf[:-STD_FRAME_LEN]
        return frames


def std_payload_values(payload: bytes) -> Tuple[int, int, int, int]:
    return struct.unpack("<4h", payload)


def std_frames_to_registers(frames: Iterable[Tuple[int, bytes]]) -> Dict[int, int]:
    """Merge streamed data frames into a ``{register: int16}`` image."""
    image: Dict[int, int] = {}
    for ftype, payload in frames:
        regs = STD_FRAME_REGISTERS.get(ftype)
        if regs is None:
            continue
        for reg, val in zip(regs, std_payload_values(payload)):
            if reg is not None:
                image[reg] = val
    return image
