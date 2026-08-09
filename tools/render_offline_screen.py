#!/usr/bin/env python3
"""Render the offline panel with the real controller fonts.

The board draws this once the backend has been silent for OFFLINE_AFTER
seconds. One PNG per elapsed step, because the badge is the part that changes.

    python tools/render_offline_screen.py --out-dir previews/offline
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.fetch_and_render import make_renderer, save_image  # noqa: E402

OUT_DIR = "previews/offline"

# One per unit the badge can print, so a change to the label is visible here.
STEPS = [("1m", 65), ("12m", 12 * 60), ("3h", 3 * 3600), ("2d", 2 * 86400)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=OUT_DIR)
    args = parser.parse_args()

    renderer = make_renderer("sports")
    for name, seconds in STEPS:
        img = renderer.draw_offline_screen(seconds)
        save_image(img.convert("RGB"), os.path.join(args.out_dir, f"offline_{name}.png"))


if __name__ == "__main__":
    main()
