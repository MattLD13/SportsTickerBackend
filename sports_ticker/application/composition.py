"""Compose the rewrite application services."""

from __future__ import annotations

import time
import hashlib
import secrets
from collections.abc import Mapping
from dataclasses import replace
from math import isfinite
from threading import Lock
from typing import Any, Callable

from sports_ticker.domain import DisplaySettings
from sports_ticker.fleet import DeviceMetadata, TickerRecord, TickerRepository
from sports_ticker.providers import ProviderHealth
from sports_ticker.projections import project_data_v2, select_display_content

from .events import EventService, event_to_mapping
from .scheduler import RefreshScheduler, SchedulerHealth
from .state_store import SnapshotStore


class BackendApplication:
    """Own the rewrite repositories, snapshot store, and optional scheduler."""

    def __init__(
        self,
        repository: TickerRepository,
        snapshot_store: SnapshotStore,
        scheduler: RefreshScheduler | None = None,
        *,
        runtime: object | None = None,
        spotify_service: object | None = None,
        catalog: object | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Capture infrastructure through dependency injection."""

        self.repository = repository
        self.snapshot_store = snapshot_store
        self.scheduler = scheduler
        self.runtime = runtime
        self.spotify_service = spotify_service
        self.catalog = catalog
        self._clock = clock
        self._close_lock = Lock()
        self._closed = False
        self.event_service = EventService(repository, clock=clock)
        self.events = self.event_service
        if self.scheduler is not None:
            for ticker in self.repository.list_tickers():
                self._register_scheduler_ticker(ticker.ticker_id)

    @property
    def ticker_repository(self) -> TickerRepository:
        """Return the owned ticker repository."""

        return self.repository

    @property
    def store(self) -> SnapshotStore:
        """Return the owned snapshot store."""

        return self.snapshot_store

    def list_tickers(self) -> tuple[TickerRecord, ...]:
        """Return all configured tickers."""

        return self.repository.list_tickers()

    def get_ticker(self, ticker_id: str) -> TickerRecord | None:
        """Return one configured ticker."""

        return self.repository.get_ticker(ticker_id)

    def exchange_pairing_code(self, pairing_code: str) -> tuple[TickerRecord, str]:
        """Consume one pairing code and return one opaque controller token once."""

        token = f"ctk_{secrets.token_urlsafe(32)}"
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        ticker = self.repository.exchange_pairing_code(
            pairing_code,
            token_hash,
            now=self._clock(),
        )
        self._register_scheduler_ticker(ticker.ticker_id)
        return ticker, token

    def issue_pairing_code(self, ticker_id: str) -> str:
        """Issue one unique six-digit code for another controller."""

        identifier = str(ticker_id).strip()
        for _ in range(10):
            code = f"{secrets.randbelow(1_000_000):06d}"
            try:
                self.repository.issue_pairing_code(identifier, code)
                return code
            except ValueError as error:
                if str(error) != "pairing code is already in use":
                    raise
        raise RuntimeError("could not issue a unique pairing code")

    def unpair_ticker(self, ticker_id: str) -> tuple[TickerRecord, str]:
        """Revoke controller access and return one new pairing code."""

        identifier = str(ticker_id).strip()
        for _ in range(10):
            code = f"{secrets.randbelow(1_000_000):06d}"
            try:
                return self.repository.unpair_ticker(identifier, code), code
            except ValueError as error:
                if str(error) != "pairing code is already in use":
                    raise
        raise RuntimeError("could not issue a unique pairing code")

    def authorize_controller(self, ticker_id: str, token: str) -> bool:
        """Validate one opaque controller token for one ticker."""

        digest = hashlib.sha256(str(token).encode("utf-8")).hexdigest()
        return self.repository.authorize_controller(
            str(ticker_id).strip(), digest, now=self._clock()
        )

    def create_ticker(
        self,
        ticker_id: str,
        *,
        name: str = "Ticker",
        display_settings: DisplaySettings | Mapping[str, Any] | None = None,
        pairing: Mapping[str, Any] | None = None,
        device: Mapping[str, Any] | None = None,
    ) -> TickerRecord:
        """Create one configured ticker."""

        ticker = self.repository.create_ticker(
            ticker_id,
            display_settings=display_settings,
            name=name,
            pairing=pairing,
            device=device,
        )
        self._register_scheduler_ticker(ticker.ticker_id)
        return ticker

    def update_ticker(self, ticker_id: str, **changes: object) -> TickerRecord:
        """Apply one validated partial ticker update."""

        return self.repository.update_ticker(ticker_id, **changes)

    def delete_ticker(self, ticker_id: str) -> bool:
        """Delete one configured ticker."""

        deleted = self.repository.delete_ticker(ticker_id)
        if deleted and self.scheduler is not None:
            self.scheduler.unregister_ticker(ticker_id)
        return deleted

    def _register_scheduler_ticker(self, ticker_id: str) -> None:
        """Attach one repository-backed settings resolver to the scheduler."""

        if self.scheduler is None or self.scheduler.has_ticker(ticker_id):
            return
        self.scheduler.register_ticker(ticker_id, self._resolve_ticker_settings)

    def _resolve_ticker_settings(self, ticker_id: str) -> DisplaySettings:
        """Read the current isolated display settings for one scheduler refresh."""

        ticker = self.repository.get_ticker(ticker_id)
        if ticker is None:
            raise KeyError(f"ticker not found: {ticker_id}")
        return ticker.display_settings

    def get_snapshot(self, ticker_id: str):
        """Return the latest immutable snapshot for one ticker."""

        return self.snapshot_store.get(ticker_id)

    def project_data(
        self,
        ticker_id: str,
        meta: Mapping[str, Any] | None = None,
        *,
        mode: str | None = None,
    ) -> dict[str, Any]:
        """Project one snapshot with active durable events appended."""

        identifier = str(ticker_id).strip()
        snapshot = self.get_snapshot(identifier)
        if snapshot is None:
            raise KeyError(f"ticker snapshot not found: {identifier}")
        ticker = self.repository.get_ticker(identifier)
        if ticker is None:
            raise KeyError(f"ticker not found: {identifier}")
        self.event_service.remove_expired()
        data = project_data_v2(
            replace(snapshot, effective_settings=ticker.display_settings),
            self.provider_health(),
            {"stale": False} if meta is None else meta,
        )
        settings = data["settings"]
        if ticker.pairing is None or not ticker.pairing.paired:
            settings["mode"] = "pairing"
        elif mode is not None:
            settings["mode"] = str(mode).strip().lower()
            settings["sports_presentation"] = "rotation"
            settings["pinned_content_id"] = ""
        data["content"] = select_display_content(data["content"], settings)
        pairing = ticker.pairing
        data["meta"]["pairing"] = {
            "paired": bool(pairing is not None and pairing.paired),
            "code": None if pairing is None or pairing.paired else pairing.pairing_code,
        }
        pending_update = ticker.device.metadata.get("pending_update")
        if isinstance(pending_update, Mapping):
            version = str(pending_update.get("version") or "").strip()
            if version:
                data["meta"]["update"] = {"version": version}
        events = self.event_service.pending(identifier)
        event_payload = data["events"]
        event_payload["alerts"] = list(event_payload["alerts"])
        event_payload["news"] = list(event_payload["news"])
        for event in events:
            event_payload[event.event_type].append(event_to_mapping(event))
        return data

    def get_data(self, ticker_id: str, meta: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Return one projected ticker data response."""

        return self.project_data(ticker_id, meta)

    def publish_alert_event(self, payload: Mapping[str, Any], **values: Any):
        """Publish one score alert overlay."""

        return self.event_service.publish_alert(payload, **values)

    def publish_news_event(self, payload: Mapping[str, Any], **values: Any):
        """Publish one news overlay."""

        return self.event_service.publish_news(payload, **values)

    def acknowledge_event(self, ticker_id: str, event_id: str) -> bool:
        """Acknowledge one overlay for one ticker."""

        return self.event_service.acknowledge(ticker_id, event_id)

    def heartbeat(self, ticker_id: str, payload: Mapping[str, Any]) -> TickerRecord:
        """Persist one device heartbeat and return the updated ticker."""

        current = self.repository.get_ticker(ticker_id)
        if current is None:
            raise KeyError(str(ticker_id).strip())

        raw_metadata = payload.get("metadata")
        if raw_metadata is None:
            raw_metadata = {
                key: value
                for key, value in payload.items()
                if key not in {"last_seen", "last_seen_at"}
            }
        if not isinstance(raw_metadata, Mapping):
            raise ValueError("metadata must be an object")
        metadata = dict(current.device.metadata)
        metadata.update(
            {
                key: value
                for key, value in raw_metadata.items()
                if key not in {"last_seen", "last_seen_at"}
            }
        )

        raw_last_seen = payload.get("last_seen_at", payload.get("last_seen"))
        last_seen = self._clock() if raw_last_seen is None else _finite_timestamp(raw_last_seen)
        device = DeviceMetadata(last_seen_at=last_seen, metadata=metadata)
        return self.repository.update_ticker(ticker_id, device=device)

    def request_update(self, ticker_id: str, version: str) -> TickerRecord:
        """Persist one pending controller update for the target ticker."""

        identifier = str(ticker_id).strip()
        current = self.repository.get_ticker(identifier)
        if current is None:
            raise KeyError(identifier)
        release = str(version).strip()
        if not release:
            raise ValueError("update version must not be empty")
        metadata = dict(current.device.metadata)
        metadata["pending_update"] = {"version": release}
        return self.repository.update_ticker(
            identifier,
            device=DeviceMetadata(last_seen_at=current.device.last_seen_at, metadata=metadata),
        )

    def acknowledge_update(self, ticker_id: str, version: str) -> bool:
        """Clear the matching pending update before the Pi restarts itself."""

        identifier = str(ticker_id).strip()
        current = self.repository.get_ticker(identifier)
        if current is None:
            raise KeyError(identifier)
        metadata = dict(current.device.metadata)
        pending = metadata.get("pending_update")
        if not isinstance(pending, Mapping) or str(pending.get("version") or "") != str(version).strip():
            return False
        del metadata["pending_update"]
        self.repository.update_ticker(
            identifier,
            device=DeviceMetadata(last_seen_at=current.device.last_seen_at, metadata=metadata),
        )
        return True

    def close(self) -> None:
        """Stop owned work and close the owned repository once."""

        with self._close_lock:
            if self._closed:
                return
            self._closed = True

        failures: list[Exception] = []
        for component in (self.runtime, self.scheduler):
            if component is None:
                continue
            stop = getattr(component, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception as error:
                    failures.append(error)
            close = getattr(component, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as error:
                    failures.append(error)
        try:
            self.repository.close()
        except Exception as error:
            failures.append(error)

        if failures:
            raise failures[0]

    def scheduler_health(self) -> Mapping[str, SchedulerHealth] | None:
        """Return scheduler health without exposing scheduler internals to routes."""

        if self.scheduler is None:
            return None
        return self.scheduler.health

    def provider_health(self) -> ProviderHealth:
        """Summarize scheduler errors for the data projection."""

        health = self.scheduler_health()
        if health is None:
            return ProviderHealth(provider="backend")

        errors: list[str] = []
        for name, item in health.items():
            error = item.get("last_error") if isinstance(item, Mapping) else getattr(item, "last_error", None)
            if error:
                errors.append(f"{name}: {error}")
        return ProviderHealth(
            provider="scheduler",
            healthy=not errors,
            error="; ".join(errors) if errors else None,
        )


def _finite_timestamp(value: object) -> float:
    """Convert one heartbeat timestamp and reject non-finite values."""

    try:
        timestamp = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("last_seen_at must be a finite number") from exc
    if not isfinite(timestamp):
        raise ValueError("last_seen_at must be a finite number")
    return timestamp


__all__ = ["BackendApplication"]
