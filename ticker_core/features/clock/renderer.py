"""Renderer for the full-panel clock feature."""

from datetime import datetime
from typing import TypeAlias

from PIL import Image, ImageDraw, ImageFont

from ...context import RenderContext
from .scene import ClockScene


PANEL_WIDTH = 384
PANEL_HEIGHT = 32
DATE_COLOR = (200, 200, 200)
TIME_COLOR = (255, 255, 255)
RAIL_COLOR = (30, 30, 30)
PROGRESS_COLOR = (0, 200, 255)
Font: TypeAlias = ImageFont.ImageFont | ImageFont.FreeTypeFont


class ClockRenderer:
    """Draw clock scenes with caller-owned font objects."""

    def __init__(self, tiny_font: Font, clock_font: Font) -> None:
        self._tiny_font = tiny_font
        self._clock_font = clock_font

    def render(self, context: RenderContext, scene: ClockScene) -> Image.Image:
        """Render a 384 by 32 RGBA clock frame for the context time."""
        del scene
        return self.render_at(context.now)

    def render_at(self, now: datetime) -> Image.Image:
        """Render a clock frame for one injected local time."""
        image = Image.new("RGBA", (PANEL_WIDTH, PANEL_HEIGHT), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)

        date_text = now.strftime("%A %B %d").upper()
        date_width = draw.textlength(date_text, font=self._tiny_font)
        draw.text(
            ((PANEL_WIDTH - date_width) / 2, -1),
            date_text,
            font=self._tiny_font,
            fill=DATE_COLOR,
        )

        time_text = now.strftime("%I:%M:%S").lstrip("0")
        time_width = draw.textlength(time_text, font=self._clock_font)
        draw.text(
            ((PANEL_WIDTH - time_width) / 2, 4),
            time_text,
            font=self._clock_font,
            fill=TIME_COLOR,
        )

        total_seconds = now.second + (now.microsecond / 1_000_000.0)
        progress_width = int((total_seconds / 60.0) * PANEL_WIDTH)
        draw.rectangle((0, 31, PANEL_WIDTH, 31), fill=RAIL_COLOR)
        draw.rectangle((0, 31, progress_width, 31), fill=PROGRESS_COLOR)
        return image
