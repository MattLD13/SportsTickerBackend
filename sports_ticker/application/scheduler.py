"""Deterministic scheduling for provider-backed ticker snapshots."""

from __future__ import annotations

import math
import time
from inspect import Parameter, signature
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Protocol, TypeAlias

from sports_ticker.domain import DisplaySettings
from sports_ticker.providers import ProviderResult, normalize_settings


MonotonicClock: TypeAlias = Callable[[], float]
WallClock: TypeAlias = Callable[[], datetime]
SettingsResolver: TypeAlias = Callable[
    [str], DisplaySettings | Mapping[str, object] | None
]
ProviderSettingsKey: TypeAlias = Callable[[DisplaySettings], object]
ProviderRefresh: TypeAlias = Callable[..., object]
SnapshotRefreshCallable: TypeAlias = Callable[
    [str, DisplaySettings, Mapping[str, object]], object
]


class SnapshotRefreshService(Protocol):
    """Port for one complete ticker snapshot transaction."""

    def refresh(
        self,
        ticker_id: str,
        settings: DisplaySettings,
        provider_data: Mapping[str, object],
    ) -> object:
        """Publish one complete snapshot from one immutable provider view."""


@dataclass(frozen=True, slots=True)
class SchedulerHealth:
    """Report one provider job's immutable scheduler health."""

    last_success: datetime | None = None
    last_error: str | None = None
    next_due: datetime | None = None
    consecutive_failures: int = 0


@dataclass(frozen=True, slots=True)
class _ProviderJob:
    name: str
    interval: float
    refresh: ProviderRefresh
    settings_key: ProviderSettingsKey
    next_due: float
    data_by_ticker: Mapping[str, "_CachedProviderData"] = field(
        default_factory=dict
    )
    health: SchedulerHealth = SchedulerHealth()


@dataclass(frozen=True, slots=True)
class _Ticker:
    ticker_id: str
    settings: SettingsResolver


@dataclass(frozen=True, slots=True)
class _CachedProviderData:
    """Keep one provider result with the exact settings that produced it."""

    settings_key: object
    value: object


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _all_settings_key(settings: DisplaySettings) -> DisplaySettings:
    """Keep the established full-settings cache behavior by default."""

    return settings


def _freeze(value: Any) -> object:
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


def _error_text(error: object) -> str:
    """Return stable text for one failed operation."""

    return str(error) or type(error).__name__


def _refresh_succeeded(result: object) -> tuple[bool, str | None]:
    """Read optional health fields from provider and snapshot results."""

    if result is False:
        return False, "refresh failed"
    if isinstance(result, ProviderResult):
        if result.health.healthy:
            return True, None
        return False, result.health.error or "provider unhealthy"

    success = getattr(result, "success", None)
    if success is False:
        error = getattr(result, "error", None)
        return False, str(error) if error else "refresh failed"
    return True, None


