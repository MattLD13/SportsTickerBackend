"""Deterministic scheduling for provider-backed ticker snapshots."""

from __future__ import annotations

from sports_ticker.immutable import freeze as _freeze

import math
import hashlib
import inspect
import time
from inspect import Parameter, signature
from collections.abc import Callable, Mapping
from concurrent.futures import Executor, Future
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from threading import Lock
from typing import Protocol, TypeAlias

from .provider_recovery import ProviderRecovery

from sports_ticker.domain import DisplaySettings
from sports_ticker.providers import ProviderResult, normalize_settings


MonotonicClock: TypeAlias = Callable[[], float]
WallClock: TypeAlias = Callable[[], datetime]
ProviderDemandCallable: TypeAlias = Callable[
    [tuple[str, ...], Mapping[str, DisplaySettings], datetime],
    Mapping[str, frozenset[str]],
]
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
    refresh_calls: int = 0
    paused_refreshes: int = 0


@dataclass(frozen=True, slots=True)
class _ProviderJob:
    name: str
    interval: float
    refresh: ProviderRefresh
    settings_key: ProviderSettingsKey
    next_due: float
    refresh_changed: ProviderRefresh | None = None
    refresh_batch: Callable | None = None
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


@dataclass(slots=True)
class _JobTally:
    """Collect the per-ticker outcomes of one provider job in one pass."""

    data_by_ticker: dict[str, _CachedProviderData]
    published: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[tuple[str, str]] = field(default_factory=list)
    successes: int = 0
    skipped: int = 0


class _PassSettingsKeys:
    """Freeze each provider settings key once per scheduler pass."""

    def __init__(self) -> None:
        self._values: dict[tuple[str, str], object] = {}

    def __call__(self, job: _ProviderJob, ticker_id: str, settings: DisplaySettings) -> object:
        cache_key = (job.name, ticker_id)
        if cache_key not in self._values:
            self._values[cache_key] = _freeze(job.settings_key(settings))
        return self._values[cache_key]


@dataclass(frozen=True, slots=True)
class _SchedulerPass:
    """Hold the inputs that every job in one scheduler pass shares."""

    current: float
    settings_by_ticker: Mapping[str, DisplaySettings]
    active_by_name: Mapping[str, frozenset[str]]
    requested: Mapping[str, set[str]]
    completed: Mapping[str, tuple[Mapping[str, object], Mapping[str, object]]]
    settings_key_for: _PassSettingsKeys


def _job_refresh(job: _ProviderJob, changed_only: bool) -> ProviderRefresh:
    """Use the live-change refresh for a change-only pass when the job has one."""

    return job.refresh_changed if changed_only and job.refresh_changed is not None else job.refresh


