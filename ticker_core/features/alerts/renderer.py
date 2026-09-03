"""Render alert takeovers and news overlays without controller state."""

from __future__ import annotations

import math
import random
import re
from collections.abc import Mapping
from typing import Any

from PIL import Image, ImageDraw

from ticker_core.features.sports.renderer import LogoSource, pixel_text
from ticker_core.rendering import FontSet
from ticker_core.runtime.model import DEFAULT_SCORE_ALERT_DURATION

from .news_banner_port import PreparedNewsBannerRenderer
from .score_alert_port import PreparedScoreAlertRenderer

PANEL_W = 384
PANEL_H = 32
WIPE_IN = 0.40
WIPE_OUT = 0.35
SLIDE = 0.30
BANNER_W = 192


def _hex(value: Any) -> tuple[int, int, int] | None:
    raw = str(value or "").strip().lstrip("#")
    if len(raw) == 6:
        try:
            return tuple(int(raw[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
        except ValueError:
            pass
    return None


def _scale(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(value * factor))) for value in color)


def _mix(left: tuple[int, int, int], right: tuple[int, int, int], weight: float) -> tuple[int, int, int]:
    return tuple(int(left[index] + (right[index] - left[index]) * weight) for index in range(3))


def _luma(color: tuple[int, int, int]) -> float:
    return 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]


def score_alert_duration(alert: Mapping[str, Any] | None) -> float:
    """Return the full visible duration for one score alert."""
    return DEFAULT_SCORE_ALERT_DURATION


def news_banner_duration(item: Mapping[str, Any] | None) -> float:
    """Return the full visible duration for one news banner."""
    hold = 7.4 if (item or {}).get("domain") == "stocks" else 6.4
    return SLIDE + hold + SLIDE


def _status_label(value: Any, sport: Any) -> str:
    text = str(value or "").upper().strip()
    text = text.replace("PERIOD", "P").replace("QUARTER", "Q")
    text = text.replace("TOP ", "T").replace("BOT ", "B")
    return text[:16]