class RefreshScheduler:
    """Schedule provider refreshes and publish complete ticker snapshots."""

    def __init__(
        self,
        refresh_service: SnapshotRefreshService | SnapshotRefreshCallable,
        *,
        monotonic: MonotonicClock = time.monotonic,
        wall_clock: WallClock = _utc_now,
    ) -> None:
        """Capture refresh and clock ports without starting background work."""

        self._refresh_service = refresh_service
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._providers: dict[str, _ProviderJob] = {}
        self._tickers: dict[str, _Ticker] = {}

    def register_provider(
        self,
        name: str,
        interval: float,
        refresh: ProviderRefresh,
        *,
        settings_key: ProviderSettingsKey | None = None,
    ) -> None:
        """Register one named settings-aware provider refresh job."""

        provider_name = str(name).strip()
        if not provider_name:
            raise ValueError("provider name must not be empty")
        if provider_name in self._providers:
            raise ValueError(f"provider already registered: {provider_name}")
        if interval <= 0:
            raise ValueError("provider interval must be positive")
        if not callable(refresh):
            raise TypeError("provider refresh must be callable")
        if settings_key is not None and not callable(settings_key):
            raise TypeError("settings_key must be callable")

        now = self._monotonic()
        wall_now = self._wall_clock()
        self._providers[provider_name] = _ProviderJob(
            name=provider_name,
            interval=float(interval),
            refresh=refresh,
            settings_key=settings_key or _all_settings_key,
            next_due=now,
            health=SchedulerHealth(next_due=wall_now),
        )

    def register_ticker(self, ticker_id: str, settings: SettingsResolver) -> None:
        """Register one ticker and its effective-settings resolver."""

        identifier = str(ticker_id).strip()
        if not identifier:
            raise ValueError("ticker ID must not be empty")
        if identifier in self._tickers:
            raise ValueError(f"ticker already registered: {identifier}")
        if not callable(settings):
            raise TypeError("ticker settings resolver must be callable")
        self._tickers[identifier] = _Ticker(identifier, settings)

    def unregister_ticker(self, ticker_id: str) -> bool:
        """Remove one ticker and every provider result scoped to that ticker."""

        identifier = str(ticker_id).strip()
        if identifier not in self._tickers:
            return False
        del self._tickers[identifier]
        for name, job in self._providers.items():
            data_by_ticker = dict(job.data_by_ticker)
            data_by_ticker.pop(identifier, None)
            self._providers[name] = replace(job, data_by_ticker=data_by_ticker)
        return True

    def has_ticker(self, ticker_id: str) -> bool:
        """Return whether the scheduler has one ticker registration."""

        return str(ticker_id).strip() in self._tickers

    @property
    def health(self) -> Mapping[str, SchedulerHealth]:
        """Return an immutable health snapshot keyed by provider name."""

        return MappingProxyType(
            {name: job.health for name, job in self._providers.items()}
        )

    def get_health(self, name: str) -> SchedulerHealth:
        """Return immutable health for one registered provider."""

        try:
            return self._providers[str(name).strip()].health
        except KeyError as error:
            raise KeyError(f"unknown provider: {name}") from error

    def run_due(self, now: float | None = None) -> tuple[str, ...]:
        """Run due jobs once and return ticker IDs published in this pass."""

        current = self._monotonic() if now is None else float(now)
        settings_by_ticker: dict[str, DisplaySettings] = {}
        failures_by_ticker: dict[str, list[str]] = {}
        for ticker in self._tickers.values():
            try:
                settings_by_ticker[ticker.ticker_id] = normalize_settings(
                    ticker.settings(ticker.ticker_id)
                )
            except Exception as error:
                failures_by_ticker.setdefault(ticker.ticker_id, []).append(
                    f"settings: {_error_text(error)}"
                )

        due_by_name = {
            job.name: job
            for job in self._providers.values()
            if current >= job.next_due
        }
        for job in self._providers.values():
            for ticker_id, settings in settings_by_ticker.items():
                cached = job.data_by_ticker.get(ticker_id)
                if cached is None and job.health.last_success is not None:
                    due_by_name[job.name] = job
                elif cached is not None and cached.settings_key != _freeze(job.settings_key(settings)):
                    due_by_name[job.name] = job
        due = tuple(due_by_name.values())
        if not due:
            return ()

        wall_now = self._wall_clock()

        for job in due:
            advanced = _advance_due(job.next_due, current, job.interval)
            wall_due = wall_now + timedelta(seconds=advanced - current)
            updated = replace(
                job,
                next_due=advanced,
                health=replace(job.health, next_due=wall_due),
            )
            data_by_ticker = dict(job.data_by_ticker)
            errors: list[str] = []
            success_count = 0
            for ticker_id, settings in settings_by_ticker.items():
                try:
                    result = _run_provider_refresh(job.refresh, ticker_id, settings)
                    ok, error = _refresh_succeeded(result)
                    if not ok:
                        raise RuntimeError(error or "provider refresh failed")
                except Exception as error:
                    message = _error_text(error)
                    failures_by_ticker.setdefault(ticker_id, []).append(
                        f"{job.name}: {message}"
                    )
                    errors.append(f"{ticker_id}: {message}")
                else:
                    data_by_ticker[ticker_id] = _CachedProviderData(
                        settings_key=_freeze(job.settings_key(settings)),
                        value=_freeze(result),
                    )
                    success_count += 1

            if errors:
                health = SchedulerHealth(
                    last_success=wall_now if success_count else job.health.last_success,
                    last_error="; ".join(errors),
                    next_due=wall_due,
                    consecutive_failures=job.health.consecutive_failures + 1,
                )
            else:
                health = SchedulerHealth(
                    last_success=wall_now,
                    last_error=None,
                    next_due=wall_due,
                    consecutive_failures=0,
                )
            self._providers[job.name] = replace(
                updated,
                data_by_ticker=data_by_ticker,
                health=health,
            )

        published: list[str] = []
        for ticker in self._tickers.values():
            ticker_id = ticker.ticker_id
            settings = settings_by_ticker.get(ticker_id)
            if settings is None or ticker_id in failures_by_ticker:
                continue
            provider_data: dict[str, object] = {}
            for name, job in self._providers.items():
                cached = job.data_by_ticker.get(ticker_id)
                if cached is None or cached.settings_key != _freeze(job.settings_key(settings)):
                    break
                provider_data[name] = cached.value
            else:
                try:
                    result = _run_snapshot_refresh(
                        self._refresh_service,
                        ticker_id,
                        settings,
                        MappingProxyType(provider_data),
                    )
                    ok, error = _refresh_succeeded(result)
                    if not ok:
                        raise RuntimeError(error or "snapshot refresh failed")
                except Exception as error:
                    self._record_refresh_failure(due, error)
                else:
                    published.append(ticker_id)
                continue
            # A provider can wait for its first successful fetch.
            # Keep its own health result. Skip unrelated health changes.

        return tuple(published)

    def _record_refresh_failure(
        self,
        due: tuple[_ProviderJob, ...],
        error: Exception,
    ) -> None:
        """Record a full-snapshot failure against each job in this pass."""

        message = _error_text(error)
        for original in due:
            current = self._providers[original.name]
            self._providers[original.name] = replace(
                current,
                health=SchedulerHealth(
                    last_success=current.health.last_success,
                    last_error=message,
                    next_due=current.health.next_due,
                    consecutive_failures=current.health.consecutive_failures + 1,
                ),
            )


