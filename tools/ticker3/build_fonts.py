"""Build the 1-bit glyph tables of the Ticker 3 player from the bundled DejaVu fonts.

Each player, in Python or C++, draws text from the same table, so a frame is
the same on every device. Run: python tools/ticker3/build_fonts.py
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "ticker_core" / "rendering" / "font_assets"
OUTPUT = ROOT / "ticker3" / "player" / "fonts.json"
# The sizes match the deployed Six font set in ticker_core/rendering/fonts.py.
FONTS = {
    "micro": ("DejaVuSansMono.ttf", 7), "tiny": ("DejaVuSansMono.ttf", 9), "small": ("DejaVuSansMono-Bold.ttf", 10),
    "medium": ("DejaVuSansMono-Bold.ttf", 12), "big": ("DejaVuSansMono-Bold.ttf", 14),
    "huge": ("DejaVuSans-Bold.ttf", 20), "clock": ("DejaVuSans-Bold.ttf", 28),
}
CHARACTERS = [chr(code) for code in range(32, 127)] + [chr(code) for code in range(0xA0, 0x100)]
# The line box spans these characters. Taller marks, such as accents on capitals, are clipped.
LINE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789°()/:-"


def build_font(file: str, size: int) -> dict:
    font = ImageFont.truetype(str(SOURCE / file), size, layout_engine=ImageFont.Layout.BASIC)
    ascent, descent = font.getmetrics()
    canvas = (size * 2, ascent + descent + 4)
    rendered = {}
    for character in CHARACTERS:
        image = Image.new("1", canvas, 0)
        draw = ImageDraw.Draw(image)
        draw.fontmode = "1"
        draw.text((0, 2), character, font=font, fill=1)
        rendered[character] = (image, round(font.getlength(character)))
    rows = [y for character in LINE for y in range(canvas[1]) if any(rendered[character][0].getpixel((x, y)) for x in range(canvas[0]))]
    top, bottom = min(rows), max(rows)
    glyphs = {}
    for character, (image, advance) in rendered.items():
        width = max(advance, max((x + 1 for x in range(canvas[0]) for y in range(top, bottom + 1) if image.getpixel((x, y))), default=0))
        bits = []
        for y in range(top, bottom + 1):
            row = 0
            for x in range(width):
                if image.getpixel((x, y)):
                    row |= 1 << x
            bits.append(row)
        glyphs[character] = {"advance": advance, "width": width, "rows": [f"{row:x}" for row in bits]}
    return {"height": bottom - top + 1, "glyphs": glyphs}


def main() -> None:
    table = {name: build_font(file, size) for name, (file, size) in FONTS.items()}
    OUTPUT.write_text(json.dumps(table, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    for name, font in table.items():
        print(f"{name:7} height {font['height']:2} digit advance {font['glyphs']['0']['advance']}")
    print(f"{OUTPUT.relative_to(ROOT)}: {OUTPUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
