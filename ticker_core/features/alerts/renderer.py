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
        self._port = PreparedScoreAlertRenderer(fonts, logos)

    def render(self, alert: Mapping[str, Any], elapsed: float, under: Image.Image | None = None) -> Image.Image:
        """Render one deterministic score-alert frame."""
        return self._port.draw_score_alert(dict(alert), elapsed, under)


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
