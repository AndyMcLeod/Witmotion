"""A decoded measurement from the sensor."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Mapping, Optional, Tuple

from .registers import (
    ACC_SCALE, ANGLE_SCALE, GYRO_SCALE, QUAT_SCALE, TEMP_SCALE, Reg, decode_chip_time,
)

Vec3 = Tuple[float, float, float]


@dataclass
class Sample:
    """One reading. Angles are WitMotion's fused Euler angles in degrees."""

    t: float                          # host time (unix seconds)
    seq: int = 0
    acc: Vec3 = (0.0, 0.0, 0.0)       # g
    gyro: Vec3 = (0.0, 0.0, 0.0)      # deg/s
    mag: Tuple[int, int, int] = (0, 0, 0)  # raw LSB
    roll: float = 0.0                 # X angle, deg
    pitch: float = 0.0                # Y angle, deg
    yaw: float = 0.0                  # Z angle, deg
    temperature: float = 0.0          # degC
    quaternion: Tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)
    chip_time: Optional[str] = None
    raw: Dict[int, int] = field(default_factory=dict, repr=False)

    # ---- derived values ------------------------------------------------- #
    @property
    def tilt(self) -> float:
        """Total inclination from level, from the fused roll and pitch (deg)."""
        c = math.cos(math.radians(self.roll)) * math.cos(math.radians(self.pitch))
        return math.degrees(math.acos(max(-1.0, min(1.0, c))))

    @property
    def acc_norm(self) -> float:
        return math.sqrt(sum(a * a for a in self.acc))

    @property
    def mag_norm(self) -> float:
        return math.sqrt(sum(float(m) * m for m in self.mag))

    @property
    def heading(self) -> float:
        """Yaw expressed as a 0-360 compass heading."""
        return self.yaw % 360.0

    def to_dict(self) -> dict:
        r4 = lambda v: round(v, 4)  # noqa: E731
        return {
            "t": self.t,
            "seq": self.seq,
            "acc": [r4(v) for v in self.acc],
            "gyro": [r4(v) for v in self.gyro],
            "mag": list(self.mag),
            "roll": r4(self.roll),
            "pitch": r4(self.pitch),
            "yaw": r4(self.yaw),
            "tilt": r4(self.tilt),
            "heading": r4(self.heading),
            "temperature": round(self.temperature, 2),
            "quaternion": [round(q, 5) for q in self.quaternion],
            "acc_norm": r4(self.acc_norm),
            "mag_norm": round(self.mag_norm, 1),
            "chip_time": self.chip_time,
        }

    @staticmethod
    def csv_header() -> List[str]:
        return [
            "host_time_iso", "host_time_unix", "seq", "chip_time",
            "roll_deg", "pitch_deg", "yaw_deg", "tilt_deg",
            "acc_x_g", "acc_y_g", "acc_z_g", "acc_norm_g",
            "gyro_x_dps", "gyro_y_dps", "gyro_z_dps",
            "mag_x", "mag_y", "mag_z",
            "q0", "q1", "q2", "q3", "temperature_c",
        ]

    def csv_row(self) -> list:
        iso = datetime.fromtimestamp(self.t, timezone.utc).astimezone().isoformat(timespec="milliseconds")
        return [
            iso, f"{self.t:.3f}", self.seq, self.chip_time or "",
            f"{self.roll:.4f}", f"{self.pitch:.4f}", f"{self.yaw:.4f}", f"{self.tilt:.4f}",
            f"{self.acc[0]:.5f}", f"{self.acc[1]:.5f}", f"{self.acc[2]:.5f}", f"{self.acc_norm:.5f}",
            f"{self.gyro[0]:.4f}", f"{self.gyro[1]:.4f}", f"{self.gyro[2]:.4f}",
            self.mag[0], self.mag[1], self.mag[2],
            f"{self.quaternion[0]:.5f}", f"{self.quaternion[1]:.5f}",
            f"{self.quaternion[2]:.5f}", f"{self.quaternion[3]:.5f}",
            f"{self.temperature:.2f}",
        ]


def decode_sample(image: Mapping[int, int], t: Optional[float] = None, seq: int = 0) -> Sample:
    """Turn a ``{register: int16}`` image into a :class:`Sample`.

    Missing registers decode as zero, so partial images (e.g. a TTL sensor that
    only streams angle frames) still produce a usable sample.
    """
    g = lambda reg: image.get(reg, 0)  # noqa: E731
    chip_time = None
    if all(r in image for r in (Reg.YYMM, Reg.DDHH, Reg.MMSS, Reg.MS)):
        chip_time = decode_chip_time(g(Reg.YYMM), g(Reg.DDHH), g(Reg.MMSS), g(Reg.MS))
    has_quat = any(image.get(r, 0) for r in (Reg.Q0, Reg.Q1, Reg.Q2, Reg.Q3))
    return Sample(
        t=time.time() if t is None else t,
        seq=seq,
        acc=(g(Reg.AX) * ACC_SCALE, g(Reg.AY) * ACC_SCALE, g(Reg.AZ) * ACC_SCALE),
        gyro=(g(Reg.GX) * GYRO_SCALE, g(Reg.GY) * GYRO_SCALE, g(Reg.GZ) * GYRO_SCALE),
        mag=(g(Reg.HX), g(Reg.HY), g(Reg.HZ)),
        roll=g(Reg.ROLL) * ANGLE_SCALE,
        pitch=g(Reg.PITCH) * ANGLE_SCALE,
        yaw=g(Reg.YAW) * ANGLE_SCALE,
        temperature=g(Reg.TEMP) * TEMP_SCALE,
        quaternion=(
            (g(Reg.Q0) * QUAT_SCALE, g(Reg.Q1) * QUAT_SCALE, g(Reg.Q2) * QUAT_SCALE, g(Reg.Q3) * QUAT_SCALE)
            if has_quat else (1.0, 0.0, 0.0, 0.0)
        ),
        chip_time=chip_time,
        raw=dict(image),
    )
