"""Command-line interface: ``python -m witmotion <command>``."""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import threading
import time
import webbrowser
from pathlib import Path

from . import __version__, discovery
from .device import PROTOCOLS, WitMotionError, create_device, register_table
from .engine import SensorEngine
from .sample import Sample, decode_sample


def _int(text: str) -> int:
    return int(text, 0)


def _add_device_args(p: argparse.ArgumentParser, required: bool = False) -> None:
    p.add_argument("-d", "--device", required=required, help="serial port, e.g. COM8 or /dev/ttyUSB0")
    p.add_argument("-b", "--baud", type=int, default=115200, help="baud rate (default 115200)")
    p.add_argument("-a", "--address", type=_int, default=0x50, help="Modbus address (default 0x50)")
    p.add_argument("-p", "--protocol", choices=sorted(PROTOCOLS), default="modbus",
                   help="modbus = RS-485 models; standard = TTL/RS-232 0x55 stream; simulated = no hardware")


def _open(args):
    port = args.device or ("SIMULATOR" if args.protocol == "simulated" else None)
    if not port:
        sys.exit("error: --device is required (try `python -m witmotion scan`)")
    return create_device(args.protocol, port, args.baud, args.address).open()


# --------------------------------------------------------------------------- #

def cmd_serve(args) -> int:
    from .server import make_server, serve_forever

    engine = SensorEngine(Path(args.data_dir))
    if args.simulate:
        args.protocol, args.device = "simulated", "SIMULATOR"
    target = None
    if args.device:
        target = dict(port=args.device, baudrate=args.baud, address=args.address,
                      protocol=args.protocol, rate_hz=args.rate)
    elif not args.no_reconnect:
        last = engine.load_settings().get("last_connection")
        if last:
            target = dict(port=last["port"], baudrate=last["baudrate"], address=last["address"],
                          protocol=last["protocol"], rate_hz=last.get("rate_hz", args.rate))
    if target:
        try:
            engine.connect(**target)
            print(f"Connected to {target['port']} @ {target['baudrate']} baud "
                  f"(address 0x{target['address']:02X}, {target['protocol']})")
        except (WitMotionError, ValueError) as exc:
            print(f"Could not connect to {target['port']}: {exc}\n"
                  f"Use the Connect panel in the browser to pick a port.")

    try:
        server = make_server(engine, args.host, args.http_port)
    except OSError as exc:
        engine.disconnect()
        sys.exit(f"error: cannot listen on {args.host}:{args.http_port}: {exc}")
    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0', '::') else args.host}:{args.http_port}/"
    print(f"WitMotion web interface: {url}  (Ctrl+C to stop)")
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: listening on a non-local interface; anyone on the network can control the sensor.")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        serve_forever(server)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        engine.recorder.stop()
        engine.disconnect()
    return 0


def cmd_ports(args) -> int:
    ports = discovery.list_ports()
    if not ports:
        print("No serial ports found.")
    for p in ports:
        tag = "  <- USB-serial bridge" if p["likely"] else ""
        print(f"{p['device']:<10} {p['description']}{tag}")
    return 0


def cmd_scan(args) -> int:
    ports = args.ports or None
    bauds = args.bauds or discovery.DEFAULT_BAUDS
    found = discovery.scan(ports, bauds, args.addresses or [0x50], all_ports=args.all_ports,
                           progress=(lambda m: print("  " + m)) if args.verbose else None)
    if not found:
        print("No WitMotion sensors found." + ("" if args.all_ports else " (try --all-ports)"))
        return 1
    for f in found:
        addr = f"address 0x{f['address']:02X}" if f["address"] is not None else "streaming"
        print(f"{f['port']}: {f['protocol']} @ {f['baudrate']} baud, {addr}")
    return 0


