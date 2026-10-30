"""Turn tickers and settings into worker subscriptions, and publish each new result.

BackendApplication and the API read the engine through `register_ticker`,
`unregister_ticker`, `has_ticker`, `health`, `recovery_health`, `status`, `stop`,
and `close`. The engine publishes each ticker snapshot through RefreshService.

Each pass, the engine:
1. resolves the settings of each registered ticker,
2. asks the demand policy which tickers need each provider,
3. sends each provider worker its subscriptions: one for each ticker and
   provider settings key, as the old scheduler cached them,
4. publishes each ticker that got a new result, from the results of its current settings keys.
"""
from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ticker.server.contract.results import decode_result, encode
from ticker.server.contract.health import JobHealth
from ticker.shared.domain import DisplaySettings
from ticker.server.providers.contracts import ProviderResult
from ticker.server.providers.normalization import normalize_provider_result, normalize_settings

from ticker.server.contract.wire import canonical

from ticker.server.core.supervisor import Supervisor, WorkerSpec

# The core makes the clock result itself, because the clock has no upstream.
BUILTIN_INTERVALS = {"clock": 3600.0}
READ_SECONDS = 120.0


@dataclass(frozen=True)
class _Held:
    key: str
    result: ProviderResult
    at: float


class Engine:
    def __init__(self, refresh_service, event_service=None, *, providers: list[str], settings_key: Callable[[str], Callable],
                 builtins: Mapping[str, Any], socket_path: Path, state_path: Path, release_path: Callable[[str], Path],
                 initial_release: str, log_directory: Path, worker_arguments: tuple[str, ...] = (),
                 tick_seconds: float = 0.2, stall_seconds: float = 90.0, supervisor_options: Mapping[str, Any] | None = None,
                 monotonic: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.refresh_service, self.event_service = refresh_service, event_service
        self.providers, self.builtins = tuple(providers), dict(builtins)
        self.monotonic, self.wall_clock = monotonic, wall_clock
        self.tick_seconds, self.stall_seconds = tick_seconds, stall_seconds
        self._keys = {name: settings_key(name) for name in (*self.providers, *self.builtins)}
        self._demand = None
        self._lock = threading.RLock()
        self._tickers: dict[str, Callable[[str], Any]] = {}
        self._held: dict[str, dict[str, _Held]] = {name: {} for name in (*self.providers, *self.builtins)}
        self._subs: dict[str, dict[str, tuple[str, dict[str, Any]]]] = {name: {} for name in self.providers}
        self._reads: dict[str, dict[str, tuple[str, dict[str, Any], float, list[Future]]]] = {name: {} for name in self.providers}
        self._sent: dict[str, str] = {}
        self._job_health: dict[str, JobHealth] = {}
        self._recovery: dict[str, dict] = {}
        self._dirty: set[str] = set()
        self._cycles, self._completed_at, self._started_at, self._last_error = 0, None, None, None
        self.active_provider: str | None = None
        self.last_progress_at: float | None = None
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()
        self.supervisor = Supervisor(socket_path, state_path, [WorkerSpec(name) for name in self.providers], release_path,
                                     initial_release=initial_release, log_directory=log_directory,
                                     wanted=self._wanted, deliver=self._deliver, worker_arguments=worker_arguments,
                                     **dict(supervisor_options or {}))

    # Scheduler interface

    def set_provider_demand(self, policy) -> None:
        self._demand = policy

    def register_ticker(self, ticker_id: str, settings: Callable[[str], Any]) -> None:
        identifier = str(ticker_id).strip()
        if not identifier:
            raise ValueError("ticker ID must not be empty")
        with self._lock:
            if identifier in self._tickers:
                raise ValueError(f"ticker already registered: {identifier}")
            self._tickers[identifier] = settings
        self._wake_soon()

    def unregister_ticker(self, ticker_id: str) -> bool:
        identifier = str(ticker_id).strip()
        with self._lock:
            if self._tickers.pop(identifier, None) is None:
                return False
            for held in self._held.values():
                held.pop(identifier, None)
        self._wake_soon()
        return True

    def has_ticker(self, ticker_id: str) -> bool:
        with self._lock:
            return str(ticker_id).strip() in self._tickers

    @property
    def health(self) -> Mapping[str, JobHealth]:
        status = self.supervisor.status()
        result = {}
        with self._lock:
            for name in self.providers:
                health = self._job_health.get(name, JobHealth())
                if not status[name]["connected"]:
                    health = JobHealth(last_success=health.last_success, last_error="the provider worker is not connected",
                                             next_due=health.next_due, consecutive_failures=max(1, health.consecutive_failures),
                                             refresh_calls=health.refresh_calls, paused_refreshes=health.paused_refreshes)
                result[name] = health
            for name in self.builtins:
                result[name] = self._job_health.get(name, JobHealth())
        return MappingProxyType(result)

    def recovery_health(self) -> dict:
        with self._lock:
            merged = {}
            for snapshot in self._recovery.values():
                merged.update(snapshot)
            return merged

    def workers(self) -> dict[str, Any]:
        """Return the supervisor status of each provider worker."""
        return self.supervisor.status()

    def deploy(self, name: str, release: str, *, timeout: float = 150.0) -> bool:
        """Start `release` of one provider worker next to the active release. Return True when it becomes active."""
        if name not in self.providers:
            raise KeyError(name)
        if self._loop is None or not self._running:
            raise RuntimeError("the engine is not running")
        future = asyncio.run_coroutine_threadsafe(self.supervisor.deploy(name, release), self._loop)
        return future.result(timeout=timeout)

    # Runtime interface

    def start(self) -> None:
        """Start the engine thread with the supervisor and the publish loop."""
        if self._thread is not None:
            return
        ready = threading.Event()
        failure: list[BaseException] = []

        def run() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._main(ready))
            except BaseException as error:
                failure.append(error)
                ready.set()
            finally:
                loop.close()

        self._thread = threading.Thread(target=run, name="ticker3-engine", daemon=True)
        self._thread.start()
        ready.wait(timeout=30)
        if failure:
            raise failure[0]

    def status(self) -> dict:
        with self._lock:
            now = self.monotonic()
            age = None if self._completed_at is None else max(0, now - self._completed_at)
            progress_age = None if self.last_progress_at is None else max(0, now - self.last_progress_at)
            recent = age is not None and age < self.stall_seconds
            return {"enabled": True, "running": self._running, "ready": self._running and recent,
                    "last_progress_age_seconds": progress_age, "last_completed_age_seconds": age, "cycles": self._cycles,
                    "active_provider": self.active_provider,
                    "cycle_age_seconds": None if self._started_at is None else max(0, now - self._started_at),
                    "last_error_type": self._last_error}

    def stop(self, *, stop_workers: bool = False) -> None:
        """Stop the engine. Workers keep running unless `stop_workers` is set, so a core restart reads nothing again."""
        if self._loop is None or self._stopped.is_set():
            return
        self._stopped.set()
        self._stop_workers = stop_workers
        self._loop.call_soon_threadsafe(self._wake.set)
        if self._thread is not None:
            self._thread.join(timeout=20)

    def close(self) -> None:
        self.stop()

    # On-demand reads

    def read(self, provider: str, ticker_id: str, settings: DisplaySettings, *, timeout: float = 30.0) -> ProviderResult:
        """Return a result for settings that no ticker uses, such as the public demo. The read stays wanted for two minutes."""
        if provider in self.builtins:
            return self._builtin_result(provider, settings)
        key = self._key(provider, ticker_id, settings)
        future: Future = Future()
        with self._lock:
            held = self._held[provider].get(ticker_id)
            if held is not None and held.key == key:
                future.set_result(held.result)
            current = self._reads[provider].get(ticker_id)
            waiters = current[3] if current is not None and current[0] == key else []
            if not future.done():
                waiters.append(future)
            self._reads[provider][ticker_id] = (key, {"ticker": ticker_id, "settings": encode(settings)},
                                                self.monotonic() + READ_SECONDS, waiters)
        self._wake_soon()
        return future.result(timeout=timeout)

    # Engine loop

    async def _main(self, ready: threading.Event) -> None:
        self._wake = asyncio.Event()
        await self.supervisor.start()
        with self._lock:
            self._running = True
        ready.set()
        try:
            while not self._stopped.is_set():
                self._pass()
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=self.tick_seconds)
                except asyncio.TimeoutError:
                    pass
        finally:
            with self._lock:
                self._running = False
            await self.supervisor.stop(stop_workers=getattr(self, "_stop_workers", False))

    def _pass(self) -> None:
        with self._lock:
            self._started_at = self.monotonic()
            self.last_progress_at = self._started_at
        try:
            settings_by_ticker = self._settings()
            demand = self._demand_for(settings_by_ticker)
            self._subscribe(settings_by_ticker, demand)
            self._run_builtins(settings_by_ticker, demand)
            self._publish(settings_by_ticker)
            if self.event_service is not None:
                self.event_service.remove_expired()
        except Exception as error:
            with self._lock:
                self._last_error = type(error).__name__
            raise
        with self._lock:
            self._completed_at = self.monotonic()
            self.last_progress_at = self._completed_at
            self._cycles += 1
            self._last_error = None

    def _settings(self) -> dict[str, DisplaySettings]:
        with self._lock:
            tickers = dict(self._tickers)
        resolved = {}
        for ticker_id, resolver in tickers.items():
            try:
                resolved[ticker_id] = normalize_settings(resolver(ticker_id))
            except Exception:
                continue
        return resolved

    def _demand_for(self, settings_by_ticker: Mapping[str, DisplaySettings]) -> Mapping[str, frozenset[str]]:
        names = (*self.providers, *self.builtins)
        if self._demand is None:
            return {name: frozenset(settings_by_ticker) for name in names}
        return self._demand(names, settings_by_ticker, self.wall_clock())

    def _subscribe(self, settings_by_ticker, demand) -> None:
        now = self.monotonic()
        for name in self.providers:
            subs: dict[str, tuple[str, dict[str, Any]]] = {}
            for ticker_id in sorted(demand.get(name, ())):
                settings = settings_by_ticker.get(ticker_id)
                if settings is not None:
                    subs[self._key(name, ticker_id, settings)] = (ticker_id, {"ticker": ticker_id, "settings": encode(settings)})
            with self._lock:
                for ticker_id, (key, config, until, waiters) in list(self._reads[name].items()):
                    if until < now:
                        del self._reads[name][ticker_id]
                        for waiter in waiters:
                            if not waiter.done():
                                waiter.set_exception(TimeoutError("the provider sent no result in time"))
                    elif ticker_id not in {ticker for ticker, _ in subs.values()}:
                        subs[key] = (ticker_id, config)
                self._subs[name] = subs
            wanted = {key: config for key, (_, config) in subs.items()}
            digest = canonical(sorted(wanted))
            if self._sent.get(name) != digest:
                self._sent[name] = digest
                self.supervisor.subscribe(name, wanted)

    def _wanted(self, name: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {key: config for key, (_, config) in self._subs.get(name, {}).items()}

    def _deliver(self, name: str, message: dict[str, Any]) -> None:
        """Take one result or health message from the active worker of a provider."""
        if message["t"] == "health":
            job = message["job"]
            health = JobHealth(**{field: _time(job.get(field)) if field in ("last_success", "next_due") else job.get(field)
                                        for field in ("last_success", "last_error", "next_due", "consecutive_failures",
                                                      "refresh_calls", "paused_refreshes")})
            with self._lock:
                self._job_health[name] = health
                self._recovery[name] = message["recovery"]
            return
        if message["t"] != "result":
            return
        with self._lock:
            target = self._subs.get(name, {}).get(message["sub"])
        if target is None:
            return
        ticker_id = target[0]
        now_ms = time.time() * 1000.0
        result = decode_result(message["result"], receipt={"source": name, "request_started_ms": message["started_ms"],
                                                         "core_received_at_ms": now_ms})
        with self._lock:
            self._held[name][ticker_id] = _Held(message["sub"], result, self.monotonic())
            read = self._reads[name].get(ticker_id)
            if read is not None and read[0] == message["sub"]:
                for waiter in read[3]:
                    if not waiter.done():
                        waiter.set_result(result)
                read[3].clear()
            if ticker_id in self._tickers:
                self._dirty.add(ticker_id)
        self._wake.set()

    def _run_builtins(self, settings_by_ticker, demand) -> None:
        now = self.monotonic()
        for name in self.builtins:
            for ticker_id in demand.get(name, ()):
                settings = settings_by_ticker.get(ticker_id)
                if settings is None:
                    continue
                key = self._key(name, ticker_id, settings)
                held = self._held[name].get(ticker_id)
                if held is not None and held.key == key and now - held.at < BUILTIN_INTERVALS[name]:
                    continue
                result = self._builtin_result(name, settings)
                with self._lock:
                    self._held[name][ticker_id] = _Held(key, result, now)
                    self._job_health[name] = JobHealth(last_success=self.wall_clock(),
                                                             refresh_calls=self._job_health.get(name, JobHealth()).refresh_calls + 1)
                    self._dirty.add(ticker_id)

    def _builtin_result(self, name: str, settings: DisplaySettings) -> ProviderResult:
        return normalize_provider_result(self.builtins[name].fetch(settings), settings, provider=name)

    def _publish(self, settings_by_ticker: Mapping[str, DisplaySettings]) -> None:
        with self._lock:
            dirty, self._dirty = self._dirty, set()
        for ticker_id in sorted(dirty):
            settings = settings_by_ticker.get(ticker_id)
            if settings is None:
                continue
            with self._lock:
                provider_data = {name: held[ticker_id].result for name, held in self._held.items()
                                 if ticker_id in held and held[ticker_id].key == self._key(name, ticker_id, settings)}
            if not provider_data:
                continue
            try:
                self.refresh_service.refresh(ticker_id, settings, MappingProxyType(provider_data))
            except Exception as error:
                # The old scheduler kept running after a snapshot failure, so this pass does too.
                with self._lock:
                    self._last_error = type(error).__name__

    def _key(self, name: str, ticker_id: str, settings: DisplaySettings) -> str:
        """Return the subscription key of one ticker and the provider settings that change its result."""
        identity = canonical([name, ticker_id, encode(self._keys[name](settings))])
        return hashlib.sha256(identity.encode()).hexdigest()[:16]

    def _wake_soon(self) -> None:
        loop, wake = self._loop, self._wake
        if loop is not None and wake is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(wake.set)
            except RuntimeError:
                pass


def _time(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else None
