"""Draw the full-panel score alert: who scored, what happened, and the score.

The alert answers three questions in the order a fan asks them: who (the logo and team colors),
what (the headline, such as "GRAND SLAM"), and the new score. The panels limit current, so the
background is a third of the team color. Only the headline and the accent rails are bright.
"""
from __future__ import annotations

import math
import random
import re
from collections.abc import Mapping
from typing import Any

from PIL import Image, ImageDraw

from ticker.panel.content import DEFAULT_SCORE_ALERT_DURATION

from ticker.panel.frame import Logos
from ticker.panel.palette import is_near_black, is_near_white, parse_hex_color
from ticker.panel.text import FontSet, draw_hybrid, draw_tiny, load_monospace_font

WIDTH, HEIGHT = 384, 32
WIPE_IN, WIPE_OUT = 0.40, 0.35
# The headline flips like a split-flap board. Letters land left to right after the shutters open.
# A monospace face keeps the width steady while the letters cycle.
FLAP_STEP = 0.055
FLAP_CHARACTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
FLAP_SIZES = (20, 16, 13)
SCORE_PANEL, LOGO_PANEL = 96, 38
FACT_TOP, FACT_HEIGHT, FACT_PAD, FACT_GAP = 21, 9, 5, 2
DIM = (110, 110, 118)
STATUS_TEXT = (200, 200, 210)
FACT_KEYS = ("player", "data", "primary_assist", "secondary_assist")


