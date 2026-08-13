"""Immutable durable overlay event models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from types import MappingProxyType
from typing import Any, ClassVar
from uuid import uuid4


def _freeze(value: Any) -> Any:
    """Copy event payload values into immutable containers."""

    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)
    return value


def _timestamp(value: float | datetime | str) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("event times must be numbers or ISO timestamps") from exc
        return parsed.timestamp()
    result = float(value)
    if not isfinite(result):
        raise ValueError("event times must be finite")
    return result


@dataclass(frozen=True, slots=True)
class OverlayEvent:
    """Represent one immutable event independent from ticker snapshots."""

    event_id: str = ""
    kind: str = "event"
    payload: Mapping[str, Any] = field(default_factory=dict)
    created_at: float | datetime | str = 0.0
    expires_at: float | datetime | str = 60.0
    target_ticker_ids: tuple[str, ...] | None = None
    delivery_state: str = "pending"

    channel: ClassVar[str] = "events"

    def __post_init__(self) -> None:
        """Normalize event identity, payload, times, targets, and state."""

        event_id = str(self.event_id).strip() or str(uuid4())
        kind = str(self.kind).strip().lower() or "event"
        if not isinstance(self.payload, Mapping):
            raise TypeError("event payload must be an object")
        payload = _freeze(self.payload)
        created_at = _timestamp(self.created_at)
        expires_at = _timestamp(self.expires_at)
        if expires_at <= created_at:
            raise ValueError("event expiry must be after creation")
        targets = None
        if self.target_ticker_ids:
            if isinstance(self.target_ticker_ids, str):
                raise TypeError("target_ticker_ids must be a sequence")
            normalized = tuple(
                dict.fromkeys(
                    str(ticker_id).strip()
                    for ticker_id in self.target_ticker_ids
                    if str(ticker_id).strip()
                )
            )
            targets = normalized or None
        state = str(self.delivery_state).strip().lower() or "pending"
        if state not in {"pending", "acknowledged", "expired"}:
            raise ValueError("delivery_state must be pending, acknowledged, or expired")
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "target_ticker_ids", targets)
        object.__setattr__(self, "delivery_state", state)

    @property
    def created_time(self) -> float:
        """Return the event creation timestamp."""

        return self.created_at  # type: ignore[return-value]

    @property
    def expiry_time(self) -> float:
        """Return the event expiry timestamp."""

        return self.expires_at  # type: ignore[return-value]

    @property
    def event_type(self) -> str:
        """Return the projection channel for this event."""

        return self.channel


@dataclass(frozen=True, slots=True)
class ScoreAlertEvent(OverlayEvent):
    """Represent one durable score alert."""

    kind: str = "score_alert"
    channel: ClassVar[str] = "alerts"


@dataclass(frozen=True, slots=True)
class NewsEvent(OverlayEvent):
    """Represent one durable news overlay."""

    kind: str = "news"
    channel: ClassVar[str] = "news"


Event = OverlayEvent
ScoreAlert = ScoreAlertEvent
News = NewsEvent


__all__ = [
    "Event",
    "News",
    "NewsEvent",
    "OverlayEvent",
    "ScoreAlert",
    "ScoreAlertEvent",
]
