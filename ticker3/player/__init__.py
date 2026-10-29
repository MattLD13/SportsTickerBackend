"""The reference template player. It draws a screen from one template block and its values.

The device players must draw the same pixels. This player has no I/O: the
caller gives it a logo source, the time, and the screens.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image

from ticker3.contract.templates import COLOR, PLACEHOLDER, fill, shown, text_of

HERE = Path(__file__).resolve().parent
WHITE = (255, 255, 255)
Logos = Callable[[str, int], "Image.Image | None"]


@lru_cache(maxsize=1)
def fonts() -> dict[str, Any]:
    table = json.loads((HERE / "fonts.json").read_text(encoding="utf-8"))
    for font in table.values():
        for glyph in font["glyphs"].values():
            glyph["bits"] = [int(row, 16) for row in glyph["rows"]]
    return table


@lru_cache(maxsize=1)
def icons() -> dict[str, list[list[tuple[int, int, int] | None]]]:
    data = json.loads((HERE / "icons.json").read_text(encoding="utf-8"))
    palette = {key: _rgb(value) for key, value in data["palette"].items()}
    return {name: [[palette.get(character) for character in row] for row in rows] for name, rows in data["icons"].items()}


def text_width(font: str, text: str) -> int:
    glyphs = fonts()[font]["glyphs"]
    return sum(glyphs.get(character, glyphs["?"])["advance"] for character in text)


def text_extent(part: dict[str, Any], values: dict[str, Any], *, now: float) -> tuple[int, int] | None:
    """Return the left and right edges of a text or time part, or None if it draws nothing."""
    if part["part"] == "text":
        text = fill(part["value"], values)
    elif part["part"] == "time":
        epoch = fill(part["value"], values)
        text = _time_text(datetime.fromtimestamp(float(epoch), _zone(fill(part["tz"], values))), part["format"]) if epoch else None
    else:
        return None
    if not text:
        return None
    width = text_width(part["font"], text)
    if part.get("max_width"):
        width = min(width, part["max_width"])
    x = part["at"][0]
    align = part.get("align", "left")
    left = x - width // 2 if align == "center" else x - width if align == "right" else x
    return left, left + width


def draw_screen(block: dict[str, Any], values: dict[str, Any], *, now: float, logos: Logos | None = None) -> Image.Image:
    """Draw one screen into an image of the block box size."""
    image = Image.new("RGB", tuple(block["box"]), (0, 0, 0))
    for part in block["parts"]:
        if shown(part.get("show_when"), values):
            _draw_part(image, part, values, now, logos)
    return image


def draw_frame(panel: str, blocks: list[tuple[dict[str, Any], dict[str, Any]]], *, now: float, offset: int = 0,
               logos: Logos | None = None) -> Image.Image:
    """Draw one panel frame. Scroll screens join into one strip that starts `offset` pixels to the left."""
    width, height = (int(number) for number in panel[1:].split("h"))
    frame = Image.new("RGB", (width, height), (0, 0, 0))
    if not blocks:
        return frame
    if blocks[0][0]["flow"] == "page":
        frame.paste(draw_screen(*blocks[0], now=now, logos=logos), (0, 0))
        return frame
    x = -offset
    for block, values in blocks:
        if block["flow"] != "scroll" or x >= width:
            break
        if x + block["box"][0] > 0:
            frame.paste(draw_screen(block, values, now=now, logos=logos), (x, 0))
        x += block["box"][0]
    return frame


def _draw_part(image: Image.Image, part: dict[str, Any], values: dict[str, Any], now: float, logos: Logos | None) -> None:
    x, y = part["at"]
    kind = part["part"]
    color = _color(part.get("color"), values)
    if kind == "text":
        text = fill(part["value"], values)
        if text:
            _text(image, part["font"], text, x, y, color, part.get("align", "left"), part.get("max_width"))
    elif kind == "rect":
        width, height = part["size"]
        image.paste(color, (x, y, min(image.width, x + width), min(image.height, y + height)))
    elif kind == "logo":
        source = fill(part["value"], values)
        logo = logos(source, part["size"]) if source and logos else None
        if logo is not None:
            image.paste(logo, (x, y), logo if logo.mode == "RGBA" else None)
    elif kind == "icon":
        name = fill(part["value"], values)
        bitmap = icons().get(name or "")
        if bitmap:
            for row, pixels in enumerate(bitmap):
                for column, pixel in enumerate(pixels):
                    if pixel is not None:
                        _put(image, x + column, y + row, color if part.get("color") else pixel)
    elif kind == "bases":
        _bases(image, fill(part["value"], values) or "000", x, y, part.get("size", 3), part.get("color"), values)
    elif kind == "dots":
        _dots(image, fill(part["value"], values) or "", x, y, part.get("spacing", 4))
    elif kind in ("clock", "time"):
        zone = _zone(fill(part["tz"], values))
        if kind == "clock":
            moment = datetime.fromtimestamp(now, zone)
            text = moment.strftime("%H:%M") if fill(part["format"], values) == "24h" else f"{moment.hour % 12 or 12}:{moment:%M}"
        else:
            epoch = fill(part["value"], values)
            if not epoch:
                return
            text = _time_text(datetime.fromtimestamp(float(epoch), zone), part["format"])
        _text(image, part["font"], text, x, y, color, part.get("align", "left"), None)


def _text(image: Image.Image, font_name: str, text: str, x: int, y: int, color, align: str, max_width: int | None) -> None:
    font = fonts()[font_name]
    width = text_width(font_name, text)
    if max_width is not None and width > max_width:
        while text and text_width(font_name, text) > max_width:
            text = text[:-1]
        width = text_width(font_name, text)
    left = x - width // 2 if align == "center" else x - width if align == "right" else x
    limit = left + (max_width if max_width is not None else image.width)
    for character in text:
        glyph = font["glyphs"].get(character, font["glyphs"]["?"])
        for row, bits in enumerate(glyph["bits"]):
            column = 0
            while bits:
                if bits & 1 and left + column < limit:
                    _put(image, left + column, y + row, color)
                bits >>= 1
                column += 1
        left += glyph["advance"]


def _bases(image: Image.Image, occupied: str, x: int, y: int, size: int, color_value: str | None, values) -> None:
    """Draw second base on top, first base on the right, and third base on the left."""
    filled = _color(color_value, values) if color_value else (255, 208, 0)
    empty = (90, 90, 90)
    spots = {0: (2 * size, size), 1: (size, 0), 2: (0, size)}
    for index, (dx, dy) in spots.items():
        on = len(occupied) > index and occupied[index] == "1"
        center_x, center_y = x + dx + size, y + dy
        for row in range(-size + 1, size):
            reach = size - 1 - abs(row)
            for column in range(-reach, reach + 1):
                edge = abs(column) == reach
                if on or edge:
                    _put(image, center_x + column, center_y + row, filled if on else empty)


def _dots(image: Image.Image, marks: str, x: int, y: int, spacing: int) -> None:
    colors = {"x": (64, 255, 64), "o": (255, 48, 48), "-": (90, 90, 90)}
    for index, mark in enumerate(marks):
        color = colors.get(mark)
        if color:
            for row in range(2):
                for column in range(2):
                    _put(image, x + index * spacing + column, y + row, color)


def _time_text(moment: datetime, style: str) -> str:
    clock = f"{moment.hour % 12 or 12}:{moment:%M}"
    half = "AM" if moment.hour < 12 else "PM"
    if style == "time":
        return f"{clock} {half}"
    if style == "weekday_time":
        return f"{moment:%a}".upper() + f" {clock}{half[0]}"
    if style == "weekday":
        return f"{moment:%a}".upper()
    return f"{moment:%b} {moment.day}".upper()


def _zone(name: str | None):
    try:
        return ZoneInfo(name) if name else timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def _color(value: str | None, values: dict[str, Any]) -> tuple[int, int, int]:
    if not value:
        return WHITE
    if PLACEHOLDER.fullmatch(value):
        value = text_of(values.get(value[1:-1])) or ""
    return _rgb(value) if COLOR.match(value) else WHITE


def _rgb(value: str) -> tuple[int, int, int]:
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def _put(image: Image.Image, x: int, y: int, color) -> None:
    if 0 <= x < image.width and 0 <= y < image.height:
        image.putpixel((x, y), color)
