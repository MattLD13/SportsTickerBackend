"""Own every Six typeface: the bitmap glyphs and the bundled TrueType fonts.

A bitmap font draws one point for each set bit. Each glyph advances the cursor 5 pixels.
The `~` character is a 2-pixel space. Every draw call returns the drawn width.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import ImageDraw, ImageFont

# The pane glyphs: rows of three columns, and five columns for "#". The Mini uses the same rows.
PANE = {
    '0':[[1,1,1],[1,0,1],[1,0,1],[1,0,1],[1,1,1]],
    '1':[[0,1,0],[1,1,0],[0,1,0],[0,1,0],[1,1,1]],
    '2':[[1,1,1],[0,0,1],[1,1,1],[1,0,0],[1,1,1]],
    '3':[[1,1,1],[0,0,1],[0,1,1],[0,0,1],[1,1,1]],
    '4':[[1,0,1],[1,0,1],[1,1,1],[0,0,1],[0,0,1]],
    '5':[[1,1,1],[1,0,0],[1,1,1],[0,0,1],[1,1,1]],
    '6':[[1,1,1],[1,0,0],[1,1,1],[1,0,1],[1,1,1]],
    '7':[[1,1,1],[0,0,1],[0,1,0],[0,1,0],[0,1,0]],
    '8':[[1,1,1],[1,0,1],[1,1,1],[1,0,1],[1,1,1]],
    '9':[[1,1,1],[1,0,1],[1,1,1],[0,0,1],[1,1,1]],
    'A':[[0,1,0],[1,0,1],[1,1,1],[1,0,1],[1,0,1]],
    'B':[[1,1,0],[1,0,1],[1,1,0],[1,0,1],[1,1,0]],
    'C':[[0,1,1],[1,0,0],[1,0,0],[1,0,0],[0,1,1]],
    'D':[[1,1,0],[1,0,1],[1,0,1],[1,0,1],[1,1,0]],
    'E':[[1,1,1],[1,0,0],[1,1,0],[1,0,0],[1,1,1]],
    'F':[[1,1,1],[1,0,0],[1,1,0],[1,0,0],[1,0,0]],
    'G':[[0,1,1],[1,0,0],[1,0,1],[1,0,1],[0,1,1]],
    'H':[[1,0,1],[1,0,1],[1,1,1],[1,0,1],[1,0,1]],
    'I':[[1,1,1],[0,1,0],[0,1,0],[0,1,0],[1,1,1]],
    'J':[[0,0,1],[0,0,1],[0,0,1],[1,0,1],[0,1,1]],
    'K':[[1,0,1],[1,1,0],[1,0,0],[1,1,0],[1,0,1]],
    'L':[[1,0,0],[1,0,0],[1,0,0],[1,0,0],[1,1,1]],
    'M':[[1,0,1],[1,1,1],[1,0,1],[1,0,1],[1,0,1]],
    'N':[[1,0,1],[1,1,1],[1,1,1],[1,0,1],[1,0,1]],
    'O':[[0,1,0],[1,0,1],[1,0,1],[1,0,1],[0,1,0]],
    'P':[[1,1,0],[1,0,1],[1,1,0],[1,0,0],[1,0,0]],
    'Q':[[0,1,0],[1,0,1],[1,0,1],[1,1,1],[0,1,1]],
    'R':[[1,1,0],[1,0,1],[1,1,0],[1,0,1],[1,0,1]],
    'S':[[0,1,1],[1,0,0],[0,1,0],[0,0,1],[1,1,0]],
    'T':[[1,1,1],[0,1,0],[0,1,0],[0,1,0],[0,1,0]],
    'U':[[1,0,1],[1,0,1],[1,0,1],[1,0,1],[0,1,1]],
    'V':[[1,0,1],[1,0,1],[1,0,1],[1,0,1],[0,1,0]],
    'W':[[1,0,1],[1,0,1],[1,0,1],[1,1,1],[1,0,1]],
    'X':[[1,0,1],[1,0,1],[0,1,0],[1,0,1],[1,0,1]],
    'Y':[[1,0,1],[1,0,1],[0,1,0],[0,1,0],[0,1,0]],
    'Z':[[1,1,1],[0,0,1],[0,1,0],[1,0,0],[1,1,1]],
    '-':[[0,0,0],[0,0,0],[1,1,1],[0,0,0],[0,0,0]],
    ':':[[0,0,0],[0,1,0],[0,0,0],[0,1,0],[0,0,0]],
    '.':[[0,0,0],[0,0,0],[0,0,0],[0,0,0],[0,1,0]],
    "'":[[0,1,0],[0,1,0],[0,0,0],[0,0,0],[0,0,0]],
    '/':[[0,0,1],[0,0,1],[0,1,0],[1,0,0],[1,0,0]],
    '+':[[0,0,0],[0,1,0],[1,1,1],[0,1,0],[0,0,0]],
    '%':[[1,0,1],[0,0,1],[0,1,0],[1,0,0],[1,0,1]],
    '&':[[0,1,0],[1,0,1],[0,1,0],[1,0,1],[0,1,1]],
    '#':[[0,1,0,1,0],[1,1,1,1,1],[0,1,0,1,0],[1,1,1,1,1],[0,1,0,1,0]],
    '|':[[0,1,0],[0,1,0],[0,1,0],[0,1,0],[0,1,0]],
    '▲':[[0,1,0],[1,1,1],[1,1,1],[0,0,0],[0,0,0]],
    '▼':[[0,0,0],[0,0,0],[1,1,1],[1,1,1],[0,1,0]],
    '>':[[1,0,0],[0,1,0],[0,0,1],[0,1,0],[1,0,0]],
    '<':[[0,0,1],[0,1,0],[1,0,0],[0,1,0],[0,0,1]],
    '^':[[0,1,0],[1,0,1],[0,0,0],[0,0,0],[0,0,0]],
    ' ':[[0,0,0],[0,0,0],[0,0,0],[0,0,0],[0,0,0]],
}

# The five-row glyphs. Each row is a bit mask. The bits 8, 4, 2, 1, and 16 are the columns from left to right.
TINY = {
    "A": [6, 9, 15, 9, 9], "B": [14, 9, 14, 9, 14], "C": [6, 9, 8, 9, 6], "D": [14, 9, 9, 9, 14], "E": [15, 8, 14, 8, 15], "F": [15, 8, 14, 8, 8], "G": [6, 9, 11, 9, 6], "H": [9, 9, 15, 9, 9], "I": [14, 4, 4, 4, 14], "J": [7, 2, 2, 10, 4], "K": [9, 10, 12, 10, 9], "L": [8, 8, 8, 8, 15], "M": [9, 15, 15, 9, 9], "N": [9, 13, 15, 11, 9], "O": [6, 9, 9, 9, 6], "P": [14, 9, 14, 8, 8], "Q": [6, 9, 9, 10, 5], "R": [14, 9, 14, 10, 9], "S": [7, 8, 6, 1, 14], "T": [15, 4, 4, 4, 4], "U": [9, 9, 9, 9, 6], "V": [9, 9, 9, 10, 4], "W": [9, 9, 15, 15, 9], "X": [9, 9, 6, 9, 9], "Y": [9, 9, 6, 2, 2], "Z": [15, 1, 6, 8, 15],
    "0": [6, 9, 9, 9, 6], "1": [4, 12, 4, 4, 14], "2": [14, 1, 6, 8, 15], "3": [14, 1, 6, 1, 14], "4": [9, 9, 15, 1, 1], "5": [15, 8, 14, 1, 14], "6": [6, 8, 14, 9, 6], "7": [15, 1, 2, 4, 4], "8": [6, 9, 6, 9, 6], "9": [6, 9, 7, 1, 6],
    "+": [0, 4, 14, 4, 0], "-": [0, 0, 14, 0, 0], ".": [0, 0, 0, 0, 4], " ": [0, 0, 0, 0, 0], "/": [1, 2, 4, 8, 0], "'": [4, 4, 0, 0, 0], "$": [4, 15, 5, 15, 4], "%": [9, 2, 4, 8, 18], "^": [4, 10, 0, 0, 0], ":": [0, 4, 0, 4, 0], ",": [0, 0, 0, 4, 8], "!": [4, 4, 4, 0, 4], "?": [6, 1, 2, 0, 2], "@": [6, 11, 11, 8, 6], "#": [10, 15, 10, 15, 10], "&": [4, 10, 5, 10, 5], "*": [0, 10, 4, 10, 0], "=": [0, 15, 0, 15, 0], "_": [0, 0, 0, 0, 15], "<": [1, 2, 4, 2, 1], ">": [4, 2, 1, 2, 4], "[": [6, 4, 4, 4, 6], "]": [6, 2, 2, 2, 6], "\"": [10, 10, 0, 0, 0], ";": [0, 4, 0, 4, 8], "~": [0, 0, 0, 0, 0], "(": [2, 4, 4, 4, 2], ")": [4, 2, 2, 2, 4],
    "▲": [2, 7, 31, 0, 0], "▼": [31, 7, 2, 0, 0],
}

HYBRID = {key: value + [0] for key, value in TINY.items()}
HYBRID.update({"A": [6, 9, 9, 15, 9, 9], "B": [14, 9, 9, 14, 9, 14], "C": [6, 9, 8, 8, 9, 6], "D": [14, 9, 9, 9, 9, 14], "E": [15, 8, 14, 8, 8, 15], "F": [15, 8, 14, 8, 8, 8], "G": [6, 9, 8, 11, 9, 6], "H": [9, 9, 9, 15, 9, 9], "I": [14, 4, 4, 4, 4, 14], "J": [7, 2, 2, 2, 10, 4], "K": [9, 10, 12, 12, 10, 9], "L": [8, 8, 8, 8, 8, 15], "M": [9, 15, 15, 9, 9, 9], "N": [9, 13, 15, 11, 9, 9], "O": [6, 9, 9, 9, 9, 6], "P": [14, 9, 9, 14, 8, 8], "Q": [6, 9, 9, 9, 10, 5], "R": [14, 9, 9, 14, 10, 9], "S": [7, 8, 6, 1, 1, 14], "T": [15, 4, 4, 4, 4, 4], "U": [9, 9, 9, 9, 9, 6], "V": [9, 9, 9, 9, 10, 4], "W": [9, 9, 9, 15, 15, 9], "X": [9, 9, 6, 6, 9, 9], "Y": [9, 9, 9, 6, 2, 2], "Z": [15, 1, 2, 4, 8, 15]})
HYBRID.update({
    "B": [14, 9, 14, 9, 9, 14],
    "0": [6, 9, 9, 9, 9, 6], "1": [4, 12, 4, 4, 4, 14],
    "2": [14, 9, 2, 4, 8, 15], "3": [14, 9, 2, 1, 9, 14],
    "4": [9, 9, 15, 1, 1, 1], "5": [15, 8, 14, 1, 9, 14],
    "6": [6, 8, 14, 9, 9, 6], "7": [15, 1, 2, 4, 8, 8],
    "8": [6, 9, 6, 9, 9, 6], "9": [6, 9, 9, 7, 1, 6],
    "+": [0, 0, 4, 14, 4, 0], "-": [0, 0, 0, 14, 0, 0],
    ".": [0, 0, 0, 0, 0, 4], "/": [1, 2, 2, 4, 4, 8],
    ",": [0, 0, 0, 0, 4, 8], "!": [4, 4, 4, 4, 0, 4],
    "?": [6, 9, 2, 4, 0, 4], "@": [6, 9, 11, 11, 8, 6],
    "#": [10, 15, 10, 10, 15, 10], "&": [4, 10, 4, 10, 9, 6],
    "=": [0, 15, 0, 0, 15, 0], "_": [0, 0, 0, 0, 0, 15],
    "<": [1, 2, 4, 4, 2, 1], ">": [4, 2, 1, 1, 2, 4],
    "[": [6, 4, 4, 4, 4, 6], "]": [6, 2, 2, 2, 2, 6],
    ";": [0, 4, 0, 0, 4, 8], "$": [4, 15, 12, 6, 15, 4],
    "%": [9, 2, 2, 4, 4, 9], "(": [2, 4, 4, 4, 4, 2],
    ")": [4, 2, 2, 2, 2, 4], "^": [0, 0, 4, 10, 0, 0],
    ":": [0, 6, 6, 0, 6, 6],
})


# The five-row glyphs of the golf scoreboard. The bits 4, 2, and 1 are the columns.
GOLF = {
    "A": [2, 5, 7, 5, 5], "B": [6, 5, 7, 5, 6], "C": [7, 4, 4, 4, 7], "D": [6, 5, 5, 5, 6], "E": [7, 4, 7, 4, 7], "F": [7, 4, 7, 4, 4], "G": [7, 4, 5, 5, 7], "H": [5, 5, 7, 5, 5], "I": [7, 2, 2, 2, 7], "J": [1, 1, 1, 5, 2], "K": [5, 6, 4, 6, 5], "L": [4, 4, 4, 4, 7], "M": [5, 7, 7, 5, 5], "N": [5, 7, 5, 5, 5], "O": [7, 5, 5, 5, 7], "P": [7, 5, 7, 4, 4], "Q": [7, 5, 5, 7, 1], "R": [7, 5, 6, 5, 5], "S": [7, 4, 7, 1, 7], "T": [7, 2, 2, 2, 2], "U": [5, 5, 5, 5, 7], "V": [5, 5, 5, 2, 2], "W": [5, 5, 7, 7, 5], "X": [5, 5, 2, 5, 5], "Y": [5, 5, 2, 2, 2], "Z": [7, 1, 2, 4, 7], "0": [7, 5, 5, 5, 7], "1": [2, 6, 2, 2, 7], "2": [7, 1, 7, 4, 7], "3": [7, 1, 7, 1, 7], "4": [5, 5, 7, 1, 1], "5": [7, 4, 7, 1, 7], "6": [7, 4, 7, 5, 7], "7": [7, 1, 1, 1, 1], "8": [7, 5, 7, 5, 7], "9": [7, 5, 7, 1, 7], "-": [0, 0, 7, 0, 0], "+": [0, 2, 7, 2, 0], ".": [0, 0, 0, 0, 2], " ": [0, 0, 0, 0, 0],
}


def plain_text(value: object) -> str:
    """Return ASCII text that the bitmap glyphs can draw."""
    text = str(value)
    text = text.replace("Â°", "o").replace("°", "o")
    text = text.replace("â†’", "->").replace("→", "->")
    text = text.translate(str.maketrans({
        "’": "'", "‘": "'", "“": '"', "”": '"',
        "–": "-", "—": "-", "…": "...", "·": ".",
        "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE",
        "ø": "o", "Ø": "O", "ł": "l", "Ł": "L",
        "đ": "d", "Đ": "D", "ð": "d", "Ð": "D",
        "þ": "th", "Þ": "Th", "ß": "ss",
    }))
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


@dataclass(frozen=True)
class BitmapFont:
    """Draw one bitmap glyph table. A character with no glyph draws as a space."""

    glyphs: dict[str, list[int]]
    columns: tuple[int, ...]
    advance: int = 5
    # The width of "~", a narrow space. None draws "~" as an ordinary character.
    tilde: int | None = 2
    keep_lowercase_v: bool = False

    def width(self, text: object) -> int:
        return sum(self.tilde if char == "~" and self.tilde is not None else self.advance for char in plain_text(text))

    def draw(self, draw: ImageDraw.ImageDraw, x: int, y: int, text: object, color: object) -> int:
        cursor = int(x)
        y = int(y)
        space = self.glyphs[" "]
        for char in plain_text(text):
            if char == "~" and self.tilde is not None:
                cursor += self.tilde
                continue
            rows = HYBRID_SMALL_V if self.keep_lowercase_v and char == "v" else self.glyphs.get(char.upper(), space)
            for row, value in enumerate(rows):
                for column, bit in enumerate(self.columns):
                    if value & bit:
                        draw.point((cursor + column, y + row), fill=color)
            cursor += self.advance
        return cursor - int(x)


# A lowercase "v" in six-row text is a small check mark.
HYBRID_SMALL_V = [0, 0, 10, 4, 0, 0]
TINY_FONT = BitmapFont(TINY, (8, 4, 2, 1, 16))
HYBRID_FONT = BitmapFont(HYBRID, (8, 4, 2, 1), keep_lowercase_v=True)
GOLF_FONT = BitmapFont(GOLF, (4, 2, 1), advance=4, tilde=None)


def draw_tiny(draw: ImageDraw.ImageDraw, x: int | float, y: int | float, text: object, color: object) -> int:
    """Draw uppercase five-row text and return its width."""
    return TINY_FONT.draw(draw, int(x), int(y), text, color)


def draw_hybrid(draw: ImageDraw.ImageDraw, x: int | float, y: int | float, text: object, color: object) -> int:
    """Draw six-row text and return its width."""
    return HYBRID_FONT.draw(draw, int(x), int(y), text, color)


def draw_pane(draw: ImageDraw.ImageDraw, x: int, y: int, text: object, color, scale: int = 1) -> int:
    """Draw pane glyphs at a scale and return the width. Each glyph advances its width plus one column."""
    fill = (*(max(0, min(255, int(channel))) for channel in color[:3]), 255)
    cursor = x
    for char in str(text).upper():
        rows = PANE.get(char.upper(), PANE[" "])
        for row in range(5):
            for column, bit in enumerate(rows[row]):
                if bit:
                    left, top = cursor + column * scale, y + row * scale
                    draw.rectangle([left, top, left + scale - 1, top + scale - 1], fill=fill)
        cursor += (len(rows[0]) + 1) * scale
    return cursor - x


def pane_width(text: object, scale: int = 1) -> int:
    return sum(len(PANE.get(char.upper(), PANE[" "])[0]) + 1 for char in str(text)) * scale


def clean_text(value: object) -> str:
    """Return drawable text without surrounding space."""
    return plain_text(value).strip()


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
