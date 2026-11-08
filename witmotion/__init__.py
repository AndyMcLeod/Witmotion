"""Python engine and browser interface for WitMotion IMU / inclinometer sensors.

Developed against a WT901C-485 (RS-485, Modbus RTU). The TTL/RS-232 variants
that stream the WitMotion standard 0x55 protocol are supported too.
"""

__version__ = "0.1.0"

from .device import (  # noqa: E402
    BaseDevice, ModbusDevice, SimulatedDevice, StandardDevice, WitMotionError, create_device,
)
from .engine import SensorEngine  # noqa: E402
from .protocol import ProtocolError, crc16_modbus  # noqa: E402
from .registers import Reg  # noqa: E402
from .sample import Sample, decode_sample  # noqa: E402

__all__ = [
    "__version__", "BaseDevice", "ModbusDevice", "StandardDevice", "SimulatedDevice",
    "WitMotionError", "ProtocolError", "create_device", "SensorEngine", "Reg", "Sample",
    "decode_sample", "crc16_modbus",
]
