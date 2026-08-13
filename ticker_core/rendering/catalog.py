"""Route content families without controller inheritance."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from ticker_core.context import RenderContext

from .model import ContentScene, RenderedContent


class ContentRenderer(Protocol):
    """Render one normalized content family."""

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        """Render one content item."""


class DuplicateContentRendererError(ValueError):
    """Report duplicate ownership for one content family."""


class UnknownContentRendererError(KeyError):
    """Report content without an installed renderer."""


def content_family(item: Mapping[str, Any], mode: str) -> str:
    """Return the stable renderer family for one backend item."""
    item_type = str(item.get("type", "")).lower()
    sport = str(item.get("sport", "")).lower()
    lowered_mode = mode.lower()
    if item.get("no_games"):
        return "empty"
    if sport == "clock" or sport.startswith("clock"):
        return "clock"
    if item_type == "racing" or sport in {"indycar", "f1", "nascar"}:
        return "racing"
    if item_type in {"golf", "masters"} or sport in {"golf", "masters"}:
        return "golf"
    if item_type == "music" or sport == "music":
        return "music"
    if item_type == "weather":
        return "weather"
    if item_type == "stock_ticker" or sport.startswith("stock"):
        return "stock"
    if item_type == "leaderboard":
        return "leaderboard"
    if item_type in {"flight_visitor", "flight_airport_hud"}:
        return "flight"
    return "scoreboard"


class ContentRendererCatalog:
    """Own explicit content-family renderer registrations."""

    def __init__(self) -> None:
        self._renderers: dict[str, ContentRenderer] = {}

    def register(self, family: str, renderer: ContentRenderer) -> None:
        """Register one renderer family."""
        if not family:
            raise ValueError("A content family cannot be empty.")
        if family in self._renderers:
            raise DuplicateContentRendererError(f"Renderer family {family!r} already exists.")
        self._renderers[family] = renderer

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        """Resolve and render one content scene."""
        family = content_family(scene.item, scene.mode)
        try:
            renderer = self._renderers[family]
        except KeyError as error:
            raise UnknownContentRendererError(f"No renderer owns content family {family!r}.") from error
        return renderer.render(context, scene)
