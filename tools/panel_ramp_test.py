#!/usr/bin/env python3
"""Show a low-end ramp on the panel to measure how much dark detail survives.

The full-bleed cards paint their fields in the bottom ~15% of the 8-bit range,
which is exactly where the display pipeline can throw detail away. The library
keeps 11 internal bitplanes and emits only the top ``pwm_bits`` of them, so
``pwm_bits=8`` drops the low 3 bits; CIE1931 correction, when enabled, packs
dark inputs into those same 3 bits. Together they flatten the field palette to
about five distinct levels, which is why an edge fade renders as bands.

Run it both ways on the Pi and photograph each:

    sudo systemctl stop ticker-controller
    cd /home/mld
    sudo python3 tools/panel_ramp_test.py                     # as shipped
    sudo TICKER_LUMINANCE=0 python3 tools/panel_ramp_test.py   # linear
    sudo systemctl start ticker-controller

Top half is a continuous 0..MAX green ramp: count the bands. Bottom half is
discrete swatches at known values, separated by black: count how many are
distinguishable from their neighbour, and how many are distinguishable from
black at all. Predicted 0..34 distinct levels — CIE+8bit: 5, linear+8bit: 35.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ticker_controller.config import PANEL_H, PANEL_W  # noqa: E402


def build_frame(max_value, channel):
    img = Image.new("RGB", (PANEL_W, PANEL_H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    idx = {"r": 0, "g": 1, "b": 2}[channel]

    def col(v):
        c = [0, 0, 0]
        c[idx] = int(v)
        return tuple(c)

    # Continuous ramp, top half.
    for x in range(PANEL_W):
        d.line([(x, 0), (x, PANEL_H // 2 - 2)], fill=col(x * max_value / (PANEL_W - 1)))

    # Discrete swatches, bottom half — 16 steps with black gaps between them.
    steps = 16
    cell = PANEL_W // steps
    for i in range(steps):
        v = round((i + 1) * max_value / steps)
        x0 = i * cell
        d.rectangle([x0, PANEL_H // 2 + 1, x0 + cell - 3, PANEL_H - 1], fill=col(v))
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=34,
                    help="top of the ramp (default 34 = the field palette's brightest grass)")
    ap.add_argument("--channel", default="g", choices=["r", "g", "b"])
    ap.add_argument("--seconds", type=float, default=60.0)
    args = ap.parse_args()

    from ticker_controller.matrix import build_matrix

    matrix = build_matrix()
    frame = build_frame(args.max, args.channel)
    matrix.SetImage(frame)

    corrected = getattr(matrix, "luminanceCorrect", "unknown")
    print(f"channel={args.channel}  ramp 0..{args.max}")
    print(f"luminanceCorrect={corrected}  "
          f"pwm_bits={os.environ.get('TICKER_PWM_BITS') or 8}")
    print(f"Holding {args.seconds}s — photograph the panel, then Ctrl-C.")
    try:
        time.sleep(args.seconds)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
