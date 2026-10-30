"""Draw the 32-pixel score card that scrolls in the sports strip.

The card has a team logo at each end. The status sits in a header row above a rule, and the
double-size score sits between the logos. Each sport family adds its own marks: the possession
ball and the down, the count and the bases, power plays and shootouts, and red cards.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw

from ticker.shared.sports_display import sport_family

from ticker.panel.layers import ImageTemplates, image_key
from ticker.panel.palette import PLAY_TEXT, RED_ZONE_TEXT, SCORE_TEXT, STATUS_TEXT, TOURNAMENT_SEED, sports_rule_color
from ticker.panel.text import HYBRID, draw_pane, pane_width
from ticker.panel.sports.logos import Outline, draw_missing_team_badge, paste_team_logo, team_logo

HEIGHT = 32
LOGO = 22
LOGO_GAP = 2
ZONE = LOGO + LOGO_GAP
MAX_WIDTH = 160
RANK = (255, 220, 80)
MISS = (220, 55, 55)
GOAL = (50, 200, 70)
OPEN = (55, 55, 55)
POWER_PLAY, EMPTY_NET, MUTED = (255, 220, 0), (255, 100, 100), (200, 210, 225)
LIVE_WORDS = ("q", "p", "h", "inning", "top", "bot", "'", "live")


def _rgb(value: object) -> tuple[int, int, int]:
    text = str(value or "").strip().lstrip("#")
    if len(text) == 6:
        try:
            return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))
        except ValueError:
            pass
    return (80, 80, 80)


def _game_state(item: Mapping[str, Any]) -> str:
    """Return the explicit game state, or read pre, in, or post from the status text."""
    if "state" in item:
        return item["state"]
    status = str(item.get("game_state", item.get("status", ""))).lower()
    if "final" in status or "post" in status:
        return "post"
    return "in" if any(word in status for word in LIVE_WORDS) else "pre"


@dataclass(frozen=True)
class PaneGame:
    """The facts one score card draws, read once from the projected game."""

    item: Mapping[str, Any]
    sport: str
    family: str
    state: str
    status: str
    away_score: int
    home_score: int
    away_color: tuple[int, int, int]
    home_color: tuple[int, int, int]
    situation: Mapping[str, Any]
    inning: Mapping[str, Any]

    @classmethod
    def read(cls, item: Mapping[str, Any]) -> "PaneGame":
        sport = item.get("sport", "unknown")
        return cls(item, str(sport).lower(), sport_family(sport), _game_state(item), str(item.get("status") or ""),
                   int(item.get("away_score", 0) or 0), int(item.get("home_score", 0) or 0),
                   _rgb(item.get("away_color", "")), _rgb(item.get("home_color", "")),
                   item.get("situation", {}) or {}, item.get("baseball_inning") or {})

    @property
    def inning_shown(self) -> bool:
        return self.family == "baseball" and self.inning.get("phase") in {"playing", "break"}

    def code(self, side: str) -> str:
        return str(self.item.get(f"{side}_abbr") or self.item.get(side, ""))

    def side(self, value: object) -> str | None:
        """Return "home" or "away" for a team code, a team ID, or a side name."""
        text = str(value).strip().upper() if value is not None else ""
        if not text:
            return None
        for side, letter in (("home", "H"), ("away", "A")):
            names = {str(self.item.get(side, self.item.get(f"{side}_abbr", "???"))).strip().upper(),
                     *(str(self.item.get(key, "")).strip().upper() for key in (f"{side}_abbr", f"{side}_id")),
                     side.upper(), letter} - {""}
            if text in names:
                return side
        return None


@dataclass(frozen=True)
class PaneLayout:
    """The logo and content positions of one card width."""

    width: int

    @property
    def away_x(self) -> int:
        return 1

    @property
    def home_x(self) -> int:
        return self.width - LOGO - 1

    @property
    def center(self) -> int:
        return (self.away_x + LOGO + LOGO_GAP + self.home_x - LOGO_GAP) // 2

    @property
    def center_x(self) -> float:
        return (self.away_x + LOGO + LOGO_GAP + self.home_x - LOGO_GAP) / 2.0

    def logo_center(self, side: str) -> int:
        return (self.home_x if side == "home" else self.away_x) + LOGO // 2


def card_width(game: PaneGame) -> int:
    """Return the smallest even width that keeps the center content clear of both logos."""
    situation = game.situation
    score = pane_width(game.away_score, 2) + pane_width("-", 2) + pane_width(game.home_score, 2)
    center = score + 2 if game.inning_shown else max(score, pane_width(game.status))
    down = situation.get("downDist", "") or ""
    if game.family == "football" and game.state == "in" and down:
        center = max(center, pane_width(down))
    if game.family in {"hockey", "soccer"} and situation.get("shootout"):
        center = max(center, score + 14)
    if game.family == "hockey":
        center = max(center, pane_width(str(situation.get("manpower", {}).get("scrollLabel") or "")))
    return min(MAX_WIDTH, int((ZONE + 4 + center + 4 + ZONE + 1) // 2 * 2))


def fill(draw: ImageDraw.ImageDraw, x, y, width, height, color) -> None:
    if width > 0 and height > 0:
        x, y, width, height = (int(round(value)) for value in (x, y, width, height))
        draw.rectangle([x, y, x + width - 1, y + height - 1], fill=(*(max(0, min(255, int(c))) for c in color[:3]), 255))


def draw_status(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, color) -> None:
    """Draw upper-case six-row glyphs with a 5-pixel advance and no text normalization."""
    for index, char in enumerate(text):
        for row, bits in enumerate(HYBRID.get(char.upper(), HYBRID.get(" ", [0] * 6))):
            for column, bit in enumerate((8, 4, 2, 1)):
                if bits & bit:
                    draw.point((x + index * 5 + column, y + row), fill=color)


def draw_ball(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    """Draw the 9 by 5 possession football with dark tips and one lace stripe."""
    brown, tip = (150, 75, 20), (110, 54, 14)
    for row, half in enumerate((2, 3, 4, 3, 2)):
        fill(draw, cx - half, cy + row, half * 2 + 1, 1, brown)
    fill(draw, cx - 4, cy + 2, 1, 1, tip)
    fill(draw, cx + 4, cy + 2, 1, 1, tip)
    fill(draw, cx - 2, cy + 2, 5, 1, (255, 255, 255))


def draw_bases(draw: ImageDraw.ImageDraw, cx: int, top: int, first: bool, second: bool, third: bool) -> None:
    """Draw second base at the top, first base on the right, and third base on the left."""
    for x, y, occupied in ((cx, top, second), (cx + 4, top + 4, first), (cx - 4, top + 4, third)):
        color = (255, 200, 0) if occupied else OPEN
        fill(draw, x - 2, y, 5, 1, color)
        fill(draw, x - 1, y + 1, 3, 1, color)
        fill(draw, x, y + 2, 1, 1, color)


def draw_kick(draw: ImageDraw.ImageDraw, x: int, y: int, result: str) -> None:
    """Draw one 5-pixel shootout kick: a green goal, a red cross, or an open slot."""
    if result == "goal":
        fill(draw, x, y, 5, 5, GOAL)
    elif result == "miss":
        for dx, dy in ((0, 0), (3, 0), (0, 3), (3, 3)):
            fill(draw, x + dx, y + dy, 2, 2, MISS)
        fill(draw, x + 1, y + 2, 3, 1, MISS)
    else:
        fill(draw, x, y, 5, 5, OPEN)
        fill(draw, x + 1, y + 1, 3, 3, (10, 10, 14))


def draw_hockey_shootout(draw: ImageDraw.ImageDraw, x: int, y: int, shootout: Mapping[str, Any], side: str) -> None:
    """Draw the three shootout rounds of one team in their given order. A frame marks the next shooter."""
    for index, round_ in enumerate(shootout.get("displayRounds", ())):
        top = y + index * 7
        if round_[side] == "not_taken":
            fill(draw, x, top, 5, 5, (20, 25, 32))
            fill(draw, x + 1, top + 2, 3, 1, (65, 70, 80))
        else:
            draw_kick(draw, x, top, round_[side])
        if round_.get("nextSide") == side:
            draw.rectangle((x - 1, top - 1, x + 5, top + 5), outline=(90, 190, 255))


def _centered(draw: ImageDraw.ImageDraw, center: int, y: int, text: str, color) -> None:
    draw_pane(draw, center - pane_width(text) // 2, y, text, color)


class PaneCard:
    """Draw score cards from prepared logos. The team layer of each card is cached."""

    def __init__(self, logos) -> None:
        self._logos = logos
        self._bases = ImageTemplates(max_bytes=4 * 1024 * 1024)

    def card(self, item: Mapping[str, Any]) -> Image.Image:
        game = PaneGame.read(item)
        layout = PaneLayout(card_width(game))
        rule = sports_rule_color(item.get("competition_stage"))
        image = self._base(game, layout.width, rule)
        draw = ImageDraw.Draw(image, "RGBA")
        if not game.inning_shown:
            self._header(draw, layout.width, game.status[:12].upper())
            fill(draw, 0, 7, layout.width, 1, rule)
            self._score(image, layout, str(game.away_score), str(game.home_score))
        if game.family == "football" and game.state == "in":
            self._football(draw, game, layout)
        if game.family == "hockey":
            self._hockey(draw, game, layout)
        if game.inning_shown:
            self._baseball(draw, game, layout, rule)
        if game.family == "soccer":
            self._soccer(draw, game.situation, layout)
        if "march" in game.sport:
            self._seeds(draw, game, layout.width)
        return image.convert("RGB")

    def _logo(self, side: str, item: Mapping[str, Any]):
        url = item.get(f"{side}_logo")
        return team_logo(self._logos, str(url) if url else None, (LOGO, LOGO), item.get(f"{side}_logo_rendering"))

    def _base(self, game: PaneGame, width: int, rule) -> Image.Image:
        """Return the cached layer with the logos, the college ranks, and the rule."""
        logos = self._logo("away", game.item), self._logo("home", game.item)
        key = (width, rule, game.sport, game.away_color, game.home_color, game.code("away"), game.code("home"),
               str(game.item.get("away_rank") or ""), str(game.item.get("home_rank") or ""), *map(image_key, logos))
        return self._bases.render(key, lambda: self._build_base(game, width, rule, logos))

    @staticmethod
    def _build_base(game: PaneGame, width: int, rule, logos) -> Image.Image:
        image = Image.new("RGBA", (width, HEIGHT), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image, "RGBA")
        fill(draw, 0, 7, width, 1, rule)
        top = HEIGHT - LOGO - 1
        sides = (("away", 1, logos[0], game.away_color), ("home", width - LOGO - 1, logos[1], game.home_color))
        for side, x, logo, color in sides:
            if logo:
                paste_team_logo(image, logo, (x, top), outline=Outline.SCROLL)
            else:
                draw_missing_team_badge(image, (x, top), LOGO, color, game.code(side))
        if game.sport in {"ncf_fbs", "ncf_fcs"}:
            for side, x, _, _ in sides:
                rank = str(game.item.get(f"{side}_rank") or "").strip()
                if rank:
                    rank_x = x + LOGO - pane_width(rank) - 1 if side == "home" else x + 1
                    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        draw_pane(draw, rank_x + dx, top + LOGO - 6 + dy, rank, (0, 0, 0))
                    draw_pane(draw, rank_x, top + LOGO - 6, rank, RANK)
        return image

    @staticmethod
    def _header(draw: ImageDraw.ImageDraw, width: int, label: str) -> None:
        """Draw the status in the header row with a dark drop shadow."""
        if label:
            x = max(1, (width - len(label) * 5) // 2)
            draw_status(draw, x + 1, 2, label, (8, 8, 8, 180))
            draw_status(draw, x, 1, label, (*STATUS_TEXT, 255))

    @staticmethod
    def _score(image: Image.Image, layout: PaneLayout, away: str, home: str) -> None:
        """Draw the double-size score, stretched one row taller, at the content center."""
        away_width, dash_width = pane_width(away, 2), pane_width("-", 2)
        width = away_width + dash_width + pane_width(home, 2)
        layer = Image.new("RGBA", (width, 10), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer, "RGBA")
        draw_pane(draw, 0, 0, away, SCORE_TEXT, 2)
        draw_pane(draw, away_width, 0, "-", SCORE_TEXT, 2)
        draw_pane(draw, away_width + dash_width, 0, home, SCORE_TEXT, 2)
        image.alpha_composite(layer.resize((width, 11), Image.Resampling.NEAREST), (int(round(layout.center_x - width / 2.0)), 9))

    @staticmethod
    def _football(draw: ImageDraw.ImageDraw, game: PaneGame, layout: PaneLayout) -> None:
        situation = game.situation
        side = game.side(situation.get("activeTeam", ""))
        if side:
            # The ball stays clear of the rule at row 7.
            draw_ball(draw, layout.logo_center(side) - 1, 1)
        red_zone = situation.get("isRedZone", False)
        if red_zone:
            draw.rectangle([0, 0, layout.width - 1, HEIGHT - 1], outline=(255, 40, 40, 153), width=1)
        down = situation.get("downDist", "")
        if down:
            _centered(draw, layout.center, 23, down, RED_ZONE_TEXT if red_zone else PLAY_TEXT)

    @staticmethod
    def _hockey(draw: ImageDraw.ImageDraw, game: PaneGame, layout: PaneLayout) -> None:
        situation = game.situation
        shootout = situation.get("shootout")
        if shootout:
            draw_hockey_shootout(draw, layout.away_x + LOGO + 2, 9, shootout, "away")
            draw_hockey_shootout(draw, layout.home_x - 7, 9, shootout, "home")
            _centered(draw, layout.center, 23, str(shootout.get("roundLabel") or ""), MUTED)
            return
        if game.state not in {"in", "crit"}:
            return
        power_play, empty_net = bool(situation.get("powerPlay")), bool(situation.get("emptyNet"))
        manpower = situation.get("manpower", {})
        if empty_net:
            side = game.side(situation.get("emptyNetSide"))
            if side:
                _centered(draw, layout.logo_center(side), 2, "EN", EMPTY_NET)
        elif power_play:
            side = game.side(situation.get("powerPlayTeam"))
            if side:
                _centered(draw, layout.logo_center(side), 2, str(manpower.get("powerPlayLabel") or ""), POWER_PLAY)
        label = str(manpower.get("scrollLabel") or "")
        if label:
            _centered(draw, layout.center, 23, label, POWER_PLAY if power_play else EMPTY_NET if empty_net else MUTED)

    @staticmethod
    def _baseball(draw: ImageDraw.ImageDraw, game: PaneGame, layout: PaneLayout, rule) -> None:
        """Draw the inning in the header, the count over the batting team, the score, the bases, and the outs."""
        situation, inning, width = game.situation, game.inning, layout.width
        fill(draw, 0, 0, width, 8, (0, 0, 0))
        fill(draw, 0, 7, width, 1, rule)
        # Between halves a dash shows the break. It does not point at a half.
        arrow = {"top": "▲", "bottom": "▼"}.get(inning.get("half", "none"), "-")
        number = str(inning["number"]) if inning.get("number") else ""
        arrow_width = pane_width(arrow)
        x = max(1, (width - (arrow_width + pane_width(number))) // 2)
        draw_pane(draw, x + 1, 2, arrow, (8, 8, 8))
        draw_pane(draw, x + arrow_width + 1, 2, number, (8, 8, 8))
        draw_pane(draw, x, 1, arrow, (255, 220, 105))
        draw_pane(draw, x + arrow_width, 1, number, (255, 240, 150))
        balls, strikes = str(int(situation.get("balls", 0) or 0)), str(int(situation.get("strikes", 0) or 0))
        outs = int(situation.get("outs", 0) or 0)
        side = game.side(situation.get("activeTeam", ""))
        if side is not None:
            x = layout.logo_center(side) - (pane_width(balls) + pane_width("-") + pane_width(strikes)) // 2
            x += draw_pane(draw, x, 2, balls, (60, 200, 60))
            x += draw_pane(draw, x, 2, "-", (160, 160, 160))
            draw_pane(draw, x, 2, strikes, (255, 140, 40))
        away, home = str(game.away_score), str(game.home_score)
        away_width, dash_width = pane_width(away, 2), pane_width("-", 2)
        dash = int(round(layout.center_x - (away_width + dash_width + pane_width(home, 2)) / 2.0)) + away_width
        draw_pane(draw, dash - away_width, 8, away, (255, 255, 255), 2)
        draw_pane(draw, dash, 8, "-", (255, 255, 255), 2)
        draw_pane(draw, dash + dash_width, 8, home, (255, 255, 255), 2)
        draw_bases(draw, dash + 3, 19, bool(situation.get("onFirst", False)), bool(situation.get("onSecond", False)),
                   bool(situation.get("onThird", False)))
        for index in range(3):
            fill(draw, dash + 3 - 7 + index * 5, 28, 4, 3, (210, 70, 70) if index < outs else (45, 45, 45))

    @staticmethod
    def _soccer(draw: ImageDraw.ImageDraw, situation: Mapping[str, Any], layout: PaneLayout) -> None:
        shootout = situation.get("shootout")
        if shootout:
            for x, kicks in ((layout.away_x + LOGO + 2, shootout.get("away", [])), (layout.home_x - 5, shootout.get("home", []))):
                for index in range(5):
                    result = kicks[index] if index < len(kicks) else "pending"
                    fill(draw, x, 8 + index * 5, 3, 3, GOAL if result == "goal" else MISS if result == "miss" else (80, 80, 80))
        # A 5 by 7 red card sits above the inner edge of the logo. More than one card shows the count.
        cards = situation.get("red_cards") or []
        counts = sum(1 for card in cards if not card.get("is_home")), sum(1 for card in cards if card.get("is_home"))
        for count, x in zip(counts, (layout.away_x + 2, layout.home_x + LOGO - 7)):
            if count > 0:
                draw.rectangle([x, 0, x + 4, 6], fill=(210, 30, 30))
                if count > 1:
                    draw_pane(draw, x + 1, 1, str(min(count, 9)), (255, 255, 255))

    @staticmethod
    def _seeds(draw: ImageDraw.ImageDraw, game: PaneGame, width: int) -> None:
        """Draw the tournament seeds. A final shows the winner in green and the loser in red."""
        final = game.state == "post"
        away_won, home_won = final and game.away_score > game.home_score, final and game.home_score > game.away_score
        away, home = str(game.item.get("away_seed", "")), str(game.item.get("home_seed", ""))
        draw_pane(draw, 2, 2, away, (100, 210, 100) if away_won else (170, 70, 70) if home_won else TOURNAMENT_SEED)
        draw_pane(draw, width - pane_width(home) - 2, 2, home,
                  (100, 210, 100) if home_won else (170, 70, 70) if away_won else TOURNAMENT_SEED)
