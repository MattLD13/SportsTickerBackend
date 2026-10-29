"""Provide small deterministic drawing helpers."""

from __future__ import annotations

from PIL import ImageDraw, ImageFont

from ticker_core.ui.text import draw_hybrid, draw_tiny, plain_text


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
    draw_tiny(draw, int(x), int(y), text, color)


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
    draw_hybrid(draw, int(x), int(y), text, color)


def normal_text(value: object) -> str:
    """Return display-safe text without controller state."""
    return plain_text(str(value)).strip()