class ScoreAlertRenderer:
    """Render a full-panel score alert over an optional prior frame."""

    def __init__(self, fonts: FontSet, logos: LogoSource) -> None:
        self._fonts = fonts
        self._logos = logos
        self._port = PreparedScoreAlertRenderer(fonts, logos)

    def render(self, alert: Mapping[str, Any], elapsed: float, under: Image.Image | None = None) -> Image.Image:
        """Render one deterministic score-alert frame."""
        return self._port.draw_score_alert(dict(alert), elapsed, under)

    def _render_implementation(self, alert: Mapping[str, Any], elapsed: float, under: Image.Image | None = None) -> Image.Image:
        """Render without the exact independent alert port."""
        base, accent = self._palette(alert)
        image = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255))
        self._background(image, base, accent, elapsed)
        self._logo_panel(image, alert, base, accent)
        self._score_panel(image, alert, accent)
        self._headline(image, alert, accent, elapsed)
        return self._shutters(image, alert, elapsed, accent, under)

    def _palette(self, alert: Mapping[str, Any]) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
        base = _hex(alert.get("team_color"))
        alt = _hex(alert.get("team_alt_color"))
        if base is None or _luma(base) < 8:
            base = alt if alt is not None and _luma(alt) >= 8 else (40, 90, 190)
        if _luma(base) > 150:
            base = _scale(base, 150 / _luma(base))
        if _luma(base) < 55:
            base = _scale(base, 55 / max(1, _luma(base)))
        if alt is None or _luma(alt) < 8 or _luma(alt) > 240:
            alt = _mix(base, (255, 255, 255), 0.55)
        return base, alt

    @staticmethod
    def _background(image: Image.Image, base: tuple[int, int, int], accent: tuple[int, int, int], elapsed: float) -> None:
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, PANEL_W, PANEL_H), fill=_scale(base, 0.30))
        offset = int(elapsed * 26) % 26
        for x in range(-58, PANEL_W + 58, 26):
            draw.line((x + offset, PANEL_H, x + offset + PANEL_H, 0), fill=_scale(base, 0.62), width=7)
        rail = _scale(accent, 0.55 + 0.25 * math.sin(elapsed * 3.2))
        draw.line((0, 0, PANEL_W, 0), fill=rail)
        draw.line((0, PANEL_H - 1, PANEL_W, PANEL_H - 1), fill=rail)

    def _logo_panel(self, image: Image.Image, alert: Mapping[str, Any], base: tuple[int, int, int], accent: tuple[int, int, int]) -> None:
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 1, 36, 30), fill=_scale(base, 0.12))
        draw.line((37, 1, 37, 30), fill=accent)
        logo = self._logos.get(str(alert.get("team_logo")) if alert.get("team_logo") else None, (24, 24))
        if logo is not None:
            image.paste(logo, (6, 4), logo)
        else:
            pixel_text(draw, str(alert.get("team_abbr", ""))[:3], 5, 13, (235, 235, 235))

    def _score_panel(self, image: Image.Image, alert: Mapping[str, Any], accent: tuple[int, int, int]) -> None:
        draw = ImageDraw.Draw(image)
        x = 288
        draw.rectangle((x - 1, 1, PANEL_W, 30), fill=(0, 0, 0, 190))
        draw.line((x - 2, 1, x - 2, 30), fill=_scale(accent, 0.5))
        scorer = str(alert.get("team_abbr", "")).upper()
        for index, (abbr, score) in enumerate(((alert.get("away_abbr", ""), alert.get("away_score")), (alert.get("home_abbr", ""), alert.get("home_score")))):
            top = 1 + index * 12
            bright = str(abbr).upper() == scorer
            color = (255, 255, 255) if bright else (110, 110, 118)
            if bright:
                draw.rectangle((x + 1, top, x + 2, top + 10), fill=accent)
            pixel_text(draw, str(abbr)[:3], x + 6, top + 2, color)
            draw.text((381, top + 5), str(score if score is not None else ""), font=self._fonts.medium, fill=color, anchor="rm")
        raw = str(alert.get("status", ""))
        sport = str(alert.get("sport", "")).lower()
        if any(name in sport for name in ("mlb", "baseball", "wbc")):
            inning = re.search(r"\d+", raw)
            if inning and "FINAL" not in raw.upper():
                arrow = "▲" if "TOP" in raw.upper() or raw.startswith("^") else "▼" if "BOT" in raw.upper() or raw.startswith("V") else ""
                if arrow:
                    pixel_text(draw, arrow + inning.group(), x + 6, 25, (200, 200, 210))
                    return
        pixel_text(draw, _status_label(raw, sport), x + 6, 25, (200, 200, 210))

    def _headline(self, image: Image.Image, alert: Mapping[str, Any], accent: tuple[int, int, int], elapsed: float) -> None:
        draw = ImageDraw.Draw(image)
        headline = str(alert.get("headline", "SCORE")).upper()
        detail = str(alert.get("detail", "")).upper()
        text = self._flap(headline, elapsed)
        font = self._fonts.huge
        if draw.textlength(headline, font=font) > 240:
            font = self._fonts.big
        draw.text((163, 11 if detail else 16), text, font=font, fill=(255, 255, 255), stroke_width=1, stroke_fill=(0, 0, 0), anchor="mm")
        if detail and text == headline:
            draw.text((163, 26), detail, font=self._fonts.tiny, fill=_mix(accent, (255, 255, 255), 0.4), stroke_width=1, stroke_fill=(0, 0, 0), anchor="mm")

    @staticmethod
    def _flap(text: str, elapsed: float) -> str:
        settled = int(max(0.0, elapsed - WIPE_IN) / 0.055)
        if settled >= len(text):
            return text
        randomizer = random.Random(int(elapsed * 24))
        return "".join(character if index < settled or not character.isalnum() else randomizer.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for index, character in enumerate(text))

    @staticmethod
    def _shutters(image: Image.Image, alert: Mapping[str, Any], elapsed: float, accent: tuple[int, int, int], under: Image.Image | None) -> Image.Image:
        total = score_alert_duration(alert)
        if elapsed < WIPE_IN:
            t = elapsed / WIPE_IN
            fraction = t * t * (3 - 2 * t)
        elif elapsed >= total - WIPE_OUT:
            t = min(1.0, (elapsed - (total - WIPE_OUT)) / WIPE_OUT)
            fraction = 1 - t * t
        else:
            fraction = 1.0
        if fraction >= 1:
            return image.convert("RGB")
        backdrop = under.convert("RGB").copy() if under is not None else Image.new("RGB", (PANEL_W, PANEL_H), (0, 0, 0))
        half = int(PANEL_W * fraction / 2)
        if half <= 0:
            return backdrop
        center = PANEL_W // 2
        backdrop.paste(image.convert("RGB").crop((center - half, 0, center + half, PANEL_H)), (center - half, 0))
        draw = ImageDraw.Draw(backdrop)
        draw.line((center - half, 0, center - half, PANEL_H), fill=accent)
        draw.line((center + half, 0, center + half, PANEL_H), fill=accent)
        return backdrop


