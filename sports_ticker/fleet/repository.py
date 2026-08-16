"""SQLite persistence for immutable ticker fleet configuration."""

from __future__ import annotations

import json
import hmac
import sqlite3
import threading
import time
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from sports_ticker.domain import DisplaySettings, OverlayEvent, NewsEvent, ScoreAlertEvent

from .models import (
    DeviceMetadata,
    PairingState,
    SpotifyConnection,
    SpotifyOAuthAttempt,
    TickerRecord,
)


_UNSET = object()


def _jsonable(value: Any) -> Any:
    """Convert immutable containers into JSON-compatible values."""

    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, frozenset, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, bytearray):
        return bytes(value).decode("utf-8")
    return value


def _dump(value: Any) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"))


def _display_payload(settings: DisplaySettings) -> dict[str, Any]:
    return {
        "active_sports": dict(settings.active_sports),
        "my_teams": list(settings.my_teams),
        "mode": settings.mode,
        "sports_filter": settings.sports_filter,
        "sports_presentation": settings.sports_presentation,
        "pinned_content_id": settings.pinned_content_id,
        "brightness": settings.brightness,
        "inverted": settings.inverted,
        "timezone": settings.timezone,
        "weather_city": settings.weather_city,
        "weather_lat": settings.weather_lat,
        "weather_lon": settings.weather_lon,
        "airport_code_iata": settings.airport_code_iata,
        "airport_code_icao": settings.airport_code_icao,
        "airport_name": settings.airport_name,
        "track_flight_id": settings.track_flight_id,
        "track_guest_name": settings.track_guest_name,
        "live_delay_mode": settings.live_delay_mode,
        "live_delay_seconds": settings.live_delay_seconds,
        "scroll_seamless": settings.scroll_seamless,
        "scroll_speed": settings.scroll_speed,
        "score_alerts": settings.score_alerts,
    }


def _display_settings(value: DisplaySettings | Mapping[str, Any] | None) -> DisplaySettings:
    if isinstance(value, DisplaySettings):
        return value
    if value is None:
        return DisplaySettings()
    return DisplaySettings(
        active_sports=value.get("active_sports", {}),
        my_teams=value.get("my_teams", ()),
        mode=value.get("mode", "sports"),
        sports_filter=value.get("sports_filter", "all"),
        sports_presentation=value.get("sports_presentation", "rotation"),
        pinned_content_id=value.get("pinned_content_id", ""),
        brightness=value.get("brightness", 100.0),
        inverted=value.get("inverted", False),
        timezone=value.get("timezone", ""),
        weather_city=value.get("weather_city", "New York"),
        weather_lat=value.get("weather_lat", 40.7128),
        weather_lon=value.get("weather_lon", -74.0060),
        airport_code_iata=value.get("airport_code_iata", "EWR"),
        airport_code_icao=value.get("airport_code_icao", "KEWR"),
        airport_name=value.get("airport_name", "Newark Liberty International"),
        track_flight_id=value.get("track_flight_id", ""),
        track_guest_name=value.get("track_guest_name", ""),
        live_delay_mode=value.get("live_delay_mode", False),
        live_delay_seconds=value.get("live_delay_seconds", 45.0),
        scroll_seamless=value.get("scroll_seamless", True),
        scroll_speed=value.get("scroll_speed", 0.03),
        score_alerts=value.get("score_alerts", True),
    )


def _pairing(value: PairingState | Mapping[str, Any] | None) -> PairingState | None:
    if value is None or isinstance(value, PairingState):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("pairing must be PairingState, a mapping, or None")
    clients = value.get("client_ids", value.get("clients", ()))
    return PairingState(
        pairing_code=value.get("pairing_code"),
        pairing_code_expires_at=value.get("pairing_code_expires_at", value.get("expires_at")),
        paired=value.get("paired", False),
        client_ids=clients,
    )


def _device(value: DeviceMetadata | Mapping[str, Any] | None) -> DeviceMetadata:
    if value is None:
        return DeviceMetadata()
    if isinstance(value, DeviceMetadata):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("device metadata must be DeviceMetadata, a mapping, or None")
    metadata = value.get("metadata", {})
    if not isinstance(metadata, Mapping):
        metadata = {}
    metadata = dict(metadata)
    metadata.update(
        {
            key: item
            for key, item in value.items()
            if key not in {"last_seen", "last_seen_at", "metadata"}
        }
    )
    return DeviceMetadata(
        last_seen_at=value.get("last_seen_at", value.get("last_seen")),
        metadata=metadata,
    )


