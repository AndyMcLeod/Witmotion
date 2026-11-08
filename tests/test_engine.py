import json
import queue
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from witmotion.device import SimulatedDevice
from witmotion.engine import SensorEngine
from witmotion.registers import Reg
from witmotion.server import make_server


class SimulatorDeviceTests(unittest.TestCase):
    def setUp(self):
        self.dev = SimulatedDevice().open()

    def test_poll_and_config(self):
        image = self.dev.poll()
        self.assertIn(Reg.ROLL, image)
        cfg = self.dev.read_config()
        self.assertEqual(cfg["baudrate"], 115200)
        self.assertEqual(cfg["address"], 0x50)
        self.assertEqual(cfg["bandwidth_label"], "20 Hz")

    def test_settings(self):
        self.dev.set_bandwidth(2)
        self.assertEqual(self.dev.read_registers(Reg.BANDWIDTH, 1), [2])
        self.dev.set_address(0x51)
        self.assertEqual(self.dev.address, 0x51)
        self.dev.set_baudrate(9600)
        self.assertEqual(self.dev.baudrate, 9600)
        with self.assertRaises(ValueError):
            self.dev.set_baudrate(12345)
        with self.assertRaises(ValueError):
            self.dev.set_address(0x80)

    def test_zero_heading(self):
        self.dev.zero_heading()
        yaw = self.dev.read_sample().yaw
        self.assertLess(abs(yaw), 1.0)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.engine = SensorEngine(self.tmp)

    def tearDown(self):
        self.engine.recorder.stop()
        self.engine.disconnect()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_connect_stream_record(self):
        q = self.engine.subscribe()
        self.engine.connect("SIMULATOR", 115200, 0x50, "simulated", rate_hz=100)
        kinds = set()
        deadline = time.time() + 3
        while time.time() < deadline and "sample" not in kinds:
            kind, _ = q.get(timeout=1)
            kinds.add(kind)
        self.assertIn("sample", kinds)
        self.engine.recorder.start("unit test")
        time.sleep(0.3)
        info = self.engine.recorder.stop()
        self.assertGreater(info["rows"], 5)
        files = self.engine.recorder.list()
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0]["name"].endswith("_unit_test.csv"))
        self.assertIsNone(self.engine.recorder.path_for("../secret.csv"))
        self.assertIsNotNone(self.engine.recorder.path_for(files[0]["name"]))
        settings = json.loads((self.tmp / "settings.json").read_text())
        self.assertEqual(settings["last_connection"]["protocol"], "simulated")

    def test_commands(self):
        self.engine.connect("SIMULATOR", 115200, 0x50, "simulated")
        r = self.engine.command("read_registers", {"start": 0x3D, "count": 3})
        self.assertEqual([row["name"] for row in r["result"]], ["ROLL", "PITCH", "YAW"])
        r = self.engine.command("write_register", {"addr": Reg.BANDWIDTH, "value": 3})
        self.assertEqual(r["result"]["readback"], 3)
        self.engine.command("set_rate", {"rate_hz": 20})
        self.assertEqual(self.engine.rate_hz, 20)
        with self.assertRaises(ValueError):
            self.engine.command("nope")
        with self.assertRaises(ValueError):
            self.engine.command("set_rate", {"rate_hz": 1000})

    def test_not_connected(self):
        from witmotion.device import WitMotionError
        with self.assertRaises(WitMotionError):
            self.engine.command("save")


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.engine = SensorEngine(cls.tmp)
        cls.server = make_server(cls.engine, "127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stopping.set()
        cls.server.shutdown()
        cls.server.server_close()
        cls.engine.disconnect()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, path, body=None, headers=None, method=None):
        data = None if body is None else json.dumps(body).encode()
        h = {"Content-Type": "application/json"} if body is not None else {}
        h.update(headers or {})
        r = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_static_and_meta(self):
        status, body = self.req("/")
        self.assertEqual(status, 200)
        self.assertIn(b"WitMotion", body)
        status, body = self.req("/api/meta")
        self.assertEqual(status, 200)
        self.assertIn("registers", json.loads(body))

    def test_connect_and_stream(self):
        status, body = self.req("/api/connect", {"protocol": "simulated", "rate_hz": 50})
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["state"], "connected")
        with urllib.request.urlopen(self.base + "/api/stream", timeout=5) as resp:
            seen = set()
            deadline = time.time() + 5
            while time.time() < deadline and "sample" not in seen:
                line = resp.readline().decode()
                if line.startswith("event:"):
                    seen.add(line.split(":", 1)[1].strip())
        self.assertIn("status", seen)
        self.assertIn("sample", seen)
        status, body = self.req("/api/command", {"action": "read_config"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["result"]["address"], 0x50)

    def test_request_guards(self):
        status, _ = self.req("/api/command", headers={"Content-Type": "text/plain"}, method="POST")
        self.assertEqual(status, 415)
        status, _ = self.req("/api/command", {"action": "save"}, headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        status, _ = self.req("/api/status", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)
        status, _ = self.req("/recordings/..%2F..%2Fsettings.json")
        self.assertEqual(status, 404)
        status, _ = self.req("/api/command", {"action": "bogus"})
        self.assertIn(status, (400, 409))


if __name__ == "__main__":
    unittest.main()
