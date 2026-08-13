"""Build and retain seamless strips outside the runtime state machine."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw

from ticker_core.context import RenderContext
from ticker_core.rendering import ContentRendererCatalog, ContentScene
from ticker_core.runtime import Content, StripLayout, StripSegment


@dataclass(frozen=True, slots=True)
class PreparedStrip:
    """Hold one completed strip until the display thread installs it."""

    key: str
    layout: StripLayout | None
    image: Image.Image | None


class StripRepository:
    """Build and retain the current seamless strip."""

    def __init__(self, catalog: ContentRendererCatalog) -> None:
        self._catalog = catalog
        self._payload_key: str | None = None
        self._image: Image.Image | None = None

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
        for item in tuple(items)[:60]:
            rendered = self._catalog.render(context, ContentScene(_plain_mapping(item.data), mode))
            cards.append((item, rendered.image.convert("RGBA")))
        if not cards:
            return PreparedStrip(payload_key, None, None)
        segments = tuple(StripSegment(item.id, card.width + 1) for item, card in cards)
        width = sum(segment.width for segment in segments)
        strip = Image.new("RGBA", (width + 384, 32), (0, 0, 0, 255))
        draw = ImageDraw.Draw(strip)
        x = 0
        index = 0
        while x < strip.width:
            _, card = cards[index % len(cards)]
            draw.line((x, 0, x, 31), fill=(45, 45, 45, 255))
            x += 1
            strip.paste(card, (x, 0), card)
            x += card.width
            index += 1
        return PreparedStrip(payload_key, StripLayout(width, segments), strip)

    def install(self, prepared: PreparedStrip) -> None:
        """Make one fully rendered strip visible on the next frame."""
        self._payload_key = prepared.key
        self._image = prepared.image

    def get(self, payload_key: str | None) -> Image.Image | None:
        """Return the strip for the current payload."""
        if self._image is None or self._payload_key != payload_key:
            return None
        return self._image


def _plain_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Copy frozen protocol data into renderer-friendly JSON values."""
    return {str(key): _plain(item) for key, item in value.items()}


def _plain(value: Any) -> Any:
    """Convert immutable protocol containers without changing scalar values."""
    if isinstance(value, Mapping):
        return _plain_mapping(value)
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value
