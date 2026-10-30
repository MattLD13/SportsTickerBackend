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

from ticker.shared.domain import (
    DisplaySettings,
)

from ticker.shared.domain.settings import settings_from_mapping, settings_to_mapping

from ticker.server.store.event_records import EventRecords
from ticker.server.store.json_values import _dump
from ticker.server.store.models import (
    DeviceMetadata,
    PairingState,
    TickerRecord,
)
from ticker.server.store.pairing_records import PairingRecords
from ticker.server.store.schedule_records import ScheduleRecords
from ticker.server.store.schema import SchemaMigrations
from ticker.server.store.spotify_records import SpotifyRecords


_UNSET = object()


def _clear_incompatible_sports_pin(settings: dict[str, Any]) -> None:
    """Clear pinned sports fields when a partial update changes the top-level mode."""

    if str(settings.get("mode", "sports")).strip().lower() != "sports":
        settings["sports_presentation"] = "rotation"
        settings["pinned_content_id"] = ""


def _pairing(value: PairingState | Mapping[str, Any] | None) -> PairingState | None:
    if value is None or isinstance(value, PairingState):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("pairing must be PairingState, a mapping, or None")
    clients = value.get("client_ids", value.get("clients", ()))
    return PairingState(
        pairing_code=value.get("pairing_code"),
        pairing_code_expires_at=value.get("pairing_code_expires_at", value.get("expires_at")),
        controller_group_id=value.get("controller_group_id"),
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


class TickerRepository(SchemaMigrations, ScheduleRecords, EventRecords, PairingRecords, SpotifyRecords):
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
        from ticker.server.store.update_ledger import UpdateLedger
        self.updates = UpdateLedger(self)

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

    def merge_device_telemetry(self, ticker_id: str, values: Mapping[str, Any], *, now: float) -> TickerRecord:
        """Merge device facts without overwriting concurrent server commands."""
        with self._transaction():
            ticker = self.get_ticker(ticker_id)
            if ticker is None:
                raise KeyError(ticker_id)
            metadata = dict(ticker.device.metadata)
            metadata.update({key: value for key, value in values.items() if key not in {"last_seen", "last_seen_at"}})
            return self.update_ticker(ticker_id, device=DeviceMetadata(last_seen_at=now, metadata=metadata))

    def set_device_credential_hash(self, ticker_id: str, token_sha256: str, *, now: float) -> None:
        """Rotate one device credential through an authorized application operation."""
        from ticker.server.store.device_credentials import validate_device_hash
        digest = validate_device_hash(token_sha256)
        with self._transaction():
            if self.get_ticker(ticker_id) is None:
                raise KeyError(ticker_id)
            # The token alone identifies the ticker, so two tickers cannot share one token.
            if self._connection.execute("SELECT 1 FROM device_credentials WHERE token_sha256 = ? AND ticker_id != ?",
                                        (digest, ticker_id)).fetchone() is not None:
                raise ValueError("device token belongs to another ticker")
            self._connection.execute(
                "INSERT INTO device_credentials(ticker_id, token_sha256, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(ticker_id) DO UPDATE SET token_sha256=excluded.token_sha256, updated_at=excluded.updated_at",
                (ticker_id, digest, now),
            )

    def authorize_device(self, ticker_id: str, token: str) -> bool:
        """Compare one supplied device credential with its durable hash."""
        from ticker.server.store.device_credentials import device_token_hash
        try:
            supplied = device_token_hash(token)
        except ValueError:
            return False
        return self.authorize_device_hash(ticker_id, supplied)

    def ticker_for_device_token(self, token: str) -> str | None:
        """Return the ticker that owns one device token, or None if no single ticker owns it."""
        from ticker.server.store.device_credentials import device_token_hash
        try:
            supplied = device_token_hash(token)
        except ValueError:
            return None
        with self._lock:
            rows = self._connection.execute("SELECT ticker_id, token_sha256 FROM device_credentials WHERE token_sha256 = ?",
                                            (supplied,)).fetchall()
        owners = [row["ticker_id"] for row in rows if hmac.compare_digest(supplied, row["token_sha256"])]
        return owners[0] if len(owners) == 1 else None

    def authorize_device_hash(self, ticker_id: str, digest: str) -> bool:
        """Authorize a registration digest inside the registration transaction boundary."""
        with self._lock:
            row = self._connection.execute("SELECT token_sha256 FROM device_credentials WHERE ticker_id = ?", (ticker_id,)).fetchone()
        return row is not None and hmac.compare_digest(digest, row["token_sha256"])

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
        credential_hash: str | None = None,
    ) -> TickerRecord:
        if isinstance(ticker_id, TickerRecord):
            record = ticker_id
        else:
            now = time.time()
            record = TickerRecord(
                ticker_id=ticker_id,
                name=name,
                display_settings=settings_from_mapping(display_settings),
                pairing=_pairing(pairing),
                device=_device(device),
                created_at=now,
                updated_at=now,
            )

        with self._transaction():
            try:
                self._insert_record(record)
                if credential_hash is not None:
                    self.set_device_credential_hash(record.ticker_id, credential_hash, now=record.created_at)
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
            (record.ticker_id, _dump(settings_to_mapping(record.display_settings))),
        )
        if record.pairing is not None:
            self._connection.execute(
                "INSERT INTO ticker_pairing "
                "(ticker_id, pairing_code, pairing_code_expires_at, controller_group_id, paired, client_ids_json) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record.ticker_id,
                    record.pairing.pairing_code,
                    record.pairing.pairing_code_expires_at,
                    record.pairing.controller_group_id,
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
            "SELECT pairing_code, pairing_code_expires_at, controller_group_id, paired, client_ids_json FROM ticker_pairing WHERE ticker_id = ?",
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
                controller_group_id=pairing_row["controller_group_id"],
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
            display = settings_from_mapping(json.loads(display_row["settings_json"]))
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
                if isinstance(display_settings, Mapping):
                    merged_settings = settings_to_mapping(current.display_settings)
                    merged_settings.update(display_settings)
                    _clear_incompatible_sports_pin(merged_settings)
                    next_settings = settings_from_mapping(merged_settings)
                else:
                    next_settings = settings_from_mapping(display_settings)  # type: ignore[arg-type]
            elif settings is not _UNSET:
                if isinstance(settings, Mapping):
                    merged_settings = settings_to_mapping(current.display_settings)
                    merged_settings.update(settings)
                    _clear_incompatible_sports_pin(merged_settings)
                    next_settings = settings_from_mapping(merged_settings)
                else:
                    next_settings = settings_from_mapping(settings)  # type: ignore[arg-type]
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

    def _require_ticker_locked(self, ticker_id: str) -> None:
        if not ticker_id:
            raise ValueError("ticker_id must not be empty")
        row = self._connection.execute(
            "SELECT ticker_id FROM tickers WHERE ticker_id = ?", (ticker_id,)
        ).fetchone()
        if row is None:
            raise KeyError(ticker_id)

__all__ = ["TickerRepository"]
