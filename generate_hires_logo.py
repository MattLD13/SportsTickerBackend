#!/usr/bin/env python3
"""
High-res iOS icon generator using the actual StadiumRenderer ticker frame.
1. Renders the 84×32 ticker card with StadiumRenderer (authentic LED style).
2. Scales it up with nearest-neighbour to a 2048×2048 master (pixel-perfect, crisp).
3. Downsamples with LANCZOS to every iOS icon size.
"""

import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from ticker_controller.stadium import StadiumRenderer

# ── Game: STL (away) @ NYR (home) — pre-game 0-0, 7:00 PM ──────────────────
GAME = {
    "sport": "nhl",
    "state": "pre",
    "status": "7:00 PM",
    "home_abbr": "NYR",
    "away_abbr": "STL",
    "home_score": 0,
    "away_score": 0,
    "home_logo": "https://a.espncdn.com/i/teamlogos/nhl/500/nyr.png",
    "away_logo": "https://a.espncdn.com/i/teamlogos/nhl/500/stl.png",
    "home_color": "#0038A8",
    "away_color": "#FCB514",
}

MASTER = 2048           # master canvas side (px)
BG     = (28, 28, 28)  # #1c1c1c dark grey

# ── iOS icon table ────────────────────────────────────────────────────────────
IOS_ICONS = [
    ("Icon-Noti-20@2x.png",      40,  "20x20",      "2x", "iphone"),
    ("Icon-Noti-20@3x.png",      60,  "20x20",      "3x", "iphone"),
    ("Icon-Settings-29@2x.png",  58,  "29x29",      "2x", "iphone"),
    ("Icon-Settings-29@3x.png",  87,  "29x29",      "3x", "iphone"),
    ("Icon-Spot-40@2x.png",      80,  "40x40",      "2x", "iphone"),
    ("Icon-Spot-40@3x.png",     120,  "40x40",      "3x", "iphone"),
    ("Icon-Home-60@2x.png",     120,  "60x60",      "2x", "iphone"),
    ("Icon-Home-60@3x.png",     180,  "60x60",      "3x", "iphone"),
    ("Icon-iPad-Noti-20@1x.png", 20,  "20x20",      "1x", "ipad"),
    ("Icon-iPad-Noti-20@2x.png", 40,  "20x20",      "2x", "ipad"),
    ("Icon-iPad-Set-29@1x.png",  29,  "29x29",      "1x", "ipad"),
    ("Icon-iPad-Set-29@2x.png",  58,  "29x29",      "2x", "ipad"),
    ("Icon-iPad-Spot-40@1x.png", 40,  "40x40",      "1x", "ipad"),
    ("Icon-iPad-Spot-40@2x.png", 80,  "40x40",      "2x", "ipad"),
    ("Icon-iPad-Home-76@1x.png", 76,  "76x76",      "1x", "ipad"),
    ("Icon-iPad-Home-76@2x.png",152,  "76x76",      "2x", "ipad"),
    ("Icon-iPad-Pro-83@2x.png", 167,  "83.5x83.5",  "2x", "ipad"),
    ("Icon-AppStore-1024.png", 1024,  "1024x1024",  "1x", "ios-marketing"),
]


def build_master(ticker: Image.Image) -> Image.Image:
    """
    Scale the 84×32 ticker frame up with NEAREST (pixel-perfect crisp blocks),
    targeting 88% of the master canvas width, then centre it on a dark-grey canvas.
    """
    tw, th = ticker.size
    max_w = int(MASTER * 0.88)
    max_h = int(MASTER * 0.88)
    scale = min(max_w // tw, max_h // th)
    scale = max(scale, 1)

    scaled = ticker.resize((tw * scale, th * scale), Image.NEAREST)
    print(f"  Ticker {tw}×{th}  →  scaled {scaled.width}×{scaled.height}  (×{scale})")

    canvas = Image.new("RGB", (MASTER, MASTER), BG)
    x = (MASTER - scaled.width)  // 2
    y = (MASTER - scaled.height) // 2
    if scaled.mode == "RGBA":
        canvas.paste(scaled, (x, y), scaled)
    else:
        canvas.paste(scaled, (x, y))
    return canvas


def main() -> None:
    out = ROOT / "ios_icons"
    asset_dir = out / "AppIcon.appiconset"
    asset_dir.mkdir(parents=True, exist_ok=True)

    print("Rendering ticker frame with StadiumRenderer …")
    renderer = StadiumRenderer()
    ticker, card_w = renderer.render(GAME)
    ticker.save(out / "ticker_frame_raw.png")

    print("Building 2048×2048 master …")
    master = build_master(ticker)
    master.save(out / "AppIcon_master_2048.png")
    master.resize((1024, 1024), Image.LANCZOS).save(out / "AppIcon_base_1024.png")

    print("Generating iOS icon set …")
    contents_images = []
    master_rgba = master.convert("RGBA")
    for filename, px, pt_str, scale_str, idiom in IOS_ICONS:
        icon = master_rgba.resize((px, px), Image.LANCZOS).convert("RGB")
        icon.save(asset_dir / filename)
        print(f"  {filename:42s}  {px}×{px}")
        contents_images.append({
            "filename": filename,
            "idiom":    idiom,
            "scale":    scale_str,
            "size":     pt_str,
        })

    contents = {"images": contents_images, "info": {"author": "xcode", "version": 1}}
    (asset_dir / "Contents.json").write_text(json.dumps(contents, indent=2))

    print(f"\nDone.")
    print(f"  Raw frame:  ios_icons/ticker_frame_raw.png")
    print(f"  Master:     ios_icons/AppIcon_master_2048.png")
    print(f"  Base 1024:  ios_icons/AppIcon_base_1024.png")
    print(f"  Icon set:   ios_icons/AppIcon.appiconset/")


if __name__ == "__main__":
    main()
