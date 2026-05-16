#!/usr/bin/env python3
"""
High-res iOS icon generator using the actual StadiumRenderer ticker frame.
1. Renders the 84×32 ticker card with StadiumRenderer (authentic LED style).
2. Saves a faithful nearest-neighbour upscale of the raw frame as a separate asset.
3. Builds a polished 2048×2048 iOS icon around that exact frame, then exports the icon set.
"""

import json
import sys
import io
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter

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
BG     = (72, 72, 74)   # requested background color
FRAME_SCALE = 24        # exact integer upscale for the raw ticker frame


LOGO_BOX = (22 * FRAME_SCALE, 22 * FRAME_SCALE)


def fetch_smooth_logo(url: str, size: tuple[int, int]) -> Image.Image | None:
    """Fetch a logo and resize it smoothly for hi-res composition."""
    if not url:
        return None
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        logo = Image.open(io.BytesIO(response.content)).convert("RGBA")
        logo.thumbnail(size, Image.Resampling.LANCZOS)
        out = Image.new("RGBA", size, (0, 0, 0, 0))
        out.paste(logo, ((size[0] - logo.width) // 2, (size[1] - logo.height) // 2), logo)
        return out
    except Exception:
        return None


def overlay_smooth_logos(frame: Image.Image) -> Image.Image:
    """Replace the pixel-art logos in the upscaled frame with smooth originals."""
    composed = frame.copy()
    logo_y = 9 * FRAME_SCALE
    away_x = 1 * FRAME_SCALE
    home_x = (frame.width - (22 + 1) * FRAME_SCALE)

    away_logo = fetch_smooth_logo(GAME.get("away_logo", ""), LOGO_BOX)
    home_logo = fetch_smooth_logo(GAME.get("home_logo", ""), LOGO_BOX)

    if away_logo:
        composed.paste(away_logo, (away_x, logo_y), away_logo)
    if home_logo:
        composed.paste(home_logo, (home_x, logo_y), home_logo)

    return composed


def upscale_exact(img: Image.Image, scale: int) -> Image.Image:
    """Nearest-neighbour upscale that preserves the raw frame exactly."""
    scale = max(int(scale), 1)
    return img.resize((img.width * scale, img.height * scale), Image.NEAREST)


def build_fullres_frame(ticker: Image.Image) -> Image.Image:
    """Return a full-resolution copy of the ticker frame with no re-rendering."""
    return overlay_smooth_logos(upscale_exact(ticker, FRAME_SCALE))


def build_master(fullres_frame: Image.Image) -> Image.Image:
    """Compose a polished square iOS icon around the exact upscaled frame."""
    canvas = Image.new("RGBA", (MASTER, MASTER), (*BG, 255))

    # Soft shadow beneath the frame to lift it off the background.
    mask = fullres_frame.getchannel("A").filter(ImageFilter.GaussianBlur(22))
    shadow = Image.new("RGBA", fullres_frame.size, (0, 0, 0, 170))
    shadow.putalpha(mask)

    x = (MASTER - fullres_frame.width) // 2
    y = (MASTER - fullres_frame.height) // 2
    canvas.paste(shadow, (x, y + 22), shadow)

    # Build the frame border as a solid ring so the corners and bottom are fully enclosed.
    border_color = (190, 190, 192, 255)
    border_width = 14
    border_pad = 14
    border_layer = Image.new("RGBA", (MASTER, MASTER), (0, 0, 0, 0))
    border_draw = ImageDraw.Draw(border_layer)
    outer_box = (x - border_pad, y - border_pad, x + fullres_frame.width + border_pad, y + fullres_frame.height + border_pad)
    inner_box = (outer_box[0] + border_width, outer_box[1] + border_width, outer_box[2] - border_width, outer_box[3] - border_width)
    outer_radius = 32
    inner_radius = max(0, outer_radius - border_width)
    border_draw.rounded_rectangle(outer_box, radius=outer_radius, fill=border_color)
    border_draw.rounded_rectangle(inner_box, radius=inner_radius, fill=(*BG, 255))
    canvas.alpha_composite(border_layer)
    canvas.paste(fullres_frame, (x, y), fullres_frame)

    return canvas

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


def main() -> None:
    out = ROOT / "ios_icons"
    asset_dir = out / "AppIcon.appiconset"
    asset_dir.mkdir(parents=True, exist_ok=True)

    print("Rendering ticker frame with StadiumRenderer …")
    renderer = StadiumRenderer()
    ticker, card_w = renderer.render(GAME)
    ticker.save(out / "ticker_frame_raw.png")

    print("Building full-resolution ticker frame …")
    fullres_frame = build_fullres_frame(ticker)
    fullres_frame.save(out / "ticker_frame_fullres.png")
    print(f"  Ticker {ticker.width}×{ticker.height}  →  fullres {fullres_frame.width}×{fullres_frame.height}  (×{FRAME_SCALE})")

    print("Building 2048×2048 master …")
    master = build_master(fullres_frame)
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
    print(f"  Fullres:    ios_icons/ticker_frame_fullres.png")
    print(f"  Master:     ios_icons/AppIcon_master_2048.png")
    print(f"  Base 1024:  ios_icons/AppIcon_base_1024.png")
    print(f"  Icon set:   ios_icons/AppIcon.appiconset/")


if __name__ == "__main__":
    main()
