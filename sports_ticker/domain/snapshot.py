"""Immutable ticker snapshots and their value-freezing helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import TypeAlias

from .models import ContentItem, DisplaySettings


SnapshotContent: TypeAlias = tuple[ContentItem, ...]
SnapshotEvents: TypeAlias = tuple[object, ...]


def _freeze(value: object) -> object:
    """Copy common mutable containers into immutable values."""

    if isinstance(value, Mapping):
        return MappingProxyType(
            {_freeze(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)
    return value


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
