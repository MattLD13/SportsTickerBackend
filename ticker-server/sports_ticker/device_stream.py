"""Stream effective V2 ticker projections to connected devices."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from threading import Lock
from time import perf_counter, time
from types import MappingProxyType
from typing import Any
from uuid import uuid4


PROTOCOL_VERSION = 1
SUBPROTOCOL = "ticker-v2"
DEFAULT_QUEUE_SIZE = 32
DEFAULT_REPLAY_SIZE = 256
DEFAULT_PROJECTION_CHECK_SECONDS = 1.0


def _encoded_object(sections: Mapping[str, str]) -> str:
    """Join detached JSON sections without traversing their nested values again."""
    return "{" + ",".join(json.dumps(key, ensure_ascii=False) + ":" + value for key, value in sections.items()) + "}"


@dataclass(frozen=True, slots=True)
class StreamProjection:
    """Own immutable encoded sections prepared outside the event loop."""

    sections: Mapping[str, str] = field(compare=False)
    encoded: str = field(compare=False)
    comparison: Mapping[str, str]
    prepared_at_ms: float | None = field(default=None, compare=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "StreamProjection":
        prepared_at_ms = time() * 1000.0
        sections = {
            key: json.dumps(value, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
            for key, value in payload.items()
        }
        comparison = sections
        snapshot = payload.get("snapshot")
        if isinstance(snapshot, Mapping) and "timing" in snapshot:
            comparison = {**sections, "snapshot": json.dumps(
                {key: value for key, value in snapshot.items() if key != "timing"},
                separators=(",", ":"), ensure_ascii=False, sort_keys=True,
            )}
        timed = isinstance(snapshot, Mapping) and "timing" in snapshot
        return cls(MappingProxyType(sections), _encoded_object(sections), MappingProxyType(comparison), prepared_at_ms if timed else None)


def project_stream_payload(projector: Callable[[str], Mapping[str, Any]], ticker_id: str) -> StreamProjection:
    """Project and detach one JSON result in the same background task."""
    return StreamProjection.from_payload(projector(ticker_id))


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    """Share one complete immutable wire message across subscribers and replay."""

    sequence: int
    base_sequence: int
    encoded: str


@dataclass(slots=True)
class _TickerStreamState:
    """Retain one ticker projection and its bounded sequence history."""

    sequence: int = 0
    projection: StreamProjection | None = None
    replay: deque[OutboundMessage] = field(default_factory=deque)


@dataclass(slots=True, eq=False)
class _Subscriber:
    """Hold one event-loop-owned outbound queue."""

    queue: asyncio.Queue[OutboundMessage]


class DeviceStreamHub:
    """Own per-process sequences, bounded replay, and bounded client queues."""

    def __init__(self, *, queue_size: int = DEFAULT_QUEUE_SIZE, replay_size: int = DEFAULT_REPLAY_SIZE) -> None:
        if queue_size < 1 or replay_size < 1:
            raise ValueError("stream queue and replay sizes must be positive")
        self.stream_id = uuid4().hex
        self.queue_size = queue_size
        self.replay_size = replay_size
        self._states: dict[str, _TickerStreamState] = {}
        self._subscribers: dict[str, set[_Subscriber]] = {}
        self._generation = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake_event: asyncio.Event | None = None
        self._dirty_lock = Lock()
        self._dirty_tickers: set[str] = set()
        self._dirty_all = False
        self.projection_reads = 0
        self.projection_seconds = 0.0
        self.published_deltas = 0
        self.queue_resets = 0

    @property
    def generation(self) -> int:
        """Return the event-loop projection generation."""
        return self._generation

    @property
    def active_tickers(self) -> tuple[str, ...]:
        """Return tickers with at least one connected device stream."""
        return tuple(self._subscribers)

    @property
    def metrics(self) -> dict[str, float | int]:
        """Return bounded counters for stream operations and projection cost."""
        return {
            "active_tickers": len(self._subscribers),
            "projection_reads": self.projection_reads,
            "projection_seconds": self.projection_seconds,
            "published_deltas": self.published_deltas,
            "queue_resets": self.queue_resets,
        }

    def notify_ticker_changed(self, ticker_id: str) -> None:
        """Wake the stream projector after one source snapshot changes."""
        with self._dirty_lock:
            self._dirty_tickers.add(str(ticker_id))
        self._wake_projector()

    def notify_all_changed(self) -> None:
        """Wake the stream projector after a fleet or event mutation."""
        with self._dirty_lock:
            self._dirty_all = True
        self._wake_projector()

    def subscribe(
        self,
        ticker_id: str,
        projection: StreamProjection,
        *,
        resume_stream_id: str | None,
        after_seq: int | None,
    ) -> tuple[_Subscriber, tuple[OutboundMessage, ...]]:
        """Join one stream and return a snapshot, replay, or ready message."""
        state = self._states.setdefault(ticker_id, _TickerStreamState())
        if state.projection != projection:
            self.publish(ticker_id, projection)
        subscriber = _Subscriber(asyncio.Queue(maxsize=self.queue_size))
        self._subscribers.setdefault(ticker_id, set()).add(subscriber)
        if resume_stream_id == self.stream_id and after_seq is not None:
            replay = self._replay_after(state, after_seq)
            if replay is not None:
                if replay:
                    return subscriber, tuple(replay)
                return subscriber, (self._ready(state),)
        return subscriber, (self._snapshot(state),)

    def unsubscribe(self, ticker_id: str, subscriber: _Subscriber) -> None:
        """Remove one client queue and its ticker index when unused."""
        clients = self._subscribers.get(ticker_id)
        if clients is None:
            return
        clients.discard(subscriber)
        if not clients:
            del self._subscribers[ticker_id]

    def publish(self, ticker_id: str, projection: StreamProjection) -> None:
        """Compare prepared sections and publish one immutable message on the event loop."""
        state = self._states.setdefault(ticker_id, _TickerStreamState())
        if state.projection == projection:
            return
        current = projection.sections
        previous = state.projection.sections if state.projection is not None else {}
        changes = {key: value for key, value in current.items() if previous.get(key) != value}
        removed = [key for key in previous if key not in current]
        base_seq = state.sequence
        state.sequence += 1
        message = self._message(state, "delta", base_seq, "changes", _encoded_object(changes), removed, projection=projection)
        state.projection = projection
        self._generation += 1
        self.published_deltas += 1
        state.replay.append(message)
        while len(state.replay) > self.replay_size:
            state.replay.popleft()
        for subscriber in tuple(self._subscribers.get(ticker_id, ())):
            self._enqueue(subscriber, message, state)

    async def refresh_active(self, projector) -> None:
        """Refresh effective projections for active tickers outside the event loop."""
        await self.refresh_tickers(projector, self.active_tickers)

    async def refresh_tickers(self, projector, ticker_ids) -> None:
        """Project a selected active ticker set outside the event loop."""
        active = set(self.active_tickers)
        for ticker_id in ticker_ids:
            if ticker_id in active:
                await self._refresh_one(projector, ticker_id)

    async def _refresh_one(self, projector, ticker_id: str) -> None:
        started = perf_counter()
        try:
            projection = await asyncio.to_thread(project_stream_payload, projector, ticker_id)
        except Exception:
            self.projection_reads += 1
            self.projection_seconds += perf_counter() - started
            return
        self.projection_reads += 1
        self.projection_seconds += perf_counter() - started
        self.publish(ticker_id, projection)

    async def serve_updates(
        self,
        projector,
        stop: asyncio.Event,
        *,
        interval: float = DEFAULT_PROJECTION_CHECK_SECONDS,
    ) -> None:
        """Project notifications promptly and check time-based policies once per second."""
        loop = asyncio.get_running_loop()
        self._loop = loop
        self._wake_event = asyncio.Event()
        wake = self._wake_event
        with self._dirty_lock:
            dirty = self._dirty_all or bool(self._dirty_tickers)
        if dirty:
            wake.set()
        try:
            while not stop.is_set():
                periodic_check = False
                try:
                    await asyncio.wait_for(wake.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    periodic_check = True
                if stop.is_set():
                    return
                if periodic_check:
                    ticker_ids = self.active_tickers
                else:
                    wake.clear()
                    with self._dirty_lock:
                        all_tickers = self._dirty_all
                        ticker_ids = tuple(self._dirty_tickers)
                        self._dirty_all = False
                        self._dirty_tickers.clear()
                    if all_tickers:
                        ticker_ids = self.active_tickers
                    else:
                        active = set(self.active_tickers)
                        ticker_ids = tuple(item for item in ticker_ids if item in active)
                await self.refresh_tickers(projector, ticker_ids)
        finally:
            self._loop = None
            self._wake_event = None

    def _wake_projector(self) -> None:
        loop, wake = self._loop, self._wake_event
        if loop is None or wake is None:
            return
        try:
            loop.call_soon_threadsafe(wake.set)
        except RuntimeError:
            return

    def _enqueue(self, subscriber: _Subscriber, message: OutboundMessage, state: _TickerStreamState) -> None:
        """Replace queued deltas with a current snapshot for a slow client."""
        try:
            subscriber.queue.put_nowait(message)
        except asyncio.QueueFull:
            self.queue_resets += 1
            while not subscriber.queue.empty():
                try:
                    subscriber.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            subscriber.queue.put_nowait(self._snapshot(state))

    def _replay_after(self, state: _TickerStreamState, after_seq: int) -> list[OutboundMessage] | None:
        """Return a contiguous replay or no result when the cursor expired."""
        if after_seq < 0 or after_seq > state.sequence:
            return None
        if after_seq == state.sequence:
            return []
        replay = [item for item in state.replay if item.sequence > after_seq]
        if not replay or replay[0].base_sequence != after_seq:
            return None
        expected = after_seq
        for item in replay:
            if item.base_sequence != expected:
                return None
            expected = item.sequence
        return replay if expected == state.sequence else None

    def _snapshot(self, state: _TickerStreamState) -> OutboundMessage:
        payload = state.projection.encoded if state.projection is not None else "{}"
        return self._message(state, "snapshot", state.sequence, "payload", payload)

    def _ready(self, state: _TickerStreamState) -> OutboundMessage:
        return self._message(state, "ready", state.sequence)

    def _message(
        self, state: _TickerStreamState, kind: str, base_sequence: int,
        body_key: str | None = None, body: str = "", removed: list[str] | None = None,
        *, projection: StreamProjection | None = None,
    ) -> OutboundMessage:
        header = {
            "type": kind,
            "protocol_version": PROTOCOL_VERSION,
            "stream_id": self.stream_id,
            "seq": state.sequence,
            "base_seq": base_sequence,
            "server_time": _server_time(),
        }
        current = projection if projection is not None else state.projection
        if current is not None and current.prepared_at_ms is not None:
            header["timing"] = {"projected_at_ms": current.prepared_at_ms}
        encoded = json.dumps(header, separators=(",", ":"), ensure_ascii=False)
        if body_key is not None:
            encoded = encoded[:-1] + "," + json.dumps(body_key) + ":" + body
            if removed is not None:
                encoded += ',"removed":' + json.dumps(removed, separators=(",", ":"), ensure_ascii=False)
            encoded += "}"
        return OutboundMessage(state.sequence, base_sequence, encoded)


def _server_time() -> str:
    return datetime.now(timezone.utc).isoformat()
