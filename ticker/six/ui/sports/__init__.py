"""Draw sports items: a score card in the strip, a pinned game across the panel, or a campaign card."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PIL import Image

from ticker.six.ui.frame import ContentScene, ItemKey, RenderContext, RenderedContent
from ticker.six.ui.text import FontSet
from ticker.six.ui.sports.ad import ad_card, is_ad
from ticker.six.ui.sports.logos import team_logo
from ticker.six.ui.sports.pane import PaneCard
from ticker.six.ui.sports.pinned import PinnedCard, hockey_pages

PAGE_SECONDS = 5


def _pinned(item: Mapping[str, Any]) -> bool:
    return item.get("sports_presentation") == "pinned"


class SportsCard:
    """Draw one sports item from prepared logos. Drawing does no I/O."""

    def __init__(self, fonts: FontSet, logos) -> None:
        self._logos = logos
        self._pane = PaneCard(logos)
        self._pinned = PinnedCard(fonts, logos)
        self._key = ItemKey("scoreboard")
        self._asset_item: Mapping[str, Any] | None = None
        self._asset_revision: int | None = None
        self._logos_ready = (False, False)

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        if _pinned(scene.item):
            return RenderedContent(self.pinned(scene.item, int(context.now.timestamp()) // PAGE_SECONDS))
        return RenderedContent(self.card(scene.item))

    def card(self, item: Mapping[str, Any]) -> Image.Image:
        """Return the 32-pixel strip card of one game or campaign."""
        return ad_card(item, self._logos) if is_ad(item) else self._pane.card(item)

    def pinned(self, item: Mapping[str, Any], page: int = 0) -> Image.Image:
        """Return the 384 by 32 pinned layout of one game. The page selects the hockey goal page."""
        return self._pinned.frame(item, page)

    def visual_key(self, context: RenderContext, scene: ContentScene, asset_revision: int | None = None) -> object:
        """Change the key when the item, its logos, or the hockey goal page changes.

        A pinned game reads only its two logos, so other asset changes keep its key.
        """
        item = scene.item
        pages = hockey_pages(item.get("situation") or {}) if _pinned(item) and str(item.get("sport") or "").lower() in {"nhl", "hockey"} else 1
        page = (int(context.now.timestamp()) // PAGE_SECONDS) % pages if pages > 1 else None
        if not _pinned(item):
            return self._key(scene, asset_revision, page)
        if item is not self._asset_item or asset_revision != self._asset_revision:
            self._asset_item, self._asset_revision = item, asset_revision
            self._logos_ready = tuple(bool(team_logo(self._logos, str(item.get(f"{side}_logo") or "") or None, (24, 24),
                                                     item.get(f"{side}_logo_rendering"))) for side in ("home", "away"))
        return self._key(scene, self._logos_ready, page)


__all__ = ["SportsCard"]
