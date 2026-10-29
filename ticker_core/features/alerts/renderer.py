"""Render alert takeovers and news overlays without controller state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PIL import Image

from ticker_core.features.sports.renderer import LogoSource
from ticker_core.ui import FontSet

from .news_banner import PreparedNewsBannerRenderer
from .score_alert import PreparedScoreAlertRenderer


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
        self._port = PreparedNewsBannerRenderer()

    def render(self, item: Mapping[str, Any]) -> Image.Image:
        """Render a stable trade or market banner."""
        return self._port.draw_news_banner(dict(item))

    def apply(self, frame: Image.Image, item: Mapping[str, Any], elapsed: float) -> Image.Image:
        """Composite the animated banner over one normal ticker frame."""
        return self._port.apply_news_banner(frame, dict(item), elapsed)
