"""Immutable ticker snapshots and their value-freezing helpers."""

from __future__ import annotations

from ticker.shared.immutable import freeze as _freeze

from dataclasses import dataclass, field
from datetime import datetime
from typing import TypeAlias

from ticker.shared.domain.models import ContentItem, DisplaySettings


SnapshotContent: TypeAlias = tuple[ContentItem, ...]
SnapshotEvents: TypeAlias = tuple[object, ...]




@dataclass(frozen=True, slots=True)
class TickerSnapshot:
    """Represent one complete, immutable view of a ticker."""

    ticker_id: str
    revision: int
    observed_at: datetime
    content: SnapshotContent
    alerts: SnapshotEvents
    news: SnapshotEvents
    effective_settings: DisplaySettings
    committed_at_ms: float | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        """Freeze snapshot collections and validate the revision value."""

        if self.revision < 0:
            raise ValueError("revision must be non-negative")
        content = tuple(self.content)
        if not all(isinstance(item, ContentItem) for item in content):
            raise TypeError("snapshot content must contain ContentItem values")
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "alerts", _freeze(self.alerts))
        object.__setattr__(self, "news", _freeze(self.news))


__all__ = ["SnapshotContent", "SnapshotEvents", "TickerSnapshot"]