def _advance_due(next_due: float, now: float, interval: float) -> float:
    """Advance a due time beyond the current monotonic reading."""

    if next_due > now:
        return next_due
    steps = math.floor((now - next_due) / interval) + 1
    return next_due + steps * interval


def _run_snapshot_refresh(
    service: SnapshotRefreshService | SnapshotRefreshCallable,
    ticker_id: str,
    settings: DisplaySettings,
    provider_data: Mapping[str, object],
) -> object:
    """Run either a callable port or an object with a refresh method."""

    if callable(service):
        return service(ticker_id, settings, provider_data)
    return service.refresh(ticker_id, settings, provider_data)


def _run_provider_refresh(
    refresh: ProviderRefresh,
    ticker_id: str,
    settings: DisplaySettings,
) -> object:
    """Call a ticker-scoped provider when its declared signature accepts one."""

    try:
        parameters = tuple(signature(refresh).parameters.values())
    except (TypeError, ValueError):
        return refresh(settings)
    positional = tuple(
        value
        for value in parameters
        if value.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
    )
    has_variadic = any(value.kind is Parameter.VAR_POSITIONAL for value in parameters)
    if has_variadic or len(positional) >= 2:
        return refresh(ticker_id, settings)
    return refresh(settings)


__all__ = [
    "MonotonicClock",
    "ProviderRefresh",
    "ProviderSettingsKey",
    "RefreshScheduler",
    "SchedulerHealth",
    "SnapshotRefreshCallable",
    "SettingsResolver",
    "SnapshotRefreshService",
    "WallClock",
]
