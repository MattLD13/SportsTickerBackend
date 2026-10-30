"""Draw the news banner over the left half of the panel, while the strip keeps scrolling in the right half.

A score alert takes the whole panel and stops the strip. News does not: the banner rides on each
ordinary frame. A sports item shows its kind and the clubs over two lines of text. A stock item
shows the symbol and the move over three lines of headline.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from PIL import Image, ImageDraw

from ticker.six.ui.text import draw_hybrid, draw_tiny

WIDTH, HEIGHT, BANNER = 384, 32, 192
SLIDE, HOLD_SPORTS, HOLD_STOCKS = 0.30, 6.4, 7.4
TEXT_COLUMNS = 35
BACKGROUND, RULE, EDGE = (8, 9, 12, 255), (52, 56, 66), (70, 76, 88)
NEWS_CYAN, UP, DOWN, NEUTRAL = (70, 175, 255), (60, 205, 95), (235, 75, 75), (139, 147, 163)
KINDS = {
    "TRADE": ((255, 176, 20), "TRADE"), "MAJOR": ((255, 145, 35), "MAJOR"), "BLOCKBUSTER": ((245, 70, 170), "BLOCK"),
    "SIGNING": ((60, 205, 95), "SIGN"), "EXTENSION": ((170, 120, 255), "EXTEND"), "INJURY": ((235, 75, 75), "INJURY"),
    "WAIVER": ((70, 190, 255), "WAIVER"), "DFA": ((255, 95, 55), "DFA"), "RELEASE": ((170, 180, 195), "RELEASE"),
    "OPTION": ((155, 115, 245), "OPTION"), "RECALL": ((55, 210, 150), "RECALL"), "ACTIVATED": ((50, 200, 205), "ACTIVE"),
    "SUSPENSION": ((235, 55, 75), "SUSPEND"), "RETIREMENT": ((225, 225, 235), "RETIRE"), "NO_TENDER": ((220, 135, 45), "NON-TEND"),
}


def banner_duration(item: Mapping[str, Any] | None) -> float:
    """Return the seconds from the start of the slide in to the end of the slide out."""
    return SLIDE + (HOLD_STOCKS if (item or {}).get("domain") == "stocks" else HOLD_SPORTS) + SLIDE


class NewsBanner:
    def __init__(self) -> None:
        # One banner shows at a time, so one cached image is enough.
        self._key: str | None = None
        self._image: Image.Image | None = None

    def banner(self, item: Mapping[str, Any]) -> Image.Image:
        item = dict(item)
        key = json.dumps(item, sort_keys=True, separators=(",", ":"), default=str)
        if key != self._key or self._image is None:
            self._key = key
            self._image = _stock_banner(item) if str(item.get("domain")) == "stocks" else _sports_banner(item)
        return self._image

    def apply(self, frame: Image.Image, item: Mapping[str, Any], elapsed: float) -> Image.Image:
        """Lay the banner over the left half of one frame. It slides in from the left and out to the left."""
        total = banner_duration(item)
        if elapsed < SLIDE:
            travel = int(BANNER * (1 - _ease(elapsed / SLIDE)))
        elif elapsed > total - SLIDE:
            travel = int(BANNER * _ease((elapsed - (total - SLIDE)) / SLIDE))
        else:
            travel = 0
        out = frame.convert("RGBA")
        out.alpha_composite(self.banner(item), (-travel, 0))
        ImageDraw.Draw(out).line([(BANNER - travel, 0), (BANNER - travel, HEIGHT)], fill=EDGE)
        return out.convert("RGB")


def _sports_banner(item: Mapping[str, Any]) -> Image.Image:
    """Draw the kind, the clubs (from, an arrow, and to, for a trade), and two lines of text."""
    image = Image.new("RGBA", (BANNER, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image, "RGBA")
    from_color, to_color = _readable(_hex(item.get("from_color"))), _readable(_hex(item.get("to_color")))
    accent, kind = _kind(item)
    draw.rectangle([0, 0, 2, HEIGHT], fill=accent)
    _gradient(draw, _header_colors(item, accent))
    draw_tiny(draw, 7, 3, kind, (255, 255, 255))
    x = 12 + len(kind) * 5
    from_abbr, to_abbr = str(item.get("from_abbr", ""))[:4], str(item.get("to_abbr", ""))[:4]
    if str(item.get("kind") or "").strip().upper() == "TRADE" and from_abbr and to_abbr:
        x += draw_hybrid(draw, x, 2, from_abbr, _team_text(item, "from", from_color))
        _arrow(draw, x + 4, 4, 13, from_color, to_color)
        x += 23
    draw_hybrid(draw, x, 2, to_abbr or from_abbr, _team_text(item, "to" if to_abbr else "from", to_color))
    draw.line([(4, 11), (BANNER, 11)], fill=RULE)
    lines = wrap_lines(item.get("text"), max_lines=2)
    if len(lines) == 1:
        # One short line centers in the body.
        draw_hybrid(draw, 7, 20, lines[0], (255, 255, 255))
    else:
        draw_hybrid(draw, 7, 15, lines[0], (255, 255, 255))
        draw_hybrid(draw, 7, 24, lines[1], (206, 211, 222))
    return image


def _stock_banner(item: Mapping[str, Any]) -> Image.Image:
    """Draw "NEWS", the symbol, the move in percent, and three lines of headline."""
    image = Image.new("RGBA", (BANNER, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image, "RGBA")
    try:
        move = float(item.get("pct") or 0.0)
    except (TypeError, ValueError):
        move = 0.0
    accent = UP if move >= 0 else DOWN
    draw.rectangle([0, 0, 2, HEIGHT], fill=accent)
    draw.rectangle([4, 0, BANNER, 9], fill=(22, 24, 30))
    draw.rectangle([6, 1, 34, 8], fill=NEWS_CYAN)
    draw_tiny(draw, 8, 2, "NEWS", (8, 10, 14))
    draw_hybrid(draw, 40, 1, str(item.get("to_abbr", ""))[:6], (255, 255, 255))
    if item.get("pct") is not None:
        label = f"{move:+.1f}%"
        draw_tiny(draw, BANNER - 5 - len(label) * 5, 2, label, accent)
    draw.line([(4, 10), (BANNER, 10)], fill=RULE)
    # Rows 12 to 31 hold three 6-pixel lines with one row between them.
    for index, line in enumerate(wrap_lines(item.get("text"), max_lines=3)):
        draw_hybrid(draw, 7, 12 + index * 7, line, (255, 255, 255) if index == 0 else (203, 209, 220))
    return image


def wrap_lines(text: object, columns: int = TEXT_COLUMNS, max_lines: int = 2) -> list[str]:
    """Break text on words into at most `max_lines` lines. Text that does not fit ends the last line with a period."""
    lines = [""]
    for word in str(text or "").upper().split():
        candidate = f"{lines[-1]} {word}".strip()
        if len(candidate) <= columns:
            lines[-1] = candidate
        elif len(lines) < max_lines:
            lines.append(word)
        else:
            lines[-1] = lines[-1][:columns - 1] + "."
            break
    return lines


def _kind(item: Mapping[str, Any]) -> tuple[tuple[int, int, int], str]:
    """Return the accent color and the short label of the news kind. An impact tier takes priority."""
    tier = str(item.get("impact_tier") or "").strip().upper()
    kind = tier if tier in KINDS else str(item.get("kind") or "NEWS").strip().upper()
    return KINDS.get(kind, (NEUTRAL, kind[:6]))


def _header_colors(item: Mapping[str, Any], accent) -> list[tuple[int, int, int]]:
    """Return the dimmed team colors of the header gradient. A trade runs from the old club to the new club."""
    sides = ("from", "to") if str(item.get("kind") or "").strip().upper() == "TRADE" else ("to", "from")
    colors = [_hex(item[f"{side}_{suffix}"]) for side in sides for suffix in ("color", "alt_color") if item.get(f"{side}_{suffix}")]
    colors = colors or [accent]
    if len(colors) == 1:
        colors.append(accent)
    colors = [_dim(color, 0.38) for color in colors[:4]]
    if len(colors) == 2:
        colors.insert(1, _dim(accent, 0.30))
    return colors


def _gradient(draw: ImageDraw.ImageDraw, colors: list[tuple[int, int, int]], left: int = 0, right: int = BANNER - 1) -> None:
    span, segments = max(1, right - left), max(1, len(colors) - 1)
    for x in range(left, right + 1):
        position = (x - left) / span * segments
        segment = min(segments - 1, int(position))
        blend = position - segment
        start, end = colors[segment], colors[segment + 1]
        draw.line([(x, 0), (x, 10)], fill=tuple(int(start[channel] + (end[channel] - start[channel]) * blend) for channel in range(3)))


def _arrow(draw: ImageDraw.ImageDraw, x: int, y: int, length: int, start, end) -> None:
    """Draw a 2-pixel shaft that fades from the old club color to the new club color, with a head."""
    for index in range(length):
        t = index / max(1, length - 1)
        shade = tuple(int(start[channel] + (end[channel] - start[channel]) * t) for channel in range(3))
        draw.point((x + index, y), fill=shade)
        draw.point((x + index, y + 1), fill=shade)
    tip = x + length
    draw.polygon([(tip, y - 2), (tip, y + 3), (tip + 3, y + 1)], fill=end)


def _team_text(item: Mapping[str, Any], side: str, fallback) -> tuple[int, int, int]:
    """Return the first team color that reads on black without a filled chip, or white."""
    for color in (_hex(item.get(f"{side}_color"), fallback), _hex(item.get(f"{side}_alt_color"), (255, 255, 255))):
        if _luminance(color) >= 130:
            return color
    return (255, 255, 255)


def _readable(color) -> tuple[int, int, int]:
    """Scale a dark club color up until it reads on the black banner. Scaling keeps navy navy."""
    luminance = _luminance(color)
    if luminance >= 95:
        return color
    return tuple(min(255, int(channel * 95.0 / max(1.0, luminance))) for channel in color)


def _dim(color, factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(channel * factor))) for channel in color)


def _hex(value: object, fallback=NEUTRAL) -> tuple[int, int, int]:
    text = str(value).strip().lstrip("#")
    if len(text) == 6:
        try:
            return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))
        except ValueError:
            pass
    return fallback


def _luminance(color) -> float:
    return 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]


def _ease(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return 1 - (1 - value) ** 3
