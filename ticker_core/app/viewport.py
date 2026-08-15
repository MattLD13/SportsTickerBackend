"""Render a scrolling viewport from independent card surfaces."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
from threading import Lock
from typing import Any

from PIL import Image, ImageDraw

from ticker_core.context import RenderContext
from ticker_core.rendering import ContentRendererCatalog, ContentScene
from ticker_core.runtime import Content, StripLayout, StripSegment


@dataclass(frozen=True, slots=True)
class _CardRequest:
    """Describe one card image that a worker must render."""

    item: Content
    mode: str
    key: str
    context: RenderContext


@dataclass(frozen=True, slots=True)
class _CardSurface:
    """Hold one completed card image and its render revision."""

    item_id: str
    key: str
    image: Image.Image


class CardViewport:
    """Own scrolling card surfaces without building one long strip image."""

    def __init__(self, catalog: ContentRendererCatalog) -> None:
        self._catalog = catalog
        self._lock = Lock()
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ticker-card")
        self._future: Future[_CardSurface] | None = None
        self._active_request: _CardRequest | None = None
        self._pending: OrderedDict[str, _CardRequest] = OrderedDict()
        self._desired: dict[str, _CardRequest] = {}
        self._order: tuple[str, ...] = ()
        self._surfaces: dict[str, _CardSurface] = {}
        self._layout: StripLayout | None = None
        self._asset_generation = 0

    @property
    def layout(self) -> StripLayout | None:
        """Return current card geometry without image composition."""
        with self._lock:
            return self._layout

    def update(self, items: Iterable[Content], context: RenderContext, mode: str) -> StripLayout | None:
        """Queue only cards whose full renderer scene changed."""
        content = tuple(items)[:60]
        requests = tuple(
            _CardRequest(item, mode, _card_key(item, mode, self._asset_generation), context)
            for item in content
        )
        with self._lock:
            self._order = tuple(request.item.id for request in requests)
            self._desired = {request.item.id: request for request in requests}
            self._surfaces = {item_id: surface for item_id, surface in self._surfaces.items() if item_id in self._desired}
            for request in requests:
                current = self._surfaces.get(request.item.id)
                active = self._active_request
                if current is not None and current.key == request.key:
                    continue
                if active is not None and active.item.id == request.item.id and active.key == request.key:
                    continue
                self._pending[request.item.id] = request
            self._layout = self._layout_now()
            self._start_next()
            return self._layout

    def install_completed(self) -> StripLayout | None:
        """Commit one completed card at a frame boundary."""
        with self._lock:
            future = self._future
            request = self._active_request
            if future is None or request is None or not future.done():
                return None
            self._future = None
            self._active_request = None
        try:
            surface = future.result()
        except Exception:
            surface = None
        with self._lock:
            desired = self._desired.get(request.item.id)
            if surface is not None and desired is not None and desired.key == surface.key:
                self._surfaces[surface.item_id] = surface
            before = self._layout
            self._layout = self._layout_now()
            self._start_next()
            return self._layout if self._layout != before else None

    def invalidate(self) -> None:
        """Queue new card surfaces after prepared assets change."""
        with self._lock:
            self._asset_generation += 1
            for request in self._desired.values():
                refreshed = _CardRequest(
                    request.item,
                    request.mode,
                    _card_key(request.item, request.mode, self._asset_generation),
                    request.context,
                )
                self._desired[refreshed.item.id] = refreshed
                self._pending[refreshed.item.id] = refreshed
            self._start_next()

    def frame(self, offset: int, width: int = 384, height: int = 32) -> Image.Image:
        """Build one viewport from only cards visible at this offset."""
        with self._lock:
            layout = self._layout
            surfaces = dict(self._surfaces)
            order = self._order
        image = Image.new("RGB", (width, height), "black")
        if layout is None or not order:
            return image
        position = offset % layout.width
        start = 0
        index = 0
        for index, segment in enumerate(layout.segments):
            if start + segment.width > position:
                break
            start += segment.width
        x = start - position
        draw = ImageDraw.Draw(image)
        while x < width:
            segment = layout.segments[index % len(layout.segments)]
            surface = surfaces.get(segment.item_id)
            draw.line((x, 0, x, height - 1), fill=(45, 45, 45))
            if surface is not None:
                image.paste(surface.image, (x + 1, 0), surface.image)
            x += segment.width
            index += 1
        return image

    def close(self) -> None:
        """Stop the owned card renderer."""
        self._worker.shutdown(wait=True, cancel_futures=True)

    def _start_next(self) -> None:
        if self._future is not None:
            return
        while self._pending:
            _, request = self._pending.popitem(last=False)
            desired = self._desired.get(request.item.id)
            if desired is None or desired.key != request.key:
                continue
            self._active_request = request
            self._future = self._worker.submit(self._render, request)
            return

    def _layout_now(self) -> StripLayout | None:
        if not self._order:
            return None
        segments = tuple(
            StripSegment(item_id, (self._surfaces.get(item_id).image.width if item_id in self._surfaces else 96) + 1)
            for item_id in self._order
        )
        return StripLayout(sum(segment.width for segment in segments), segments)

    def _render(self, request: _CardRequest) -> _CardSurface:
        rendered = self._catalog.render(request.context, ContentScene(_plain_mapping(request.item.data), request.mode))
        return _CardSurface(request.item.id, request.key, rendered.image.convert("RGBA"))


def _card_key(item: Content, mode: str, asset_generation: int) -> str:
    """Hash every field that can alter one renderer result."""
    value = {
        "id": item.id,
        "type": item.type,
        "sport": item.sport,
        "mode": mode,
        "assets": asset_generation,
        "data": _plain_mapping(item.data),
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _plain_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Copy immutable protocol mappings for the renderer worker."""
    return {str(key): _plain(item) for key, item in value.items()}


def _plain(value: Any) -> Any:
    """Convert immutable protocol values into JSON-compatible objects."""
    if isinstance(value, Mapping):
        return _plain_mapping(value)
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value
