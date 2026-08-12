"""Render score cards without controller state or network access."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from PIL import Image, ImageDraw

from ticker_core.context import RenderContext
from ticker_core.rendering import ContentScene, FontSet, RenderedContent
from ticker_core.rendering.pixels import draw_hybrid_text

from .full_port import PreparedSportsFullRenderer
from .stadium_port import PreparedStadiumRenderer

PANEL_W = 384
PANEL_H = 32
LOGO_SIZE = 22


class LogoSource(Protocol):
    """Load a prepared logo without network access."""

    def get(self, url: str | None, size: tuple[int, int]) -> Image.Image | None:
        """Return one prepared RGBA logo."""


def _clamp(value: int | float) -> int:
    return max(0, min(255, int(value)))


def _hex(value: Any, fallback: tuple[int, int, int] = (80, 80, 80)) -> tuple[int, int, int]:
    text = str(value or "").strip().lstrip("#")
    if len(text) == 6:
        try:
            return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
        except ValueError:
            pass
    return fallback


def _dark(color: tuple[int, int, int], factor: float = 0.5) -> tuple[int, int, int]:
    return tuple(int(channel * (1 - factor)) for channel in color)


PIXELS: dict[str, tuple[str, ...]] = {
    "0": ("111", "101", "101", "101", "111"), "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"), "3": ("111", "001", "011", "001", "111"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"), "7": ("111", "001", "010", "010", "010"),
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
    "-": ("000", "000", "111", "000", "000"), ".": ("000", "000", "000", "000", "010"),
    ":": ("000", "010", "000", "010", "000"), " ": ("000", "000", "000", "000", "000"),
    "▲": ("010", "111", "111", "000", "000"), "▼": ("000", "000", "111", "111", "010"),
}


def pixel_width(text: Any, scale: int = 1) -> int:
    """Return fixed width for a pixel label."""
    return len(str(text)) * 4 * scale


def pixel_text(draw: ImageDraw.ImageDraw, text: Any, x: int, y: int, color: tuple[int, int, int], scale: int = 1) -> int:
    """Draw a fixed width pixel label."""
    cursor = x
    for character in str(text).upper():
        rows = PIXELS.get(character, PIXELS[" "])
        for row_index, row in enumerate(rows):
            for column, on in enumerate(row):
                if on == "1":
                    draw.rectangle((cursor + column * scale, y + row_index * scale, cursor + (column + 1) * scale - 1, y + (row_index + 1) * scale - 1), fill=color)
        cursor += 4 * scale
    return cursor


def _normalise(game: Mapping[str, Any]) -> dict[str, Any]:
    game = dict(game)
    result = dict(game)
    result["sport"] = str(game.get("sport", ""))
    result["state"] = str(game.get("state", "pre"))
    result["status"] = str(game.get("status", ""))
    result["as"] = game.get("away_score", game.get("as", 0))
    result["hs"] = game.get("home_score", game.get("hs", 0))
    result["ac"] = _hex(game.get("away_color", game.get("ac")))
    result["hc"] = _hex(game.get("home_color", game.get("hc")))
    result["sit"] = dict(game.get("situation") or game.get("sit") or {})
    return result


def card_width(game: Mapping[str, Any]) -> int:
    """Return the smallest card width that protects both logos."""
    normal = _normalise(game)
    sport = normal["sport"].lower()
    scores = pixel_width(normal["as"], 2) + pixel_width("-", 2) + pixel_width(normal["hs"], 2)
    active = normal["state"] == "in"
    baseball = "baseball" in sport or "mlb" in sport
    delayed = any(word in normal["status"].lower() for word in ("delay", "suspended", "postponed", "canceled", "ppd"))
    center = max(scores + 2, 0) if baseball and active and not delayed else max(scores, pixel_width(normal["status"][:12]))
    if normal["state"] == "in" and ("football" in sport or "nfl" in sport):
        center = max(center, pixel_width(normal["sit"].get("downDist", normal.get("dd", ""))))
    if normal["sit"].get("shootout") and ("hockey" in sport or "soccer" in sport):
        center = max(center, scores + 14)
    return min(160, int((56 + center + 1) // 2 * 2))


class SportsRenderer:
    """Render the scoreboard and full sports card families."""

    def __init__(self, fonts: FontSet, logos: LogoSource) -> None:
        self._fonts = fonts
        self._logos = logos
        self._stadium = PreparedStadiumRenderer(logos)
        self._full = PreparedSportsFullRenderer(fonts, logos)

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        """Render one score card or a 384 pixel full display."""
        if scene.mode.lower() == "sports_full":
            return RenderedContent(self.render_full(scene.item), static=False)
        return RenderedContent(self.render_strip((scene.item,)), static=False)

    def render_strip(self, games: Sequence[Mapping[str, Any]], repeat: int = 1) -> Image.Image:
        """Render a gap-separated sequence of normal score cards."""
        cards = [self.render_card(game) for game in games]
        width = sum(card.width for card in cards) * max(1, repeat)
        frame = Image.new("RGB", (max(1, width), PANEL_H), (0, 0, 0))
        x = 0
        for _ in range(max(1, repeat)):
            for card in cards:
                frame.paste(card, (x, 0))
                x += card.width
        return frame

    def render_card(self, game: Mapping[str, Any]) -> Image.Image:
        """Render one 32 pixel stadium score card."""
        legacy_image, _ = self._stadium.render(dict(game))
        return legacy_image.convert("RGB")

    def _render_card_implementation(self, game: Mapping[str, Any]) -> Image.Image:
        """Render a card without the exact stadium port."""
        game = _normalise(game)
        width = card_width(game)
        image = Image.new("RGBA", (width, PANEL_H), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        sport = game["sport"].lower()
        active = game["state"] == "in"
        baseball = "baseball" in sport or "mlb" in sport
        football = "football" in sport or "nfl" in sport
        hockey = "hockey" in sport or "nhl" in sport
        soccer = "soccer" in sport
        sit = game["sit"]
        draw.line((0, 7, width, 7), fill=(55, 76, 130))
        away_x, home_x, logo_y = 1, width - LOGO_SIZE - 1, 9
        self._paste_logo(image, game.get("away_logo"), away_x, logo_y, game["ac"])
        self._paste_logo(image, game.get("home_logo"), home_x, logo_y, game["hc"])
        center = width // 2
        status = str(game["status"])[:12]
        delay = any(word in status.lower() for word in ("delay", "suspended", "postponed", "canceled", "ppd"))
        if not baseball or not active or delay:
            text_x = max(1, (width - len(status.upper()) * 5) // 2)
            draw_hybrid_text(draw, text_x + 1, 2, status, (8, 8, 8, 180))
            draw_hybrid_text(draw, text_x, 1, status, (255, 240, 150, 255))
            self._draw_score(draw, center, 9, game["as"], game["hs"])
        else:
            self._draw_baseball(draw, width, center, game)
        if football and active:
            self._draw_football(draw, width, game)
        if hockey and active:
            self._draw_hockey(draw, width, game)
        if soccer:
            self._draw_soccer(draw, width, game)
        return image.convert("RGB")

    def _paste_logo(self, image: Image.Image, url: Any, x: int, y: int, color: tuple[int, int, int]) -> None:
        logo = self._logos.get(str(url) if url else None, (LOGO_SIZE, LOGO_SIZE))
        if logo is not None:
            image.paste(logo, (x, y), logo)
            return
        draw = ImageDraw.Draw(image)
        draw.rectangle((x, y, x + 21, y + 21), fill=_dark(color))
        draw.rectangle((x + 2, y + 2, x + 19, y + 19), fill=_dark(color, 0.1))
        draw.rectangle((x, y, x + 21, y + 21), outline=color)

    @staticmethod
    def _draw_score(draw: ImageDraw.ImageDraw, center: int, y: int, away: Any, home: Any) -> None:
        value = f"{away}-{home}"
        pixel_text(draw, value, center - pixel_width(value, 2) // 2, y, (255, 255, 255), 2)

    def _draw_football(self, draw: ImageDraw.ImageDraw, width: int, game: Mapping[str, Any]) -> None:
        sit = game["sit"]
        possession = str(sit.get("possession", game.get("poss", ""))).upper()
        team = "home" if possession in {"HOME", str(game.get("home_abbr", "")).upper()} else "away"
        x = width - 12 if team == "home" else 8
        draw.ellipse((x - 4, 1, x + 4, 5), fill=(150, 75, 20), outline=(110, 54, 14))
        draw.line((x - 2, 3, x + 2, 3), fill=(255, 255, 255))
        down = str(sit.get("downDist", game.get("dd", "")))
        if down:
            color = (235, 70, 70) if sit.get("isRedZone", game.get("rz")) else (0, 200, 60)
            pixel_text(draw, down, width // 2 - pixel_width(down) // 2, 23, color)
        if sit.get("isRedZone", game.get("rz")):
            draw.rectangle((0, 0, width - 1, 31), outline=(255, 40, 40))

    def _draw_hockey(self, draw: ImageDraw.ImageDraw, width: int, game: Mapping[str, Any]) -> None:
        sit = game["sit"]
        shootout = sit.get("shootout")
        if shootout:
            for x, results in ((25, shootout.get("away", [])), (width - 30, shootout.get("home", []))):
                for index, result in enumerate((list(results) + ["pending"] * 3)[:3]):
                    color = (50, 200, 70) if result == "goal" else (220, 55, 55) if result == "miss" else (55, 55, 55)
                    draw.rectangle((x, 9 + index * 7, x + 4, 13 + index * 7), fill=color)
            return
        badge = "EN" if sit.get("emptyNet") else "PP" if sit.get("powerPlay") else ""
        if badge:
            pixel_text(draw, badge, width - pixel_width(badge) - 2, 2, (255, 100, 100) if badge == "EN" else (255, 220, 0))

    def _draw_baseball(self, draw: ImageDraw.ImageDraw, width: int, center: int, game: Mapping[str, Any]) -> None:
        sit = game["sit"]
        status = str(game["status"])
        top = "TOP" in status.upper() or status.startswith("^")
        inning = re.search(r"\d+", status)
        label = ("▲" if top else "▼") + (inning.group() if inning else "")
        pixel_text(draw, label, center - pixel_width(label) // 2, 1, (255, 240, 150))
        score = f"{game['as']}-{game['hs']}"
        pixel_text(draw, score, center - pixel_width(score, 2) // 2, 8, (255, 255, 255), 2)
        bases = ((center + 4, 23, bool(sit.get("onFirst"))), (center, 19, bool(sit.get("onSecond"))), (center - 4, 23, bool(sit.get("onThird"))))
        for x, y, occupied in bases:
            draw.polygon(((x, y), (x + 2, y + 2), (x, y + 4), (x - 2, y + 2)), fill=(255, 200, 0) if occupied else (55, 55, 55))
        outs = int(sit.get("outs", game.get("outs", 0)) or 0)
        for index in range(3):
            draw.rectangle((center - 6 + index * 5, 28, center - 3 + index * 5, 30), fill=(210, 70, 70) if index < outs else (45, 45, 45))

    def _draw_soccer(self, draw: ImageDraw.ImageDraw, width: int, game: Mapping[str, Any]) -> None:
        sit = game["sit"]
        shootout = sit.get("shootout")
        if shootout:
            for x, results in ((25, shootout.get("away", [])), (width - 28, shootout.get("home", []))):
                for index, result in enumerate((list(results) + ["pending"] * 5)[:5]):
                    color = (50, 200, 70) if result == "goal" else (220, 55, 55) if result == "miss" else (80, 80, 80)
                    draw.rectangle((x, 8 + index * 5, x + 2, 10 + index * 5), fill=color)
        cards = sit.get("red_cards") or []
        for home, x in ((False, 3), (True, width - 8)):
            count = sum(1 for card in cards if bool(card.get("is_home")) == home)
            if count:
                draw.rectangle((x, 0, x + 4, 6), fill=(210, 30, 30))
                if count > 1:
                    pixel_text(draw, min(count, 9), x + 1, 1, (255, 255, 255))

    def render_full(self, game: Mapping[str, Any]) -> Image.Image:
        """Render the 384 by 32 sport-specific full display."""
        return self._full.draw_sport_full_bleed(dict(game)).convert("RGB")

    def _render_full_implementation(self, game: Mapping[str, Any]) -> Image.Image:
        """Render a full card without the exact full-screen port."""
        game = _normalise(game)
        sport = game["sport"].lower()
        image = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        if "football" in sport or "nfl" in sport:
            self._full_football(draw, game)
        elif "baseball" in sport or "mlb" in sport:
            self._full_baseball(draw, game)
        elif "basket" in sport or "nba" in sport:
            self._full_basketball(draw)
        elif "hockey" in sport or "nhl" in sport:
            self._full_hockey(draw)
        elif "soccer" in sport:
            self._full_soccer(draw)
        else:
            draw.rectangle((0, 0, PANEL_W - 1, PANEL_H - 1), fill=(12, 18, 28))
        self._full_overlay(image, game)
        return image.convert("RGB")

    def _full_football(self, draw: ImageDraw.ImageDraw, game: Mapping[str, Any]) -> None:
        home, away = _hex(game.get("home_color"), (155, 32, 32)), _hex(game.get("away_color"), (32, 62, 155))
        draw.rectangle((0, 0, 31, 31), fill=home)
        draw.rectangle((352, 0, 383, 31), fill=away)
        for index in range(10):
            x = 32 + index * 32
            draw.rectangle((x, 0, x + 31, 31), fill=(22, 52, 18) if index % 2 == 0 else (27, 64, 24))
        for index in range(1, 10):
            x = 32 + index * 32
            draw.line((x, 0, x, 31), fill=(240, 240, 220))

    @staticmethod
    def _full_basketball(draw: ImageDraw.ImageDraw) -> None:
        draw.rectangle((0, 0, 383, 31), fill=(200, 120, 58))
        draw.rectangle((1, 1, 382, 30), outline=(255, 255, 255))
        draw.line((192, 0, 192, 31), fill=(255, 255, 255))
        draw.ellipse((181, 5, 203, 27), outline=(255, 255, 255))
        draw.rectangle((0, 6, 69, 25), outline=(255, 255, 255), fill=(160, 80, 32))
        draw.rectangle((314, 6, 383, 25), outline=(255, 255, 255), fill=(160, 80, 32))

    @staticmethod
    def _full_hockey(draw: ImageDraw.ImageDraw) -> None:
        draw.rectangle((0, 0, 383, 31), fill=(205, 228, 248))
        draw.line((107, 0, 107, 31), fill=(34, 85, 204), width=2)
        draw.line((276, 0, 276, 31), fill=(34, 85, 204), width=2)
        draw.line((192, 0, 192, 31), fill=(204, 26, 26))
        draw.ellipse((179, 4, 205, 30), outline=(204, 26, 26))

    @staticmethod
    def _full_soccer(draw: ImageDraw.ImageDraw) -> None:
        draw.rectangle((0, 0, 383, 31), fill=(24, 92, 42))
        draw.rectangle((1, 1, 382, 30), outline=(215, 235, 215))
        draw.line((192, 0, 192, 31), fill=(215, 235, 215))
        draw.ellipse((180, 5, 204, 29), outline=(215, 235, 215))

    @staticmethod
    def _full_baseball(draw: ImageDraw.ImageDraw, game: Mapping[str, Any]) -> None:
        draw.rectangle((0, 0, 383, 31), fill=(8, 28, 4))
        draw.ellipse((165, 5, 219, 47), fill=(153, 111, 49))
        draw.polygon(((192, 4), (205, 17), (192, 30), (179, 17)), fill=(11, 34, 6))
        for x, y in ((192, 4), (205, 17), (179, 17)):
            draw.polygon(((x, y - 3), (x + 3, y), (x, y + 3), (x - 3, y)), fill=(255, 255, 255))

    def _full_overlay(self, image: Image.Image, game: Mapping[str, Any]) -> None:
        draw = ImageDraw.Draw(image)
        self._scrim(image)
        draw = ImageDraw.Draw(image)
        status = str(game["status"])
        draw.text((192, 16), status, font=self._fonts.big, fill=(255, 255, 255), stroke_width=1, stroke_fill=(0, 0, 0), anchor="mm")
        for side, x, anchor in (("home", 8, "lm"), ("away", 376, "rm")):
            score = str(game.get("hs" if side == "home" else "as", ""))
            draw.text((x + (28 if side == "home" else -28), 16), score, font=self._fonts.clock, fill=(255, 255, 255), stroke_width=1, stroke_fill=(0, 0, 0), anchor=anchor)
        self._paste_logo(image, game.get("home_logo"), 8, 4, game["hc"])
        self._paste_logo(image, game.get("away_logo"), 354, 4, game["ac"])

    @staticmethod
    def _scrim(image: Image.Image) -> None:
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for x in range(100):
            alpha = 252 if x < 8 else int(252 * (1 - ((x - 8) / 92) ** 2 * (3 - 2 * ((x - 8) / 92))))
            draw.line((x, 0, x, 31), fill=(0, 0, 0, alpha))
            draw.line((383 - x, 0, 383 - x, 31), fill=(0, 0, 0, alpha))
        image.alpha_composite(overlay)
