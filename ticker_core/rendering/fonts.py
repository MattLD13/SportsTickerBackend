"""Load the complete font set once at application startup."""

from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path

from PIL import ImageFont


@dataclass(frozen=True, slots=True)
class FontSet:
    """Provide explicit fonts to every content renderer."""

    normal: ImageFont.ImageFont | ImageFont.FreeTypeFont
    medium: ImageFont.ImageFont | ImageFont.FreeTypeFont
    big: ImageFont.ImageFont | ImageFont.FreeTypeFont
    huge: ImageFont.ImageFont | ImageFont.FreeTypeFont
    clock: ImageFont.ImageFont | ImageFont.FreeTypeFont
    tiny: ImageFont.ImageFont | ImageFont.FreeTypeFont
    tiny_small: ImageFont.ImageFont | ImageFont.FreeTypeFont
    micro: ImageFont.ImageFont | ImageFont.FreeTypeFont


FONT_DIRECTORY = Path(__file__).with_name("font_assets")


@lru_cache(maxsize=64)
def load_monospace_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load the same bundled monospace typeface on every display host."""
    name = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
    return ImageFont.truetype(FONT_DIRECTORY / name, size, layout_engine=ImageFont.Layout.BASIC)


@lru_cache(maxsize=64)
def load_display_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load the same bundled display typeface on every display host."""
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(FONT_DIRECTORY / name, size, layout_engine=ImageFont.Layout.BASIC)


@lru_cache(maxsize=1)
def load_default_font_set() -> FontSet:
    """Load fonts that match the deployed controller."""
    return FontSet(
        normal=load_monospace_font(10, bold=True),
        medium=load_monospace_font(12, bold=True),
        big=load_monospace_font(14, bold=True),
        huge=load_display_font(20, bold=True),
        clock=load_display_font(28, bold=True),
        tiny=load_monospace_font(9),
        tiny_small=load_monospace_font(8),
        micro=load_monospace_font(7),
    )
