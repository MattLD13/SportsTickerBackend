"""Prepare validated updates on their producer thread before the drawing loop receives them."""

from collections.abc import Mapping
from dataclasses import dataclass
from queue import Queue
from threading import Lock

from ticker_core.protocol import DisplayDelta, TickerResponse, apply_display_delta
from ticker_core.runtime import Content, prepare_content

from .poller import PollSucceeded


@dataclass(frozen=True, slots=True)
class PreparedUpdate:
    event: PollSucceeded
    response: TickerResponse
    content: tuple[Content, ...]
    changed_ids: frozenset[str]
    settings_changed: bool
    issues: tuple[tuple[str, Exception], ...] = ()


@dataclass(frozen=True, slots=True)
class RejectedUpdate:
    error: Exception


class PreparedEventQueue:
    """Keep deserialization, asset planning, and payload copying outside the drawing consumer."""

    def __init__(self, *, cache, assets):
        self._queue = Queue()
        self._lock = Lock()
        self._previous = None
        self._content = ()
        self._cache, self._assets = cache, assets

    def put(self, event):
        if not isinstance(event, PollSucceeded):
            self._queue.put(event)
            return
        with self._lock:
            try:
                prepared = self._prepare(event)
            except Exception as error:
                self._queue.put(RejectedUpdate(error))
            else:
                self._queue.put(prepared)

    def get_nowait(self):
        return self._queue.get_nowait()

    def _prepare(self, event):
        response = event.payload
        if isinstance(response, Mapping):
            response = TickerResponse.from_payload(response)
        previous = self._previous
        delta = response if isinstance(response, DisplayDelta) else None
        if delta is not None:
            if previous is None:
                raise ValueError("Received a delta before a display snapshot")
            response = apply_display_delta(previous, delta)
        previous_items = {item.id: item for item in previous.content} if previous is not None else {}
        changed = (frozenset(item.id for item in delta.changed) if delta is not None else
                   frozenset(item.id for item in response.content if previous_items.get(item.id) != item))
        content = prepare_content(response.content, self._content, changed)
        settings_changed = previous is None or previous.settings != response.settings
        issues = []
        if previous is None or previous.payload_key != response.payload_key:
            if delta is None:
                try:
                    self._cache.store(response.data)
                except Exception as error:
                    issues.append(("content_cache", error))
            if delta is None or delta.settings_changed:
                asset_source = response
            else:
                asset_source = delta_asset_source(delta)
            try:
                self._assets.prefetch_payload(asset_source)
            except Exception as error:
                issues.append(("asset_prefetch", error))
        self._previous, self._content = response, content
        return PreparedUpdate(event, response, content, changed, settings_changed, tuple(issues))


def delta_asset_source(delta: DisplayDelta) -> tuple[Mapping[str, object], ...]:
    """Return changed content and overlays that can introduce assets."""
    records = [item.data for item in delta.changed]
    records.extend(data for _, _, data in delta.alerts)
    records.extend(data for _, _, data in delta.news)
    return tuple(records)
