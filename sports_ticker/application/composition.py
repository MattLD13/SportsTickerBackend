"""Compose the rewrite application services."""

from __future__ import annotations

import time
import hashlib
import secrets
from uuid import uuid4
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
from math import isfinite
from threading import Lock
from typing import TYPE_CHECKING, Any

from sports_ticker.domain import DisplaySettings, TickerSnapshot
from sports_ticker.fleet import DeviceMetadata, TickerProfile, TickerRecord, TickerRepository
from sports_ticker.providers.contracts import ProviderHealth
from sports_ticker.projections import project_data_v2, select_display_content
from sports_ticker.projections.device_data import project_device_data, compact_mini_data

from .events import EventService, event_to_mapping
from .scheduler import RefreshScheduler, SchedulerHealth
from .schedule import ScheduleService
from .state_store import SnapshotStore

if TYPE_CHECKING:
    from sports_ticker.assets.mini_artwork import MiniArtworkService
    from sports_ticker.assets.mini_service import MiniSpriteService


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
        weather_location_resolver: Callable[[str], Mapping[str, object] | None] | None = None,
        schedule_service: ScheduleService | None = None,
        clock: Callable[[], float] = time.time,
        pairing_code_ttl_seconds: float = 600.0,
        mini_sprites: MiniSpriteService | None = None,
        mini_artwork: MiniArtworkService | None = None,
        owned_resources: tuple[object, ...] = (),
    ) -> None:
        """Capture infrastructure through dependency injection."""

        self.repository = repository
        self.snapshot_store = snapshot_store
        self.scheduler = scheduler
        self.runtime = runtime
        self.spotify_service = spotify_service
        self.catalog = catalog
        self.mini_sprites = mini_sprites
        self.mini_artwork = mini_artwork
        self.weather_location_resolver = weather_location_resolver
        self._clock = clock
        if pairing_code_ttl_seconds <= 0:
            raise ValueError("pairing_code_ttl_seconds must be positive")
        self._pairing_code_ttl_seconds = pairing_code_ttl_seconds
        self._close_lock = Lock()
        self._pairing_refresh_lock = Lock()
        self._closed = False
        self._owned_resources = list(owned_resources)
        self.schedule_service = schedule_service or ScheduleService(
            repository,
            snapshot_store,
            clock=clock,
        )
        self.event_service = EventService(
            repository,
            clock=clock,
            retention_seconds=self._maximum_live_delay,
        )
        self.events = self.event_service
        if self.scheduler is not None:
            for ticker in self.repository.list_tickers():
                self._register_scheduler_ticker(ticker.ticker_id)

    @property
    def store(self) -> SnapshotStore:
        """Return the owned snapshot store."""

        return self.snapshot_store

    def list_tickers(self) -> tuple[TickerRecord, ...]:
        """Return tickers seen within thirty days for fleet lists."""

        return self.visible_tickers(self.repository.list_tickers())

    def visible_tickers(self, tickers: Iterable[TickerRecord]) -> tuple[TickerRecord, ...]:
        """Hide inactive records while retaining their settings and controller ownership."""
        cutoff = self._clock() - 30 * 24 * 60 * 60
        return tuple(
            ticker for ticker in tickers
            if (ticker.created_at if ticker.device.last_seen_at is None else ticker.device.last_seen_at) > cutoff
        )

    def list_tickers_for_controller(self, token: str) -> tuple[TickerRecord, ...]:
        """Return the fleet visible to one opaque controller token."""

        digest = hashlib.sha256(str(token).encode("utf-8")).hexdigest()
        return self.repository.list_tickers_for_controller(digest)

    def get_ticker(self, ticker_id: str) -> TickerRecord | None:
        """Return one configured ticker."""

        return self.repository.get_ticker(ticker_id)

    def register_device(
        self,
        device_id: str,
        *,
        name: str = "Ticker",
        metadata: Mapping[str, Any] | None = None,
        profile: Mapping[str, Any] | TickerProfile | None = None,
        pairing_code: str | None = None,
        credential_hash: str | None = None,
    ) -> tuple[TickerRecord, str | None, bool]:
        """Create or refresh one device-owned ticker and its pairing session code."""

        identifier = str(device_id).strip()
        if not identifier:
            raise ValueError("device_id must not be empty")
        device_metadata = dict(metadata or {})
        profile_mapping = profile.to_mapping() if isinstance(profile, TickerProfile) else profile
        device_profile = TickerProfile.from_mapping(profile_mapping, metadata=device_metadata)
        device_metadata["profile"] = device_profile.to_mapping()
        current = self.repository.get_ticker(identifier)
        created = False
        if current is None:
            try:
                current = self.create_ticker(
                    identifier,
                    credential_hash=credential_hash,
                    name=str(name).strip() or "Ticker",
                    display_settings={"mode": "sports"},
                    pairing={"paired": False},
                    device={"metadata": device_metadata},
                )
                created = True
            except ValueError as error:
                if str(error) != f"ticker already exists: {identifier}":
                    raise
                current = self.repository.get_ticker(identifier)
        if current is None:
            raise KeyError(identifier)

        if credential_hash is not None and not self.repository.authorize_device_hash(identifier, credential_hash):
            raise PermissionError("device authorization is invalid")
        if credential_hash is not None and not created and current.profile.product_family != device_profile.product_family:
            raise ValueError("registered product family cannot change")
        current = self.heartbeat(identifier, {"metadata": device_metadata}, registration=True)
        self._ensure_display_snapshot(current)
        current, response_pairing_code = self._device_pairing_record(identifier, pairing_code)
        return current, response_pairing_code, created

    def _device_pairing_record(self, identifier: str, pairing_code: str | None = None) -> tuple[TickerRecord, str | None]:
        """Keep one current app code across registration and snapshot reads."""
        with self._pairing_refresh_lock:
            current = self.repository.get_ticker(identifier)
            if current is None:
                raise KeyError(identifier)
            pairing = current.pairing
            requested_pairing_code = str(pairing_code or "").strip()
            response_pairing_code = None
            if pairing is None or not pairing.paired:
                current_code = pairing.pairing_code if pairing is not None else None
                expires_at = pairing.pairing_code_expires_at if pairing is not None else None
                if requested_pairing_code and current_code == requested_pairing_code:
                    # Keep the code already exposed by the mini valid while its BLE session completes.
                    self.repository.issue_pairing_code(
                        identifier,
                        requested_pairing_code,
                        expires_at=self._clock() + self._pairing_code_ttl_seconds,
                    )
                    current = self.repository.get_ticker(identifier)
                    if current is None:
                        raise KeyError(identifier)
                    response_pairing_code = requested_pairing_code
                else:
                    response_pairing_code = current_code
                if not response_pairing_code or (
                    requested_pairing_code != response_pairing_code
                    and expires_at is not None
                    and self._clock() >= float(expires_at)
                ):
                    response_pairing_code = self.issue_pairing_code(identifier)
                    current = self.repository.get_ticker(identifier)
                    if current is None:
                        raise KeyError(identifier)
            return current, response_pairing_code

    def _ensure_display_snapshot(self, ticker: TickerRecord) -> None:
        """Create the first empty snapshot before a device starts polling."""

        if self.snapshot_store.get(ticker.ticker_id) is not None:
            return
        self.snapshot_store.replace(
            TickerSnapshot(
                ticker_id=ticker.ticker_id,
                revision=0,
                observed_at=datetime.fromtimestamp(self._clock(), tz=timezone.utc),
                content=(),
                alerts=(),
                news=(),
                effective_settings=ticker.display_settings,
            )
        )

    def exchange_pairing_code(
        self,
        pairing_code: str,
        *,
        controller_group_id: str | None = None,
        controller_group_secret: str | None = None,
    ) -> tuple[TickerRecord, str, str | None, str | None]:
        """Consume one pairing code and return a token plus optional shared group credentials."""

        normalized_code = str(pairing_code).strip()
        supplied_group_id = str(controller_group_id or "").strip() or None
        supplied_group_secret = str(controller_group_secret or "").strip() or None
        if (supplied_group_id is None) != (supplied_group_secret is None):
            raise ValueError("controller group credentials must be provided together")
        existing_group_id = self.repository.controller_group_id_for_pairing_code(normalized_code)
        new_group = supplied_group_id is None and existing_group_id is None
        group_id = supplied_group_id or (None if existing_group_id else f"cg_{secrets.token_urlsafe(18)}")
        group_secret = supplied_group_secret or (f"cgs_{secrets.token_urlsafe(32)}" if new_group else None)
        token = f"ctk_{secrets.token_urlsafe(32)}"
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        ticker = self.repository.exchange_pairing_code(
            normalized_code,
            token_hash,
            now=self._clock(),
            controller_group_id=group_id,
            controller_group_secret_hash=hashlib.sha256(group_secret.encode("utf-8")).hexdigest() if group_secret else None,
        )
        self._register_scheduler_ticker(ticker.ticker_id)
        returned_group_id = (
            ticker.pairing.controller_group_id
            if ticker.pairing is not None and (new_group or supplied_group_id is not None)
            else None
        )
        return ticker, token, returned_group_id, group_secret if new_group else None

    def issue_pairing_code(self, ticker_id: str) -> str:
        """Issue one unique six-digit code for another controller."""

        identifier = str(ticker_id).strip()
        for _ in range(10):
            code = f"{secrets.randbelow(1_000_000):06d}"
            try:
                self.repository.issue_pairing_code(
                    identifier,
                    code,
                    expires_at=self._clock() + self._pairing_code_ttl_seconds,
                )
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
                result = self.repository.unpair_ticker(
                    identifier,
                    code,
                    expires_at=self._clock() + self._pairing_code_ttl_seconds,
                )
                return result, code
            except ValueError as error:
                if str(error) != "pairing code is already in use":
                    raise
        raise RuntimeError("could not issue a unique pairing code")

    def authorize_device(self, ticker_id: str, token: str) -> bool:
        """Authorize the physical device independently of controller sessions."""
        return self.repository.authorize_device(ticker_id, token)

    def enroll_device_credential(self, ticker_id: str, token_sha256: str) -> None:
        """Persist an administrator-authorized device credential hash."""
        self.repository.set_device_credential_hash(ticker_id, token_sha256, now=self._clock())

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
        credential_hash: str | None = None,
    ) -> TickerRecord:
        """Create one configured ticker."""

        ticker = self.repository.create_ticker(
            ticker_id,
            display_settings=display_settings,
            name=name,
            pairing=pairing,
            device=device,
            credential_hash=credential_hash,
        )
        self._register_scheduler_ticker(ticker.ticker_id)
        return ticker

    def update_ticker(self, ticker_id: str, **changes: object) -> TickerRecord:
        """Apply one validated partial ticker update."""

        schedule_override = changes.pop("schedule_override", None)
        if schedule_override is not None and not isinstance(schedule_override, bool):
            raise TypeError("schedule_override must be a boolean")
        changes = self._resolve_weather_location(changes)
        ticker = self.repository.update_ticker(ticker_id, **changes)
        if schedule_override is not None:
            self.schedule_service.set_schedule_override(
                ticker.ticker_id,
                schedule_override,
                settings=ticker.display_settings,
            )
        return self.repository.get_ticker(ticker.ticker_id)

    def _resolve_weather_location(self, changes: Mapping[str, object]) -> dict[str, object]:
        """Canonicalize a ZIP code before the repository stores weather settings."""

        resolver = self.weather_location_resolver
        settings = changes.get("display_settings")
        if resolver is None or not isinstance(settings, Mapping):
            return dict(changes)
        try:
            location = resolver(str(settings.get("weather_city", "")))
        except Exception:
            return dict(changes)
        if not isinstance(location, Mapping):
            return dict(changes)
        updated = dict(settings)
        updated.update(location)
        resolved = dict(changes)
        resolved["display_settings"] = updated
        return resolved

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
        return self._effective_settings_for_ticker(ticker)

    def schedule_document(self, ticker_id: str) -> dict[str, object]:
        """Return one ticker's recurring schedule document."""

        ticker = self.repository.get_ticker(ticker_id)
        if ticker is None:
            raise KeyError(f"ticker not found: {ticker_id}")
        return self.schedule_service.document(
            ticker.ticker_id,
            ticker.display_settings,
            allowed_modes=ticker.profile.capabilities.modes,
        )

    def schedule_status(self, ticker_id: str) -> dict[str, object]:
        """Return one ticker's current schedule status."""

        ticker = self.repository.get_ticker(ticker_id)
        if ticker is None:
            raise KeyError(f"ticker not found: {ticker_id}")
        return self.schedule_service.status(
            ticker.ticker_id,
            ticker.display_settings,
            allowed_modes=ticker.profile.capabilities.modes,
        )

    def schedule_override(self, ticker_id: str) -> bool:
        """Return whether one ticker follows an app-owned mode override."""

        return self.schedule_service.schedule_override(ticker_id)

    def schedule_override_expires_at(self, ticker_id: str) -> float | None:
        """Return one ticker's temporary app override expiry."""

        return self.schedule_service.schedule_override_expires_at(ticker_id)

    def create_schedule_block(self, ticker_id: str, **values: object):
        """Create one ticker-owned recurring schedule block."""

        return self.schedule_service.create_block(ticker_id, **values)

    def update_schedule_block(self, ticker_id: str, block_id: str, **values: object):
        """Update one ticker-owned recurring schedule block."""

        return self.schedule_service.update_block(ticker_id, block_id, **values)

    def delete_schedule_block(self, ticker_id: str, block_id: str) -> bool:
        """Delete one ticker-owned recurring schedule block."""

        return self.schedule_service.delete_block(ticker_id, block_id)

    def create_schedule_condition(self, ticker_id: str, **values: object):
        """Create one ticker-owned recurring schedule condition."""

        return self.schedule_service.create_condition(ticker_id, **values)

    def update_schedule_condition(self, ticker_id: str, condition_id: str, **values: object):
        """Update one ticker-owned recurring schedule condition."""

        return self.schedule_service.update_condition(ticker_id, condition_id, **values)

    def delete_schedule_condition(self, ticker_id: str, condition_id: str) -> bool:
        """Delete one ticker-owned recurring schedule condition."""

        return self.schedule_service.delete_condition(ticker_id, condition_id)

    def _effective_settings_for_ticker(self, ticker: TickerRecord) -> DisplaySettings:
        """Resolve one ticker's schedule rules against its base settings."""

        return self.schedule_service.effective_settings(
            ticker.ticker_id,
            ticker.display_settings,
            allowed_modes=ticker.profile.capabilities.modes,
        )

    def get_snapshot(self, ticker_id: str):
        """Return the latest immutable snapshot for one ticker."""

        return self.snapshot_store.get(ticker_id)

    def project_data(
        self,
        ticker_id: str,
        meta: Mapping[str, Any] | None = None,
        *,
        mode: str | None = None,
        device_view: bool = False,
    ) -> dict[str, Any]:
        """Project one snapshot with active durable events appended."""

        identifier = str(ticker_id).strip()
        snapshot = self.get_snapshot(identifier)
        if snapshot is None:
            raise KeyError(f"ticker snapshot not found: {identifier}")
        ticker, _ = self._device_pairing_record(identifier)
        effective_settings, schedule = self.schedule_service.resolve(
            identifier,
            ticker.display_settings,
            allowed_modes=ticker.profile.capabilities.modes,
        )
        delayed = bool(effective_settings.live_delay_mode)
        if delayed:
            delayed_snapshot = self.snapshot_store.get_delayed(
                identifier,
                effective_settings.live_delay_seconds,
            )
            if delayed_snapshot is not None:
                snapshot = delayed_snapshot
        self.event_service.remove_expired()
        data = project_data_v2(
            replace(snapshot, effective_settings=effective_settings),
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
        data["content"] = select_display_content(
            data["content"],
            settings,
            allowed_modes=ticker.profile.capabilities.modes,
        )
        if device_view:
            data = project_device_data(data)
        if ticker.profile.product_family == "mini":
            self._attach_mini_assets(data["content"], ticker)
        pairing = ticker.pairing
        data["meta"]["pairing"] = {
            "paired": bool(pairing is not None and pairing.paired),
            "code": None if pairing is None or pairing.paired else pairing.pairing_code,
        }
        data["meta"]["profile"] = ticker.profile.to_mapping()
        data["meta"]["schedule"] = schedule
        data["meta"]["live_delay"] = {
            "enabled": delayed,
            "seconds": effective_settings.live_delay_seconds if delayed else 0,
        }
        data["meta"].update(_command_meta(self._active_commands(ticker)))
        visible_at = self._clock() - effective_settings.live_delay_seconds if delayed else None
        events = self.event_service.pending(identifier, visible_at=visible_at)
        event_payload = data["events"]
        event_payload["alerts"] = list(event_payload["alerts"])
        event_payload["news"] = list(event_payload["news"])
        for event in events:
            event_payload[event.event_type].append(event_to_mapping(event))
        return compact_mini_data(data) if device_view and ticker.profile.product_family == "mini" else data

    def _attach_mini_assets(self, content: Mapping[str, Any], ticker: TickerRecord) -> None:
        """Add Mini sprite and artwork references to the visible content of one Mini."""

        if self.mini_sprites is not None and ticker.device.metadata.get("mini_sprite_protocol") == 1:
            from sports_ticker.providers.logo_overrides import mini_logo_sources

            for item in content.get("sports", ()):
                if not item.get("is_shown", True):
                    continue
                game = item["data"]
                for side in ("away", "home"):
                    game[f"{side}_logo_asset"] = self.mini_sprites.reference(*mini_logo_sources(game, side))
            for item in content.get("stock", ()):
                if not item.get("is_shown", True):
                    continue
                stock = item["data"]
                stock["home_logo_asset"] = self.mini_sprites.reference(stock.get("home_logo", ""))
        if self.mini_artwork is not None:
            for item in content.get("music", ()):
                music = item["data"]
                music.update(self.mini_artwork.music_references(music))

    def publish_alert_event(self, payload: Mapping[str, Any], **values: Any):
        """Publish one score alert overlay."""

        return self.event_service.publish_alert(payload, **values)

    def publish_news_event(self, payload: Mapping[str, Any], **values: Any):
        """Publish one news overlay."""

        return self.event_service.publish_news(payload, **values)

    def acknowledge_event(self, ticker_id: str, event_id: str) -> bool:
        """Acknowledge one overlay for one ticker."""

        return self.event_service.acknowledge(ticker_id, event_id)

    def heartbeat(self, ticker_id: str, payload: Mapping[str, Any], *, registration: bool = False) -> TickerRecord:
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
        reserved = {"pending_commands", "pending_update", "pending_reboot", "last_update_result"}
        if not registration:
            reserved.add("profile")
        if reserved.intersection(raw_metadata):
            raise ValueError("device telemetry contains server-owned fields")
        return self.repository.merge_device_telemetry(ticker_id, raw_metadata, now=self._clock())

    def request_update(self, ticker_id: str, version: str) -> TickerRecord:
        """Persist one pending controller update for the target ticker."""

        identifier = str(ticker_id).strip()
        current = self.repository.get_ticker(identifier)
        if current is None:
            raise KeyError(identifier)
        release = str(version).strip()
        if not release:
            raise ValueError("update version must not be empty")
        return self.repository.updates.queue(identifier, release, self._clock())

    def request_reboot(self, ticker_id: str) -> TickerRecord:
        """Persist one reboot command for the target controller."""

        identifier = str(ticker_id).strip()
        current = self.repository.get_ticker(identifier)
        if current is None:
            raise KeyError(identifier)
        metadata = self._queue_command_metadata(current, "reboot", {})
        return self.repository.update_ticker(
            identifier,
            device=DeviceMetadata(last_seen_at=current.device.last_seen_at, metadata=metadata),
        )

    def acknowledge_reboot(self, ticker_id: str, command_id: str) -> bool:
        """Clear one matching reboot command before the controller restarts."""

        identifier = str(ticker_id).strip()
        current = self.repository.get_ticker(identifier)
        if current is None:
            raise KeyError(identifier)
        received = str(command_id).strip()
        metadata = dict(current.device.metadata)
        command = self._find_command(metadata, "reboot", lambda payload: True, command_id=received)
        if command is None:
            return False
        self._remove_command(metadata, received)
        self.repository.update_ticker(
            identifier,
            device=DeviceMetadata(last_seen_at=current.device.last_seen_at, metadata=metadata),
        )
        return True

    def _queue_command_metadata(self, ticker: TickerRecord, command_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Append one durable command to device metadata and return the next metadata mapping."""

        metadata = dict(ticker.device.metadata)
        commands = [dict(item) for item in metadata.get("pending_commands", ()) if isinstance(item, Mapping)]
        command = {
            "id": str(uuid4()),
            "type": command_type,
            "payload": dict(payload),
            "created_at": self._clock(),
            "expires_at": self._clock() + 900.0,
        }
        commands = [item for item in commands if str(item.get("type") or "") != command_type]
        commands.append(command)
        metadata["pending_commands"] = commands
        return metadata

    def _active_commands(self, ticker: TickerRecord) -> tuple[Mapping[str, Any], ...]:
        """Return unexpired durable commands."""

        raw = ticker.device.metadata.get("pending_commands", ())
        now = self._clock()
        commands = []
        if isinstance(raw, (list, tuple)):
            for item in raw:
                if not isinstance(item, Mapping):
                    continue
                expires_at = item.get("expires_at")
                if expires_at is not None:
                    try:
                        if float(expires_at) <= now:
                            continue
                    except (TypeError, ValueError):
                        continue
                commands.append(dict(item))
        return tuple(commands)

    @staticmethod
    def _find_command(
        metadata: Mapping[str, Any],
        command_type: str,
        predicate: Callable[[Mapping[str, Any]], bool],
        *,
        command_id: str | None = None,
    ) -> Mapping[str, Any] | None:
        raw = metadata.get("pending_commands", ())
        items = list(raw) if isinstance(raw, (list, tuple)) else []
        for item in items:
            if not isinstance(item, Mapping) or str(item.get("type") or "") != command_type:
                continue
            if command_id is not None and str(item.get("id") or "") != command_id:
                continue
            payload = item.get("payload")
            if isinstance(payload, Mapping) and predicate(payload):
                return item
        return None

    @staticmethod
    def _remove_command(metadata: dict[str, Any], command_id: object) -> None:
        """Remove one acknowledged command."""

        identifier = str(command_id)
        raw = metadata.get("pending_commands", ())
        if isinstance(raw, (list, tuple)):
            metadata["pending_commands"] = [item for item in raw if not isinstance(item, Mapping) or str(item.get("id") or "") != identifier]

    def _maximum_live_delay(self) -> float:
        """Return the event retention needed by every delayed ticker."""

        delays = (
            float(ticker.display_settings.live_delay_seconds)
            for ticker in self.repository.list_tickers()
            if ticker.display_settings.live_delay_mode
        )
        return max((delay for delay in delays if isfinite(delay) and delay >= 0), default=0.0)

    def own_resource(self, resource: object) -> None:
        """Register one resource created by application composition."""
        with self._close_lock:
            if self._closed:
                raise RuntimeError("application is closed")
            if all(item is not resource for item in self._owned_resources):
                self._owned_resources.append(resource)

    def close(self) -> None:
        """Stop owned work and close the owned repository once."""

        with self._close_lock:
            if self._closed:
                return
            self._closed = True

        failures: list[Exception] = []
        for component in (self.runtime, self.scheduler, self.mini_sprites, self.mini_artwork, *self._owned_resources):
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


def _command_meta(commands: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Project the latest valid update and reboot commands into response metadata."""

    meta: dict[str, Any] = {}
    for command in commands:
        command_type = str(command.get("type") or "").strip().lower()
        command_id = str(command.get("id") or "").strip()
        payload = command.get("payload")
        if not command_id or not isinstance(payload, Mapping):
            continue
        if command_type == "update":
            version = str(payload.get("version") or "").strip()
            if version:
                meta["update"] = {"id": command_id, "version": version, "expires_at": command.get("expires_at")}
        elif command_type == "reboot":
            meta["reboot"] = {"id": command_id, "expires_at": command.get("expires_at")}
    return meta


__all__ = ["BackendApplication"]