def _job_health(
    health: SchedulerHealth, tally: _JobTally, wall_now: datetime, wall_due: datetime,
) -> SchedulerHealth:
    """Return the job health after one pass from the prior health and the pass outcomes."""

    attempted = len(tally.published)
    if not attempted:
        result = replace(health, next_due=wall_due)
    elif tally.errors:
        result = SchedulerHealth(
            last_success=wall_now if tally.successes else health.last_success,
            last_error=_format_ticker_messages(tally.errors + tally.warnings),
            next_due=wall_due,
            consecutive_failures=health.consecutive_failures + 1,
        )
    else:
        result = SchedulerHealth(
            last_success=wall_now,
            last_error=_format_ticker_messages(tally.warnings),
            next_due=wall_due,
            consecutive_failures=0,
        )
    return replace(
        result,
        refresh_calls=health.refresh_calls + attempted,
        paused_refreshes=health.paused_refreshes + tally.skipped,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _all_settings_key(settings: DisplaySettings) -> DisplaySettings:
    """Keep the established full-settings cache behavior by default."""

    return settings


def _all_provider_demand(
    providers: tuple[str, ...],
    settings_by_ticker: Mapping[str, DisplaySettings],
    now: datetime,
) -> Mapping[str, frozenset[str]]:
    """Enable every registered ticker when the application sets no demand policy."""
    identifiers = frozenset(settings_by_ticker)
    return {name: identifiers for name in providers}


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


def _refresh_warning(result: object) -> str | None:
    """Read a nonblocking degraded-health message from an accepted provider result."""

    if isinstance(result, ProviderResult) and result.health.healthy:
        return result.health.error or None
    return None


def _format_ticker_messages(messages: list[tuple[str, str]]) -> str | None:
    """Collapse repeated provider messages before publishing scheduler health."""

    grouped: dict[str, list[str]] = {}
    for ticker_id, message in messages:
        grouped.setdefault(message, []).append(ticker_id)
    formatted: list[str] = []
    for message, ticker_ids in grouped.items():
        if len(ticker_ids) == 1:
            formatted.append(f"{ticker_ids[0]}: {message}")
        else:
            formatted.append(f"{len(ticker_ids)} tickers: {message}")
    return "; ".join(formatted) if formatted else None


class RefreshScheduler:
    """Schedule provider refreshes and publish complete ticker snapshots."""

    def __init__(
        self,
        refresh_service: SnapshotRefreshService | SnapshotRefreshCallable,
        *,
        monotonic: MonotonicClock = time.monotonic,
        wall_clock: WallClock = _utc_now,
        incidents=None,
        recovery: ProviderRecovery | None = None,
        executor: Executor | None = None,
    ) -> None:
        """Capture refresh and clock ports without starting background work."""

        self._incidents = incidents
        self.recovery = recovery or ProviderRecovery()
        self.active_provider: str | None = None
        self.last_progress_at: float | None = None
        self._refresh_service = refresh_service
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._providers: dict[str, _ProviderJob] = {}
        self._tickers: dict[str, _Ticker] = {}
        self._provider_demand: ProviderDemandCallable = _all_provider_demand
        self._last_demand: Mapping[str, frozenset[str]] = {}
        self._executor = executor
        self._pending: dict[str, tuple[Future, dict[str, object]]] = {}
        self._requested: dict[str, set[str]] = {}
        self._request_lock = Lock()
        self._wake: Callable[[], None] = lambda: None

    def set_wake(self, wake: Callable[[], None]) -> None:
        """Wake the runtime when source changes or provider results arrive."""
        self._wake = wake

    def request_refresh(self, name: str, topics: set[str]) -> None:
        """Coalesce source notifications until the next scheduler pass."""
        with self._request_lock:
            self._requested.setdefault(name, set()).update(topics)
        self._wake()

    def set_provider_demand(self, policy: ProviderDemandCallable) -> None:
        """Set the application policy that selects demand once per scheduler pass."""
        self._provider_demand = policy

    def register_provider(
        self,
        name: str,
        interval: float,
        refresh: ProviderRefresh,
        *,
        settings_key: ProviderSettingsKey | None = None,
        refresh_changed: ProviderRefresh | None = None,
        refresh_batch: Callable | None = None,
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
            refresh_changed=refresh_changed,
            refresh_batch=refresh_batch,
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

    def recovery_health(self) -> dict:
        """Expose circuit state using the scheduler's own monotonic clock."""
        return self.recovery.snapshot(self._monotonic())

    def get_health(self, name: str) -> SchedulerHealth:
        """Return immutable health for one registered provider."""

        try:
            return self._providers[str(name).strip()].health
        except KeyError as error:
            raise KeyError(f"unknown provider: {name}") from error

    def run_due(self, now: float | None = None) -> tuple[str, ...]:
        """Run due jobs once and return ticker IDs published in this pass."""

        current = self._monotonic() if now is None else float(now)
        completed = self._take_completed()
        requested = self._take_requests(completed)
        self.last_progress_at = self._monotonic()
        settings_by_ticker = self._resolve_settings()
        run = _SchedulerPass(
            current=current,
            settings_by_ticker=settings_by_ticker,
            active_by_name=self._provider_demand(tuple(self._providers), settings_by_ticker, self._wall_clock()),
            requested=requested,
            completed=completed,
            settings_key_for=_PassSettingsKeys(),
        )
        due = self._due_jobs(run)
        self._last_demand = run.active_by_name
        if not due:
            return ()

        wall_now = self._wall_clock()
        publish_targets: set[str] = set()
        for job in due:
            topics = requested.get(job.name, set())
            changed_only = bool(topics) and current < job.next_due
            advanced = (
                job.next_due if job.name in completed or changed_only
                else _advance_due(job.next_due, current, job.interval)
            )
            wall_due = wall_now + timedelta(seconds=advanced - current)
            updated = replace(job, next_due=advanced, health=replace(job.health, next_due=wall_due))
            selected = {
                ticker_id: settings for ticker_id, settings in settings_by_ticker.items()
                if ticker_id in run.active_by_name[job.name]
                and (not changed_only or any(settings.active_sports.get(topic, True) for topic in topics))
            }
            if self._executor is not None and job.name not in completed:
                self._submit_job(self._executor, updated, selected, changed_only, run)
                continue
            tally = self._refresh_job(job, selected, changed_only, run)
            publish_targets.update(tally.published)
            self._providers[job.name] = replace(
                updated,
                data_by_ticker=tally.data_by_ticker,
                health=_job_health(job.health, tally, wall_now, wall_due),
            )
        return self._publish(publish_targets, due, run)

    def _take_completed(self) -> dict[str, tuple[Mapping[str, object], dict[str, object]]]:
        """Remove finished background reads and return their results and settings keys."""

        completed = {}
        for name, (future, keys) in tuple(self._pending.items()):
            if future.done():
                completed[name] = (future.result(), keys)
                del self._pending[name]
        return completed

    def _take_requests(self, completed: Mapping[str, object]) -> dict[str, set[str]]:
        """Remove the source notifications that this pass can serve."""

        with self._request_lock:
            requested = {name: topics for name, topics in self._requested.items()
                         if name not in self._pending and name not in completed}
            for name in requested:
                del self._requested[name]
        return requested

    def _resolve_settings(self) -> dict[str, DisplaySettings]:
        """Resolve each ticker's settings, and leave out tickers whose resolver fails."""

        settings_by_ticker: dict[str, DisplaySettings] = {}
        for ticker in self._tickers.values():
            try:
                settings_by_ticker[ticker.ticker_id] = normalize_settings(ticker.settings(ticker.ticker_id))
            except Exception:
                continue
        return settings_by_ticker

    def _due_jobs(self, run: _SchedulerPass) -> tuple[_ProviderJob, ...]:
        """Select jobs that are due by time, by request, by new demand, or by changed settings."""

        current, active_by_name = run.current, run.active_by_name
        due_by_name = {
            job.name: job
            for job in self._providers.values()
            if current >= job.next_due and job.name not in self._pending
        }
        for job in self._providers.values():
            if job.name in self._pending:
                continue
            if job.name in run.requested or job.name in run.completed:
                due_by_name[job.name] = job
            if active_by_name[job.name] - self._last_demand.get(job.name, frozenset()):
                due_by_name[job.name] = job
            for ticker_id, settings in run.settings_by_ticker.items():
                if ticker_id not in active_by_name[job.name]:
                    continue
                cached = job.data_by_ticker.get(ticker_id)
                if cached is None and job.health.last_success is not None:
                    due_by_name[job.name] = job
                elif cached is not None and cached.settings_key != run.settings_key_for(job, ticker_id, settings):
                    due_by_name[job.name] = job
        return tuple(due_by_name.values())

    def _submit_job(
        self,
        executor: Executor,
        job: _ProviderJob,
        selected: Mapping[str, DisplaySettings],
        changed_only: bool,
        run: _SchedulerPass,
    ) -> None:
        """Start one background provider read for the tickers that recovery permits."""

        keys: dict[str, object] = {}
        for ticker_id, settings in selected.items():
            key = run.settings_key_for(job, ticker_id, settings)
            if self.recovery.permitted(job.name, ticker_id, key, run.current):
                keys[ticker_id] = key
        if not keys:
            self._providers[job.name] = job
            return
        future = executor.submit(
            _read_provider_batch,
            _job_refresh(job, changed_only),
            {ticker_id: selected[ticker_id] for ticker_id in keys},
            batch=job.refresh_batch,
            live_only=changed_only,
        )
        self._pending[job.name] = (future, keys)
        self._providers[job.name] = job
        future.add_done_callback(lambda done: self._wake())

    def _refresh_job(
        self,
        job: _ProviderJob,
        selected: Mapping[str, DisplaySettings],
        changed_only: bool,
        run: _SchedulerPass,
    ) -> _JobTally:
        """Refresh one job for each selected ticker, or apply its finished background read."""

        tally = _JobTally(data_by_ticker=dict(job.data_by_ticker))
        refresh = _job_refresh(job, changed_only)
        completed = run.completed.get(job.name)
        for ticker_id, settings in run.settings_by_ticker.items():
            if ticker_id not in selected:
                tally.skipped += 1
                continue
            key = run.settings_key_for(job, ticker_id, settings)
            results = None
            if completed is not None:
                results, keys = completed
                if ticker_id not in keys:
                    continue
                if keys[ticker_id] != key:
                    # The settings changed during the background read, so read again.
                    self.request_refresh(job.name, set())
                    continue
            if not self.recovery.permitted(job.name, ticker_id, key, run.current):
                tally.skipped += 1
                continue
            tally.published.append(ticker_id)
            self._refresh_ticker(job, ticker_id, settings, key, refresh, results, run.current, tally)
        return tally

    def _refresh_ticker(
        self,
        job: _ProviderJob,
        ticker_id: str,
        settings: DisplaySettings,
        key: object,
        refresh: ProviderRefresh,
        results: Mapping[str, object] | None,
        current: float,
        tally: _JobTally,
    ) -> None:
        """Read or apply one ticker's provider result and record its health."""

        result = None
        self.active_provider = job.name
        self.last_progress_at = self._monotonic()
        try:
            if results is not None:
                result = results[ticker_id]
                if isinstance(result, Exception):
                    raise result
            else:
                result = _run_provider_refresh(refresh, ticker_id, settings)
            ok, error = _refresh_succeeded(result)
            if not ok:
                raise RuntimeError(error or "provider refresh failed")
            warning = _refresh_warning(result)
        except Exception as error:
            tally.errors.append((ticker_id, _error_text(error)))
            retry_at = self.recovery.failed(job.name, ticker_id, key, current)
            if self._incidents is not None:
                diagnostic = getattr(getattr(result, "health", None), "diagnostic", None)
                self._incidents.record("provider_failure", component=job.name, error=error, context={
                    "ticker_id": ticker_id, "settings_fingerprint": hashlib.sha256(repr(key).encode()).hexdigest(),
                    "entrypoint": getattr(job.refresh, "__module__", "") + "." + getattr(job.refresh, "__qualname__", ""),
                    "source_file": inspect.getsourcefile(job.refresh) if inspect.isfunction(job.refresh) or inspect.ismethod(job.refresh) else None,
                    "retry_in_seconds": max(0, retry_at - current), "source_failure": dict(diagnostic) if diagnostic else None,
                })
        else:
            recovered = self.recovery.succeeded(job.name, ticker_id, key)
            if recovered and self._incidents is not None:
                self._incidents.record("provider_recovered", component=job.name, context={"ticker_id": ticker_id})
            if warning:
                tally.warnings.append((ticker_id, warning))
                if self._incidents is not None:
                    self._incidents.record("provider_degraded", component=job.name, error=warning,
                                           context={"ticker_id": ticker_id, "entrypoint": getattr(job.refresh, "__qualname__", "")})
            tally.data_by_ticker[ticker_id] = _CachedProviderData(settings_key=key, value=_freeze(result))
            tally.successes += 1
        finally:
            self.active_provider = None
            self.last_progress_at = self._monotonic()

    def _publish(
        self,
        publish_targets: set[str],
        due: tuple[_ProviderJob, ...],
        run: _SchedulerPass,
    ) -> tuple[str, ...]:
        """Publish one snapshot for each refreshed ticker from the provider data of its current settings."""

        published: list[str] = []
        for ticker_id in self._tickers:
            if ticker_id not in publish_targets:
                continue
            settings = run.settings_by_ticker[ticker_id]
            provider_data: dict[str, object] = {
                name: cached.value
                for name, job in self._providers.items()
                if (cached := job.data_by_ticker.get(ticker_id)) is not None
                and cached.settings_key == run.settings_key_for(job, ticker_id, settings)
            }
            if not provider_data:
                continue
            try:
                self.last_progress_at = self._monotonic()
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

    def close(self) -> None:
        """Close the refresh service and its owned providers."""

        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
        close = getattr(self._refresh_service, "close", None)
        if callable(close):
            close()


def _read_provider_batch(refresh: ProviderRefresh, settings_by_ticker: Mapping[str, DisplaySettings], *,
                         batch: Callable | None = None, live_only: bool = False) -> dict[str, object]:
    """Read one provider batch outside the scheduler state owner."""
    if batch is not None:
        try:
            result = batch(settings_by_ticker, live_only=live_only)
            if not isinstance(result, Mapping) or set(result) != set(settings_by_ticker):
                raise ValueError("provider batch returned the wrong ticker identifiers")
            return dict(result)
        except Exception as error:
            return {ticker_id: error for ticker_id in settings_by_ticker}
    results = {}
    for ticker_id, settings in settings_by_ticker.items():
        try:
            results[ticker_id] = _run_provider_refresh(refresh, ticker_id, settings)
        except Exception as error:
            results[ticker_id] = error
    return results


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
