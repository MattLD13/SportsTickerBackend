"""Route content families without controller inheritance."""

from __future__ import annotations

from collections.abc import Mapping
import json
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

    def visual_key(self, context: RenderContext, scene: ContentScene, asset_revision: int | None = None) -> object:
        """Return one renderer-owned key without rasterizing the scene."""
        family = content_family(scene.item, scene.mode)
        try:
            renderer = self._renderers[family]
        except KeyError as error:
            raise UnknownContentRendererError(f"No renderer owns content family {family!r}.") from error
        method = getattr(renderer, "visual_key", None)
        if callable(method):
            return method(context, scene, asset_revision)
        phase = _family_phase(family, scene.item, context, scene.elapsed)
        return (family, _stable_item(scene.item), scene.mode, asset_revision, phase)


def _stable_item(item: Mapping[str, Any]) -> str:
    """Serialize one small content mapping for invalidation."""
    return json.dumps(item, sort_keys=True, default=str, separators=(",", ":"))


def _family_phase(family: str, item: Mapping[str, Any], context: RenderContext, elapsed: float = 0.0) -> int | None:
    """Own cadence facts for renderers without local animation state."""
    timestamp = context.now.timestamp()
    if family in {"music", "weather", "racing"}:
        return int(timestamp * 30)
    if family == "golf" and str(item.get("sports_presentation", "")).lower() == "pinned":
        return int(max(0.0, elapsed) // 4.0)
    if family == "clock":
        return int(timestamp)
    return None