class TickerRepository:
    """Persist global settings and isolated ticker records in SQLite."""

    def __init__(self, database: str | Path | sqlite3.Connection) -> None:
        """Open the database and create every required table explicitly."""

        if isinstance(database, sqlite3.Connection):
            self._connection = database
            self._owns_connection = False
        else:
            self._connection = sqlite3.connect(str(database), check_same_thread=False)
            self._owns_connection = True
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.RLock()
        self._create_schema()

    def _create_schema(self) -> None:
        with self._transaction():
            schema = (
                """
                CREATE TABLE IF NOT EXISTS tickers (
                    ticker_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """,
                """

                CREATE TABLE IF NOT EXISTS ticker_display_settings (
                    ticker_id TEXT PRIMARY KEY,
                    settings_json TEXT NOT NULL,
                    FOREIGN KEY (ticker_id) REFERENCES tickers(ticker_id) ON DELETE CASCADE
                );
                """,
                """

                CREATE TABLE IF NOT EXISTS ticker_pairing (
                    ticker_id TEXT PRIMARY KEY,
                    pairing_code TEXT,
                    pairing_code_expires_at REAL,
                    paired INTEGER NOT NULL,
                    client_ids_json TEXT NOT NULL,
                    FOREIGN KEY (ticker_id) REFERENCES tickers(ticker_id) ON DELETE CASCADE
                );
                """,
                """

                CREATE TABLE IF NOT EXISTS ticker_devices (
                    ticker_id TEXT PRIMARY KEY,
                    last_seen_at REAL,
                    metadata_json TEXT NOT NULL,
                    FOREIGN KEY (ticker_id) REFERENCES tickers(ticker_id) ON DELETE CASCADE
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS overlay_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL CHECK (event_type IN ('alerts', 'news')),
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    target_ticker_ids_json TEXT,
                    delivery_state TEXT NOT NULL CHECK (
                        delivery_state IN ('pending', 'acknowledged', 'expired')
                    )
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS overlay_event_deliveries (
                    event_id TEXT NOT NULL,
                    ticker_id TEXT NOT NULL,
                    delivery_state TEXT NOT NULL CHECK (
                        delivery_state IN ('acknowledged', 'expired')
                    ),
                    acknowledged_at REAL,
                    PRIMARY KEY (event_id, ticker_id),
                    FOREIGN KEY (event_id) REFERENCES overlay_events(event_id) ON DELETE CASCADE,
                    FOREIGN KEY (ticker_id) REFERENCES tickers(ticker_id) ON DELETE CASCADE
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS spotify_connections (
                    ticker_id TEXT NOT NULL,
                    spotify_account_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    refresh_token_ciphertext TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('connected', 'reauthorization_required')),
                    priority INTEGER NOT NULL DEFAULT 0 CHECK (priority IN (0, 1)),
                    connected_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (ticker_id, spotify_account_id),
                    FOREIGN KEY (ticker_id) REFERENCES tickers(ticker_id) ON DELETE CASCADE
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS spotify_oauth_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    ticker_id TEXT NOT NULL,
                    state_hash TEXT NOT NULL,
                    verifier_ciphertext TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    used_at REAL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (ticker_id) REFERENCES tickers(ticker_id) ON DELETE CASCADE
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS controller_sessions (
                    token_hash TEXT PRIMARY KEY,
                    ticker_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_used_at REAL NOT NULL,
                    FOREIGN KEY (ticker_id) REFERENCES tickers(ticker_id) ON DELETE CASCADE
                );
                """,
                """
                CREATE INDEX IF NOT EXISTS controller_sessions_ticker_id
                ON controller_sessions(ticker_id);
                """,
            )
            for statement in schema:
                self._connection.execute(statement)
            self._migrate_pairing_expiry_locked()
            self._migrate_spotify_connections_locked()
            self._connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS spotify_connections_one_priority "
                "ON spotify_connections(ticker_id) WHERE priority = 1"
            )

    def _migrate_spotify_connections_locked(self) -> None:
        """Replace the former one-account table while preserving its account."""

        columns = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(spotify_connections)")
        }
        if "priority" in columns:
            return
        self._connection.execute(
            "CREATE TABLE spotify_connections_next ("
            "ticker_id TEXT NOT NULL, spotify_account_id TEXT NOT NULL, "
            "display_name TEXT NOT NULL, scopes_json TEXT NOT NULL, "
            "refresh_token_ciphertext TEXT NOT NULL, "
            "status TEXT NOT NULL CHECK (status IN ('connected', 'reauthorization_required')), "
            "priority INTEGER NOT NULL DEFAULT 0 CHECK (priority IN (0, 1)), "
            "connected_at REAL NOT NULL, updated_at REAL NOT NULL, "
            "PRIMARY KEY (ticker_id, spotify_account_id), "
            "FOREIGN KEY (ticker_id) REFERENCES tickers(ticker_id) ON DELETE CASCADE)"
        )
        self._connection.execute(
            "INSERT INTO spotify_connections_next "
            "(ticker_id, spotify_account_id, display_name, scopes_json, "
            "refresh_token_ciphertext, status, priority, connected_at, updated_at) "
            "SELECT ticker_id, spotify_account_id, display_name, scopes_json, "
            "refresh_token_ciphertext, status, 0, connected_at, updated_at "
            "FROM spotify_connections"
        )
        self._connection.execute("DROP TABLE spotify_connections")
        self._connection.execute("ALTER TABLE spotify_connections_next RENAME TO spotify_connections")

    def _migrate_pairing_expiry_locked(self) -> None:
        """Add durable pairing expiry to databases created before the field existed."""

        columns = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(ticker_pairing)")
        }
        if "pairing_code_expires_at" not in columns:
            self._connection.execute(
                "ALTER TABLE ticker_pairing ADD COLUMN pairing_code_expires_at REAL"
            )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            started = not self._connection.in_transaction
            if started:
                self._connection.execute("BEGIN")
            try:
                yield
            except Exception:
                if started:
                    self._connection.rollback()
                raise
            else:
                if started:
                    self._connection.commit()

    def close(self) -> None:
        """Close the owned database connection."""

        if self._owns_connection:
            with self._lock:
                self._connection.close()

    def __enter__(self) -> TickerRepository:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def create_ticker(
        self,
        ticker_id: str | TickerRecord,
        display_settings: DisplaySettings | Mapping[str, Any] | None = None,
        *,
        name: str = "Ticker",
        pairing: PairingState | Mapping[str, Any] | None = None,
        device: DeviceMetadata | Mapping[str, Any] | None = None,
    ) -> TickerRecord:
        if isinstance(ticker_id, TickerRecord):
            record = ticker_id
        else:
            now = time.time()
            record = TickerRecord(
                ticker_id=ticker_id,
                name=name,
                display_settings=_display_settings(display_settings),
                pairing=_pairing(pairing),
                device=_device(device),
                created_at=now,
                updated_at=now,
            )

        with self._transaction():
            try:
                self._insert_record(record)
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"ticker already exists: {record.ticker_id}") from exc
        return self.get_ticker(record.ticker_id)  # type: ignore[return-value]

    def _insert_record(self, record: TickerRecord) -> None:
        self._connection.execute(
            "INSERT INTO tickers (ticker_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (record.ticker_id, record.name, record.created_at, record.updated_at),
        )
        self._write_children(record)

    def _write_children(self, record: TickerRecord) -> None:
        self._connection.execute(
            "INSERT INTO ticker_display_settings (ticker_id, settings_json) VALUES (?, ?)",
            (record.ticker_id, _dump(_display_payload(record.display_settings))),
        )
        if record.pairing is not None:
            self._connection.execute(
                "INSERT INTO ticker_pairing "
                "(ticker_id, pairing_code, pairing_code_expires_at, paired, client_ids_json) VALUES (?, ?, ?, ?, ?)",
                (
                    record.ticker_id,
                    record.pairing.pairing_code,
                    record.pairing.pairing_code_expires_at,
                    int(record.pairing.paired),
                    _dump(record.pairing.client_ids),
                ),
            )
        self._connection.execute(
            "INSERT INTO ticker_devices (ticker_id, last_seen_at, metadata_json) VALUES (?, ?, ?)",
            (record.ticker_id, record.device.last_seen_at, _dump(record.device.metadata)),
        )

    def get_ticker(self, ticker_id: str) -> TickerRecord | None:
        identifier = str(ticker_id).strip()
        with self._lock:
            row = self._connection.execute(
                "SELECT ticker_id, name, created_at, updated_at FROM tickers WHERE ticker_id = ?",
                (identifier,),
            ).fetchone()
            if row is None:
                return None
            return self._read_record(row)

    def _read_record(self, row: sqlite3.Row) -> TickerRecord:
        ticker_id = row["ticker_id"]
        display_row = self._connection.execute(
            "SELECT settings_json FROM ticker_display_settings WHERE ticker_id = ?",
            (ticker_id,),
        ).fetchone()
        pairing_row = self._connection.execute(
            "SELECT pairing_code, pairing_code_expires_at, paired, client_ids_json FROM ticker_pairing WHERE ticker_id = ?",
            (ticker_id,),
        ).fetchone()
        device_row = self._connection.execute(
            "SELECT last_seen_at, metadata_json FROM ticker_devices WHERE ticker_id = ?",
            (ticker_id,),
        ).fetchone()
        pairing = None
        if pairing_row is not None:
            pairing = PairingState(
                pairing_code=pairing_row["pairing_code"],
                pairing_code_expires_at=pairing_row["pairing_code_expires_at"],
                paired=bool(pairing_row["paired"]),
                client_ids=tuple(json.loads(pairing_row["client_ids_json"])),
            )
        device = DeviceMetadata()
        if device_row is not None:
            device = DeviceMetadata(
                last_seen_at=device_row["last_seen_at"],
                metadata=json.loads(device_row["metadata_json"]),
            )
        display = DisplaySettings()
        if display_row is not None:
            display = _display_settings(json.loads(display_row["settings_json"]))
        return TickerRecord(
            ticker_id=ticker_id,
            name=row["name"],
            display_settings=display,
            pairing=pairing,
            device=device,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_tickers(self) -> tuple[TickerRecord, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT ticker_id, name, created_at, updated_at FROM tickers ORDER BY ticker_id"
            ).fetchall()
            return tuple(self._read_record(row) for row in rows)

    def list_tickers_for_controller(self, token_hash: str) -> tuple[TickerRecord, ...]:
        """Return only tickers owned by one hashed controller token."""

        digest = str(token_hash).strip()
        if not digest:
            return ()
        with self._lock:
            rows = self._connection.execute(
                "SELECT t.ticker_id, t.name, t.created_at, t.updated_at "
                "FROM tickers AS t "
                "INNER JOIN controller_sessions AS s ON s.ticker_id = t.ticker_id "
                "WHERE s.token_hash = ? ORDER BY t.ticker_id",
                (digest,),
            ).fetchall()
            return tuple(self._read_record(row) for row in rows)

    def update_ticker(
        self,
        ticker_id: str,
        *,
        name: str | object = _UNSET,
        display_settings: DisplaySettings | Mapping[str, Any] | object = _UNSET,
        settings: DisplaySettings | Mapping[str, Any] | object = _UNSET,
        pairing: PairingState | Mapping[str, Any] | None | object = _UNSET,
        device: DeviceMetadata | Mapping[str, Any] | None | object = _UNSET,
    ) -> TickerRecord:
        if display_settings is not _UNSET and settings is not _UNSET:
            raise TypeError("provide display_settings or settings, not both")
        identifier = str(ticker_id).strip()
        with self._transaction():
            row = self._connection.execute(
                "SELECT ticker_id, name, created_at, updated_at FROM tickers WHERE ticker_id = ?",
                (identifier,),
            ).fetchone()
            if row is None:
                raise KeyError(identifier)
            current = self._read_record(row)
            next_settings = current.display_settings
            if display_settings is not _UNSET:
                next_settings = _display_settings(display_settings)  # type: ignore[arg-type]
            elif settings is not _UNSET:
                next_settings = _display_settings(settings)  # type: ignore[arg-type]
            next_pairing = current.pairing if pairing is _UNSET else _pairing(pairing)  # type: ignore[arg-type]
            next_device = current.device if device is _UNSET else _device(device)  # type: ignore[arg-type]
            next_record = TickerRecord(
                ticker_id=current.ticker_id,
                name=current.name if name is _UNSET else str(name),
                display_settings=next_settings,
                pairing=next_pairing,
                device=next_device,
                created_at=current.created_at,
                updated_at=time.time(),
            )
            self._connection.execute(
                "UPDATE tickers SET name = ?, updated_at = ? WHERE ticker_id = ?",
                (next_record.name, next_record.updated_at, identifier),
            )
            self._connection.execute(
                "DELETE FROM ticker_display_settings WHERE ticker_id = ?", (identifier,)
            )
            self._connection.execute("DELETE FROM ticker_pairing WHERE ticker_id = ?", (identifier,))
            self._connection.execute("DELETE FROM ticker_devices WHERE ticker_id = ?", (identifier,))
            self._write_children(next_record)
        return self.get_ticker(identifier)  # type: ignore[return-value]

    def delete_ticker(self, ticker_id: str) -> bool:
        identifier = str(ticker_id).strip()
        with self._transaction():
            row = self._connection.execute(
                "SELECT ticker_id FROM tickers WHERE ticker_id = ?", (identifier,)
            ).fetchone()
            if row is None:
                return False
            events = self._connection.execute(
                "SELECT event_id, target_ticker_ids_json FROM overlay_events "
                "WHERE target_ticker_ids_json IS NOT NULL"
            ).fetchall()
            for event in events:
                targets = tuple(str(value) for value in json.loads(event["target_ticker_ids_json"]))
                if identifier not in targets:
                    continue
                remaining = tuple(target for target in targets if target != identifier)
                if remaining:
                    self._connection.execute(
                        "UPDATE overlay_events SET target_ticker_ids_json = ? WHERE event_id = ?",
                        (_dump(remaining), event["event_id"]),
                    )
                else:
                    self._connection.execute(
                        "DELETE FROM overlay_events WHERE event_id = ?", (event["event_id"],)
                    )
            cursor = self._connection.execute("DELETE FROM tickers WHERE ticker_id = ?", (identifier,))
            return cursor.rowcount == 1

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

    def publish(self, event: OverlayEvent) -> OverlayEvent:
        """Persist one durable overlay event."""

        return self.publish_event(event)

    def publish_alert(self, event: ScoreAlertEvent) -> ScoreAlertEvent:
        """Persist one score alert event."""

        result = self.publish_event(event)
        return result  # type: ignore[return-value]

    def publish_news(self, event: NewsEvent) -> NewsEvent:
        """Persist one news event."""

        result = self.publish_event(event)
        return result  # type: ignore[return-value]

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

    def pending_events_for_ticker(
        self,
        ticker_id: str,
        *,
        now: float | None = None,
    ) -> tuple[OverlayEvent, ...]:
        """Return pending events for one ticker."""

        return self.read_pending_events(ticker_id, now=now)

    def read_pending_alerts(
        self,
        ticker_id: str,
        *,
        now: float | None = None,
    ) -> tuple[OverlayEvent, ...]:
        """Return pending score alerts for one ticker."""

        return self.read_pending_events(ticker_id, now=now, event_type="alerts")

    def read_pending_news(
        self,
        ticker_id: str,
        *,
        now: float | None = None,
    ) -> tuple[OverlayEvent, ...]:
        """Return pending news events for one ticker."""

        return self.read_pending_events(ticker_id, now=now, event_type="news")

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

    def acknowledge(self, ticker_id: str, event_id: str, *, now: float | None = None) -> bool:
        """Acknowledge one durable event for one ticker."""

        return self.acknowledge_event(ticker_id, event_id, now=now)

    def remove_expired_events(self, *, now: float | None = None) -> int:
        """Delete expired events and their per-ticker delivery records."""

        current_time = time.time() if now is None else float(now)
        with self._transaction():
            cursor = self._connection.execute(
                "DELETE FROM overlay_events WHERE expires_at <= ?",
                (current_time,),
            )
            return int(cursor.rowcount)

    def remove_expired(self, *, now: float | None = None) -> int:
        """Delete expired durable events."""

        return self.remove_expired_events(now=now)

    def save_spotify_connection(self, connection: SpotifyConnection) -> SpotifyConnection:
        """Create or update one encrypted Spotify connection."""

        if not isinstance(connection, SpotifyConnection):
            raise TypeError("connection must be SpotifyConnection")
        with self._transaction():
            self._require_ticker_locked(connection.ticker_id)
            self._connection.execute(
                "INSERT INTO spotify_connections "
                "(ticker_id, spotify_account_id, display_name, scopes_json, "
                "refresh_token_ciphertext, status, priority, connected_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(ticker_id, spotify_account_id) DO UPDATE SET "
                "display_name = excluded.display_name, scopes_json = excluded.scopes_json, "
                "refresh_token_ciphertext = excluded.refresh_token_ciphertext, "
                "status = excluded.status, updated_at = excluded.updated_at",
                (
                    connection.ticker_id,
                    connection.spotify_account_id,
                    connection.display_name,
                    _dump(connection.scopes),
                    connection.refresh_token_ciphertext,
                    connection.status,
                    int(connection.priority),
                    connection.connected_at,
                    connection.updated_at,
                ),
            )
        return self.get_spotify_connection(
            connection.ticker_id, connection.spotify_account_id
        )  # type: ignore[return-value]

    def get_spotify_connection(
        self, ticker_id: str, spotify_account_id: str | None = None
    ) -> SpotifyConnection | None:
        """Read one encrypted Spotify connection for backend-only use."""

        identifier = str(ticker_id).strip()
        account_id = str(spotify_account_id).strip()
        clause = "WHERE ticker_id = ?"
        values: tuple[str, ...] = (identifier,)
        if account_id:
            clause += " AND spotify_account_id = ?"
            values = (identifier, account_id)
        with self._lock:
            row = self._connection.execute(
                "SELECT ticker_id, spotify_account_id, display_name, scopes_json, "
                "refresh_token_ciphertext, status, priority, connected_at, updated_at "
                f"FROM spotify_connections {clause} "
                "ORDER BY priority DESC, connected_at ASC LIMIT 1",
                values,
            ).fetchone()
        if row is None:
            return None
        return self._spotify_connection_from_row(row)

    def list_spotify_connections(self, ticker_id: str) -> tuple[SpotifyConnection, ...]:
        """Read every encrypted Spotify connection for one ticker."""

        identifier = str(ticker_id).strip()
        with self._lock:
            rows = self._connection.execute(
                "SELECT ticker_id, spotify_account_id, display_name, scopes_json, "
                "refresh_token_ciphertext, status, priority, connected_at, updated_at "
                "FROM spotify_connections WHERE ticker_id = ? "
                "ORDER BY priority DESC, connected_at ASC",
                (identifier,),
            ).fetchall()
        return tuple(self._spotify_connection_from_row(row) for row in rows)

    @staticmethod
    def _spotify_connection_from_row(row: sqlite3.Row) -> SpotifyConnection:
        """Build one Spotify connection from a database row."""

        return SpotifyConnection(
            ticker_id=row["ticker_id"],
            spotify_account_id=row["spotify_account_id"],
            display_name=row["display_name"],
            scopes=tuple(json.loads(row["scopes_json"])),
            refresh_token_ciphertext=row["refresh_token_ciphertext"],
            status=row["status"],
            priority=bool(row["priority"]),
            connected_at=row["connected_at"],
            updated_at=row["updated_at"],
        )

    def set_spotify_priority(
        self, ticker_id: str, spotify_account_id: str | None
    ) -> tuple[SpotifyConnection, ...]:
        """Set one preferred account, or clear the account preference."""

        identifier = str(ticker_id).strip()
        account_id = str(spotify_account_id or "").strip()
        with self._transaction():
            self._require_ticker_locked(identifier)
            if account_id:
                row = self._connection.execute(
                    "SELECT 1 FROM spotify_connections "
                    "WHERE ticker_id = ? AND spotify_account_id = ?",
                    (identifier, account_id),
                ).fetchone()
                if row is None:
                    raise KeyError(account_id)
            self._connection.execute(
                "UPDATE spotify_connections SET priority = 0 WHERE ticker_id = ?",
                (identifier,),
            )
            if account_id:
                self._connection.execute(
                    "UPDATE spotify_connections SET priority = 1 "
                    "WHERE ticker_id = ? AND spotify_account_id = ?",
                    (identifier, account_id),
                )
        return self.list_spotify_connections(identifier)

    def delete_spotify_connection(
        self, ticker_id: str, spotify_account_id: str | None = None
    ) -> bool:
        """Delete one Spotify connection, or all ticker connections when omitted."""

        identifier = str(ticker_id).strip()
        account_id = str(spotify_account_id or "").strip()
        with self._transaction():
            self._require_ticker_locked(identifier)
            if not account_id:
                self._connection.execute(
                    "DELETE FROM spotify_oauth_attempts WHERE ticker_id = ?", (identifier,)
                )
                cursor = self._connection.execute(
                    "DELETE FROM spotify_connections WHERE ticker_id = ?", (identifier,)
                )
            else:
                cursor = self._connection.execute(
                    "DELETE FROM spotify_connections "
                    "WHERE ticker_id = ? AND spotify_account_id = ?",
                    (identifier, account_id),
                )
            return cursor.rowcount > 0

    def exchange_pairing_code(
        self,
        pairing_code: str,
        token_hash: str,
        *,
        now: float | None = None,
    ) -> TickerRecord:
        """Consume one pairing code and create one controller token record."""

        code = str(pairing_code).strip()
        digest = str(token_hash).strip()
        if not code or not digest:
            raise ValueError("pairing code and controller token are required")
        current_time = time.time() if now is None else float(now)
        with self._transaction():
            row = self._connection.execute(
                "SELECT ticker_id, pairing_code_expires_at FROM ticker_pairing WHERE pairing_code = ?",
                (code,),
            ).fetchone()
            if row is None:
                raise ValueError("pairing code is invalid or already used")
            expires_at = row["pairing_code_expires_at"]
            if expires_at is not None and current_time > float(expires_at):
                raise ValueError("pairing code has expired")
            ticker_id = str(row["ticker_id"])
            self._connection.execute(
                "INSERT INTO controller_sessions (token_hash, ticker_id, created_at, last_used_at) "
                "VALUES (?, ?, ?, ?)",
                (digest, ticker_id, current_time, current_time),
            )
            self._connection.execute(
                "UPDATE ticker_pairing SET paired = 1, pairing_code = NULL WHERE ticker_id = ?",
                (ticker_id,),
            )
            ticker_row = self._connection.execute(
                "SELECT ticker_id, name, created_at, updated_at FROM tickers WHERE ticker_id = ?",
                (ticker_id,),
            ).fetchone()
            if ticker_row is None:
                raise KeyError(ticker_id)
            return self._read_record(ticker_row)

    def issue_pairing_code(
        self,
        ticker_id: str,
        pairing_code: str,
        *,
        expires_at: float | None = None,
    ) -> TickerRecord:
        """Issue one unused controller pairing code for an existing ticker."""

        identifier = str(ticker_id).strip()
        code = str(pairing_code).strip()
        if not identifier or not code:
            raise ValueError("ticker ID and pairing code are required")
        with self._transaction():
            self._require_ticker_locked(identifier)
            existing = self._connection.execute(
                "SELECT ticker_id FROM ticker_pairing WHERE pairing_code = ?",
                (code,),
            ).fetchone()
            if existing is not None and str(existing["ticker_id"]) != identifier:
                raise ValueError("pairing code is already in use")
            pairing_row = self._connection.execute(
                "SELECT paired FROM ticker_pairing WHERE ticker_id = ?",
                (identifier,),
            ).fetchone()
            if pairing_row is None:
                self._connection.execute(
                    "INSERT INTO ticker_pairing "
                    "(ticker_id, pairing_code, pairing_code_expires_at, paired, client_ids_json) VALUES (?, ?, ?, ?, ?)",
                    (identifier, code, expires_at, 0, _dump(())),
                )
            else:
                self._connection.execute(
                    "UPDATE ticker_pairing SET pairing_code = ?, pairing_code_expires_at = ? WHERE ticker_id = ?",
                    (code, expires_at, identifier),
                )
            ticker_row = self._connection.execute(
                "SELECT ticker_id, name, created_at, updated_at FROM tickers WHERE ticker_id = ?",
                (identifier,),
            ).fetchone()
            if ticker_row is None:
                raise KeyError(identifier)
            return self._read_record(ticker_row)

    def unpair_ticker(
        self,
        ticker_id: str,
        pairing_code: str,
        *,
        expires_at: float | None = None,
    ) -> TickerRecord:
        """Revoke one controller and reset the ticker to pairing mode."""

        identifier = str(ticker_id).strip()
        code = str(pairing_code).strip()
        if not identifier or not code:
            raise ValueError("ticker ID and pairing code are required")
        with self._transaction():
            self._require_ticker_locked(identifier)
            existing = self._connection.execute(
                "SELECT ticker_id FROM ticker_pairing WHERE pairing_code = ?",
                (code,),
            ).fetchone()
            if existing is not None and str(existing["ticker_id"]) != identifier:
                raise ValueError("pairing code is already in use")
            self._connection.execute(
                "DELETE FROM controller_sessions WHERE ticker_id = ?", (identifier,)
            )
            self._connection.execute(
                "DELETE FROM spotify_oauth_attempts WHERE ticker_id = ?", (identifier,)
            )
            self._connection.execute(
                "DELETE FROM spotify_connections WHERE ticker_id = ?", (identifier,)
            )
            self._connection.execute(
                "INSERT INTO ticker_pairing "
                "(ticker_id, pairing_code, pairing_code_expires_at, paired, client_ids_json) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(ticker_id) DO UPDATE SET pairing_code = excluded.pairing_code, "
                "pairing_code_expires_at = excluded.pairing_code_expires_at, "
                "paired = excluded.paired, client_ids_json = excluded.client_ids_json",
                (identifier, code, expires_at, 0, _dump(())),
            )
            self._connection.execute(
                "UPDATE tickers SET updated_at = ? WHERE ticker_id = ?",
                (time.time(), identifier),
            )
            row = self._connection.execute(
                "SELECT ticker_id, name, created_at, updated_at FROM tickers WHERE ticker_id = ?",
                (identifier,),
            ).fetchone()
            if row is None:
                raise KeyError(identifier)
            return self._read_record(row)

    def authorize_controller(
        self,
        ticker_id: str,
        token_hash: str,
        *,
        now: float | None = None,
    ) -> bool:
        """Validate one opaque controller token for its bound ticker."""

        identifier = str(ticker_id).strip()
        digest = str(token_hash).strip()
        if not identifier or not digest:
            return False
        current_time = time.time() if now is None else float(now)
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE controller_sessions SET last_used_at = ? "
                "WHERE ticker_id = ? AND token_hash = ?",
                (current_time, identifier, digest),
            )
            return cursor.rowcount == 1

    def create_spotify_oauth_attempt(self, attempt: SpotifyOAuthAttempt) -> None:
        """Persist one authorization attempt before opening Spotify."""

        if not isinstance(attempt, SpotifyOAuthAttempt):
            raise TypeError("attempt must be SpotifyOAuthAttempt")
        with self._transaction():
            self._require_ticker_locked(attempt.ticker_id)
            self._connection.execute(
                "DELETE FROM spotify_oauth_attempts WHERE expires_at <= ? OR used_at IS NOT NULL",
                (attempt.created_at,),
            )
            self._connection.execute(
                "INSERT INTO spotify_oauth_attempts "
                "(attempt_id, ticker_id, state_hash, verifier_ciphertext, expires_at, used_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    attempt.attempt_id,
                    attempt.ticker_id,
                    attempt.state_hash,
                    attempt.verifier_ciphertext,
                    attempt.expires_at,
                    attempt.used_at,
                    attempt.created_at,
                ),
            )

    def consume_spotify_oauth_attempt(
        self,
        attempt_id: str,
        state_hash: str,
        *,
        now: float | None = None,
    ) -> SpotifyOAuthAttempt:
        """Atomically consume a matching unexpired OAuth attempt."""

        identifier = str(attempt_id).strip()
        digest = str(state_hash).strip()
        current_time = time.time() if now is None else float(now)
        with self._transaction():
            row = self._connection.execute(
                "SELECT attempt_id, ticker_id, state_hash, verifier_ciphertext, expires_at, used_at, created_at "
                "FROM spotify_oauth_attempts WHERE attempt_id = ?",
                (identifier,),
            ).fetchone()
            if row is None or row["used_at"] is not None or row["expires_at"] <= current_time:
                raise ValueError("Spotify authorization attempt is invalid or expired")
            if not hmac.compare_digest(str(row["state_hash"]), digest):
                raise ValueError("Spotify authorization state is invalid")
            self._connection.execute(
                "UPDATE spotify_oauth_attempts SET used_at = ? WHERE attempt_id = ? AND used_at IS NULL",
                (current_time, identifier),
            )
            return SpotifyOAuthAttempt(
                attempt_id=row["attempt_id"],
                ticker_id=row["ticker_id"],
                state_hash=row["state_hash"],
                verifier_ciphertext=row["verifier_ciphertext"],
                expires_at=row["expires_at"],
                created_at=row["created_at"],
                used_at=current_time,
            )

    def _require_ticker_locked(self, ticker_id: str) -> None:
        if not ticker_id:
            raise ValueError("ticker_id must not be empty")
        row = self._connection.execute(
            "SELECT ticker_id FROM tickers WHERE ticker_id = ?", (ticker_id,)
        ).fetchone()
        if row is None:
            raise KeyError(ticker_id)

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
            target_ticker_ids=TickerRepository._event_targets(row),
            delivery_state=row["delivery_state"],
        )

    def create(self, *args: Any, **kwargs: Any) -> TickerRecord:
        return self.create_ticker(*args, **kwargs)

    def get(self, ticker_id: str) -> TickerRecord | None:
        return self.get_ticker(ticker_id)

    def list(self) -> tuple[TickerRecord, ...]:
        return self.list_tickers()

    def update(self, *args: Any, **kwargs: Any) -> TickerRecord:
        return self.update_ticker(*args, **kwargs)

    def delete(self, ticker_id: str) -> bool:
        return self.delete_ticker(ticker_id)


__all__ = ["TickerRepository"]
