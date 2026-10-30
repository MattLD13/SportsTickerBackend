"""Stream live display data to connected devices.

Each ticker has one sequence. A message is one of:

- `snapshot`: the full data in `payload`.
- `delta`: the changed top-level sections in `changes` and the removed sections in `removed`.
- `ready`: the client is already current.

A client that connects again with `?stream_id=<id>&after_seq=<n>` gets the missed
deltas, if the server still holds them. Otherwise it gets a snapshot. A client
that cannot keep up gets one snapshot in place of its queued deltas.
"""
from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from time import monotonic, time
from types import MappingProxyType
from typing import Any
from uuid import uuid4

SUBPROTOCOL = "ticker"
QUEUE_SIZE = 32
REPLAY_SIZE = 256
CHECK_SECONDS = 1.0


@dataclass(frozen=True)
class Projection:
    """The encoded top-level sections of one data view. Timing is left out of the comparison."""

    sections: Mapping[str, str]
    compared: Mapping[str, str]
    projected_at_ms: float | None

    @classmethod
    def of(cls, payload: Mapping[str, Any]) -> Projection:
        sections = {key: _encode(value) for key, value in payload.items()}
        compared = dict(sections)
        snapshot = payload.get("snapshot")
        timed = isinstance(snapshot, Mapping) and "timing" in snapshot
        if timed:
            compared["snapshot"] = _encode({key: value for key, value in snapshot.items() if key != "timing"})
        return cls(MappingProxyType(sections), MappingProxyType(compared), time() * 1000.0 if timed else None)

    def same(self, other: Projection | None) -> bool:
        return other is not None and self.compared == other.compared


@dataclass(frozen=True)
class Message:
    sequence: int
    base: int
    text: str


@dataclass
class _Ticker:
    sequence: int = 0
    projection: Projection | None = None
    replay: deque = field(default_factory=lambda: deque(maxlen=REPLAY_SIZE))


@dataclass(eq=False)
class Subscriber:
    queue: asyncio.Queue