class NewsBannerRenderer:
    """Render the left-half live-news overlay."""

    def __init__(self, fonts: FontSet) -> None:
        self._fonts = fonts
        self._port = PreparedNewsBannerRenderer()

    def render(self, item: Mapping[str, Any]) -> Image.Image:
        """Render a stable trade or market banner."""
        return self._port.draw_news_banner(dict(item))

    def apply(self, frame: Image.Image, item: Mapping[str, Any], elapsed: float) -> Image.Image:
        """Composite the animated banner over one normal ticker frame."""
        return self._port.apply_news_banner(frame, dict(item), elapsed)

    @staticmethod
    def _ease(value: float) -> float:
        value = max(0.0, min(1.0, value))
        return 1 - (1 - value) ** 3

    def _trade(self, item: Mapping[str, Any]) -> Image.Image:
        image = Image.new("RGBA", (BANNER_W, PANEL_H), (8, 9, 12, 255))
        draw = ImageDraw.Draw(image)
        amber = (255, 176, 20)
        source = self._readable(_hex(item.get("from_color")) or (139, 147, 163))
        target = self._readable(_hex(item.get("to_color")) or (139, 147, 163))
        kind = str(item.get("kind") or "TRADE")[:6]
        draw.rectangle((0, 0, 2, 31), fill=amber)
        draw.rectangle((4, 0, 191, 10), fill=(22, 24, 30))
        draw.rectangle((6, 1, 8 + len(kind) * 5, 9), fill=amber)
        pixel_text(draw, kind, 8, 3, (10, 10, 12))
        x = 14 + len(kind) * 5
        pixel_text(draw, str(item.get("from_abbr", ""))[:4], x, 2, source)
        self._arrow(draw, x + 4 + len(str(item.get("from_abbr", ""))[:4]) * 4, 4, 13, source, target)
        destination = str(item.get("to_abbr", ""))[:4]
        chip = x + 23 + len(str(item.get("from_abbr", ""))[:4]) * 4
        draw.rectangle((chip, 1, chip + len(destination) * 5 + 5, 10), fill=target)
        pixel_text(draw, destination, chip + 3, 2, (10, 10, 12) if _luma(target) > 150 else (255, 255, 255))
        draw.line((4, 11, 191, 11), fill=(52, 56, 66))
        lines = self._lines(item.get("text"), 2)
        for index, line in enumerate(lines):
            pixel_text(draw, line, 7, 20 if len(lines) == 1 else 15 + index * 9, (255, 255, 255) if index == 0 else (206, 211, 222))
        return image

    def _stock(self, item: Mapping[str, Any]) -> Image.Image:
        image = Image.new("RGBA", (BANNER_W, PANEL_H), (8, 9, 12, 255))
        draw = ImageDraw.Draw(image)
        try:
            percent = float(item.get("pct") or 0.0)
        except (TypeError, ValueError):
            percent = 0.0
        accent = (60, 205, 95) if percent >= 0 else (235, 75, 75)
        draw.rectangle((0, 0, 2, 31), fill=accent)
        draw.rectangle((4, 0, 191, 9), fill=(22, 24, 30))
        draw.rectangle((6, 1, 34, 8), fill=(70, 175, 255))
        pixel_text(draw, "NEWS", 8, 2, (8, 10, 14))
        pixel_text(draw, str(item.get("to_abbr", ""))[:6], 40, 1, (255, 255, 255))
        if item.get("pct") is not None:
            label = f"{percent:+.1f}%"
            pixel_text(draw, label, 187 - len(label) * 4, 2, accent)
        draw.line((4, 10, 191, 10), fill=(52, 56, 66))
        for index, line in enumerate(self._lines(item.get("text"), 3)):
            pixel_text(draw, line, 7, 12 + index * 7, (255, 255, 255) if index == 0 else (203, 209, 220))
        return image

    @staticmethod
    def _readable(color: tuple[int, int, int]) -> tuple[int, int, int]:
        brightness = _luma(color)
        if brightness >= 95:
            return color
        return _scale(color, 95 / max(1, brightness))

    @staticmethod
    def _arrow(draw: ImageDraw.ImageDraw, x: int, y: int, length: int, left: tuple[int, int, int], right: tuple[int, int, int]) -> None:
        for index in range(length):
            shade = _mix(left, right, index / max(1, length - 1))
            draw.point((x + index, y), fill=shade)
            draw.point((x + index, y + 1), fill=shade)
        draw.polygon(((x + length, y - 2), (x + length, y + 3), (x + length + 3, y + 1)), fill=right)

    @staticmethod
    def _lines(text: Any, max_lines: int) -> list[str]:
        lines = [""]
        for word in str(text or "").upper().split():
            candidate = f"{lines[-1]} {word}".strip()
            if len(candidate) <= 35:
                lines[-1] = candidate
            elif len(lines) < max_lines:
                lines.append(word)
            else:
                lines[-1] = lines[-1][:34] + "."
                break
        return lines
