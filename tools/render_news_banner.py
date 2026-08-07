#!/usr/bin/env python3
"""Render the shipped news banner over a real scrolling ticker.

Unlike the score alert, the banner does not freeze the strip. It holds the left
half while the right half keeps scrolling, which is what these frames show.

    python tools/render_news_banner.py
    python tools/render_news_banner.py --no-gif
"""

from __future__ import annotations

import argparse
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.fetch_and_render import make_renderer, prefetch_logos, render_scroll, save_image  # noqa: E402
from tools.render_score_alert_overlay import STRIP_GAMES  # noqa: E402
from ticker_controller.config import PANEL_W, PANEL_H  # noqa: E402
from ticker_controller.modes.news_banner import news_banner_duration  # noqa: E402

OUT_DIR = "previews/news_banner"
FPS = 25
SCROLL_PX = 1.3
LEAD_IN = 1.0           # seconds of ordinary scrolling before the banner

ITEMS = [
    ("1_trade_blues", {
        "kind": "TRADE", "domain": "sports", "sport": "nhl",
        "from_abbr": "CHI", "from_color": "#CF0A2C",
        "to_abbr": "STL", "to_color": "#002F87",
        "text": "Andre Burakovsky for a 2027 second"}),
    ("2_trade_rangers", {
        "kind": "TRADE", "domain": "sports", "sport": "nhl",
        "from_abbr": "VAN", "from_color": "#00205B",
        "to_abbr": "NYR", "to_color": "#0038A8",
        "text": "J.T. Miller for Kakko, a 2027 first and a conditional third"}),
    ("3_signing_giants", {
        "kind": "SIGNS", "domain": "sports", "sport": "nfl",
        "from_abbr": "FA", "from_color": "#8B93A3",
        "to_abbr": "NYG", "to_color": "#0B2265",
        "text": "Saquon Barkley to a three-year deal worth 37.75M"}),
    ("4_stock_news", {
        "kind": "NEWS", "domain": "stocks", "pct": -3.8, "to_abbr": "TSLA",
        "text": "Musk's SpaceX, Tesla to build $16.8B Terafab chip factory in Texas"}),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=OUT_DIR)
    parser.add_argument("--scale", type=int, default=3)
    parser.add_argument("--no-gif", action="store_true")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    r = make_renderer("sports")
    prefetch_logos(r, STRIP_GAMES)
    strip = render_scroll(r, STRIP_GAMES)
    span = max(1, strip.width - PANEL_W)

    stills = []
    for name, item in ITEMS:
        total = news_banner_duration(item)
        frames, offset = [], 120.0
        for i in range(int((LEAD_IN + total + 0.8) * FPS)):
            t = i / FPS
            view = strip.crop((int(offset) % span, 0, int(offset) % span + PANEL_W, PANEL_H))
            offset += SCROLL_PX          # the strip never stops
            if LEAD_IN <= t < LEAD_IN + total:
                view = r.apply_news_banner(view, item, t - LEAD_IN)
            frames.append(view.convert("RGB"))

        still = frames[int((LEAD_IN + 2.0) * FPS)]
        save_image(still, os.path.join(args.out_dir, f"{name}.png"))
        stills.append(still)

        if args.no_gif:
            continue
        scaled = [f.resize((PANEL_W * args.scale, PANEL_H * args.scale),
                           Image.Resampling.NEAREST) for f in frames]
        path = os.path.join(args.out_dir, f"{name}.gif")
        scaled[0].save(path, save_all=True, append_images=scaled[1:],
                       duration=int(1000 / FPS), loop=0)
        print(f"Saved {path} ({len(scaled)} frames)")

    s = args.scale
    sheet = Image.new("RGB", (PANEL_W * s, (PANEL_H * s + 8) * len(stills)), (18, 18, 20))
    for i, still in enumerate(stills):
        sheet.paste(still.resize((PANEL_W * s, PANEL_H * s), Image.Resampling.NEAREST),
                    (0, i * (PANEL_H * s + 8)))
    save_image(sheet, os.path.join(args.out_dir, "_banners.png"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