class ScoreAlert:
    def __init__(self, fonts: FontSet, logos: Logos) -> None:
        self._score_font = fonts.medium
        self._logos = logos
        self._flap_fonts = [load_monospace_font(size, bold=True) for size in FLAP_SIZES]

    def frame(self, alert: Mapping[str, Any], elapsed: float, under: Image.Image | None = None) -> Image.Image:
        """Draw the alert at `elapsed` seconds. The shutters open over `under`, the frame before the alert."""
        alert = dict(alert)
        base, accent = self._palette(alert)
        image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
        _background(image, base, accent, elapsed)
        self._logo_panel(image, alert, base, accent)
        self._score_panel(image, alert, accent, _readable(base))
        self._headline(image, alert, accent, elapsed)
        return _shutters(image, elapsed, accent, under)

    def _logo(self, alert: Mapping[str, Any]) -> Image.Image | None:
        url = alert.get("team_logo")
        return self._logos.get(str(url) if url else None, (24, 24))

    def _palette(self, alert: Mapping[str, Any]) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
        """Return a base and an accent color that stay visible on the dark panel.

        A near-black primary takes the main logo color, then the alternate color, then blue.
        A near-black or near-white alternate becomes a light tint of the base.
        """
        base = parse_hex_color(alert.get("team_color"))
        alternate = parse_hex_color(alert.get("team_alt_color"))
        if not base or is_near_black(base):
            dominant = _logo_colors(self._logo(alert))
            base = dominant[0] if dominant else (alternate if alternate and not is_near_black(alternate) else (40, 90, 190))
        if _luma(base) > 150:
            # A bright gold field draws too much current and hides the white headline.
            base = _scale(base, 150.0 / _luma(base))
        if _luma(base) < 55:
            # Scale a dark color up. Mixed with white, navy becomes grey.
            base = _scale(base, 55.0 / max(1.0, _luma(base)))
        if not alternate or is_near_black(alternate) or is_near_white(alternate):
            alternate = _mix(base, (255, 255, 255), 0.55)
        return base, alternate

    def _logo_panel(self, image: Image.Image, alert: Mapping[str, Any], base, accent) -> None:
        draw = ImageDraw.Draw(image, "RGBA")
        draw.rectangle([0, 1, LOGO_PANEL - 2, HEIGHT - 2], fill=_scale(base, 0.12))
        draw.line([(LOGO_PANEL - 1, 1), (LOGO_PANEL - 1, HEIGHT - 2)], fill=accent)
        logo = self._logo(alert)
        if logo is not None:
            image.paste(logo, ((LOGO_PANEL - 1 - 24) // 2, 4), logo)
        else:
            draw_tiny(draw, 5, 13, str(alert.get("team_abbr", ""))[:3], _readable(base))

    def _score_panel(self, image: Image.Image, alert: Mapping[str, Any], accent, team_color) -> None:
        """Draw the away and home rows and the game status on a dark scrim at the right."""
        draw = ImageDraw.Draw(image, "RGBA")
        x0 = WIDTH - SCORE_PANEL
        draw.rectangle([x0 - 1, 1, WIDTH, HEIGHT - 2], fill=(0, 0, 0, 190))
        draw.line([(x0 - 2, 1), (x0 - 2, HEIGHT - 2)], fill=_scale(accent, 0.5))
        scorer = str(alert.get("team_abbr", "")).upper()
        for index, side in enumerate(("away", "home")):
            top = 1 + index * 12
            abbreviation, score = str(alert.get(f"{side}_abbr", "")), alert.get(f"{side}_score")
            scored = abbreviation.upper() == scorer
            if scored:
                draw.rectangle([x0 + 1, top, x0 + 2, top + 10], fill=accent)
            draw_hybrid(draw, x0 + 6, top + 2, abbreviation[:3], team_color if scored else DIM)
            draw.text((WIDTH - 3, top + 5), str(score if score is not None else ""), font=self._score_font,
                      fill=(255, 255, 255) if scored else DIM, anchor="rm")
        # The status is neutral grey: a dark team color is not readable at 5 pixels on the scrim.
        marker, status = _status(alert)
        x = x0 + 6
        if marker == "▲":
            draw.polygon([(x + 2, 26), (x + 4, 28), (x, 28)], fill=STATUS_TEXT)
        elif marker == "▼":
            draw.polygon([(x, 26), (x + 4, 26), (x + 2, 28)], fill=STATUS_TEXT)
        elif marker:
            draw_tiny(draw, x, 26, marker, STATUS_TEXT)
        if marker:
            x += 7
        if status:
            draw_tiny(draw, x, 25, status, STATUS_TEXT)
        _down(draw, str(alert.get("down_distance") or "").strip(), WIDTH - 3, alert.get("is_red_zone"))

    def _headline(self, image: Image.Image, alert: Mapping[str, Any], accent, elapsed: float) -> None:
        """Draw the headline between the panels, and the fact boxes once the headline settles."""
        draw = ImageDraw.Draw(image, "RGBA")
        left, right = LOGO_PANEL + 4, WIDTH - SCORE_PANEL - 5
        headline = str(alert.get("headline", "SCORE")).upper()
        # The largest face that fits. A headline that does not fit at the smallest face is clipped.
        font = next((font for font in self._flap_fonts if draw.textlength(headline, font=font) <= right - left), self._flap_fonts[-1])
        y = 10 if any(alert.get(key) for key in FACT_KEYS) else HEIGHT // 2 - 1
        shown = _flap(headline, elapsed)
        center = (left + right) // 2
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx or dy:
                    draw.text((center + dx, y + dy), shown, font=font, fill=(0, 0, 0), anchor="mm")
        draw.text((center, y), shown, font=font, fill=(255, 255, 255), anchor="mm")
        if shown == headline:
            _fact_boxes(image, alert, accent, left, right)


def fact_layout(alert: Mapping[str, Any], left: int, right: int) -> list[tuple[str, str, int, int]]:
    """Fit the player, play, and assist boxes between `left` and `right`. Return (kind, text, x, width) for each box.

    The play text drops the player name and the headline words, which other parts already show.
    When the boxes are too wide, the player name shortens to initials, then to the surname, then text is cut.
    """
    headline = set(re.findall(r"[A-Z0-9]+", str(alert.get("headline") or "").upper()))
    player = str(alert.get("player") or "").upper().split()
    play = str(alert.get("data") or "").strip().split()
    if player and play:
        folded = [_fold(word) for word in play]
        name = [_fold(word) for word in player]
        for start in range(len(folded) - len(name) + 1):
            if folded[start:start + len(name)] == name:
                del play[start:start + len(name)]
                break
    play = [word for word in play if _fold(word) not in headline]
    assists = [str(alert.get(key) or "").strip().upper().rsplit(" ", 1)[-1]
               for key in ("primary_assist", "secondary_assist") if str(alert.get(key) or "").strip()]
    prefix = "ASSIST: " if len(assists) == 1 else "ASSISTS: "
    fields = [(kind, value.upper()) for kind, value in (
        ("player", str(alert.get("player") or "").strip()), ("data", " ".join(play)),
        ("assists", prefix + ", ".join(assists) if assists else "")) if value]
    if not fields:
        return []
    room = right - left
    if _boxes_width(fields) > room:
        fields = [(kind, _initials(value) if kind == "player" else value) for kind, value in fields]
    if _boxes_width(fields) > room:
        fields = [(kind, value.rsplit(" ", 1)[-1] if kind == "player" else value) for kind, value in fields]
    limits = _share([len(value) for _, value in fields], (room - 2 * FACT_PAD * len(fields) - FACT_GAP * (len(fields) - 1)) // 5)
    fitted = []
    for (kind, value), limit in zip(fields, limits):
        if kind == "assists" and len(value) > limit:
            names = _share([len(name) for name in assists], limit - len(prefix) - 2 * (len(assists) - 1))
            value = prefix + ", ".join(_cut(name, name_limit) for name, name_limit in zip(assists, names))
        else:
            value = _cut(value, limit)
        fitted.append((kind, value))
    widths = [len(value) * 5 + 2 * FACT_PAD for _, value in fitted]
    x = left + max(0, (room - (sum(widths) + FACT_GAP * (len(widths) - 1))) // 2)
    layout = []
    for (kind, value), width in zip(fitted, widths):
        layout.append((kind, value, x, width))
        x += width + FACT_GAP
    return layout


def _fact_boxes(image: Image.Image, alert: Mapping[str, Any], accent, left: int, right: int) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    border = _mix(accent, (255, 255, 255), 0.4)
    for _, value, x, width in fact_layout(alert, left, right):
        draw.rounded_rectangle((x - 1, FACT_TOP, x + width, FACT_TOP + FACT_HEIGHT), radius=2, fill=(0, 0, 0, 180))
        draw.rounded_rectangle((x, FACT_TOP, x + width - 1, FACT_TOP + FACT_HEIGHT - 1), radius=2, fill=(12, 14, 20, 240),
                               outline=border, width=1)
        draw_tiny(draw, x + FACT_PAD, FACT_TOP + 2, value, (255, 255, 255))


def _background(image: Image.Image, base, accent, elapsed: float) -> None:
    """Fill the team color with chevrons that sweep across, and two accent rails that pulse."""
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size
    draw.rectangle([0, 0, width, height], fill=_scale(base, 0.30))
    stripe, spacing = _scale(base, 0.62), 26
    offset = int(elapsed * spacing) % spacing
    for x in range(-height - spacing, width + spacing, spacing):
        draw.line([(x + offset, height), (x + offset + height, 0)], fill=stripe, width=7)
    # The rails stay under full brightness: two light rows across the panel draw the most current.
    rail = _scale(accent, 0.55 + 0.25 * math.sin(elapsed * 3.2))
    draw.line([(0, 0), (width, 0)], fill=rail)
    draw.line([(0, height - 1), (width, height - 1)], fill=rail)


def _shutters(image: Image.Image, elapsed: float, accent, under: Image.Image | None) -> Image.Image:
    """Open the alert from the center over the frame below it, and close it the same way."""
    closing = DEFAULT_SCORE_ALERT_DURATION - WIPE_OUT
    if elapsed < WIPE_IN:
        t = elapsed / WIPE_IN
        opened = t * t * (3 - 2 * t)
    elif elapsed >= closing:
        t = min(1.0, (elapsed - closing) / WIPE_OUT)
        opened = 1.0 - t * t
    else:
        opened = 1.0
    if opened >= 1.0:
        return image.convert("RGB")
    backdrop = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    if under is not None:
        backdrop.paste(under.convert("RGB"), (0, 0))
    half = int((WIDTH / 2) * max(0.0, opened))
    if half <= 0:
        return backdrop
    center = WIDTH // 2
    backdrop.paste(image.convert("RGB").crop((center - half, 0, center + half, HEIGHT)), (center - half, 0))
    # Bright leading edges make the shutters look like light that moves outward.
    draw = ImageDraw.Draw(backdrop)
    draw.line([(center - half, 0), (center - half, HEIGHT)], fill=accent)
    draw.line([(center + half, 0), (center + half, HEIGHT)], fill=accent)
    return backdrop


def _flap(text: str, elapsed: float) -> str:
    """Return the headline mid-flip: settled letters on the left, cycling letters on the right."""
    settled = int(max(0.0, elapsed - WIPE_IN) / FLAP_STEP)
    if settled >= len(text):
        return text
    # The frame index seeds the scramble, so one moment always draws the same letters.
    rng = random.Random(int(elapsed * 24))
    return "".join(char if index < settled or not char.isalnum() else rng.choice(FLAP_CHARACTERS)
                   for index, char in enumerate(text))


def _status(alert: Mapping[str, Any]) -> tuple[str, str]:
    """Return the inning marker and the status text. Baseball shows an up or down arrow for the half inning."""
    sport, raw = str(alert.get("sport", "")).lower(), str(alert.get("status", ""))
    upper = raw.upper()
    if any(word in sport for word in ("mlb", "baseball", "wbc")) and not any(word in upper for word in ("FINAL", "DELAY", "SUSP", "PPD")):
        inning = re.search(r"\d+", raw)
        if inning:
            if "TOP" in upper or "^" in upper:
                return "▲", inning.group()
            if "BOT" in upper or "V" in upper:
                return "▼", inning.group()
            if any(word in upper for word in ("MID", "MIDDLE", "END")):
                return "-", inning.group()
    if not raw:
        return "", ""
    for old, new in (("TOP ", "^"), ("BOTTOM ", "V"), ("BOT ", "V")):
        upper = upper.replace(old, new)
    return "", upper[:16]


def _down(draw: ImageDraw.ImageDraw, value: str, right: int, red_zone: object) -> None:
    """Draw the down and distance beside the clock. Red is the red zone, and green is outside it."""
    match = re.fullmatch(r"\s*(\d+)\s*&\s*(\d+|GOAL)\s*", value, re.IGNORECASE)
    if not match:
        return
    text = f"{match.group(1)}&{'G' if match.group(2).upper() == 'GOAL' else match.group(2)}"
    x = right - (len(text) * 5 + 6)
    color = (255, 91, 104) if red_zone is True else (69, 220, 120) if red_zone is False else (220, 224, 230)
    draw.rounded_rectangle((x, 23, right, 31), radius=1, fill=(0, 0, 0, 230), outline=(105, 112, 120, 210), width=1)
    draw_tiny(draw, x + 3, 25, text, color)


def _logo_colors(logo: Image.Image | None) -> list[tuple[int, int, int]]:
    """Return the most common visible color of a logo, or nothing."""
    if logo is None:
        return []
    colors = logo.convert("RGBA").resize((24, 24), Image.NEAREST).getcolors(576) or []
    for _, color in sorted(colors, key=lambda item: item[0], reverse=True):
        if color[3] >= 90 and not is_near_black(color[:3]):
            return [tuple(int(value) for value in color[:3])]
    return []


def _boxes_width(fields: list[tuple[str, str]]) -> int:
    return sum(len(value) * 5 + 2 * FACT_PAD for _, value in fields) + FACT_GAP * (len(fields) - 1)


def _share(lengths: list[int], room: int) -> list[int]:
    """Cut the longest length by one until the lengths fit in `room` characters."""
    limits = list(lengths)
    while sum(limits) > room:
        index = max(range(len(limits)), key=limits.__getitem__)
        limits[index] -= 1
    return limits


def _cut(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] if limit < 3 else value[:limit - 2].rstrip() + ".."


def _initials(value: str) -> str:
    """Shorten a name to initials and the full surname."""
    parts = str(value or "").upper().split()
    return "".join(parts) if len(parts) < 2 else " ".join([*(f"{part[0]}." for part in parts[:-1]), parts[-1]])


def _fold(word: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", word.upper())


def _readable(color) -> tuple[int, int, int]:
    """Lift a dark team color enough to read on the score scrim."""
    luminance = _luma(color)
    return color if luminance >= 140 else _mix(color, (255, 255, 255), (140.0 - luminance) / max(1.0, 255.0 - luminance))


def _scale(color, factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(channel * factor))) for channel in color[:3])


def _mix(a, b, t: float) -> tuple[int, int, int]:
    return tuple(int(a[index] + (b[index] - a[index]) * t) for index in range(3))


def _luma(color) -> float:
    return 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]
