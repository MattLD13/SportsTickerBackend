"""Route each content item to the card that draws its family."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from ticker.six.ui.frame import ContentScene, RenderContext, RenderedContent

RACING_SPORTS = {"indycar", "f1", "nascar", "wec", "imsa"}


class Card(Protocol):
    """Draw one content family. The visual key changes exactly when the drawn image can change."""

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        """Draw one content item."""

    def visual_key(self, context: RenderContext, scene: ContentScene, asset_revision: int | None = None) -> object:
        """Return a key that is equal for two scenes only when they draw the same image."""


class DuplicateCardError(ValueError):
    """Report a second card for one family."""


class UnknownCardError(KeyError):
    """Report an item that no card draws."""


def card_family(item: Mapping[str, Any]) -> str:
    """Return the card family of one item."""
    kind, sport = str(item.get("type", "")).lower(), str(item.get("sport", "")).lower()
    if item.get("no_games"):
        return "empty"
    if sport.startswith("clock"):
        return "clock"
    if kind == "racing" or sport in RACING_SPORTS:
        return "racing"
    if kind in {"golf", "masters"} or sport in {"golf", "masters"}:
        return "golf"
    if kind == "music" or sport == "music":
        return "music"
    if kind == "weather":
        return "weather"
    if kind == "stock_ticker" or sport.startswith("stock"):
        return "stock"
    if kind in {"flight_visitor", "flight_airport_hud"}:
        return "flight"
    return "scoreboard"


class CardCatalog:
    """Hold one card for each family."""

    def __init__(self) -> None:
        self._cards: dict[str, Card] = {}

    def register(self, family: str, card: Card) -> None:
        if not family:
            raise ValueError("A card family cannot be empty.")
        if family in self._cards:
            raise DuplicateCardError(f"Card family {family!r} already exists.")
        self._cards[family] = card

    def card(self, item: Mapping[str, Any]) -> Card:
        family = card_family(item)
        try:
            return self._cards[family]
        except KeyError as error:
            raise UnknownCardError(f"No card draws family {family!r}.") from error

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        return self.card(scene.item).render(context, scene)

    def visual_key(self, context: RenderContext, scene: ContentScene, asset_revision: int | None = None) -> object:
        return self.card(scene.item).visual_key(context, scene, asset_revision)
