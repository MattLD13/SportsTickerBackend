#!/usr/bin/env python3
"""Generate a dark-mode logo + full iOS app icon set from a Rangers vs Blues ticker frame."""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from ticker_controller.stadium import StadiumRenderer

# ── Game: NYR vs STL — pre-game, 0-0, 7:00 PM ──────────────────────────────
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
    "home_color": "#0038A8",   # Rangers blue
    "away_color": "#FCB514",   # Blues gold
}

# ── iOS icon size table ─────────────────────────────────────────────────────
# (filename, pixel_size, point_size, scale, idiom)
IOS_ICONS = [
    # iPhone
    ("Icon-Noti-20@2x.png",    40,  "20x20", "2x", "iphone"),
    ("Icon-Noti-20@3x.png",    60,  "20x20", "3x", "iphone"),
    ("Icon-Settings-29@2x.png",58,  "29x29", "2x", "iphone"),
    ("Icon-Settings-29@3x.png",87,  "29x29", "3x", "iphone"),
    ("Icon-Spot-40@2x.png",    80,  "40x40", "2x", "iphone"),
    ("Icon-Spot-40@3x.png",   120,  "40x40", "3x", "iphone"),
    ("Icon-Home-60@2x.png",   120,  "60x60", "2x", "iphone"),
    ("Icon-Home-60@3x.png",   180,  "60x60", "3x", "iphone"),
    # iPad
    ("Icon-iPad-Noti-20@1x.png",  20,  "20x20", "1x", "ipad"),
    ("Icon-iPad-Noti-20@2x.png",  40,  "20x20", "2x", "ipad"),
    ("Icon-iPad-Set-29@1x.png",   29,  "29x29", "1x", "ipad"),
    ("Icon-iPad-Set-29@2x.png",   58,  "29x29", "2x", "ipad"),
    ("Icon-iPad-Spot-40@1x.png",  40,  "40x40", "1x", "ipad"),
    ("Icon-iPad-Spot-40@2x.png",  80,  "40x40", "2x", "ipad"),
    ("Icon-iPad-Home-76@1x.png",  76,  "76x76", "1x", "ipad"),
    ("Icon-iPad-Home-76@2x.png", 152,  "76x76", "2x", "ipad"),
    ("Icon-iPad-Pro-83@2x.png",  167, "83.5x83.5", "2x", "ipad"),
    # App Store
    ("Icon-AppStore-1024.png",  1024, "1024x1024", "1x", "ios-marketing"),
]


def build_base_icon(ticker: Image.Image) -> Image.Image:
    """Compose a 1024×1024 icon: dark grey background, max-res pixel-art ticker centred."""
    S = 1024
    DARK_GREY = (28, 28, 28, 255)

    canvas = Image.new("RGBA", (S, S), DARK_GREY)

    # Scale to the largest integer multiple that fits in 88% of the canvas
    tw, th = ticker.size
    scale = min(int(S * 0.88) // tw, int(S * 0.88) // th)
    scale = max(scale, 1)
    scaled = ticker.resize((tw * scale, th * scale), Image.NEAREST)

    # Centre the ticker
    x = (S - scaled.width) // 2
    y = (S - scaled.height) // 2
    if scaled.mode == "RGBA":
        canvas.paste(scaled, (x, y), scaled)
    else:
        canvas.paste(scaled, (x, y))

    return canvas.convert("RGB")


def main() -> None:
    out = ROOT / "ios_icons"
    asset_dir = out / "AppIcon.appiconset"
    asset_dir.mkdir(parents=True, exist_ok=True)

    print("Rendering Rangers vs Blues ticker frame …")
    renderer = StadiumRenderer()
    ticker_img, card_w = renderer.render(GAME)
    ticker_img.save(out / "ticker_frame_raw.png")
    print(f"  Raw frame: {ticker_img.size[0]}×{ticker_img.size[1]} px  (card_w={card_w})")

    print("Building 1024×1024 dark-mode base icon …")
    base = build_base_icon(ticker_img)
    base.save(out / "AppIcon_base_1024.png")
    base_rgba = base.convert("RGBA")

    print("Generating iOS icon set …")
    contents_images = []
    for filename, px, pt_str, scale, idiom in IOS_ICONS:
        icon = base_rgba.resize((px, px), Image.LANCZOS).convert("RGB")
        icon.save(asset_dir / filename)
        print(f"  {filename:40s}  {px}×{px} px")
        contents_images.append({
            "filename": filename,
            "idiom": idiom,
            "scale": scale,
            "size": pt_str,
        })

    contents = {"images": contents_images, "info": {"author": "xcode", "version": 1}}
    (asset_dir / "Contents.json").write_text(json.dumps(contents, indent=2))

    print(f"\nDone.  Drop  ios_icons/AppIcon.appiconset/  into your Xcode Assets.xcassets/")
    print(f"Base icon also saved at  ios_icons/AppIcon_base_1024.png")


if __name__ == "__main__":
    main()
