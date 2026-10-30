"""Draw the sports campaign parody card that sometimes rides in the sports strip."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PIL import Image, ImageDraw

from ..text import draw_hybrid, draw_tiny, plain_text

HEIGHT, MIN_WIDTH, MAX_WIDTH = 32, 112, 160


def is_ad(item: Mapping[str, Any]) -> bool:
    return str(item.get("type") or item.get("kind") or "").strip().lower() == "fan_duel_joke_ad"


def _rgb(value: object, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    text = str(value or "").strip().lstrip("#")
    if len(text) == 6:
        try:
            return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))
        except ValueError:
            pass
    return fallback


def ad_card(item: Mapping[str, Any], logos) -> Image.Image:
    """Draw the accent bar, the logo plate, the headline, the tagline, and the detail line."""
    lines = item.get("headline", "FANDUEL"), item.get("tagline", ""), item.get("detail", "PARODY")
    width = max(MIN_WIDTH, min(MAX_WIDTH, 32 + max(len(plain_text(line)) * 5 for line in lines) + 4))
    accent = _rgb(item.get("accent"), (24, 210, 110))
    image = Image.new("RGB", (width, HEIGHT), _rgb(item.get("background"), (16, 28, 42)))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width - 1, HEIGHT - 1), outline=tuple(int(channel * 0.65) for channel in accent))
    draw.rectangle((0, 0, 3, HEIGHT - 1), fill=accent)
    plate = str(item.get("logo_plate") or "").strip()
    if plate:
        draw.rectangle((7, 5, 28, 26), fill=_rgb(plate, (255, 255, 255)))
    logo = logos.get(str(item.get("logo") or ""), (18, 18))
    if logo is not None:
        image.paste(logo, (9, 7), logo)
    else:
        draw.ellipse((9, 8, 26, 25), outline=accent, width=2)
        draw_hybrid(draw, 15, 13, "S", accent)
    draw_hybrid(draw, 32, 3, item.get("headline", "FANDUEL"), (255, 255, 255))
    draw_tiny(draw, 32, 13, item.get("tagline", "MAKE EVERY MOMENT MORE"), accent)
    draw_tiny(draw, 32, 22, item.get("detail", "PARODY"), (150, 170, 185))
    return image
