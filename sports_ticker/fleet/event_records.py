"""Store durable overlay events and their per-ticker delivery state."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from sports_ticker.domain import (
    NewsEvent,
    OverlayEvent,
    ScoreAlertEvent,
)

from .json_values import _dump


class EventRecords:
    """Publish, read, acknowledge, and expire overlay events."""

    def publish_event(self, event: OverlayEvent) -> OverlayEvent:
        """Persist one alert or news event with optional ticker targets."""

        if not isinstance(event, (ScoreAlertEvent, NewsEvent)):
            raise TypeError("event must be a ScoreAlertEvent or NewsEvent")
        targets = event.target_ticker_ids
        with self._transaction():
            if targets:
                placeholders = ", ".join("?" for _ in targets)
                rows = self._connection.execute(
                    f"SELECT ticker_id FROM tickers WHERE ticker_id IN ({placeholders})",
                    tuple(targets),
                ).fetchall()
                existing = {str(row["ticker_id"]) for row in rows}
                missing = [ticker_id for ticker_id in targets if ticker_id not in existing]
                if missing:
                    raise KeyError(missing[0])
            try:
                self._connection.execute(
                    "INSERT INTO overlay_events "
                    "(event_id, event_type, kind, payload_json, created_at, expires_at, "
                    "target_ticker_ids_json, delivery_state) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.event_id,
                        event.event_type,
                        event.kind,
                        _dump(event.payload),
                        event.created_at,
                        event.expires_at,
                        None if targets is None else _dump(targets),
                        event.delivery_state,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"event already exists: {event.event_id}") from exc
        return event

    def read_pending_events(
        self,
        ticker_id: str,
        *,
        now: float | None = None,
        event_type: str | None = None,
    ) -> tuple[OverlayEvent, ...]:
        """Read unacknowledged active events visible to one ticker."""

        identifier = str(ticker_id).strip()
        current_time = time.time() if now is None else float(now)
        with self._lock:
            self._require_ticker_locked(identifier)
            query = (
                "SELECT event_id, event_type, kind, payload_json, created_at, expires_at, "
                "target_ticker_ids_json, delivery_state FROM overlay_events "
                "WHERE created_at <= ? AND expires_at > ? AND delivery_state = 'pending'"
            )
            parameters: list[Any] = [current_time, current_time]
            if event_type is not None:
                if event_type not in {"alerts", "news"}:
                    raise ValueError("event_type must be alerts or news")
                query += " AND event_type = ?"
                parameters.append(event_type)
            query += " ORDER BY created_at, event_id"
            rows = self._connection.execute(query, tuple(parameters)).fetchall()
            result: list[OverlayEvent] = []
            for row in rows:
                targets = self._event_targets(row)
                if targets is not None and identifier not in targets:
                    continue
                delivery = self._connection.execute(
                    "SELECT delivery_state FROM overlay_event_deliveries "
                    "WHERE event_id = ? AND ticker_id = ?",
                    (row["event_id"], identifier),
                ).fetchone()
                if delivery is not None and delivery["delivery_state"] == "acknowledged":
                    continue
                result.append(self._event_from_row(row))
            return tuple(result)

    def acknowledge_event(
        self,
        ticker_id: str,
        event_id: str,
        *,
        now: float | None = None,
    ) -> bool:
        """Acknowledge one event for one authorized ticker."""

        identifier = str(ticker_id).strip()
        event_identifier = str(event_id).strip()
        current_time = time.time() if now is None else float(now)
        with self._transaction():
            self._require_ticker_locked(identifier)
            row = self._connection.execute(
                "SELECT event_id, expires_at, target_ticker_ids_json FROM overlay_events "
                "WHERE event_id = ?",
                (event_identifier,),
            ).fetchone()
            if row is None:
                raise KeyError(event_identifier)
            if row["expires_at"] <= current_time:
                return False
            targets = self._event_targets(row)
            if targets is not None and identifier not in targets:
                return False
            self._connection.execute(
                "INSERT INTO overlay_event_deliveries "
                "(event_id, ticker_id, delivery_state, acknowledged_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(event_id, ticker_id) DO UPDATE SET "
                "delivery_state = excluded.delivery_state, acknowledged_at = excluded.acknowledged_at",
                (event_identifier, identifier, "acknowledged", current_time),
            )
            return True

    def remove_expired_events(self, *, now: float | None = None) -> int:
        """Delete expired events and their per-ticker delivery records."""

        current_time = time.time() if now is None else float(now)
        with self._transaction():
            cursor = self._connection.execute(
                "DELETE FROM overlay_events WHERE expires_at <= ?",
                (current_time,),
            )
            return int(cursor.rowcount)

    @staticmethod
    def _event_targets(row: sqlite3.Row) -> tuple[str, ...] | None:
        value = row["target_ticker_ids_json"]
        if value is None:
            return None
        targets = tuple(str(item) for item in json.loads(value))
        return targets or None

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> OverlayEvent:
        event_type = row["event_type"]
        event_class = ScoreAlertEvent if event_type == "alerts" else NewsEvent
        return event_class(
            event_id=row["event_id"],
            kind=row["kind"],
            payload=json.loads(row["payload_json"]),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            target_ticker_ids=EventRecords._event_targets(row),
            delivery_state=row["delivery_state"],
        )
