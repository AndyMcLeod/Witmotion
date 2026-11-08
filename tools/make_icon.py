#!/usr/bin/env python3
"""Build assets/witmotion.ico, the WitMotion Console desktop-shortcut icon.

    python tools/make_icon.py [--out assets/witmotion.ico] [--png preview.png]

The picture is an attitude indicator, because roll and pitch are what the sensor
measures and what the console puts front and centre. It shows a sky/ground dial
with the horizon rolled over, a roll scale with an amber pointer reading the
current bank, and the amber level symbol fixed in the middle. The navy tile, blue
and amber match the other console icons on this machine (Transit, Fuel, ASV), so
they read as one family.

Each size is drawn from its own 8x supersample instead of shrinking one master,
so stroke weights stay proportional. Detail is dropped as the icon shrinks. The
pitch ladder, roll scale and glass highlight disappear below 48 px, and at 16-24
px only the tile, the tilted horizon and a heavier amber bar remain. Anything
finer turns to mush at the size Windows uses in list views.

Drawn rather than downloaded, so there is no licensing question. Requires Pillow.
The .ico is committed, so this only needs rerunning when the artwork changes.
"""

from __future__ import annotations

import argparse
import io
import math
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SS = 8                                  # supersampling factor

TILE_TOP = (22, 40, 62)
TILE_BOT = (7, 15, 27)
RIM = (44, 66, 88)
BEZEL = (9, 16, 25)
BEZEL_EDGE = (78, 108, 138)
SKY_TOP = (110, 200, 255)
SKY_BOT = (34, 120, 205)
GROUND_TOP = (20, 52, 74)
GROUND_BOT = (6, 18, 30)
HORIZON = (242, 247, 251)
AMBER = (255, 207, 63)
CASING = (4, 8, 13)
GLOW = (57, 160, 255)

ROLL_DEG = 18.0                         # bank shown in the artwork (right wing down)
PITCH = 0.10                            # horizon offset, fraction of dial radius (nose up)


