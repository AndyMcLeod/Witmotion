import struct
import unittest
from datetime import datetime

from witmotion import protocol as P
from witmotion.device import _find_reply
from witmotion.registers import Reg, decode_chip_time, encode_chip_time
from witmotion.sample import decode_sample

# A real reply from a WT901C-485 (address 0x50) to "read 13 registers from 0x34".
REAL_REPLY = bytes.fromhex(
    "50 03 1a 00 26 ff f9 08 08 00 00 00 00 00 00 05 3b fa ea de d4 ff d6 ff 3c 5e 53 08 8d b6 7b"
)


class ModbusTests(unittest.TestCase):
    def test_crc_known_frames(self):
        # Frames from the WitMotion WT901C-485 documentation.
        self.assertEqual(P.modbus_write_request(0x50, 0x69, 0xB588).hex(" "), "50 06 00 69 b5 88 22 a1")
        self.assertEqual(P.modbus_write_request(0x50, 0x00, 0x0000).hex(" "), "50 06 00 00 00 00 84 4b")
        self.assertEqual(P.modbus_read_request(0x50, 0x3D, 3).hex(" "), "50 03 00 3d 00 03 99 86")

    def test_crc_standard_check_value(self):
        self.assertEqual(P.crc16_modbus(b"123456789"), 0x4B37)

    def test_parse_real_reply(self):
        vals = P.parse_modbus_read_response(REAL_REPLY, 0x50, 13)
        self.assertEqual(len(vals), 13)
        self.assertEqual(vals[0], 0x26)       # accel X
        self.assertEqual(vals[1], -7)         # accel Y (signed)
        self.assertEqual(vals[11], 0x5E53)    # yaw
        self.assertEqual(vals[12], 0x088D)    # temperature

    def test_decode_real_reply(self):
        vals = P.parse_modbus_read_response(REAL_REPLY, 0x50, 13)
        s = decode_sample({0x34 + i: v for i, v in enumerate(vals)})
        self.assertAlmostEqual(s.acc[2], 1.0039, places=3)
        self.assertAlmostEqual(s.roll, -0.2307, places=3)
        self.assertAlmostEqual(s.pitch, -1.0767, places=3)
        self.assertAlmostEqual(s.yaw, 132.643, places=2)
        self.assertAlmostEqual(s.temperature, 21.89, places=2)
        self.assertAlmostEqual(s.tilt, 1.101, places=2)

    def test_bad_crc_rejected(self):
        bad = bytearray(REAL_REPLY)
        bad[5] ^= 0xFF
        with self.assertRaises(P.ProtocolError):
            P.parse_modbus_read_response(bytes(bad), 0x50, 13)

    def test_wrong_address_rejected(self):
        with self.assertRaises(P.ProtocolError):
            P.parse_modbus_read_response(REAL_REPLY, 0x51, 13)

    def test_short_reply_rejected(self):
        with self.assertRaises(P.ProtocolError):
            P.parse_modbus_read_response(REAL_REPLY[:-3], 0x50, 13)

    def test_exception_reply(self):
        frame = bytes([0x50, 0x83, 0x02])
        crc = P.crc16_modbus(frame)
        frame += bytes([crc & 0xFF, crc >> 8])
        with self.assertRaisesRegex(P.ProtocolError, "exception code 2"):
            P.parse_modbus_read_response(frame, 0x50, 13)

    def test_write_echo(self):
        req = P.modbus_write_request(0x50, 0x1F, 4)
        P.parse_modbus_write_response(req, 0x50, 0x1F, 4)
        with self.assertRaises(P.ProtocolError):
            P.parse_modbus_write_response(req, 0x50, 0x1F, 5)

    def test_find_reply_skips_echo_and_noise(self):
        echo = P.modbus_read_request(0x50, 0x34, 13)
        buf = bytearray(b"\x00\xff" + echo + REAL_REPLY)
        self.assertEqual(_find_reply(buf, 0x50, 0x03, len(REAL_REPLY)), REAL_REPLY)

    def test_request_validation(self):
        with self.assertRaises(ValueError):
            P.modbus_read_request(0x50, 0, 0)
        with self.assertRaises(ValueError):
            P.modbus_read_request(0x50, 0, 126)
        with self.assertRaises(ValueError):
            P.modbus_write_request(0x50, 0, 0x10000)


def std_frame(ftype, *values):
    body = bytes([0x55, ftype]) + struct.pack("<4h", *values)
    return body + bytes([sum(body) & 0xFF])


class StandardProtocolTests(unittest.TestCase):
    def test_commands(self):
        self.assertEqual(P.std_command(0x69, 0xB588).hex(" "), "ff aa 69 88 b5")
        self.assertEqual(P.std_command(0x00, 0).hex(" "), "ff aa 00 00 00")
        self.assertEqual(P.std_read_command(0x3D).hex(" "), "ff aa 27 3d 00")

    def test_parser_resyncs_through_noise_and_splits(self):
        stream = (b"\x01\x02\x55\x99" + std_frame(0x51, 100, -200, 2048, 2150)
                  + std_frame(0x53, -42, -196, 24147, 0) + std_frame(0x59, 1, 2, 3, 4))
        p = P.StandardFrameParser()
        frames = []
        for i in range(0, len(stream), 7):  # feed in awkward chunks
            frames += p.feed(stream[i:i + 7])
        self.assertEqual([f[0] for f in frames], [0x51, 0x53, 0x59])
        image = P.std_frames_to_registers(frames)
        self.assertEqual(image[Reg.AX], 100)
        self.assertEqual(image[Reg.AY], -200)
        self.assertEqual(image[Reg.TEMP], 2150)
        self.assertEqual(image[Reg.YAW], 24147)
        self.assertEqual(image[Reg.Q3], 4)

    def test_parser_rejects_bad_checksum(self):
        frame = bytearray(std_frame(0x53, 1, 2, 3, 4))
        frame[-1] ^= 1
        p = P.StandardFrameParser()
        self.assertEqual(p.feed(bytes(frame)), [])


class ChipTimeTests(unittest.TestCase):
    def test_roundtrip(self):
        dt = datetime(2026, 11, 8, 13, 5, 9, 123000)
        regs = encode_chip_time(dt)
        self.assertEqual(decode_chip_time(regs[Reg.YYMM], regs[Reg.DDHH], regs[Reg.MMSS], regs[Reg.MS]),
                         "2026-11-08 13:05:09.123")

    def test_real_sensor_registers(self):
        # values read from the sensor: 0x0417 0x0D0C 0x1521 448
        self.assertEqual(decode_chip_time(0x0417, 0x0D0C, 0x1521, 448), "2023-04-12 13:33:21.448")

    def test_unset_clock(self):
        self.assertIsNone(decode_chip_time(0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
