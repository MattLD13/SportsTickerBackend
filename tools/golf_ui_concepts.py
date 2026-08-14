"""Render 18-hole golf UI concepts for the 384x32 LED panel."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ticker_core.features.golf.renderer import GolfRenderer
from ticker_core.features.utility.primitives import normal_text


PANEL_SIZE = (384, 32)
FONT = GolfRenderer._font
PARS = [4, 5, 4, 3, 4, 3, 4, 5, 4, 4, 3, 4, 5, 4, 5, 3, 4, 4]


@dataclass(frozen=True, slots=True)
class GolfPalette:
    """Store one complete panel palette."""

    background: tuple[int, int, int, int]
    ink: tuple[int, int, int, int]
    label: tuple[int, int, int, int]
    line: tuple[int, int, int, int]
    accent: tuple[int, int, int, int]
    gold: tuple[int, int, int, int]
    birdie: tuple[int, int, int, int]
    eagle: tuple[int, int, int, int]
    bogey: tuple[int, int, int, int]
    double_bogey: tuple[int, int, int, int]
    black: tuple[int, int, int, int]


PALETTES = {
    "pga": GolfPalette(
        background=(0, 0, 0, 255),
        ink=(241, 246, 250, 255),
        label=(112, 124, 136, 255),
        line=(25, 30, 35, 255),
        accent=(91, 171, 221, 255),
        gold=(235, 196, 83, 255),
        birdie=(68, 211, 128, 255),
        eagle=(242, 205, 73, 255),
        bogey=(240, 103, 103, 255),
        double_bogey=(157, 43, 67, 255),
        black=(0, 0, 0, 255),
    ),
    "masters": GolfPalette(
        background=(0, 14, 8, 255),
        ink=(244, 248, 231, 255),
        label=(145, 169, 145, 255),
        line=(24, 50, 33, 255),
        accent=(231, 199, 92, 255),
        gold=(231, 199, 92, 255),
        birdie=(164, 225, 155, 255),
        eagle=(247, 218, 104, 255),
        bogey=(241, 139, 119, 255),
        double_bogey=(170, 67, 65, 255),
        black=(0, 39, 27, 255),
    ),
}

HEADER_LABELS = {"pga": "R3", "masters": "MASTERS R3"}


PLAYERS: list[dict[str, Any]] = [
    {
        "pos": "1",
        "name": "Scottie Scheffler",
        "total": -14,
        "today": -4,
        "thru": "F",
        "holes": [4, 3, 4, 1, 4, 2, 5, 3, 4, 6, 3, 4, 5, 4, 5, 3, 4, 4],
    },
    {
        "pos": "2",
        "name": "Xander Schauffele",
        "total": -12,
        "today": -3,
        "thru": "16",
        "holes": [5, 4, 5, 3, 4, 3, 4, 4, 5, 4, 2, 4, 5, 3, 4, 3, None, None],
    },
    {
        "pos": "3",
        "name": "Rory McIlroy",
        "total": -10,
        "today": -2,
        "thru": "F",
        "holes": [4, 5, 4, 3, 3, 5, 4, 4, 4, 4, 3, 4, 5, 4, 4, 3, 4, 3],
    },
]


class GolfConceptRenderer:
    """Render one full-round golf scoreboard concept."""

    def __init__(self, palette: GolfPalette, header_label: str) -> None:
        self.palette = palette
        self.header_label = header_label

    def render(self, players: list[dict[str, Any]], window: int, page: int = 1) -> Image.Image:
        """Render a nine-hole or full 18-hole scoreboard."""

        image = Image.new("RGBA", PANEL_SIZE, self.palette.background)
        draw = ImageDraw.Draw(image)
        full_round = window == 2
        start = 0 if window == 0 else 9 if window == 1 else 0
        finish = 18 if full_round else start + 9
        window_label = "" if full_round else "OUT" if window == 0 else "IN"
        hole_x = 58 if full_round else 66
        hole_step = 14 if full_round else 15
        hole_width = 9 if full_round else 8

        self._text(draw, self.header_label, 2, 0, self.palette.gold)
        if window_label:
            self._text(draw, window_label, 2 + len(self.header_label) * 4 + 4, 0, self.palette.accent)
        self._page_indicator(draw, page)

        for index, hole in enumerate(range(start + 1, finish + 1)):
            self._center(draw, str(hole), hole_x + hole_width // 2 + index * hole_step, 1, self.palette.label)
        self._center(draw, "TODAY", 322, 1, self.palette.label)
        self._center(draw, "TOTAL", 344, 1, self.palette.label)
        self._center(draw, "THRU", 366, 1, self.palette.label)

        for index, player in enumerate(players[:3]):
            y = 8 + index * 8
            hole_count = 18 if full_round else 9
            self._player(draw, player, start, y, hole_x, hole_step, hole_width, hole_count)
        return image

    def _page_indicator(self, draw: ImageDraw.ImageDraw, page: int) -> None:
        """Show one active dot for the current position in the five-page flip."""

        selected = max(1, min(5, page))
        for index in range(5):
            color = self.palette.accent if index + 1 == selected else self.palette.line
            y = 1 + index * 6
            draw.rectangle((381, y, 382, y + 1), fill=color)

    def _player(self, draw: ImageDraw.ImageDraw, player: dict[str, Any], start: int, y: int, hole_x: int, hole_step: int, hole_width: int, hole_count: int) -> None:
        position = normal_text(player.get("pos", "-"))[:3]
        name_parts = normal_text(player.get("name", "UNKNOWN")).upper().split()
        name = name_parts[-1] if name_parts else "UNKNOWN"
        name = name[:10]
        total = self._score(player.get("total"))
        today = self._score(player.get("today"))
        thru = normal_text(player.get("thru", "-")).upper()[:3]
        if position.replace("T", "") == "1":
            draw.rectangle((0, y, 1, y + 5), fill=self.palette.gold)
        self._text(draw, position, 3, y + 1, self.palette.gold if position.replace("T", "") == "1" else self.palette.ink)
        self._text(draw, name, 14, y + 1, self.palette.ink)

        holes = player.get("holes", []) if isinstance(player.get("holes"), list) else []
        for index in range(hole_count):
            hole_index = start + index
            value = holes[hole_index] if hole_index < len(holes) else None
            par = PARS[hole_index]
            self._hole(draw, hole_x + index * hole_step, y, value, par, hole_width)
        self._center(draw, today, 322, y + 1, self._score_color(player.get("today")))
        self._center(draw, total, 344, y + 1, self._score_color(player.get("total")))
        self._center(draw, thru, 366, y + 1, self.palette.accent)

    def _hole(self, draw: ImageDraw.ImageDraw, x: int, y: int, score: Any, par: int, width: int) -> None:
        if score is None:
            draw.rectangle((x, y, x + width - 1, y + 6), outline=self.palette.label)
            self._center(draw, "-", x + width // 2, y + 1, self.palette.label)
            return
        value = int(score)
        difference = value - par
        if value == 1:
            color = self.palette.gold
        elif difference <= -2:
            right = x + width - 1
            draw.polygon(((x + 2, y), (right - 2, y), (right, y + 2), (right, y + 4), (right - 2, y + 6), (x + 2, y + 6), (x, y + 4), (x, y + 2)), fill=self.palette.eagle)
            color = self.palette.black
        elif difference == -1:
            draw.ellipse((x, y, x + width - 1, y + 6), fill=self.palette.birdie)
            color = self.palette.black
        elif difference == 0:
            draw.rectangle((x, y, x + width - 1, y + 6), outline=self.palette.label)
            color = self.palette.ink
        elif difference == 1:
            draw.rectangle((x, y, x + width - 1, y + 6), fill=self.palette.bogey)
            color = self.palette.ink
        else:
            draw.ellipse((x, y, x + width - 1, y + 6), fill=self.palette.double_bogey)
            color = self.palette.ink
        self._center(draw, str(value), x + width // 2, y + 1, color)

    def _text(self, draw: ImageDraw.ImageDraw, value: Any, x: int, y: int, color: tuple[int, int, int, int]) -> None:
        cursor = x
        for character in normal_text(value).upper():
            pattern = FONT.get(character, FONT[" "])
            for row, bits in enumerate(pattern):
                for column in range(3):
                    if (bits >> (2 - column)) & 1:
                        draw.point((cursor + column, y + row), fill=color)
            cursor += 4

    def _center(self, draw: ImageDraw.ImageDraw, value: Any, x: int, y: int, color: tuple[int, int, int, int]) -> None:
        self._text(draw, value, int(x - max(0, len(str(value)) * 4 - 1) // 2), y, color)

    @staticmethod
    def _score(value: Any) -> str:
        try:
            integer = int(value)
        except (TypeError, ValueError):
            return "-"
        return "E" if integer == 0 else f"+{integer}" if integer > 0 else str(integer)

    def _score_color(self, value: Any) -> tuple[int, int, int, int]:
        try:
            integer = int(value)
        except (TypeError, ValueError):
            return self.palette.label
        return self.palette.birdie if integer < 0 else self.palette.bogey if integer > 0 else self.palette.ink


def render_all(output_directory: Path) -> list[Path]:
    """Render both nine-hole windows in both color schemes."""

    output_directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for scheme, palette in PALETTES.items():
        for window, window_name in ((2, "18"),):
            path = output_directory / f"golf-{scheme}-{window_name}.png"
            GolfConceptRenderer(palette, HEADER_LABELS[scheme]).render(PLAYERS, window).save(path)
            paths.append(path)
    _save_contact_sheet(paths, output_directory / "golf-ui-concepts.png")
    return paths


def _save_contact_sheet(paths: list[Path], output: Path) -> None:
    """Save a large nearest-neighbour preview of the four real panel frames."""

    scale = 4
    sheet = Image.new("RGB", (PANEL_SIZE[0] * scale, PANEL_SIZE[1] * scale * len(paths)), (20, 20, 20))
    y = 0
    for path in paths:
        frame = Image.open(path).convert("RGB").resize((PANEL_SIZE[0] * scale, PANEL_SIZE[1] * scale), Image.Resampling.NEAREST)
        sheet.paste(frame, (0, y))
        y += PANEL_SIZE[1] * scale
    sheet.save(output)


def main() -> int:
    """Render selected concepts or the complete concept set."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scheme", choices=tuple(PALETTES), default="pga")
    parser.add_argument("--window", choices=("full",), default="full")
    parser.add_argument("--page", type=int, choices=(1, 2, 3, 4, 5), default=1, help="Active page dot in the five-page flip.")
    parser.add_argument("--output", type=Path, default=Path("previews/golf_concepts/golf.png"))
    parser.add_argument("--all", action="store_true", help="Render both schemes and both nine-hole windows.")
    parser.add_argument("--output-dir", type=Path, default=Path("previews/golf_concepts"))
    args = parser.parse_args()
    if args.all:
        for path in render_all(args.output_dir):
            print(f"Saved {path}")
        return 0
    window = 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    GolfConceptRenderer(PALETTES[args.scheme], HEADER_LABELS[args.scheme]).render(PLAYERS, window, args.page).save(args.output)
    print(f"Saved {args.output} (384x32)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
