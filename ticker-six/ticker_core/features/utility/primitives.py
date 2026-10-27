"""Provide small deterministic drawing helpers."""

from __future__ import annotations

from PIL import ImageDraw, ImageFont

from ticker_core.rendering.pixels import draw_hybrid_text, draw_tiny_text, normalize_special_chars


PANEL_W = 384
PANEL_H = 32


def tiny_text(
    draw: ImageDraw.ImageDraw,
    x: int | float,
    y: int | float,
    text: object,
    color: object,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
) -> None:
    """Draw text with the deployed five-pixel glyphs."""
    del font
    draw_tiny_text(draw, int(x), int(y), text, color)


def hybrid_text(
    draw: ImageDraw.ImageDraw,
    x: int | float,
    y: int | float,
    text: object,
    color: object,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
) -> None:
    """Draw text with the deployed six-pixel glyphs."""
    del font
    draw_hybrid_text(draw, int(x), int(y), text, color)


def normal_text(value: object) -> str:
    """Return display-safe text without controller state."""
    return normalize_special_chars(str(value)).strip()
