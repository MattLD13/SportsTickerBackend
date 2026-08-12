"""Load the complete font set once at application startup."""

import os
import sys
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
    nano: ImageFont.ImageFont | ImageFont.FreeTypeFont
    score_default: ImageFont.ImageFont | ImageFont.FreeTypeFont


def _font_directories() -> tuple[Path, ...]:
    """Return platform font directories in search order."""
    directories = [Path.cwd()]
    if sys.platform == "win32":
        directories.append(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            directories.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    else:
        directories.extend(
            Path(value)
            for value in (
                "/usr/share/fonts/truetype/dejavu",
                "/usr/share/fonts/truetype",
                "/usr/share/fonts",
                "/usr/local/share/fonts",
            )
        )
    return tuple(directories)


def _load_font(candidates: tuple[str, ...], size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont | None:
    """Load the first available font candidate."""
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
        for directory in _font_directories():
            try:
                return ImageFont.truetype(directory / name, size)
            except OSError:
                continue
    return None


def load_monospace_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """Load a stable cross-platform monospace font."""
    candidates = (
        ("DejaVuSansMono-Bold.ttf", "UbuntuMono-Bold.ttf", "consolab.ttf", "courbd.ttf")
        if bold
        else ("DejaVuSansMono.ttf", "UbuntuMono-Regular.ttf", "consola.ttf", "cour.ttf")
    )
    return _load_font(candidates, size) or ImageFont.load_default()


def load_display_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """Load a proportional display font with a monospace fallback."""
    candidates = (
        ("DejaVuSans-Bold.ttf", "arialbd.ttf", "ARIALBD.TTF", "Arial Bold.ttf")
        if bold
        else ("DejaVuSans.ttf", "arial.ttf", "ARIAL.TTF")
    )
    return _load_font(candidates, size) or load_monospace_font(size, bold=bold)


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
        nano=load_monospace_font(5),
        score_default=ImageFont.load_default(),
    )
