"""Stream effective V2 ticker projections to connected devices."""

from __future__ import annotations

import asyncio
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from threading import Lock
from time import perf_counter
from typing import Any
from uuid import uuid4


PROTOCOL_VERSION = 1
SUBPROTOCOL = "ticker-v2"
DEFAULT_QUEUE_SIZE = 32
DEFAULT_REPLAY_SIZE = 256
DEFAULT_PROJECTION_CHECK_SECONDS = 1.0


@dataclass(slots=True)
class _TickerStreamState:
    """Retain one ticker projection and its bounded sequence history."""

    sequence: int = 0
    payload: dict[str, Any] | None = None
    replay: deque[dict[str, Any]] = field(default_factory=deque)


@dataclass(slots=True, eq=False)
class _Subscriber:
    """Hold one event-loop-owned outbound queue."""

    queue: asyncio.Queue[dict[str, Any]]


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
        payload: dict[str, Any],
        *,
        resume_stream_id: str | None,
        after_seq: int | None,
    ) -> tuple[_Subscriber, tuple[dict[str, Any], ...]]:
        """Join one stream and return a snapshot, replay, or ready message."""
        state = self._states.setdefault(ticker_id, _TickerStreamState())
        if state.payload != payload:
            self.publish(ticker_id, payload)
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

    def publish(self, ticker_id: str, payload: dict[str, Any]) -> None:
        """Publish one effective projection change on the event loop."""
        state = self._states.setdefault(ticker_id, _TickerStreamState())
        current = deepcopy(payload)
        if state.payload is not None and state.payload == current:
            return
        previous = state.payload or {}
        changes = {key: value for key, value in current.items() if previous.get(key) != value}
        removed = [key for key in previous if key not in current]
        base_seq = state.sequence
        state.sequence += 1
        message = {
            "type": "delta",
            "protocol_version": PROTOCOL_VERSION,
            "stream_id": self.stream_id,
            "seq": state.sequence,
            "base_seq": base_seq,
            "server_time": _server_time(),
            "changes": changes,
            "removed": removed,
        }
        state.payload = current
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
            payload = await asyncio.to_thread(projector, ticker_id)
        except Exception:
            self.projection_reads += 1
            self.projection_seconds += perf_counter() - started
            return
        self.projection_reads += 1
        self.projection_seconds += perf_counter() - started
        self.publish(ticker_id, payload)

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

    def _enqueue(self, subscriber: _Subscriber, message: dict[str, Any], state: _TickerStreamState) -> None:
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

    def _replay_after(self, state: _TickerStreamState, after_seq: int) -> list[dict[str, Any]] | None:
        """Return a contiguous replay or no result when the cursor expired."""
        if after_seq < 0 or after_seq > state.sequence:
            return None
        if after_seq == state.sequence:
            return []
        replay = [item for item in state.replay if item["seq"] > after_seq]
        if not replay or replay[0]["base_seq"] != after_seq:
            return None
        expected = after_seq
        for item in replay:
            if item["base_seq"] != expected:
                return None
            expected = int(item["seq"])
        return replay if expected == state.sequence else None

    def _snapshot(self, state: _TickerStreamState) -> dict[str, Any]:
        return {
            "type": "snapshot",
            "protocol_version": PROTOCOL_VERSION,
            "stream_id": self.stream_id,
            "seq": state.sequence,
            "base_seq": state.sequence,
            "server_time": _server_time(),
            "payload": deepcopy(state.payload or {}),
        }

    def _ready(self, state: _TickerStreamState) -> dict[str, Any]:
        return {
            "type": "ready",
            "protocol_version": PROTOCOL_VERSION,
            "stream_id": self.stream_id,
            "seq": state.sequence,
            "base_seq": state.sequence,
            "server_time": _server_time(),
        }


def _server_time() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode_message(message: dict[str, Any]) -> str:
    """Encode one bounded JSON stream message."""
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False)

\n