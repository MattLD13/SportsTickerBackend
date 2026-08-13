"""Application services for durable alert and news overlays."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from datetime import datetime
from math import isfinite
from typing import Any, Callable
from uuid import uuid4

from sports_ticker.domain.events import NewsEvent, OverlayEvent, ScoreAlertEvent
from sports_ticker.fleet.repository import TickerRepository


class EventService:
    """Create, read, and acknowledge durable overlay events."""

    def __init__(
        self,
        repository: TickerRepository,
        *,
        clock: Callable[[], float] = time.time,
        default_ttl: float = 60.0,
    ) -> None:
        """Capture the repository and event clock."""

        self.repository = repository
        self._clock = clock
        self._default_ttl = float(default_ttl)
        if not isfinite(self._default_ttl) or self._default_ttl <= 0:
            raise ValueError("default_ttl must be finite and positive")

    def publish_alert(
        self,
        payload: Mapping[str, Any],
        *,
        event_id: str | None = None,
        kind: str = "score_alert",
        created_at: float | datetime | str | None = None,
        expires_at: float | datetime | str | None = None,
        target_ticker_ids: Sequence[str] | None = None,
        ttl_seconds: float | None = None,
    ) -> ScoreAlertEvent:
        """Publish one score alert event."""

        event = ScoreAlertEvent(
            event_id=event_id or str(uuid4()),
            kind=kind,
            payload=payload,
            created_at=self._created_at(created_at),
            expires_at=self._expires_at(created_at, expires_at, ttl_seconds),
            target_ticker_ids=target_ticker_ids,
        )
        return self.repository.publish_event(event)

    def publish_news(
        self,
        payload: Mapping[str, Any],
        *,
        event_id: str | None = None,
        kind: str = "news",
        created_at: float | datetime | str | None = None,
        expires_at: float | datetime | str | None = None,
        target_ticker_ids: Sequence[str] | None = None,
        ttl_seconds: float | None = None,
    ) -> NewsEvent:
        """Publish one news event."""

        event = NewsEvent(
            event_id=event_id or str(uuid4()),
            kind=kind,
            payload=payload,
            created_at=self._created_at(created_at),
            expires_at=self._expires_at(created_at, expires_at, ttl_seconds),
            target_ticker_ids=target_ticker_ids,
        )
        return self.repository.publish_event(event)

    def pending(self, ticker_id: str) -> tuple[OverlayEvent, ...]:
        """Return all pending events visible to one ticker."""

        return self.repository.read_pending_events(ticker_id, now=self._clock())

    def acknowledge(self, ticker_id: str, event_id: str) -> bool:
        """Acknowledge one event for one ticker."""

        return self.repository.acknowledge_event(
            ticker_id,
            event_id,
            now=self._clock(),
        )

    def remove_expired(self) -> int:
        """Remove all events whose expiry time has passed."""

        return self.repository.remove_expired_events(now=self._clock())

    def _created_at(self, value: float | datetime | str | None) -> float | datetime | str:
        return self._clock() if value is None else value

    def _expires_at(
        self,
        created_at: float | datetime | str | None,
        expires_at: float | datetime | str | None,
        ttl_seconds: float | None,
    ) -> float | datetime | str:
        if expires_at is not None:
            return expires_at
        ttl = self._default_ttl if ttl_seconds is None else float(ttl_seconds)
        if not isfinite(ttl) or ttl <= 0:
            raise ValueError("ttl_seconds must be finite and positive")
        created = self._clock() if created_at is None else created_at
        if isinstance(created, datetime):
            return created.timestamp() + ttl
        if isinstance(created, str):
            parsed = datetime.fromisoformat(created.replace("Z", "+00:00"))
            return parsed.timestamp() + ttl
        return float(created) + ttl


def event_to_mapping(event: OverlayEvent) -> dict[str, Any]:
    """Serialize one immutable event for JSON projections."""

    return {
        "event_id": event.event_id,
        "kind": event.kind,
        "payload": _json_value(event.payload),
        "created_at": event.created_at,
        "expires_at": event.expires_at,
        "target_ticker_ids": None
        if event.target_ticker_ids is None
        else list(event.target_ticker_ids),
        "delivery_state": event.delivery_state,
    }


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(item) for item in value]
    raise TypeError(f"value of type {type(value).__name__} is not JSON-ready")


OverlayEventService = EventService


__all__ = ["EventService", "OverlayEventService", "event_to_mapping"]
