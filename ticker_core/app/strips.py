"""Build and retain seamless strips outside the runtime state machine."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
from threading import Lock
from time import sleep
from typing import Any

from PIL import Image, ImageDraw

from ticker_core.context import RenderContext
from ticker_core.rendering import ContentRendererCatalog, ContentScene
from ticker_core.runtime import Content, StripLayout, StripSegment


@dataclass(frozen=True, slots=True)
class PreparedStrip:
    """Hold one completed strip until the display thread installs it."""

    key: str
    mode: str
    layout: StripLayout | None
    image: Image.Image | None
    item_ids: tuple[str, ...] = ()
    card_keys: tuple[str, ...] = ()
    cards: tuple[Image.Image, ...] = ()
    generation: int = 0


class StripRepository:
    """Build and retain the current seamless strip."""

    def __init__(self, catalog: ContentRendererCatalog) -> None:
        self._catalog = catalog
        self._payload_key: str | None = None
        self._mode: str | None = None
        self._image: Image.Image | None = None
        self._card_cache: OrderedDict[str, Image.Image] = OrderedDict()
        self._cache_lock = Lock()
        self._cache_generation = 0
        self._active_item_ids: tuple[str, ...] = ()
        self._active_card_keys: tuple[str, ...] = ()
        self._active_cards: tuple[Image.Image, ...] = ()
        self._active_generation = 0

    def build(
        self,
        payload_key: str,
        items: Iterable[Content],
        context: RenderContext,
        mode: str,
    ) -> StripLayout | None:
        """Build and install a seamless strip for simple callers."""
        prepared = self.prepare(payload_key, items, context, mode)
        self.install(prepared)
        return prepared.layout

    def prepare(
        self,
        payload_key: str,
        items: Iterable[Content],
        context: RenderContext,
        mode: str,
    ) -> PreparedStrip:
        """Build a strip without changing the active display image."""
        cards: list[tuple[Content, Image.Image]] = []
        card_keys: list[str] = []
        for item in tuple(items)[:60]:
            key = _card_key(item, mode)
            with self._cache_lock:
                card = self._card_cache.pop(key, None)
                card_generation = self._cache_generation
            if card is None:
                rendered = self._catalog.render(context, ContentScene(_plain_mapping(item.data), mode))
                card = rendered.image.convert("RGBA")
                with self._cache_lock:
                    if card_generation == self._cache_generation:
                        self._card_cache[key] = card
            else:
                with self._cache_lock:
                    self._card_cache[key] = card
            cards.append((item, card))
            card_keys.append(key)
        with self._cache_lock:
            while len(self._card_cache) > 256:
                self._card_cache.popitem(last=False)
            generation = self._cache_generation
        if not cards:
            return PreparedStrip(payload_key, mode, None, None, generation=generation)
        item_ids = tuple(item.id for item, _ in cards)
        card_keys = tuple(card_keys)
        card_images = tuple(card for _, card in cards)
        segments = tuple(StripSegment(item.id, card.width + 1) for item, card in cards)
        width = sum(segment.width for segment in segments)
        with self._cache_lock:
            base_image = self._image
            base_item_ids = self._active_item_ids
            base_card_keys = self._active_card_keys
            base_cards = self._active_cards
            base_generation = self._active_generation
        if (
            base_image is not None
            and base_item_ids == item_ids
            and len(base_cards) == len(card_images)
            and base_generation == generation
            and all(old.width == new.width for old, new in zip(base_cards, card_images))
        ):
            changed = {index for index, (old_key, new_key) in enumerate(zip(base_card_keys, card_keys)) if old_key != new_key}
            strip = base_image if not changed else base_image.copy()
            if changed:
                self._patch_cards(strip, card_images, changed)
        else:
            strip = self._compose_cards(card_images)
        return PreparedStrip(payload_key, mode, StripLayout(width, segments), strip, item_ids, card_keys, card_images, generation)

    @staticmethod
    def _compose_cards(cards: tuple[Image.Image, ...]) -> Image.Image:
        """Compose a complete strip when card positions cannot be reused."""
        strip = Image.new("RGBA", (sum(card.width + 1 for card in cards) + 384, 32), (0, 0, 0, 255))
        draw = ImageDraw.Draw(strip)
        x = 0
        index = 0
        while x < strip.width:
            card = cards[index % len(cards)]
            draw.line((x, 0, x, 31), fill=(45, 45, 45, 255))
            x += 1
            strip.paste(card, (x, 0), card)
            x += card.width
            index += 1
            sleep(0)
        return strip

    @staticmethod
    def _patch_cards(strip: Image.Image, cards: tuple[Image.Image, ...], changed: set[int]) -> None:
        """Replace changed cards at every repeated position in one strip."""
        x = 0
        index = 0
        while x < strip.width:
            card = cards[index % len(cards)]
            if index % len(cards) in changed:
                strip.paste(card, (x + 1, 0), card)
            x += card.width + 1
            index += 1
            sleep(0)

    def invalidate(self) -> None:
        """Discard cached cards after prepared assets change."""
        with self._cache_lock:
            self._cache_generation += 1
            self._card_cache.clear()
            self._active_item_ids = ()
            self._active_card_keys = ()
            self._active_cards = ()

    def install(self, prepared: PreparedStrip) -> None:
        """Make one fully rendered strip visible on the next frame."""
        self._payload_key = prepared.key
        self._mode = prepared.mode
        self._image = prepared.image
        self._active_item_ids = prepared.item_ids
        self._active_card_keys = prepared.card_keys
        self._active_cards = prepared.cards
        self._active_generation = prepared.generation

    def get(self, payload_key: str | None, mode: str) -> Image.Image | None:
        """Return a matching strip or the current strip during a same-mode rebuild."""

        if self._image is None:
            return None
        if self._payload_key != payload_key and self._mode != mode:
            return None
        return self._image


def _plain_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Copy frozen protocol data into renderer-friendly JSON values."""
    return {str(key): _plain(item) for key, item in value.items()}


def _card_key(item: Content, mode: str) -> str:
    """Build a stable key for one rendered card."""
    value = {
        "id": item.id,
        "type": item.type,
        "sport": item.sport,
        "mode": mode,
        "data": _plain_mapping(item.data),
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _plain(value: Any) -> Any:
    """Convert immutable protocol containers without changing scalar values."""
    if isinstance(value, Mapping):
        return _plain_mapping(value)
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value
