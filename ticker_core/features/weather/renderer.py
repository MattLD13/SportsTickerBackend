"""Render deterministic animated weather panels."""

from __future__ import annotations

from PIL import Image

from ticker_core.ui.frame import RenderContext
from ticker_core.ui import ContentScene, FontSet, RenderedContent
from .drawing import PreparedWeatherRenderer


class WeatherRenderer:
    """Render weather details without backend or network calls."""

    def __init__(self, fonts: FontSet) -> None:
        self._fonts = fonts

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        """Render a weather content item."""
        return RenderedContent(self.detailed(context, scene.item))

    def detailed(self, context: RenderContext, item: object) -> Image.Image:
        """Render the current weather and forecast view."""
        game = item if isinstance(item, dict) else {}
        return PreparedWeatherRenderer(self._fonts, context.now).draw_weather_detailed(game)
