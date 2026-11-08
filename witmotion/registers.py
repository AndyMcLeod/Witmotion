"""WitMotion register map.

The addresses and scale factors match the register editor shipped with the
WitMotion PC software (``Config/ConfigurationSpace/RegEditor/WT901C-485.xml``)
and the command panel for the WT901C-485. The same map is used by the JY901 /
WT901 family over both Modbus and the standard 0x55 protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, Optional


class Reg(IntEnum):
    SAVE = 0x00
    CALSW = 0x01
    RSW = 0x02
    RRATE = 0x03
    BAUD = 0x04
    AXOFFSET = 0x05
    AYOFFSET = 0x06
    AZOFFSET = 0x07
    GXOFFSET = 0x08
    GYOFFSET = 0x09
    GZOFFSET = 0x0A
    HXOFFSET = 0x0B
    HYOFFSET = 0x0C
    HZOFFSET = 0x0D
    D0MODE = 0x0E
    D1MODE = 0x0F
    D2MODE = 0x10
    D3MODE = 0x11
    IICADDR = 0x1A
    LEDOFF = 0x1B
    MAGRANGX = 0x1C
    MAGRANGY = 0x1D
    MAGRANGZ = 0x1E
    BANDWIDTH = 0x1F
    GYRORANGE = 0x20
    ACCRANGE = 0x21
    SLEEP = 0x22
    ORIENT = 0x23
    AXIS6 = 0x24
    FILTK = 0x25
    GPSBAUD = 0x26
    READADDR = 0x27
    ACCFILT = 0x2A
    POWONSEND = 0x2D
    VERSION1 = 0x2E
    VERSION2 = 0x2F
    YYMM = 0x30
    DDHH = 0x31
    MMSS = 0x32
    MS = 0x33
    AX = 0x34
    AY = 0x35
    AZ = 0x36
    GX = 0x37
    GY = 0x38
    GZ = 0x39
    HX = 0x3A
    HY = 0x3B
    HZ = 0x3C
    ROLL = 0x3D
    PITCH = 0x3E
    YAW = 0x3F
    TEMP = 0x40
    D0STATUS = 0x41
    D1STATUS = 0x42
    D2STATUS = 0x43
    D3STATUS = 0x44
    PRESSUREL = 0x45
    PRESSUREH = 0x46
    HEIGHTL = 0x47
    HEIGHTH = 0x48
    LONL = 0x49
    LONH = 0x4A
    LATL = 0x4B
    LATH = 0x4C
    GPSHEIGHT = 0x4D
    GPSYAW = 0x4E
    GPSVL = 0x4F
    GPSVH = 0x50
    Q0 = 0x51
    Q1 = 0x52
    Q2 = 0x53
    Q3 = 0x54
    SVNUM = 0x55
    PDOP = 0x56
    HDOP = 0x57
    VDOP = 0x58
    DELAYT = 0x59
    XMIN = 0x5A
    XMAX = 0x5B
    BATVAL = 0x5C
    ALARMPIN = 0x5D
    YMIN = 0x5E
    YMAX = 0x5F
    GYROCALITHR = 0x61
    ALARMLEVEL = 0x62
    GYROCALTIME = 0x63
    TRIGTIME = 0x68
    KEY = 0x69
    WERROR = 0x6A
    TIMEZONE = 0x6B
    WZTIME = 0x6E
    WZSTATIC = 0x6F
    MODDELAY = 0x74
    XREFROLL = 0x79
    YREFPITCH = 0x7A
    NUMBERID1 = 0x7F
    NUMBERID2 = 0x80
    NUMBERID3 = 0x81
    NUMBERID4 = 0x82
    NUMBERID5 = 0x83
    NUMBERID6 = 0x84


UNLOCK_KEY = 0xB588          # write to Reg.KEY to unlock configuration writes (~10 s)
LAST_REGISTER = 0x84

# CALSW (0x01) command codes
CAL_NORMAL = 0
CAL_ACCEL = 1
CAL_HEIGHT_RESET = 3
CAL_HEADING_ZERO = 4
CAL_MAG_START = 7
CAL_ANGLE_REFERENCE = 8
CAL_MAG_DUAL_PLANE = 9

# SAVE (0x00) command codes
SAVE_CONFIG = 0
FACTORY_RESET = 1

BAUD_RATES: Dict[int, int] = {
    1: 4800, 2: 9600, 3: 19200, 4: 38400, 5: 57600,
    6: 115200, 7: 230400, 8: 460800, 9: 921600,
}
BAUD_CODES: Dict[int, int] = {v: k for k, v in BAUD_RATES.items()}

BANDWIDTHS: Dict[int, str] = {
    0: "256 Hz", 1: "188 Hz", 2: "98 Hz", 3: "42 Hz", 4: "20 Hz", 5: "10 Hz", 6: "5 Hz",
}
ALGORITHMS: Dict[int, str] = {0: "9-axis (magnetometer heading)", 1: "6-axis (gyro heading)"}
ORIENTATIONS: Dict[int, str] = {0: "Horizontal", 1: "Vertical"}
GYRO_RANGES: Dict[int, str] = {0: "±250 °/s", 1: "±500 °/s", 2: "±1000 °/s", 3: "±2000 °/s"}
ACC_RANGES: Dict[int, str] = {0: "±2 g", 1: "±4 g", 2: "±8 g", 3: "±16 g"}
OUTPUT_RATES: Dict[int, str] = {
    1: "0.2 Hz", 2: "0.5 Hz", 3: "1 Hz", 4: "2 Hz", 5: "5 Hz", 6: "10 Hz", 7: "20 Hz",
    8: "50 Hz", 9: "100 Hz", 11: "200 Hz", 12: "Single", 13: "No output",
}
PORT_MODES: Dict[int, str] = {0: "Analog in", 1: "Digital in", 2: "Digital out high", 3: "Digital out low"}
CALSW_MODES: Dict[int, str] = {
    CAL_NORMAL: "Normal",
    CAL_ACCEL: "Accelerometer calibration",
    CAL_HEIGHT_RESET: "Height reset",
    CAL_HEADING_ZERO: "Heading zero",
    CAL_MAG_START: "Magnetometer calibration",
    CAL_ANGLE_REFERENCE: "Set angle reference",
    CAL_MAG_DUAL_PLANE: "Magnetometer calibration (dual plane)",
}

ACC_SCALE = 16.0 / 32768.0       # g per LSB
GYRO_SCALE = 2000.0 / 32768.0    # deg/s per LSB
ANGLE_SCALE = 180.0 / 32768.0    # deg per LSB
QUAT_SCALE = 1.0 / 32768.0
TEMP_SCALE = 1.0 / 100.0         # degC per LSB


@dataclass(frozen=True)
class RegisterInfo:
    addr: int
    name: str
    label: str
    unit: str = ""
    scale: Optional[float] = None
    writable: bool = False
    options: Dict[int, str] = field(default_factory=dict)
    signed: bool = True

    def scaled(self, raw: int) -> Optional[float]:
        if self.scale is None:
            return None
        return raw * self.scale

    def describe(self, raw: int) -> str:
        if self.options:
            return self.options.get(raw & 0xFFFF if not self.signed else raw, "")
        return ""

    def to_dict(self) -> dict:
        return {
            "addr": self.addr,
            "name": self.name,
            "label": self.label,
            "unit": self.unit,
            "scale": self.scale,
            "writable": self.writable,
            "options": {str(k): v for k, v in self.options.items()},
        }


def _r(addr, label, unit="", scale=None, writable=False, options=None, signed=True):
    try:
        name = Reg(addr).name
    except ValueError:
        name = f"R{addr:02X}"
    return RegisterInfo(addr, name, label, unit, scale, writable, options or {}, signed)


REGISTERS: Dict[int, RegisterInfo] = {r.addr: r for r in [
    _r(0x00, "Save / factory reset", writable=True, options={0: "Save", 1: "Factory reset"}),
    _r(0x01, "Calibration mode", writable=True, options=CALSW_MODES),
    _r(0x02, "Output content (stream)", writable=True),
    _r(0x03, "Output rate (stream)", writable=True, options=OUTPUT_RATES),
    _r(0x04, "Serial baud rate", writable=True, options={k: str(v) for k, v in BAUD_RATES.items()}),
    _r(0x05, "Accel X offset", "g", 1e-4, True),
    _r(0x06, "Accel Y offset", "g", 1e-4, True),
    _r(0x07, "Accel Z offset", "g", 1e-4, True),
    _r(0x08, "Gyro X offset", "°/s", 1e-4, True),
    _r(0x09, "Gyro Y offset", "°/s", 1e-4, True),
    _r(0x0A, "Gyro Z offset", "°/s", 1e-4, True),
    _r(0x0B, "Mag X offset", "LSB", writable=True),
    _r(0x0C, "Mag Y offset", "LSB", writable=True),
    _r(0x0D, "Mag Z offset", "LSB", writable=True),
    _r(0x0E, "D0 port mode", writable=True, options=PORT_MODES),
    _r(0x0F, "D1 port mode", writable=True, options=PORT_MODES),
    _r(0x10, "D2 port mode", writable=True, options=PORT_MODES),
    _r(0x11, "D3 port mode", writable=True, options=PORT_MODES),
    _r(0x1A, "Device (Modbus) address", writable=True, signed=False),
    _r(0x1B, "LED off", writable=True, options={0: "LED on", 1: "LED off"}),
    _r(0x1C, "Mag X calibration range", writable=True),
    _r(0x1D, "Mag Y calibration range", writable=True),
    _r(0x1E, "Mag Z calibration range", writable=True),
    _r(0x1F, "Bandwidth", writable=True, options=BANDWIDTHS),
    _r(0x20, "Gyro range", options=GYRO_RANGES),
    _r(0x21, "Accel range", options=ACC_RANGES),
    _r(0x22, "Sleep", writable=True, options={0: "Awake", 1: "Sleep"}),
    _r(0x23, "Installation orientation", writable=True, options=ORIENTATIONS),
    _r(0x24, "Fusion algorithm", writable=True, options=ALGORITHMS),
    _r(0x25, "Dynamic filter", writable=True),
    _r(0x26, "GPS baud rate", writable=True),
    _r(0x27, "Read register (stream)", writable=True),
    _r(0x2A, "Accel filter", writable=True),
    _r(0x2D, "Command start", writable=True),
    _r(0x2E, "Firmware version (low)", signed=False),
    _r(0x2F, "Firmware version (high)", signed=False),
    _r(0x30, "Chip time YY/MM", writable=True, signed=False),
    _r(0x31, "Chip time DD/HH", writable=True, signed=False),
    _r(0x32, "Chip time MM/SS", writable=True, signed=False),
    _r(0x33, "Chip time ms", "ms", writable=True),
    _r(0x34, "Accel X", "g", ACC_SCALE),
    _r(0x35, "Accel Y", "g", ACC_SCALE),
    _r(0x36, "Accel Z", "g", ACC_SCALE),
    _r(0x37, "Gyro X", "°/s", GYRO_SCALE),
    _r(0x38, "Gyro Y", "°/s", GYRO_SCALE),
    _r(0x39, "Gyro Z", "°/s", GYRO_SCALE),
    _r(0x3A, "Mag X", "LSB"),
    _r(0x3B, "Mag Y", "LSB"),
    _r(0x3C, "Mag Z", "LSB"),
    _r(0x3D, "Roll (X angle)", "°", ANGLE_SCALE),
    _r(0x3E, "Pitch (Y angle)", "°", ANGLE_SCALE),
    _r(0x3F, "Yaw (Z angle)", "°", ANGLE_SCALE),
    _r(0x40, "Temperature", "°C", TEMP_SCALE),
    _r(0x41, "D0 port status"),
    _r(0x42, "D1 port status"),
    _r(0x43, "D2 port status"),
    _r(0x44, "D3 port status"),
    _r(0x45, "Pressure (low 16)"),
    _r(0x46, "Pressure (high 16)"),
    _r(0x47, "Height (low 16)"),
    _r(0x48, "Height (high 16)"),
    _r(0x49, "Longitude (low 16)"),
    _r(0x4A, "Longitude (high 16)"),
    _r(0x4B, "Latitude (low 16)"),
    _r(0x4C, "Latitude (high 16)"),
    _r(0x4D, "GPS altitude", "m", 0.1),
    _r(0x4E, "GPS heading", "°", 0.01),
    _r(0x4F, "GPS ground speed (low 16)"),
    _r(0x50, "GPS ground speed (high 16)"),
    _r(0x51, "Quaternion q0", "", QUAT_SCALE),
    _r(0x52, "Quaternion q1", "", QUAT_SCALE),
    _r(0x53, "Quaternion q2", "", QUAT_SCALE),
    _r(0x54, "Quaternion q3", "", QUAT_SCALE),
    _r(0x55, "Satellites", "", 1.0),
    _r(0x56, "PDOP", "", 0.01),
    _r(0x57, "HDOP", "", 0.01),
    _r(0x58, "VDOP", "", 0.01),
    _r(0x59, "Alarm signal delay", writable=True),
    _r(0x5A, "X angle alarm min", "°", ANGLE_SCALE, True),
    _r(0x5B, "X angle alarm max", "°", ANGLE_SCALE, True),
    _r(0x5C, "Supply voltage", "V", 0.01),
    _r(0x5D, "Alarm pin mapping", writable=True),
    _r(0x5E, "Y angle alarm min", "°", ANGLE_SCALE, True),
    _r(0x5F, "Y angle alarm max", "°", ANGLE_SCALE, True),
    _r(0x61, "Gyro still threshold", "", 1e-3, True),
    _r(0x62, "Angle alarm level", writable=True),
    _r(0x63, "Gyro auto-calibration time", "ms", writable=True),
    _r(0x68, "Alarm continuous trigger time", writable=True),
    _r(0x69, "Unlock key", writable=True, signed=False),
    _r(0x6A, "Gyro change value", "°", 180.0 / 3141.5926),
    _r(0x6B, "GPS time zone", writable=True),
    _r(0x6E, "Gyro continuous still time", writable=True),
    _r(0x6F, "Gyro integral threshold", "", 1e-3, True),
    _r(0x74, "RS-485 reply delay", "µs", writable=True),
    _r(0x79, "Roll zero reference", "°", ANGLE_SCALE, True),
    _r(0x7A, "Pitch zero reference", "°", ANGLE_SCALE, True),
    _r(0x7F, "Serial number 1-2", signed=False),
    _r(0x80, "Serial number 3-4", signed=False),
    _r(0x81, "Serial number 5-6", signed=False),
    _r(0x82, "Serial number 7-8", signed=False),
    _r(0x83, "Serial number 9-10", signed=False),
    _r(0x84, "Serial number 11-12", signed=False),
]}


def info(addr: int) -> RegisterInfo:
    return REGISTERS.get(addr) or _r(addr, f"Register 0x{addr:02X}")


# Block the engine polls every cycle: chip time through quaternion.
POLL_START = Reg.YYMM            # 0x30
POLL_COUNT = Reg.Q3 - Reg.YYMM + 1  # 0x30..0x54 = 37 registers

# Configuration registers shown on the device page.
CONFIG_REGISTERS = [
    Reg.RSW, Reg.RRATE, Reg.BAUD, Reg.IICADDR, Reg.BANDWIDTH, Reg.GYRORANGE, Reg.ACCRANGE,
    Reg.ORIENT, Reg.AXIS6, Reg.FILTK, Reg.VERSION1, Reg.VERSION2, Reg.XREFROLL, Reg.YREFPITCH,
    Reg.MODDELAY, Reg.LEDOFF,
]


def u16(value: int) -> int:
    return value & 0xFFFF


def decode_chip_time(yymm: int, ddhh: int, mmss: int, ms: int) -> Optional[str]:
    """Registers 0x30-0x33 -> ISO-ish timestamp string, or None if unset."""
    yymm, ddhh, mmss = u16(yymm), u16(ddhh), u16(mmss)
    year, month = yymm & 0xFF, yymm >> 8
    day, hour = ddhh & 0xFF, ddhh >> 8
    minute, second = mmss & 0xFF, mmss >> 8
    if not (1 <= month <= 12 and 1 <= day <= 31 and hour < 24 and minute < 60 and second < 60):
        return None
    return f"20{year:02d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}.{max(0, ms) % 1000:03d}"


def encode_chip_time(dt) -> Dict[int, int]:
    """datetime -> register values for 0x30-0x33."""
    return {
        Reg.YYMM: ((dt.month & 0xFF) << 8) | (dt.year % 100),
        Reg.DDHH: ((dt.hour & 0xFF) << 8) | dt.day,
        Reg.MMSS: ((dt.second & 0xFF) << 8) | dt.minute,
        Reg.MS: dt.microsecond // 1000,
    }


def firmware_version(v1: int, v2: int) -> str:
    return f"0x{u16(v2):04X}{u16(v1):04X}"


def describe_config(values: Dict[int, int]) -> Dict[str, object]:
    """Human-friendly view of the configuration registers."""
    def opt(table: Dict[int, str], reg: int) -> Optional[str]:
        return table.get(values[reg]) if reg in values else None

    out: Dict[str, object] = {"raw": {f"0x{k:02X}": v for k, v in sorted(values.items())}}
    if Reg.BAUD in values:
        out["baud_code"] = values[Reg.BAUD]
        out["baudrate"] = BAUD_RATES.get(values[Reg.BAUD])
    if Reg.IICADDR in values:
        out["address"] = u16(values[Reg.IICADDR])
    if Reg.BANDWIDTH in values:
        out["bandwidth"] = values[Reg.BANDWIDTH]
        out["bandwidth_label"] = opt(BANDWIDTHS, Reg.BANDWIDTH)
    if Reg.AXIS6 in values:
        out["algorithm"] = values[Reg.AXIS6]
        out["algorithm_label"] = opt(ALGORITHMS, Reg.AXIS6)
    if Reg.ORIENT in values:
        out["orientation"] = values[Reg.ORIENT]
        out["orientation_label"] = opt(ORIENTATIONS, Reg.ORIENT)
    if Reg.GYRORANGE in values:
        out["gyro_range"] = opt(GYRO_RANGES, Reg.GYRORANGE)
    if Reg.ACCRANGE in values:
        out["acc_range"] = opt(ACC_RANGES, Reg.ACCRANGE)
    if Reg.RRATE in values:
        out["output_rate"] = opt(OUTPUT_RATES, Reg.RRATE)
    if Reg.VERSION1 in values and Reg.VERSION2 in values:
        out["firmware"] = firmware_version(values[Reg.VERSION1], values[Reg.VERSION2])
    if Reg.XREFROLL in values:
        out["roll_reference"] = round(values[Reg.XREFROLL] * ANGLE_SCALE, 4)
    if Reg.YREFPITCH in values:
        out["pitch_reference"] = round(values[Reg.YREFPITCH] * ANGLE_SCALE, 4)
    if Reg.MODDELAY in values:
        out["reply_delay_us"] = values[Reg.MODDELAY]
    return out
