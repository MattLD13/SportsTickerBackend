"""Draw a pinned game across the whole 384 by 32 panel, on the playing surface of its sport.

The pinned layout draws the away team on the left, so it swaps the home and away fields first.
After the swap, "home" is the left team. Each sport has its own layout:

- Football shows the field, the ball spot, the first-down line, and the red zone.
- Soccer shows the pitch, the time, the goal and card lanes, and the shootout.
- Baseball shows the diamond, the inning, the count, the batter, the pitcher, and the challenges.
- Hockey and basketball show the rink or the court, the period, and the side badges. Hockey also
  shows the goal pages or the shootout.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PIL import Image, ImageDraw, ImageStat

from ..layers import ImageTemplates
from ..palette import TOURNAMENT_SEED, is_near_black, is_near_white, parse_hex_color
from ..text import draw_tiny
from . import fields
from .fields import END_ZONE, HEIGHT, PLAY, WIDTH
from .logos import Outline, draw_missing_team_badge, paste_team_logo, team_logo
from .pane import draw_hockey_shootout

MARK = 24
MARK_Y = (HEIGHT - MARK) // 2
RIGHT_MARK_X = WIDTH - 3 - MARK - 5
WHITE = (255, 255, 255)
OUTLINE = (0, 0, 0, 200)
SHADOW = (0, 0, 0, 220)
STATUS = (255, 240, 150)
EMPTY_NET, POWER_PLAY = (255, 90, 90), (255, 204, 0)
NAME_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V", "VI"}
MISSING_ERA = {"-", "-.--", "N/A", "n/a"}
WEATHER_STOPS = ("delay", "delayed", "suspended", "postponed", "canceled", "ppd")
GOALS_PER_PAGE = 3


def display_sides(game: Mapping[str, Any]) -> dict[str, Any]:
    """Swap the home and away fields, so "home" names the left team."""
    swapped = {}
    for key, value in game.items():
        if key.startswith("home_"):
            swapped["away_" + key[5:]] = value
        elif key.startswith("away_"):
            swapped["home_" + key[5:]] = value
        else:
            swapped[key] = value
    return swapped


def hockey_pages(situation: Mapping[str, Any]) -> int:
    """Return the number of goal pages. Each team shows three goals on each page."""
    if situation.get("shootout"):
        return 1
    goals = situation.get("hockeyGoals", ())
    most = max(sum(goal.get("side") == side for goal in goals) for side in ("away", "home"))
    return max(1, (most + GOALS_PER_PAGE - 1) // GOALS_PER_PAGE)


def short_status(status: object) -> str:
    """Shorten a game status for the center of the panel: "Q4 12:00" shows as "Q4-12:00"."""
    if not status:
        return ""
    if any(word in str(status).lower() for word in WEATHER_STOPS):
        return str(status).title()
    text = str(status).upper().replace(" - ", " ").replace("/OT", " OT").replace("HALFTIME", "HALF")
    for old, new in (("TOP ", "^"), ("BOTTOM ", "V"), ("BOT ", "V")):
        text = text.replace(old, new)
    if text.startswith("END "):
        return text
    for number in ("10", "11", "12", "1", "2", "3", "4", "5", "6", "7", "8", "9"):
        for suffix in ("TH", "ST", "ND", "RD"):
            text = text.replace(f"{number}{suffix}", number)
    text = text.replace("1ST", "P1").replace("2ND", "P2").replace("3RD", "P3").replace("4TH", "P4").replace("FULL TIME", "FT")
    for period in ("P1", "P2", "P3", "P4", "Q1", "Q2", "Q3", "Q4", "OT"):
        text = text.replace(f"{period} ", f"{period}-")
    return text


def line_of_scrimmage(situation: Mapping[str, Any], spot: str, left: str, right: str) -> int:
    """Return the ball spot in yards from the left goal line, or -1 when the spot is not known.

    The provider measures the yard line from the home goal line. The home team is on the right
    after the swap, so the value is mirrored.
    """
    if situation.get("yardLine") is not None:
        return max(0, min(100, 100 - int(situation["yardLine"])))
    if " at " not in spot:
        return -1
    # A payload without the number still reads "... at CAR 33".
    words = spot.split(" at ", 1)[1].strip().split()
    if words == ["50"]:
        return 50
    if len(words) >= 2:
        try:
            yard = int(words[1])
        except ValueError:
            return -1
        team = words[0].upper()
        return yard if team == left else 100 - yard if team == right else 50
    return -1


def yards_to_go(situation: Mapping[str, Any], down: str) -> int:
    if situation.get("yardsToGo") is not None:
        return max(1, int(situation["yardsToGo"]))
    if "&" in down:
        try:
            return max(1, int(down.split("&", 1)[1].strip().split()[0].lower().rstrip(".,")))
        except ValueError:
            return 10
    return 10


def ordinal(number: object) -> str:
    number = int(number)
    suffix = "th" if 10 <= number % 100 <= 19 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def last_name(name: object, limit: int = 24) -> str:
    """Return the upper-case family name. A generational suffix stays with it."""
    text = str(name or "").strip()
    if not text:
        return ""
    parts = text.replace(".", " ").split()
    if len(parts) >= 2 and parts[-1].upper() in NAME_SUFFIXES:
        return f"{parts[-2]} {parts[-1]}".upper()[:limit]
    return (parts[-1] if parts else text).upper()[:limit]


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def pitch_name(full: object, abbreviation: object) -> str:
    """Return a pitch name short enough for the side lane."""
    text = str(full or "").strip()
    if text:
        text = text.split("(", 1)[0].strip().split("/", 1)[0].strip()
    if not text:
        return str(abbreviation or "").strip().upper()[:10]
    if len(text) > 12 and text.replace("-", " ").split():
        text = text.replace("-", " ").split()[-1]
    return text.title()[:12]


def batter_lines(situation: Mapping[str, Any]) -> list:
    """Return the batter name, the hits for at-bats, and the average."""
    average = _text(situation.get("batter_avg", ""))
    average = average[1:] if average.startswith("0.") else average
    hits, at_bats = _text(situation.get("batter_h", "")), _text(situation.get("batter_ab", ""))
    return [situation.get("batter_name", ""), f"{hits or '-'}/{at_bats or '-'}" if hits or at_bats else "", average]


def pitcher_lines(situation: Mapping[str, Any]) -> list:
    """Return the pitcher name, the pitch count, and the last pitch or the ERA."""
    count = _text(situation.get("pitcher_pitches", ""))
    speed = situation.get("last_pitch_speed", 0)
    kind = pitch_name(situation.get("last_pitch_type_full", ""),
                      situation.get("last_pitch_type_abbr", "") or situation.get("last_pitch_type", ""))
    if str(speed).strip() and str(speed).strip() != "0":
        pitch = f"{speed} {kind}" if kind else f"{speed} MPH"
    else:
        pitch = kind
    era = _text(situation.get("pitcher_era"))
    if not pitch and era and era not in MISSING_ERA:
        pitch = f"ERA:{era}"
    return [situation.get("pitcher_name", ""), f"P:{count}" if count else "", pitch]


def _count(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def outlined(draw: ImageDraw.ImageDraw, x, y, text: str, font, color, outline, anchor: str = "mm") -> None:
    """Draw text with a one-pixel outline in all eight directions."""
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx or dy:
                draw.text((x + dx, y + dy), text, font=font, fill=outline, anchor=anchor)
    draw.text((x, y), text, font=font, fill=color, anchor=anchor)


class PinnedCard:
    """Draw pinned games from prepared logos. The playing surfaces are cached."""

    def __init__(self, fonts, logos) -> None:
        self._fonts = fonts
        self._logos = logos
        self._surfaces = ImageTemplates(capacity=16, max_bytes=1024 * 1024)

    def frame(self, item: Mapping[str, Any], page: int = 0) -> Image.Image:
        game = display_sides(item)
        sport = str(game.get("sport", "")).lower()
        if any(word in sport for word in ("football", "nfl", "ncf")):
            image = self._football(game, sport)
        elif "soccer" in sport:
            image = self._soccer(game)
        elif "baseball" in sport or "mlb" in sport:
            image = self._baseball(game)
        else:
            image = self._rink_or_court(game, sport, page)
        return image.convert("RGB")

    # Logos and team colors.

    def _logo(self, game: Mapping[str, Any], side: str, size: int):
        url = game.get(f"{side}_logo")
        return team_logo(self._logos, str(url) if url else None, (size, size), game.get(f"{side}_logo_rendering"))

    @staticmethod
    def _mark(image: Image.Image, logo, xy, code: str, size: int, color) -> None:
        """Paste one logo at the mark size, or draw the team badge when the logo is missing."""
        if logo is None:
            draw_missing_team_badge(image, xy, size, color, code)
            return
        # A resized logo has no selected outline, so it uses the keyline policy of the full view.
        paste_team_logo(image, logo if logo.size == (size, size) else logo.resize((size, size), Image.LANCZOS), xy, outline=Outline.FULL)

    def _color(self, game: Mapping[str, Any], side: str) -> tuple[int, int, int]:
        """Return the team color, or the mean color of the logo, or gray."""
        value = game.get(f"{side}_color")
        if value:
            try:
                text = str(value).lstrip("#")
                return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))
            except (TypeError, ValueError):
                pass
        logo = self._logo(game, side, 24)
        return tuple(int(value) for value in ImageStat.Stat(logo).mean[:3]) if logo else (60, 60, 60)

    def _marks_and_scores(self, image, draw, game, left_x: int, left_color, right_color) -> tuple[int, int]:
        """Draw both marks and both giant scores. Return the inner score anchors."""
        self._mark(image, self._logo(game, "home", MARK), (left_x, MARK_Y), str(game.get("home_abbr", "")).upper(), MARK, left_color)
        self._mark(image, self._logo(game, "away", MARK), (RIGHT_MARK_X, MARK_Y), str(game.get("away_abbr", "")).upper(), MARK, right_color)
        left, right = left_x + MARK + 4, RIGHT_MARK_X - 4
        outlined(draw, left, HEIGHT // 2, str(game.get("home_score", "")), self._fonts.clock, WHITE, OUTLINE, anchor="lm")
        outlined(draw, right, HEIGHT // 2, str(game.get("away_score", "")), self._fonts.clock, WHITE, OUTLINE, anchor="rm")
        return left, right

    def _score_width(self, draw, game, side: str, empty: str = "") -> float:
        return draw.textlength(str(game.get(f"{side}_score", "")) or empty, font=self._fonts.clock)

    # Football.

    @staticmethod
    def _end_zone(game: Mapping[str, Any], side: str, fallback):
        """Use the alternate color when the primary color is a gray and the alternate is not."""
        primary = parse_hex_color(game.get(f"{side}_color")) or fallback
        alternate = parse_hex_color(game.get(f"{side}_alt_color"))
        if max(primary) - min(primary) < 25 and alternate and max(alternate) - min(alternate) >= 25:
            return alternate
        return primary

    def _football(self, game: Mapping[str, Any], sport: str) -> Image.Image:
        fonts, situation = self._fonts, game.get("situation", {}) or {}
        left, right = str(game.get("home_abbr", "")).upper(), str(game.get("away_abbr", "")).upper()
        possession = str(situation.get("possession", "")).upper()
        left_zone = self._end_zone(game, "home", self._color(game, "home"))
        right_zone = self._end_zone(game, "away", self._color(game, "away"))
        image = self._surfaces.render(("football", WIDTH, HEIGHT, left_zone, right_zone),
                                      lambda: fields.football_field(left_zone, right_zone))
        draw = ImageDraw.Draw(image, "RGBA")
        # A marker above the end zone shows possession.
        active = str(situation.get("activeTeam", "")).strip().upper()
        marker = int(END_ZONE / 2) if active and active == left else WIDTH - int(END_ZONE / 2) if active and active == right else None
        if marker is not None:
            draw.polygon([(marker - 5, 1), (marker + 5, 1), (marker, 5)], fill=(255, 235, 80), outline=(0, 0, 0, 255))

        down = situation.get("downDist", "") or situation.get("downDistFull", "")
        spot = line_of_scrimmage(situation, situation.get("downDistFull", "") or situation.get("ballOn", "") or down, left, right)
        to_go = yards_to_go(situation, down)
        # The left team drives to the right.
        rightward = possession != right
        if (bool(situation.get("isGoalToGo")) or "goal" in down.lower()) and spot >= 0:
            # On goal to go, the goal line is the first-down line.
            to_go = max(1, (100 - spot) if rightward else spot)
        red_zone = situation.get("isRedZone", False)
        if red_zone:
            overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
            zone = ImageDraw.Draw(overlay, "RGBA")
            if rightward:
                zone.rectangle([END_ZONE + int(0.8 * PLAY), 0, WIDTH - END_ZONE, HEIGHT], fill=(220, 0, 0, 128))
            else:
                zone.rectangle([END_ZONE, 0, END_ZONE + int(0.2 * PLAY), HEIGHT], fill=(220, 0, 0, 128))
            edge = END_ZONE + (0.8 if rightward else 0.2) * PLAY
            draw.line([(edge, 0), (edge, HEIGHT)], fill=(255, 34, 34, 200), width=2)
            image.alpha_composite(overlay)

        # The field has room for the full down and spot, such as "1st & 10 at ARI 42".
        period, context = short_status(game.get("status", "")), situation.get("downDistFull", "") or down
        if period or context:
            outlined(draw, WIDTH // 2, int(HEIGHT * 0.32) if context else int(HEIGHT * 0.5), period, fonts.big, WHITE, OUTLINE)
            if context:
                outlined(draw, WIDTH // 2, int(HEIGHT * 0.72), context, fonts.normal, (255, 136, 0) if red_zone else (240, 216, 0), OUTLINE)

        # In the red zone, the defending score moves into its end zone, and the logo rises above it.
        size = min(int(END_ZONE * 0.85), int(HEIGHT * 0.65))
        left_logo, right_logo = int(END_ZONE / 2), WIDTH - int(END_ZONE / 2)
        box = draw.textbbox((0, 0), "00", font=fonts.big)
        score_height = max(11, box[3] - box[1])
        score_y = min(int(HEIGHT * 0.82), HEIGHT - score_height // 2 - 1)
        left_score, right_score = int(END_ZONE + PLAY * 0.05), int(WIDTH - END_ZONE - PLAY * 0.05)
        if red_zone and possession == left:
            right_score = right_logo
        elif red_zone and possession == right:
            left_score = left_logo
        centered, raised = (HEIGHT - size) // 2, max(0, score_y - score_height // 2 - size - 1)
        for side, logo_x, score_x, code, color in (("home", left_logo, left_score, left, left_zone), ("away", right_logo, right_score, right, right_zone)):
            self._mark(image, self._logo(game, side, 24), (logo_x - size // 2, raised if score_x == logo_x else centered), code, size, color)
        for score_x, score in ((left_score, str(game.get("home_score", ""))), (right_score, str(game.get("away_score", "")))):
            if score:
                outlined(draw, score_x, score_y, score, fonts.big, WHITE, (0, 0, 0, 235))

        if 0 <= spot <= 100:
            spot_x = END_ZONE + spot * PLAY / 100
            target = min(100, spot + to_go) if rightward else max(0, spot - to_go)
            target_x = END_ZONE + target * PLAY / 100
            draw.line([(target_x, 0), (target_x, HEIGHT)], fill=(240, 216, 0, 245), width=2)
            draw.line([(spot_x, 0), (spot_x, HEIGHT)], fill=(30, 60, 180, 240), width=2)
            rx, ry, cy = max(4, int(HEIGHT * 0.13)), max(2, int(HEIGHT * 0.08)), HEIGHT // 2
            draw.ellipse([spot_x - rx, cy - ry, spot_x + rx, cy + ry], fill=(139, 69, 19), outline=(61, 26, 6))
            draw.line([(spot_x - int(rx * 0.7), cy), (spot_x + int(rx * 0.7), cy)], fill=(255, 255, 255, 165))
        return image

    # Soccer.

    def _soccer(self, game: Mapping[str, Any]) -> Image.Image:
        fonts, situation = self._fonts, game.get("situation", {}) or {}
        left_color, right_color = self._color(game, "home"), self._color(game, "away")
        image = self._surfaces.render(("soccer", WIDTH, HEIGHT), fields.soccer_pitch)
        draw = ImageDraw.Draw(image, "RGBA")
        draw.rectangle([0, 0, 3, HEIGHT], fill=left_color)
        draw.rectangle([WIDTH - 4, 0, WIDTH, HEIGHT], fill=right_color)
        left_score, right_score = self._marks_and_scores(image, draw, game, 6, left_color, right_color)
        status = str(game.get("status", "")).strip()[:12]
        if status:
            outlined(draw, WIDTH // 2, HEIGHT // 2, status, fonts.big, STATUS, SHADOW)
        # Goals and red cards sit in the lane between each score and the time. After the swap,
        # an event with is_home false belongs to the left lane.
        goals, cards = situation.get("goal_events") or [], situation.get("red_cards") or []
        lanes = {home: [(event, False) for event in goals if bool(event.get("is_home")) == home]
                 + [(event, True) for event in cards if bool(event.get("is_home")) == home] for home in (False, True)}
        time_width = draw.textlength(status, font=fonts.big) if status else 0
        self._lane(draw, lanes[False], int(left_score + self._score_width(draw, game, "home", "0")), int(WIDTH // 2 - time_width / 2) - 4)
        self._lane(draw, lanes[True], int(WIDTH // 2 + time_width / 2) + 4, int(right_score - self._score_width(draw, game, "away", "0")))
        shootout = situation.get("shootout")
        if shootout:
            for x, kicks in ((RIGHT_MARK_X + MARK + 2, shootout.get("home", [])), (1, shootout.get("away", []))):
                for index in range(5):
                    result = kicks[index] if index < len(kicks) else "pending"
                    color = (50, 200, 70) if result == "goal" else (220, 55, 55) if result == "miss" else (80, 80, 80)
                    draw.rectangle((x, 8 + index * 5, x + 2, 10 + index * 5), fill=color)
        return image

    def _lane(self, draw, lane, left: int, right: int) -> None:
        """Center the goal and card labels in one lane. More than three events use two columns."""
        if not lane:
            return
        width, micro = right - left, self._fonts.micro
        if len(lane) <= 3:
            columns, step, name = [(lane, left + width // 2)], 9, 8
        else:
            # The earlier events go in the left column.
            half = (len(lane) + 1) // 2
            columns, step, name = [(lane[:half], left + width * 30 // 100), (lane[half:], left + width * 68 // 100)], 8, 6
        for column, cx in columns:
            top = HEIGHT // 2 - (len(column) - 1) * step // 2
            for index, (event, card) in enumerate(column):
                y = top + index * step
                own_goal = not card and event.get("own_goal")
                label = f"{str(event.get('player') or '')[:name]} {str(event.get('time') or '')}{'(og)' if own_goal else ''}".strip()
                if not label:
                    continue
                if card:
                    x = int(cx - (7 + draw.textlength(label, font=micro)) / 2)
                    draw.rectangle([x, y - 4, x + 3, y + 2], fill=(220, 30, 30))
                    outlined(draw, x + 7, y, label, micro, (235, 235, 235), OUTLINE, anchor="lm")
                else:
                    outlined(draw, cx, y, label, micro, (150, 150, 150) if own_goal else (235, 235, 235), OUTLINE)

    # Baseball.

    def _baseball(self, game: Mapping[str, Any]) -> Image.Image:
        fonts, situation = self._fonts, game.get("situation", {}) or {}
        left_color, right_color = self._color(game, "home"), self._color(game, "away")
        bases = tuple(bool(situation.get(name, False)) for name in ("onFirst", "onSecond", "onThird"))
        image = self._surfaces.render(("baseball", WIDTH, HEIGHT, bases), lambda: fields.baseball_diamond(*bases))
        fields.smooth_scrim(image)
        draw = ImageDraw.Draw(image, "RGBA")
        # The challenge fields keep the provider sides: the provider away team is on the left.
        self._challenges(draw, 0, 3, situation.get("away_challenges"), situation.get("away_challenges_used"),
                         self._strip_color(game, "home", left_color))
        self._challenges(draw, WIDTH - 4, WIDTH - 1, situation.get("home_challenges"), situation.get("home_challenges_used"),
                         self._strip_color(game, "away", right_color))
        left_score, right_score = self._marks_and_scores(image, draw, game, 6, left_color, right_color)

        inning = game.get("baseball_inning") or {}
        if inning.get("phase") in {"paused", "inactive"}:
            label = str(game.get("status") or "")
            x0, y0, x1, y1 = draw.textbbox((WIDTH // 2, HEIGHT // 2), label, font=fonts.tiny_small, anchor="mm")
            draw.rectangle((x0 - 3, y0 - 2, x1 + 3, y1 + 2), fill=(0, 0, 0, 235))
            outlined(draw, WIDTH // 2, HEIGHT // 2, label, fonts.tiny_small, STATUS, SHADOW)
            return image

        # The inning sits on the side of the batting team, and the count sits on the other side.
        top, bottom = inning.get("half") == "top", inning.get("half") == "bottom"
        inning_x, count_x = (WIDTH // 2 + 40, WIDTH // 2 - 40) if bottom else (WIDTH // 2 - 40, WIDTH // 2 + 40)
        self._inning(draw, inning_x, HEIGHT // 2, top, bottom, ordinal(str(inning["number"])) if inning.get("number") else "")
        if inning.get("phase") == "break":
            return image
        for row, (label, value, color) in enumerate((("B", situation.get("balls", 0), (74, 175, 255)),
                                                     ("S", situation.get("strikes", 0), (255, 136, 0)),
                                                     ("O", situation.get("outs", 0), (224, 48, 48)))):
            draw_tiny(draw, count_x - 8, 4 + row * 8, label, (180, 180, 180))
            draw_tiny(draw, count_x, 4 + row * 8, str(value), color)
        if top:
            self._bat(draw, int(left_score + self._score_width(draw, game, "home") + 8), 7)
        elif bottom:
            self._bat(draw, int(right_score - self._score_width(draw, game, "away") - 8), 7)

        left, right = str(game.get("home_abbr", "")).upper(), str(game.get("away_abbr", "")).upper()
        active = str(situation.get("activeTeam", "")).upper()
        left_bats = bool(left and active and active == left)
        right_bats = bool(right and active and active == right)
        batter, pitcher = batter_lines(situation), pitcher_lines(situation)
        left_lines, right_lines = (batter, pitcher) if left_bats and not right_bats else (pitcher, batter)
        self._player(draw, WIDTH // 2 - 92, left_lines)
        self._player(draw, WIDTH // 2 + 92, right_lines)
        return image

    @staticmethod
    def _strip_color(game: Mapping[str, Any], side: str, fallback):
        """Return a challenge strip color that shows on the panel."""
        primary = parse_hex_color(game.get(f"{side}_color"))
        if primary and not is_near_black(primary):
            return primary
        alternate = parse_hex_color(game.get(f"{side}_alt_color"))
        if alternate and not is_near_black(alternate) and not is_near_white(alternate):
            return alternate
        return alternate or primary or fallback

    @staticmethod
    def _challenges(draw, x0: int, x1: int, remaining, used, color) -> None:
        """Draw a full-height team strip. Each lost challenge cuts an open slot, first at the top and then at the bottom."""
        draw.rectangle([x0, 0, x1, HEIGHT - 1], fill=color)
        lost, left = _count(used), _count(remaining)
        if lost is None and left is not None:
            lost = max(0, 2 - max(0, left))
        if lost is None:
            return
        lost = min(2, max(0, lost))
        x = x0 + (x1 - x0 + 1 - 2) // 2
        if lost >= 1:
            draw.rectangle([x, 1, x + 1, 14], fill=(0, 0, 0, 0))
        if lost >= 2:
            draw.rectangle([x, HEIGHT - 15, x + 1, HEIGHT - 2], fill=(0, 0, 0, 0))

    def _inning(self, draw, cx: int, cy: int, top: bool, bottom: bool, text: str) -> None:
        """Draw the half-inning arrow, the bold inning number, and the small suffix in one row."""
        if not text:
            return
        number = "".join(char for char in text if char.isdigit())
        suffix = "".join(char for char in text if not char.isdigit())
        number_width = draw.textlength(number, font=self._fonts.big)
        x = int(cx - (8 + 2 + number_width + draw.textlength(suffix, font=self._fonts.micro)) / 2)
        middle = x + 4
        if top:
            draw.polygon([(x - 1, cy + 5), (x + 9, cy + 5), (middle, cy - 5)], fill=(0, 0, 0))
            draw.polygon([(x, cy + 4), (x + 8, cy + 4), (middle, cy - 4)], fill=WHITE)
        elif bottom:
            draw.polygon([(x - 1, cy - 5), (x + 9, cy - 5), (middle, cy + 5)], fill=(0, 0, 0))
            draw.polygon([(x, cy - 4), (x + 8, cy - 4), (middle, cy + 4)], fill=WHITE)
        else:
            draw.rectangle([x, cy - 1, x + 8, cy + 1], fill=(180, 180, 180))
        x += 10
        outlined(draw, x + int(number_width / 2), cy, number, self._fonts.big, WHITE, OUTLINE)
        draw.text((x + int(number_width), cy), suffix, font=self._fonts.micro, fill=(190, 190, 190), anchor="lm")

    def _player(self, draw, cx: int, lines) -> None:
        """Draw one batter or pitcher block. A long name uses the smaller font, and it is cut only when it still does not fit."""
        for index, line in enumerate(lines):
            if index == 0:
                text, font = last_name(line), self._fonts.tiny_small
                if text and draw.textlength(text, font=font) > 64:
                    font = self._fonts.micro
                while len(text) > 1 and draw.textlength(text, font=font) > 64:
                    text = text[:-1].rstrip()
            else:
                text, font = ("" if line is None else str(line).strip()[:15]), self._fonts.tiny_small
            if text:
                outlined(draw, int(cx), 7 + index * 9, text, font, WHITE, SHADOW)

    @staticmethod
    def _bat(draw, cx: int, top: int) -> None:
        draw.rectangle([cx - 2, top, cx + 1, top + 7], fill=(220, 180, 120))
        draw.rectangle([cx - 1, top + 8, cx, top + 9], fill=(220, 180, 120))
        draw.rectangle([cx - 1, top + 10, cx, top + 15], fill=(180, 135, 65))
        draw.rectangle([cx - 2, top + 16, cx + 1, top + 17], fill=(150, 105, 40))

    # Hockey and basketball.

    def _rink_or_court(self, game: Mapping[str, Any], sport: str, page: int) -> Image.Image:
        fonts, situation = self._fonts, game.get("situation", {}) or {}
        hockey = "hockey" in sport or "nhl" in sport
        left_color, right_color = self._color(game, "home"), self._color(game, "away")
        image = self._surfaces.render(("hockey",) if hockey else ("basketball",), fields.hockey_rink if hockey else fields.basketball_court)
        draw = ImageDraw.Draw(image, "RGBA")
        period = short_status(game.get("status", ""))
        if period:
            outlined(draw, WIDTH // 2, HEIGHT // 2, period, fonts.big, WHITE, OUTLINE)
        draw.rectangle([0, 0, 2, HEIGHT], fill=left_color)
        draw.rectangle([WIDTH - 3, 0, WIDTH, HEIGHT], fill=right_color)
        left_score, right_score = self._marks_and_scores(image, draw, game, 8, left_color, right_color)
        left_edge = int(left_score + self._score_width(draw, game, "home"))
        right_edge = int(right_score - self._score_width(draw, game, "away"))
        left_badge, right_badge = self._badges(game, sport, situation, hockey)
        for x, badge in ((left_edge + 9, left_badge), (right_edge - 9, right_badge)):
            if badge:
                color = TOURNAMENT_SEED if sport == "march_madness" else EMPTY_NET if badge == "EN" else POWER_PLAY
                outlined(draw, x, 1, badge, fonts.tiny, color, SHADOW, anchor="mt")
        if hockey:
            shootout = situation.get("shootout")
            if shootout:
                draw_hockey_shootout(draw, left_edge + 7, 6, shootout, "away")
                draw_hockey_shootout(draw, right_edge - 12, 6, shootout, "home")
                label = str(shootout.get("roundLabel") or "")
                draw_tiny(draw, WIDTH // 2 - len(label) * 5 // 2, 1, label, (20, 25, 35))
            else:
                self._goals(draw, situation, page)
        return image

    @staticmethod
    def _badges(game: Mapping[str, Any], sport: str, situation: Mapping[str, Any], hockey: bool) -> tuple[str, str]:
        """Return the tournament seeds, or the hockey empty-net or power-play label beside each score."""
        left = right = ""
        if sport == "march_madness":
            left, right = str(game.get("home_seed") or ""), str(game.get("away_seed") or "")
        if hockey and situation.get("emptyNet"):
            side, label = str(situation.get("emptyNetSide") or "").upper(), "EN"
        elif hockey and situation.get("powerPlay"):
            side, label = str(situation.get("powerPlayTeam") or "").upper(), str(situation.get("manpower", {}).get("powerPlayLabel") or "")
        else:
            return left, right
        if side == str(game.get("home_abbr", "")).upper():
            left = label
        elif side == str(game.get("away_abbr", "")).upper():
            right = label
        return left, right

    def _goals(self, draw, situation: Mapping[str, Any], page: int) -> None:
        """Draw the goal labels of each team, three to a page. All teams turn the page together."""
        goals = situation.get("hockeyGoals", ())
        pages = hockey_pages(situation)
        page %= pages
        for side, cx in (("away", 108), ("home", 276)):
            if pages > 1:
                outlined(draw, cx, 2, f"{page + 1}/{pages}", self._fonts.micro, (200, 210, 225), SHADOW)
            own = [goal for goal in goals if goal.get("side") == side]
            for row, goal in enumerate(own[page * GOALS_PER_PAGE:(page + 1) * GOALS_PER_PAGE]):
                outlined(draw, cx, 8 + row * 8, str(goal.get("label") or ""), self._fonts.micro, WHITE, SHADOW)