def cmd_read(args) -> int:
    dev = _open(args)
    print(f"{'roll':>9} {'pitch':>9} {'yaw':>9} {'tilt':>7} {'ax':>8} {'ay':>8} {'az':>8} {'temp':>6}")
    n = 0
    period = 1.0 / args.rate
    try:
        while args.count <= 0 or n < args.count:
            t0 = time.monotonic()
            image = dev.poll()
            if image is not None:
                s = decode_sample(image, seq=n)
                print(f"{s.roll:9.3f} {s.pitch:9.3f} {s.yaw:9.3f} {s.tilt:7.3f} "
                      f"{s.acc[0]:8.4f} {s.acc[1]:8.4f} {s.acc[2]:8.4f} {s.temperature:6.2f}", flush=True)
                n += 1
            if not dev.streaming:
                time.sleep(max(0.0, period - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        dev.close()
    return 0


def cmd_dump(args) -> int:
    dev = _open(args)
    try:
        rows = register_table(dev.read_all_registers())
    finally:
        dev.close()
    for r in rows:
        val = "" if r["value"] is None else f"{r['value']:.4f} {r['unit']}".strip()
        text = f" [{r['text']}]" if r["text"] else ""
        print(f"0x{r['addr']:02X} {r['name']:<12} {r['raw']:>7} {r['hex']}  {val:<16} {r['label']}{text}")
    return 0


def cmd_config(args) -> int:
    dev = _open(args)
    try:
        cfg = dev.read_config()
    finally:
        dev.close()
    for k, v in cfg.items():
        if k == "address":
            v = f"0x{v:02X}"
        if k != "raw":
            print(f"{k:<18} {v}")
    return 0


def cmd_log(args) -> int:
    dev = _open(args)
    out = Path(args.out or time.strftime("witmotion_%Y%m%d_%H%M%S.csv"))
    period = 1.0 / args.rate
    n = 0
    t_end = time.monotonic() + args.duration if args.duration > 0 else float("inf")
    print(f"Logging to {out} (Ctrl+C to stop)")
    try:
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(Sample.csv_header())
            while time.monotonic() < t_end:
                t0 = time.monotonic()
                try:
                    image = dev.poll()
                except WitMotionError as exc:
                    print(f"read error: {exc}", file=sys.stderr)
                    continue
                if image is not None:
                    w.writerow(decode_sample(image, seq=n).csv_row())
                    n += 1
                if not dev.streaming:
                    time.sleep(max(0.0, period - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        dev.close()
    print(f"Wrote {n} samples to {out}")
    return 0


# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="witmotion", description="WitMotion sensor engine and web interface")
    ap.add_argument("--version", action="version", version=f"witmotion {__version__}")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS)

    p = sub.add_parser("serve", parents=[common], help="run the browser interface (default)")
    _add_device_args(p)
    p.add_argument("--rate", type=float, default=50.0, help="poll rate in Hz for Modbus devices (default 50)")
    p.add_argument("--host", default="127.0.0.1", help="interface to listen on (default 127.0.0.1)")
    p.add_argument("--http-port", type=int, default=8765, help="web server port (default 8765)")
    p.add_argument("--data-dir", default="witmotion-data", help="where recordings and settings go")
    p.add_argument("--no-browser", action="store_true", help="don't open a browser window")
    p.add_argument("--no-reconnect", action="store_true", help="don't reconnect to the last-used sensor")
    p.add_argument("--simulate", action="store_true", help="use the built-in simulator instead of hardware")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("ports", parents=[common], help="list serial ports")
    p.set_defaults(func=cmd_ports)

    p = sub.add_parser("scan", parents=[common], help="search serial ports for WitMotion sensors")
    p.add_argument("ports", nargs="*", help="ports to probe (default: USB-serial bridges)")
    p.add_argument("--all-ports", action="store_true", help="also probe Bluetooth/modem/other ports")
    p.add_argument("--bauds", type=int, nargs="+")
    p.add_argument("--addresses", type=_int, nargs="+")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("read", parents=[common], help="print live readings")
    _add_device_args(p)
    p.add_argument("--rate", type=float, default=10.0)
    p.add_argument("-n", "--count", type=int, default=0, help="stop after N samples (0 = forever)")
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("dump", parents=[common], help="print every register")
    _add_device_args(p)
    p.set_defaults(func=cmd_dump)

    p = sub.add_parser("config", parents=[common], help="print the sensor configuration")
    _add_device_args(p)
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("log", parents=[common], help="record samples to CSV")
    _add_device_args(p)
    p.add_argument("-o", "--out", help="output CSV path")
    p.add_argument("--rate", type=float, default=50.0)
    p.add_argument("--duration", type=float, default=0, help="seconds (0 = until Ctrl+C)")
    p.set_defaults(func=cmd_log)
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    args = ap.parse_args(argv)
    if args.cmd is None:  # bare `python -m witmotion [-v]` runs the web interface
        args = ap.parse_args(argv + ["serve"])
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        return args.func(args)
    except WitMotionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
