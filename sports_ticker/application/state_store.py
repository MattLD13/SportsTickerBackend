"""Thread-safe in-memory storage for complete ticker snapshots."""

from __future__ import annotations

from dataclasses import replace as dataclass_replace
from threading import RLock

from sports_ticker.domain.snapshot import TickerSnapshot


class SnapshotStore:
    """Store the latest immutable snapshot for each ticker identifier."""

    def __init__(self) -> None:
        """Initialize an empty snapshot store."""

        self._lock = RLock()
        self._snapshots: dict[str, TickerSnapshot] = {}

    def replace(self, snapshot: TickerSnapshot) -> TickerSnapshot:
        """Atomically replace a ticker snapshot and assign its next revision."""

        if not isinstance(snapshot, TickerSnapshot):
            raise TypeError("snapshot must be a TickerSnapshot")

        with self._lock:
            previous = self._snapshots.get(snapshot.ticker_id)
            revision = 1 if previous is None else previous.revision + 1
            stored = dataclass_replace(snapshot, revision=revision)
            self._snapshots[snapshot.ticker_id] = stored
            return stored

    def get(self, ticker_id: str) -> TickerSnapshot | None:
        """Return the latest stable snapshot for a ticker, or None when absent."""

        with self._lock:
            return self._snapshots.get(ticker_id)


__all__ = ["SnapshotStore"]
