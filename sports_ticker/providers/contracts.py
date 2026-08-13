"""Immutable provider records and standard-library provider ports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Protocol, TypeAlias, runtime_checkable

from sports_ticker.domain import ContentItem, DisplaySettings


ImmutableValue: TypeAlias = object


def _freeze(value: Any) -> ImmutableValue:
    """Copy common mutable values into immutable containers."""

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
class ProviderHealth:
    """Describe the health of one provider result."""

    healthy: bool = True
    provider: str = "provider"
    error: str | None = None

    def __post_init__(self) -> None:
        """Normalize provider health text."""

        object.__setattr__(self, "healthy", bool(self.healthy))
        object.__setattr__(self, "provider", str(self.provider).strip() or "provider")
        if self.error is not None:
            object.__setattr__(self, "error", str(self.error))


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """Contain one provider's complete, normalized observation."""

    content: tuple[ContentItem, ...] = ()
    alerts: tuple[ImmutableValue, ...] = ()
    news: tuple[ImmutableValue, ...] = ()
    observed_at: datetime | None = None
    health: ProviderHealth = ProviderHealth()

    def __post_init__(self) -> None:
        """Freeze provider collections and reject non-canonical content."""

        content = tuple(self.content)
        if not all(isinstance(item, ContentItem) for item in content):
            raise TypeError("provider content must contain ContentItem values")
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "alerts", tuple(_freeze(item) for item in self.alerts))
        object.__setattr__(self, "news", tuple(_freeze(item) for item in self.news))
        if self.observed_at is None:
            object.__setattr__(self, "observed_at", datetime.now(timezone.utc))
        elif not isinstance(self.observed_at, datetime):
            raise TypeError("observed_at must be a datetime or None")
        if not isinstance(self.health, ProviderHealth):
            raise TypeError("health must be a ProviderHealth")


@runtime_checkable
class Provider(Protocol):
    """Port for a provider that returns a complete immutable observation."""

    def fetch(self, settings: DisplaySettings) -> ProviderResult:
        """Fetch and return normalized data for the supplied ticker settings."""


ProviderPort: TypeAlias = Provider


__all__ = [
    "ImmutableValue",
    "Provider",
    "ProviderHealth",
    "ProviderPort",
    "ProviderResult",
]