def _vgrad(w: int, h: int, top, bot, gamma: float = 1.0) -> Image.Image:
    col = Image.new("RGB", (1, h))
    for y in range(h):
        t = (y / max(1, h - 1)) ** gamma
        col.putpixel((0, y), tuple(round(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return col.resize((w, h), Image.BILINEAR).convert("RGBA")


def _circle_mask(size: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).ellipse([0, 0, size - 1, size - 1], fill=255)
    return m


def _world(R: float, px: int) -> Image.Image:
    """Sky, ground, horizon and pitch ladder, upright, oversized so rotation can't expose corners."""
    W = int(R * 2 * 1.5)
    c = W / 2
    hy = c + PITCH * R                                  # horizon sits low: nose up
    world = Image.new("RGBA", (W, W))
    world.paste(_vgrad(W, int(hy), SKY_TOP, SKY_BOT, 0.9), (0, 0))
    world.paste(_vgrad(W, W - int(hy), GROUND_TOP, GROUND_BOT, 0.8), (0, int(hy)))
    d = ImageDraw.Draw(world)

    hw = max(SS * 1.2, R * (0.055 if px >= 32 else 0.09))
    d.rectangle([0, hy - hw / 2, W, hy + hw / 2], fill=HORIZON + (255,))

    if px >= 48:                                         # pitch ladder
        lw = max(SS, R * 0.026)
        for k, half in ((1, 0.20), (2, 0.34), (-1, 0.20), (-2, 0.34)):
            y = hy - k * R * 0.22
            a = 230 if k > 0 else 150
            d.rectangle([c - R * half, y - lw / 2, c + R * half, y + lw / 2], fill=HORIZON + (a,))
    elif px >= 32:
        lw = max(SS, R * 0.035)
        y = hy - R * 0.26
        d.rectangle([c - R * 0.22, y - lw / 2, c + R * 0.22, y + lw / 2], fill=HORIZON + (210,))
    return world


def render(px: int) -> Image.Image:
    n = px * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))

    # ---- tile ------------------------------------------------------------
    pad = n * 0.04
    radius = n * 0.20
    tile_mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(tile_mask).rounded_rectangle([pad, pad, n - pad, n - pad], radius=radius, fill=255)
    img.paste(_vgrad(n, n, TILE_TOP, TILE_BOT, 1.1), (0, 0), tile_mask)
    td = ImageDraw.Draw(img)
    td.rounded_rectangle([pad, pad, n - pad, n - pad], radius=radius,
                         outline=RIM + (255,), width=max(SS, int(n * 0.018)))
    if px >= 48:  # faint top sheen
        sheen = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        ImageDraw.Draw(sheen).rounded_rectangle(
            [pad + n * 0.03, pad + n * 0.02, n - pad - n * 0.03, n * 0.42], radius=radius * 0.8,
            fill=(255, 255, 255, 14))
        img.alpha_composite(sheen.filter(ImageFilter.GaussianBlur(n * 0.02)))

    # ---- dial geometry ---------------------------------------------------
    cx, cy = n / 2, n / 2
    R = n * (0.335 if px >= 48 else 0.37 if px >= 32 else 0.40)
    bezel_w = n * (0.055 if px >= 48 else 0.045 if px >= 32 else 0.035)

    # drop shadow under the instrument
    if px >= 32:
        sh = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        rr = R + bezel_w
        ImageDraw.Draw(sh).ellipse([cx - rr, cy - rr + n * 0.02, cx + rr, cy + rr + n * 0.02],
                                   fill=(0, 0, 0, 120))
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(n * 0.025)))

    rb = R + bezel_w
    if px >= 32:  # sky-blue halo on its own blurred layer (painting it on the tile would just darken it)
        glow = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        gw = n * 0.03
        ImageDraw.Draw(glow).ellipse([cx - rb - gw, cy - rb - gw, cx + rb + gw, cy + rb + gw],
                                     outline=GLOW + (150,), width=int(gw * 1.4))
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(n * 0.022)))

    d = ImageDraw.Draw(img)
    d.ellipse([cx - rb, cy - rb, cx + rb, cy + rb], fill=BEZEL + (255,),
              outline=BEZEL_EDGE + (255,), width=max(SS, int(n * 0.012)))

    # ---- sky / ground, rolled ------------------------------------------
    world = _world(R, px).rotate(ROLL_DEG, resample=Image.BICUBIC)
    W = world.size[0]
    D = int(round(2 * R))
    off = (W - D) // 2
    dial = world.crop((off, off, off + D, off + D))

    if px >= 48:  # roll scale and pointer, drawn on the dial before clipping
        dd = ImageDraw.Draw(dial)
        c0 = D / 2
        tick_w = max(SS, R * 0.03)
        for a, major in ((-60, True), (-45, False), (-30, True), (-20, False), (-10, False),
                         (10, False), (20, False), (30, True), (45, False), (60, True)):
            th = math.radians(a - 90)
            r1, r2 = R * 0.98, R * (0.80 if major else 0.87)
            p1 = (c0 + math.cos(th) * r1, c0 + math.sin(th) * r1)
            p2 = (c0 + math.cos(th) * r2, c0 + math.sin(th) * r2)
            dd.line([p1, p2], fill=CASING + (150,), width=int(tick_w * 2.0))
            dd.line([p1, p2], fill=HORIZON + (255,), width=int(tick_w))
        # zero index: a white triangle at the top of the scale
        t = R * 0.09
        dd.polygon([(c0, R * 0.17), (c0 - t, R * 0.02), (c0 + t, R * 0.02)], fill=HORIZON + (255,))
        # amber roll pointer rides with the horizon (bank angle = ROLL_DEG)
        th = math.radians(-ROLL_DEG - 90)
        tip = R * 0.80
        base = R * 0.60
        half = math.radians(8.0)
        pts = [(c0 + math.cos(th) * tip, c0 + math.sin(th) * tip),
               (c0 + math.cos(th - half) * base, c0 + math.sin(th - half) * base),
               (c0 + math.cos(th + half) * base, c0 + math.sin(th + half) * base)]
        dd.polygon(pts, fill=AMBER + (255,), outline=CASING + (255,), width=max(1, int(SS * 0.8)))

    if px >= 48:  # glass: soft light from the upper left
        glass = Image.new("RGBA", (D, D), (0, 0, 0, 0))
        ImageDraw.Draw(glass).ellipse([-D * 0.15, -D * 0.25, D * 0.75, D * 0.45], fill=(255, 255, 255, 38))
        dial.alpha_composite(glass.filter(ImageFilter.GaussianBlur(D * 0.08)))

    img.paste(dial, (int(round(cx - R)), int(round(cy - R))), _circle_mask(D))
    d = ImageDraw.Draw(img)
    d.ellipse([cx - R, cy - R, cx + R, cy + R], outline=CASING + (255,), width=max(SS, int(n * 0.010)))

    # ---- fixed level symbol (amber "wings") ------------------------------
    lw = n * (0.034 if px >= 48 else 0.050 if px >= 32 else 0.075)
    case = lw * 0.45

    def polyline(points):
        """Round-capped amber stroke over a dark casing (the casing keeps it legible on sky and ground)."""
        for colour, w in ((CASING, lw + 2 * case), (AMBER, lw)):
            d.line(points, fill=colour + (255,), width=int(w), joint="curve")
            for x, y in points:
                d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=colour + (255,))

    if px >= 32:
        wing_out, wing_in, drop = R * 0.66, R * 0.25, R * 0.12
        for s in (-1, 1):
            polyline([(cx + s * wing_out, cy), (cx + s * wing_in, cy), (cx + s * wing_in, cy + drop)])
        dr = lw * 0.95
        d.ellipse([cx - dr - case, cy - dr - case, cx + dr + case, cy + dr + case], fill=CASING + (255,))
        d.ellipse([cx - dr, cy - dr, cx + dr, cy + dr], fill=AMBER + (255,))
    else:
        polyline([(cx - R * 0.60, cy), (cx + R * 0.60, cy)])

    return img.resize((px, px), Image.LANCZOS)


