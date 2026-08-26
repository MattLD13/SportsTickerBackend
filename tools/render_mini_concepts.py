from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw


W, H, SCALE = 64, 32, 10
BG = (5, 10, 20)
WHITE = (235, 242, 250)
MUTED = (100, 130, 160)
CYAN = (40, 210, 240)
BLUE = (70, 150, 255)
ORANGE = (255, 150, 35)
GREEN = (75, 235, 110)
RED = (245, 70, 80)
YELLOW = (255, 220, 75)
MAGENTA = (225, 80, 220)

FONT = {
    "0": ("111", "101", "101", "101", "111"), "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"), "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"), "7": ("111", "001", "001", "001", "001"),
    "8": ("111", "101", "111", "101", "111"), "9": ("111", "101", "111", "001", "111"),
    "A": ("010", "101", "111", "101", "101"), "B": ("110", "101", "110", "101", "110"),
    "C": ("011", "100", "100", "100", "011"), "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"), "F": ("111", "100", "110", "100", "100"),
    "G": ("011", "100", "101", "101", "011"), "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"), "J": ("001", "001", "001", "101", "010"),
    "K": ("101", "110", "100", "110", "101"), "L": ("100", "100", "100", "100", "111"),
    "M": ("101", "111", "101", "101", "101"), "N": ("101", "111", "111", "101", "101"),
    "O": ("010", "101", "101", "101", "010"), "P": ("110", "101", "110", "100", "100"),
    "Q": ("010", "101", "101", "111", "011"), "R": ("110", "101", "110", "101", "101"),
    "S": ("011", "100", "010", "001", "110"), "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "011"), "V": ("101", "101", "101", "101", "010"),
    "W": ("101", "101", "101", "111", "101"), "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"), "Z": ("111", "001", "010", "100", "111"),
    ">": ("100", "010", "001", "010", "100"), "-": ("000", "000", "111", "000", "000"),
    ":": ("000", "010", "000", "010", "000"), "/": ("001", "001", "010", "100", "100"),
    " ": ("000", "000", "000", "000", "000"),
}


def text(draw: ImageDraw.ImageDraw, value: str, x: int, y: int, color: tuple[int, int, int], scale: int = 1) -> None:
    for character in value.upper():
        glyph = FONT.get(character, FONT[" "])
        for row, bits in enumerate(glyph):
            for column, bit in enumerate(bits):
                if bit == "1":
                    draw.rectangle((x + column * scale, y + row * scale, x + (column + 1) * scale - 1, y + (row + 1) * scale - 1), fill=color)
        x += 4 * scale


def frame(accent: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", (W, H), BG)
    ImageDraw.Draw(image).line((0, 0, W - 1, 0), fill=accent)
    return image


def sports() -> Image.Image:
    image = frame(CYAN)
    draw = ImageDraw.Draw(image)
    draw.line((0, 7, 63, 7), fill=(45, 75, 110))
    draw.line((0, 26, 63, 26), fill=(45, 75, 110))
    text(draw, "NFL", 1, 1, CYAN)
    text(draw, "LIVE", 45, 1, MUTED)
    text(draw, "DAL", 2, 10, ORANGE)
    text(draw, "17", 45, 9, WHITE, 2)
    text(draw, "NYG", 2, 19, BLUE)
    text(draw, "14", 45, 18, WHITE, 2)
    text(draw, "Q2 5:12", 2, 28, YELLOW)
    return image


def weather() -> Image.Image:
    image = frame(BLUE)
    draw = ImageDraw.Draw(image)
    draw.line((0, 7, 63, 7), fill=(25, 70, 130))
    text(draw, "WX NYC", 1, 1, CYAN)
    text(draw, "77", 1, 10, YELLOW, 2)
    text(draw, "F", 19, 13, YELLOW)
    text(draw, "PARTLY", 27, 10, WHITE)
    text(draw, "H58 W9", 27, 19, BLUE)
    text(draw, "TUE 82/68", 1, 28, MUTED)
    return image


def music() -> Image.Image:
    image = frame(MAGENTA)
    draw = ImageDraw.Draw(image)
    draw.ellipse((3, 10, 20, 27), outline=MAGENTA, width=2)
    draw.ellipse((9, 16, 14, 21), fill=GREEN)
    text(draw, "MUSIC", 1, 1, MAGENTA)
    text(draw, "MIDNIGHT", 23, 9, WHITE)
    text(draw, "THE WEEKND", 23, 18, MUTED)
    draw.line((0, 31, 44, 31), fill=GREEN)
    return image


def flight() -> Image.Image:
    image = frame(ORANGE)
    draw = ImageDraw.Draw(image)
    text(draw, "UA 188", 1, 1, ORANGE)
    text(draw, "ENROUTE", 37, 1, GREEN)
    text(draw, "LAX>EWR", 2, 10, BLUE)
    text(draw, "ETA 1:45", 2, 19, WHITE)
    text(draw, "34KFT 540", 2, 28, MUTED)
    draw.rectangle((45, 12, 60, 15), fill=(30, 65, 55))
    draw.rectangle((45, 12, 55, 15), fill=GREEN)
    return image


def airports() -> Image.Image:
    image = frame(GREEN)
    draw = ImageDraw.Draw(image)
    text(draw, "EWR", 1, 1, CYAN)
    text(draw, "IN", 21, 1, GREEN)
    text(draw, "OUT", 45, 1, RED)
    draw.line((31, 7, 31, 31), fill=(45, 75, 110))
    text(draw, "UA188 LAX", 1, 9, WHITE)
    text(draw, "DL402 ATL", 1, 16, MUTED)
    text(draw, "UA205 SFO", 34, 9, WHITE)
    text(draw, "B6117 MCO", 34, 16, MUTED)
    text(draw, "76F", 1, 26, YELLOW)
    return image


def clock() -> Image.Image:
    image = frame(CYAN)
    draw = ImageDraw.Draw(image)
    text(draw, "MON AUG 24", 1, 1, MUTED)
    text(draw, "8:42", 6, 10, WHITE, 2)
    text(draw, "PM", 47, 16, CYAN)
    draw.line((0, 31, 63, 31), fill=(25, 65, 85))
    draw.line((0, 31, 42, 31), fill=CYAN)
    return image


def main() -> None:
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("previews/mini_ui_concepts.png")
    concepts = [("SPORTS", sports()), ("WEATHER", weather()), ("MUSIC", music()), ("FLIGHTS", flight()), ("AIRPORTS", airports()), ("CLOCK", clock())]
    sheet = Image.new("RGB", (W * SCALE * 2 + 40, (H * SCALE + 28) * 3 + 20), (24, 28, 38))
    draw = ImageDraw.Draw(sheet)
    for index, (label, image) in enumerate(concepts):
        column, row = index % 2, index // 2
        x = 10 + column * (W * SCALE + 20)
        y = 10 + row * (H * SCALE + 28)
        sheet.paste(image.resize((W * SCALE, H * SCALE), Image.Resampling.NEAREST), (x, y))
        draw.text((x, y + H * SCALE + 5), label, fill=(210, 220, 235))
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination)
    print(destination)


if __name__ == "__main__":
    main()
