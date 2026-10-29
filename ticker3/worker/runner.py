"""Run one provider in its own process and push its results to the core.

The provider code is the existing provider in sports_ticker/providers. The
worker owns the read timing that the core scheduler owned before:

- An interval pass reads every subscription at the provider interval.
- A new subscription is read at once.
- For ESPN, a Fastcast change starts a live pass for the tickers that follow the changed league.
- A failing ticker setting pauses with the ProviderRecovery rule in recovery.py.

The worker sends each healthy result. It never sends an unhealthy result, so
the core keeps the last good data, as the old scheduler did.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import os
import sys
import time
import traceback
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from sports_ticker.domain import DisplaySettings
from sports_ticker.providers.contracts import ProviderHealth, ProviderResult
from sports_ticker.providers.normalization import normalize_provider_result
from ticker3.contract import PROTOCOL, ContractError
from ticker3.contract.health import JobHealth
from ticker3.contract.messages import core_message
from ticker3.contract.results import encode
from ticker3.contract.wire import MAX_LINE, decode, encode as encode_line

from .recovery import ProviderRecovery

# Seconds between interval passes. These are the deployed core scheduler intervals.
INTERVALS = {"espn": 5.0, "fotmob": 5.0, "weather": 300.0, "golf": 30.0, "racing": 15.0, "stock": 2.0,
             "flights": 30.0, "music": 0.6, "news": 30.0}


@dataclass
class _Subscription:
    key: str
    ticker: str
    settings: DisplaySettings


@dataclass
class _Tally:
    published: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[tuple[str, str]] = field(default_factory=list)
    successes: int = 0
    skipped: int = 0


class ProviderWorker:
    def __init__(self, name: str, provider: Any, socket_path: str, release: str, *, interval: float | None = None,
                 incidents=None, health_seconds: float = 5, orphan_seconds: float = 600, connect_seconds: float = 1,
                 monotonic=time.monotonic, wall=lambda: datetime.now(timezone.utc)) -> None:
        self.name, self.provider, self.socket_path, self.release = name, provider, socket_path, release
        self.interval = float(interval or INTERVALS[name])
        self.incidents, self.health_seconds = incidents, health_seconds
        self.orphan_seconds, self.connect_seconds = orphan_seconds, connect_seconds
        self.monotonic, self.wall = monotonic, wall
        self.recovery = ProviderRecovery()
        self.health = JobHealth(next_due=wall())
        self.subs: dict[str, _Subscription] = {}
        self.errors: dict[str, str] = {}
        self.next_due = monotonic()
        self.busy_since: float | None = None
        self._new: set[str] = set()
        self._resync = False
        self._topics: set[str] = set()
        self._wake = asyncio.Event()
        self._writer: asyncio.StreamWriter | None = None
        self._send_lock = asyncio.Lock()
        self._stopping = asyncio.Event()

    async def run(self) -> int:
        tasks = [asyncio.create_task(self._job_loop()), asyncio.create_task(self._health_loop())]
        if callable(getattr(self.provider, "wait_for_changes", None)):
            tasks.append(asyncio.create_task(self._watch_changes()))
        try:
            return await self._connect_loop()
        finally:
            self._stopping.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            close = getattr(self.provider, "close", None)
            if callable(close):
                await asyncio.to_thread(close)

    # Core connection

    async def _connect_loop(self) -> int:
        lost_at = self.monotonic()
        while not self._stopping.is_set():
            try:
                reader, writer = await asyncio.open_unix_connection(self.socket_path, limit=MAX_LINE + 1)
            except OSError:
                if self.monotonic() - lost_at > self.orphan_seconds:
                    _log(self.name, f"no core for {self.orphan_seconds:.0f} s, stopping")
                    return 0
                await asyncio.sleep(self.connect_seconds)
                continue
            try:
                refused = await self._session(reader, writer)
                if refused is not None:
                    _log(self.name, f"core refused this worker: {refused}")
                    return 3
            except (OSError, asyncio.IncompleteReadError, ContractError) as error:
                _log(self.name, f"core connection lost: {error}")
            finally:
                self._writer = None
                writer.close()
            lost_at = self.monotonic()
        return 0

    async def _session(self, reader, writer) -> str | None:
        writer.write(encode_line({"t": "hello", "protocol": PROTOCOL, "provider": self.name, "release": self.release,
                                  "pid": os.getpid()}))
        await writer.drain()
        welcome = core_message(decode(await asyncio.wait_for(reader.readline(), timeout=10)))
        if welcome["t"] != "welcome":
            raise ContractError("the core must answer hello with welcome")
        if not welcome["ok"]:
            return welcome.get("reason", "no reason")
        self._writer = writer
        # The core may have restarted, so the first subscribe after hello reads every kept subscription.
        self._resync = True
        await self._send_health()
        while True:
            line = await reader.readline()
            if not line:
                raise asyncio.IncompleteReadError(b"", None)
            message = core_message(decode(line))
            if message["t"] == "subscribe":
                self._subscribe(message["subs"])
            elif message["t"] == "drain":
                self._stopping.set()
                return None

    def _subscribe(self, wanted: dict[str, dict[str, Any]]) -> None:
        for key in set(self.subs) - set(wanted):
            del self.subs[key]
            self.errors.pop(key, None)
        for key, config in wanted.items():
            if key not in self.subs:
                self.subs[key] = _Subscription(key, str(config["ticker"]), DisplaySettings(**config["settings"]))
                self._new.add(key)
            elif self._resync:
                self._new.add(key)
        self._resync = False
        self._wake.set()

    # Provider job

    async def _job_loop(self) -> None:
        while True:
            now = self.monotonic()
            if now >= self.next_due:
                self.next_due = _advance(self.next_due, now, self.interval)
                await self._pass(list(self.subs), live=False, timed=True)
            elif self._new:
                keys, self._new = [key for key in self._new if key in self.subs], set()
                await self._pass(keys, live=False, timed=False)
            elif self._topics:
                topics, self._topics = self._topics, set()
                keys = [key for key, sub in self.subs.items() if any(sub.settings.active_sports.get(topic, True) for topic in topics)]
                await self._pass(keys, live=True, timed=False)
            self._wake.clear()
            if self._new or self._topics:
                continue
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=max(0.0, self.next_due - self.monotonic()))
            except asyncio.TimeoutError:
                pass

    async def _pass(self, keys: list[str], *, live: bool, timed: bool) -> None:
        current = self.monotonic()
        wall_now = self.wall()
        tally = _Tally()
        selected = {}
        for key in keys:
            sub = self.subs[key]
            if self.recovery.permitted(self.name, sub.ticker, key, current):
                selected[key] = sub
            else:
                tally.skipped += 1
        started_ms = time.time() * 1000.0
        self.busy_since = current
        try:
            results = await asyncio.to_thread(self._read, selected, live) if selected else {}
        finally:
            self.busy_since = None
        for key, result in results.items():
            sub = selected[key]
            if self.subs.get(key) is not sub:
                continue
            tally.published.append(sub.ticker)
            await self._apply(sub, result, started_ms, tally)
        wall_due = wall_now + timedelta(seconds=self.next_due - current)
        if timed or tally.published:
            self.health = _job_health(self.health, tally, wall_now, wall_due)

    def _read(self, selected: dict[str, _Subscription], live: bool) -> dict[str, ProviderResult]:
        """Read the provider for each selected ticker. Run in a thread, because providers block."""
        batch = getattr(self.provider, "fetch_batch_for_tickers", None)
        raw: dict[str, Any] = {}
        if callable(batch):
            try:
                values = batch({sub.ticker: sub.settings for sub in selected.values()}, live_only=live)
                if set(values) != {sub.ticker for sub in selected.values()}:
                    raise ValueError("provider batch returned the wrong ticker identifiers")
                raw = {key: values[sub.ticker] for key, sub in selected.items()}
            except Exception as error:
                raw = {key: error for key in selected}
        else:
            for key, sub in selected.items():
                try:
                    raw[key] = self._fetch(sub, live)
                except Exception as error:
                    raw[key] = error
        results = {}
        for key, value in raw.items():
            settings = selected[key].settings
            if isinstance(value, Exception):
                value = _failure(self.name, value)
            try:
                results[key] = normalize_provider_result(value, settings, provider=self.name)
            except Exception as error:
                results[key] = normalize_provider_result(_failure(self.name, error), settings, provider=self.name)
        return results

    def _fetch(self, sub: _Subscription, live: bool) -> Any:
        if live and callable(getattr(self.provider, "fetch_live_for_ticker", None)):
            return self.provider.fetch_live_for_ticker(sub.ticker, sub.settings)
        scoped = getattr(self.provider, "fetch_for_ticker", None)
        if callable(scoped):
            return scoped(sub.ticker, sub.settings)
        return self.provider.fetch(sub.settings)

    async def _apply(self, sub: _Subscription, result: ProviderResult, started_ms: float, tally: _Tally) -> None:
        current = self.monotonic()
        if not result.health.healthy:
            error = result.health.error or "provider unhealthy"
            tally.errors.append((sub.ticker, error))
            self.errors[sub.key] = error
            retry_at = self.recovery.failed(self.name, sub.ticker, sub.key, current)
            self._incident("provider_failure", error=RuntimeError(error), context={
                "ticker_id": sub.ticker, "settings_fingerprint": hashlib.sha256(sub.key.encode()).hexdigest(),
                "entrypoint": f"{type(self.provider).__module__}.{type(self.provider).__qualname__}",
                "source_file": _source_file(self.provider), "retry_in_seconds": max(0, retry_at - current),
                "source_failure": dict(result.health.diagnostic) if result.health.diagnostic else None})
            return
        self.errors.pop(sub.key, None)
        if self.recovery.succeeded(self.name, sub.ticker, sub.key):
            self._incident("provider_recovered", context={"ticker_id": sub.ticker})
        if result.health.error:
            tally.warnings.append((sub.ticker, result.health.error))
            self._incident("provider_degraded", error=result.health.error,
                           context={"ticker_id": sub.ticker, "entrypoint": type(self.provider).__qualname__})
        tally.successes += 1
        await self._send({"t": "result", "sub": sub.key, "result": encode(result), "started_ms": started_ms})

    async def _watch_changes(self) -> None:
        """Turn Fastcast version changes into live passes, as the old core change watcher did."""
        cursor: dict[str, str] = {}
        last_error_at = float("-inf")
        while True:
            try:
                versions = await asyncio.to_thread(self.provider.wait_for_changes, cursor, 2.0)
            except Exception as error:
                if self.monotonic() - last_error_at >= 60:
                    self._incident("source_notification_failure", error=error)
                    last_error_at = self.monotonic()
                await asyncio.sleep(1.0)
                continue
            changed = {topic for topic, version in versions.items() if cursor.get(topic) != version}
            if cursor and changed:
                self._topics.update(changed)
                self._wake.set()
            cursor = versions

    # Health

    async def _health_loop(self) -> None:
        while True:
            await asyncio.sleep(self.health_seconds)
            await self._send_health()

    async def _send_health(self) -> None:
        busy = 0.0 if self.busy_since is None else self.monotonic() - self.busy_since
        await self._send({"t": "health", "ok": not self.errors, "errors": dict(self.errors), "rss_mb": _rss_mb(),
                          "busy_seconds": round(busy, 1), "job": encode(self.health),
                          "recovery": self.recovery.snapshot(self.monotonic())})

    async def _send(self, message: dict[str, Any]) -> bool:
        writer = self._writer
        if writer is None:
            return False
        try:
            async with self._send_lock:
                writer.write(encode_line(message))
                await writer.drain()
            return True
        except (OSError, ContractError) as error:
            _log(self.name, f"send failed: {error}")
            return False

    def _incident(self, kind: str, **detail: Any) -> None:
        if self.incidents is not None:
            try:
                self.incidents.record(kind, component=self.name, **detail)
            except Exception as error:
                _log(self.name, f"incident record failed: {error}")


def _failure(name: str, error: BaseException) -> ProviderResult:
    return ProviderResult(health=ProviderHealth(healthy=False, provider=name, error=str(error) or type(error).__name__, diagnostic={
        "exception_type": type(error).__name__, "traceback": "".join(traceback.format_exception(error))}))


def _job_health(health: JobHealth, tally: _Tally, wall_now: datetime, wall_due: datetime) -> JobHealth:
    """Return the job health after one pass. The rules match the old core scheduler."""
    attempted = len(tally.published)
    if not attempted:
        result = replace(health, next_due=wall_due)
    elif tally.errors:
        result = JobHealth(last_success=wall_now if tally.successes else health.last_success,
                                 last_error=_messages(tally.errors + tally.warnings), next_due=wall_due,
                                 consecutive_failures=health.consecutive_failures + 1)
    else:
        result = JobHealth(last_success=wall_now, last_error=_messages(tally.warnings), next_due=wall_due,
                                 consecutive_failures=0)
    return replace(result, refresh_calls=health.refresh_calls + attempted, paused_refreshes=health.paused_refreshes + tally.skipped)


def _messages(messages: list[tuple[str, str]]) -> str | None:
    grouped: dict[str, list[str]] = {}
    for ticker_id, message in messages:
        grouped.setdefault(message, []).append(ticker_id)
    formatted = [f"{ids[0]}: {message}" if len(ids) == 1 else f"{len(ids)} tickers: {message}" for message, ids in grouped.items()]
    return "; ".join(formatted) if formatted else None


def _advance(next_due: float, now: float, interval: float) -> float:
    if next_due > now:
        return next_due
    return next_due + (int((now - next_due) // interval) + 1) * interval


def _source_file(provider: Any) -> str | None:
    try:
        return inspect.getsourcefile(type(provider))
    except TypeError:
        return None


def _rss_mb() -> float:
    try:
        with open("/proc/self/statm", encoding="ascii") as statm:
            return round(int(statm.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1048576, 1)
    except (OSError, ValueError, IndexError):
        return 0.0


def _log(name: str, text: str) -> None:
    print(f"ticker3 worker {name}: {text}", file=sys.stderr, flush=True)
