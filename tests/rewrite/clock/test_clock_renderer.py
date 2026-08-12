"""Pixel parity tests for the rewritten full-panel clock."""

from datetime import datetime

import pytest
from PIL import Image, ImageDraw

from ticker_controller.fonts import load_display_font, load_monospace_font
from ticker_core import RenderContext
from ticker_core.features.clock import ClockRenderer, ClockScene


PANEL_WIDTH = 384
PANEL_HEIGHT = 32


def legacy_clock_frame(now: datetime, tiny_font, clock_font) -> Image.Image:
    """Recreate the legacy clock algorithm without controller state."""
    image = Image.new("RGBA", (PANEL_WIDTH, PANEL_HEIGHT), (0, 0, 0, 255))
    draw = ImageDraw.Draw(image)
    date_text = now.strftime("%A %B %d").upper()
    date_width = draw.textlength(date_text, font=tiny_font)
    draw.text(
        ((PANEL_WIDTH - date_width) / 2, -1),
        date_text,
        font=tiny_font,
        fill=(200, 200, 200),
    )
    time_text = now.strftime("%I:%M:%S").lstrip("0")
    time_width = draw.textlength(time_text, font=clock_font)
    draw.text(
        ((PANEL_WIDTH - time_width) / 2, 4),
        time_text,
        font=clock_font,
        fill=(255, 255, 255),
    )
    total_seconds = now.second + (now.microsecond / 1_000_000.0)
    progress_width = int((total_seconds / 60.0) * PANEL_WIDTH)
    draw.rectangle((0, 31, PANEL_WIDTH, 31), fill=(30, 30, 30))
    draw.rectangle((0, 31, progress_width, 31), fill=(0, 200, 255))
    return image


@pytest.fixture(scope="module")
def clock_fonts():
    """Load the same font settings as the legacy controller."""
    return load_monospace_font(9), load_display_font(28, bold=True)


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 1, 1, 0, 0, 0),
        datetime(2026, 7, 4, 12, 30, 0, 500_000),
        datetime(2026, 12, 31, 23, 59, 59, 999_999),
    ],
)
def test_clock_renderer_matches_legacy_pixels(now, clock_fonts):
    """The rewrite keeps every legacy clock pixel for fixed input."""
    tiny_font, clock_font = clock_fonts
    actual = ClockRenderer(tiny_font, clock_font).render(RenderContext(now), ClockScene())
    expected = legacy_clock_frame(now, tiny_font, clock_font)

    assert actual.mode == "RGBA"
    assert actual.size == (PANEL_WIDTH, PANEL_HEIGHT)
    assert actual.tobytes() == expected.tobytes()


def test_clock_renderer_fills_minute_progress_inclusive(clock_fonts):
    """The progress line retains the legacy inclusive rectangle endpoint."""
    tiny_font, clock_font = clock_fonts
    image = ClockRenderer(tiny_font, clock_font).render(
        RenderContext(datetime(2026, 1, 1, 9, 0, 30)), ClockScene()
    )

    assert image.getpixel((192, 31)) == (0, 200, 255, 255)
    assert image.getpixel((193, 31)) == (30, 30, 30, 255)


def test_clock_scene_kind_cannot_be_reconfigured():
    """The registry key remains part of the feature contract."""
    with pytest.raises(TypeError):
        ClockScene(kind="other")