class StreamHub:
    """Own the sequence, the replay, and the client queues of each ticker. Use it on one event loop."""

    def __init__(self) -> None:
        self.stream_id = uuid4().hex
        self._tickers: dict[str, _Ticker] = {}
        self._subscribers: dict[str, set[Subscriber]] = {}
        self._dirty: set[str] = set()
        self._dirty_all = False
        self._dirty_lock = Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._reads, self._read_seconds = 0, 0.0

    @property
    def active(self) -> tuple[str, ...]:
        return tuple(self._subscribers)

    @property
    def metrics(self) -> dict[str, float]:
        """Count the projections of the stream loop and the time they took."""
        return {"projection_reads": self._reads, "projection_seconds": self._read_seconds}

    # Change notices from any thread

    def changed(self, ticker_id: str) -> None:
        with self._dirty_lock:
            self._dirty.add(ticker_id)
        self._notify()

    def changed_all(self) -> None:
        with self._dirty_lock:
            self._dirty_all = True
        self._notify()

    # Subscriptions

    def subscribe(self, ticker_id: str, projection: Projection, *, stream_id: str | None,
                  after_seq: int | None) -> tuple[Subscriber, list[Message]]:
        state = self._tickers.setdefault(ticker_id, _Ticker())
        self.publish(ticker_id, projection)
        subscriber = Subscriber(asyncio.Queue(maxsize=QUEUE_SIZE))
        self._subscribers.setdefault(ticker_id, set()).add(subscriber)
        if stream_id == self.stream_id and after_seq is not None:
            missed = self._missed(state, after_seq)
            if missed is not None:
                return subscriber, missed or [self._message(state, "ready", state.sequence)]
        return subscriber, [self._snapshot(state)]

    def unsubscribe(self, ticker_id: str, subscriber: Subscriber) -> None:
        clients = self._subscribers.get(ticker_id)
        if clients is not None:
            clients.discard(subscriber)
            if not clients:
                del self._subscribers[ticker_id]

    def publish(self, ticker_id: str, projection: Projection) -> None:
        """Send the changed sections of a new projection to each client of the ticker."""
        state = self._tickers.setdefault(ticker_id, _Ticker())
        if projection.same(state.projection):
            return
        previous = state.projection.sections if state.projection is not None else {}
        changes = {key: value for key, value in projection.sections.items() if previous.get(key) != value}
        removed = [key for key in previous if key not in projection.sections]
        base = state.sequence
        state.sequence += 1
        state.projection = projection
        message = self._message(state, "delta", base, changes=changes, removed=removed)
        state.replay.append(message)
        for subscriber in tuple(self._subscribers.get(ticker_id, ())):
            try:
                subscriber.queue.put_nowait(message)
            except asyncio.QueueFull:
                while not subscriber.queue.empty():
                    subscriber.queue.get_nowait()
                subscriber.queue.put_nowait(self._snapshot(state))

    # Projection loop

    async def run(self, project: Callable[[str], Mapping[str, Any]], stop: asyncio.Event) -> None:
        """Project changed tickers at once, and every active ticker each second for time-based rules."""
        self._loop, self._wake = asyncio.get_running_loop(), asyncio.Event()
        wake = self._wake

        async def wake_on_stop() -> None:
            await stop.wait()
            wake.set()

        stopper = asyncio.create_task(wake_on_stop())
        try:
            while not stop.is_set():
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=CHECK_SECONDS)
                    self._wake.clear()
                    with self._dirty_lock:
                        everything, dirty = self._dirty_all, set(self._dirty)
                        self._dirty_all = False
                        self._dirty.clear()
                    targets = self.active if everything else tuple(ticker for ticker in self.active if ticker in dirty)
                except asyncio.TimeoutError:
                    targets = self.active
                if stop.is_set():
                    break
                for ticker_id in targets:
                    started = monotonic()
                    try:
                        projection = await asyncio.to_thread(lambda: Projection.of(project(ticker_id)))
                    except Exception:
                        continue
                    finally:
                        self._reads += 1
                        self._read_seconds += monotonic() - started
                    self.publish(ticker_id, projection)
        finally:
            stopper.cancel()
            self._loop = self._wake = None

    def _notify(self) -> None:
        loop, wake = self._loop, self._wake
        if loop is not None and wake is not None:
            try:
                loop.call_soon_threadsafe(wake.set)
            except RuntimeError:
                pass

    # Messages

    def _missed(self, state: _Ticker, after_seq: int) -> list[Message] | None:
        """Return the contiguous deltas after `after_seq`, or None when the server no longer holds them."""
        if not 0 <= after_seq <= state.sequence:
            return None
        missed = [message for message in state.replay if message.sequence > after_seq]
        expected = after_seq
        for message in missed:
            if message.base != expected:
                return None
            expected = message.sequence
        return missed if expected == state.sequence else None

    def _snapshot(self, state: _Ticker) -> Message:
        payload = "{" + ",".join(f"{json.dumps(key)}:{value}" for key, value in (state.projection.sections.items()
                                                                                if state.projection else ())) + "}"
        return self._message(state, "snapshot", state.sequence, payload=payload)

    def _message(self, state: _Ticker, kind: str, base: int, *, payload: str | None = None,
                 changes: Mapping[str, str] | None = None, removed: list[str] | None = None) -> Message:
        header = {"type": kind, "stream_id": self.stream_id, "seq": state.sequence, "base_seq": base,
                  "server_time": datetime.now(timezone.utc).isoformat()}
        if state.projection is not None and state.projection.projected_at_ms is not None:
            header["timing"] = {"projected_at_ms": state.projection.projected_at_ms}
        text = _encode(header)[:-1]
        if payload is not None:
            text += f',"payload":{payload}'
        if changes is not None:
            text += ',"changes":{' + ",".join(f"{json.dumps(key)}:{value}" for key, value in changes.items()) + "}"
            text += f',"removed":{_encode(removed or [])}'
        return Message(state.sequence, base, text + "}")


def _encode(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
