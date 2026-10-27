"""Store current and delayed immutable ticker snapshots."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace as dataclass_replace
from threading import RLock

from sports_ticker.domain.snapshot import TickerSnapshot


@dataclass(frozen=True, slots=True)
class _StoredSnapshot:
    """Keep one source-content revision and its server receipt time."""

    snapshot: TickerSnapshot
    stored_at: float


class SnapshotStore:
    """Store the latest snapshot and a bounded source-content history."""

    def __init__(
        self,
        *,
        history_seconds: float = 180.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Initialize the store with enough history for the 120-second delay control."""

        if history_seconds <= 0:
            raise ValueError("history_seconds must be positive")
        self._history_seconds = float(history_seconds)
        self._clock = clock

        self._lock = RLock()
        self._snapshots: dict[str, TickerSnapshot] = {}
        self._history: dict[str, deque[_StoredSnapshot]] = {}
        self._change_listeners: set[Callable[[str], None]] = set()

    def add_change_listener(self, listener: Callable[[str], None]) -> None:
        """Register one callback for changed ticker snapshots."""
        if not callable(listener):
            raise TypeError("snapshot change listener must be callable")
        with self._lock:
            self._change_listeners.add(listener)

    def remove_change_listener(self, listener: Callable[[str], None]) -> None:
        """Remove one registered snapshot callback."""
        with self._lock:
            self._change_listeners.discard(listener)

    def replace(self, snapshot: TickerSnapshot) -> TickerSnapshot:
        """Atomically replace a ticker snapshot and assign its next revision."""

        if not isinstance(snapshot, TickerSnapshot):
            raise TypeError("snapshot must be a TickerSnapshot")

        with self._lock:
            stored_at = self._clock()
            previous = self._snapshots.get(snapshot.ticker_id)
            revision = 1 if previous is None else previous.revision + 1
            stored = dataclass_replace(snapshot, revision=revision, committed_at_ms=stored_at * 1000.0)
            self._snapshots[snapshot.ticker_id] = stored
            history = self._history.setdefault(snapshot.ticker_id, deque())
            if not history or _source_changed(history[-1].snapshot, stored):
                history.append(_StoredSnapshot(stored, stored_at))
            cutoff = stored_at - self._history_seconds
            while len(history) > 1 and history[0].stored_at < cutoff:
                history.popleft()
            listeners = tuple(self._change_listeners)
        for listener in listeners:
            try:
                listener(stored.ticker_id)
            except Exception:
                continue
        return stored

    def get(self, ticker_id: str) -> TickerSnapshot | None:
        """Return the latest stable snapshot for a ticker, or None when absent."""

        with self._lock:
            return self._snapshots.get(ticker_id)

    def list_snapshots(self) -> tuple[TickerSnapshot, ...]:
        """Return the latest snapshot for every ticker."""

        with self._lock:
            return tuple(self._snapshots.values())

    def get_delayed(self, ticker_id: str, delay_seconds: float) -> TickerSnapshot | None:
        """Return the source snapshot at or before one requested delay point."""

        delay = float(delay_seconds)
        if delay < 0:
            raise ValueError("delay_seconds must be non-negative")
        target = self._clock() - delay
        with self._lock:
            history = self._history.get(ticker_id)
            if not history:
                return self._snapshots.get(ticker_id)
            for entry in reversed(history):
                if entry.stored_at <= target:
                    return entry.snapshot
            return history[0].snapshot


def _source_changed(previous: TickerSnapshot, current: TickerSnapshot) -> bool:
    """Return if a new source frame needs a delayed history entry."""

    return (
        len(previous.content) != len(current.content)
        or any(not _same_source_item(left, right) for left, right in zip(previous.content, current.content))
        or previous.alerts != current.alerts
        or previous.news != current.news
    )


def _same_source_item(left, right) -> bool:
    """Keep receipt metadata from creating artificial delayed display history."""
    if left == right:
        return True
    return (
        (left.id, left.family, left.kind, left.is_shown) == (right.id, right.family, right.kind, right.is_shown)
        and {key: value for key, value in left.data.items() if key != "_source_timing"}
        == {key: value for key, value in right.data.items() if key != "_source_timing"}
    )


__all__ = ["SnapshotStore"]
