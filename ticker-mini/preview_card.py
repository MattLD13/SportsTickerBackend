from pathlib import Path

from PIL import Image, ImageDraw


SCALE = 8
WIDTH, HEIGHT = 64, 32
OUT = Path(__file__).with_name("preview_score_card.png")

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
    "/": ("001", "001", "010", "100", "100"), ":": ("000", "010", "000", "010", "000"),
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


def badge(draw: ImageDraw.ImageDraw, abbreviation: str, y: int, color: tuple[int, int, int]) -> None:
    draw.rounded_rectangle((1, y, 9, y + 8), radius=2, fill=(8, 12, 22), outline=color)
    if abbreviation == "DAL":
        rows = ("0010000", "0010000", "0101010", "0011100", "1111111", "0011100", "0101010")
        for row, bits in enumerate(rows):
            for column, bit in enumerate(bits):
                if bit == "1":
                    draw.point((2 + column, y + 1 + row), fill=color)
    else:
        text(draw, abbreviation[:2], 2, y + 2, color)


img = Image.new("RGB", (WIDTH, HEIGHT), (7, 13, 24))
draw = ImageDraw.Draw(img)
cyan = (35, 190, 235)
muted = (70, 100, 130)
away_color = (255, 130, 40)
home_color = (70, 155, 255)
draw.line((0, 0, 63, 0), fill=cyan)
draw.line((0, 6, 63, 6), fill=muted)
draw.line((0, 26, 63, 26), fill=muted)
text(draw, "NFL", 1, 1, cyan)
text(draw, "1/2", 51, 1, muted)
badge(draw, "DAL", 8, away_color)
text(draw, "DAL", 12, 10, (235, 240, 250))
text(draw, "17", 46, 8, (255, 255, 255), 2)
badge(draw, "NYG", 17, home_color)
text(draw, "NYG", 12, 19, (235, 240, 250))
text(draw, "14", 46, 17, (255, 255, 255), 2)
text(draw, "Q2 5:12", 2, 28, (255, 220, 90))

img.resize((WIDTH * SCALE, HEIGHT * SCALE), Image.Resampling.NEAREST).save(OUT)
print(OUT)