def build_ico(path: Path, sizes=SIZES) -> Path:
    """Multi-resolution .ico with PNG-compressed entries (one rendered frame per size)."""
    blobs = []
    for px in sizes:
        buf = io.BytesIO()
        render(px).save(buf, format="PNG", optimize=True)
        blobs.append(buf.getvalue())
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = len(header) + 16 * len(blobs)
    entries, payload = b"", b""
    for px, blob in zip(sizes, blobs):
        entries += struct.pack("<BBBBHHII", 0 if px >= 256 else px, 0 if px >= 256 else px,
                               0, 0, 1, 32, len(blob), offset)
        payload += blob
        offset += len(blob)
    path.write_bytes(header + entries + payload)
    return path


def main() -> None:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="Build the WitMotion Console shortcut icon")
    ap.add_argument("--out", default=str(here.parent / "assets" / "witmotion.ico"))
    ap.add_argument("--png", help="also write a preview sheet (256..16 px) at this path")
    args = ap.parse_args()

    out = build_ico(Path(args.out))
    print(f"  {out}  ({out.stat().st_size:,} bytes, sizes {', '.join(str(s) for s in SIZES)})")
    if args.png:
        sheet = Image.new("RGBA", (256 + 128 + 64 + 48 + 32 + 24 + 16 + 7 * 10, 256), (13, 17, 23, 255))
        x = 0
        for px in (256, 128, 64, 48, 32, 24, 16):
            sheet.alpha_composite(render(px), (x, 256 - px))
            x += px + 10
        sheet.save(args.png)
        print(f"  {args.png}")


if __name__ == "__main__":
    main()
