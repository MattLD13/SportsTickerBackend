"""Run one feature: connect to the core, read upstreams, and send record changes.

The runner keeps reading upstreams while the core is away. When it connects
again, it sends a full sync of each subscription. If it has no core for
`orphan_seconds`, it stops.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from ticker3.contract import PROTOCOL, ContractError
from ticker3.contract.messages import MAX_RECORDS, core_message
from ticker3.contract.records import validate_record
from ticker3.contract.wire import MAX_LINE, canonical, decode, encode

from .feature import Context, Feature
from .http import HttpClient


@dataclass
class _Subscription:
    key: str
    config: dict[str, Any]
    records: dict[str, dict[str, Any]] | None = None
    synced: bool = False
    error: str | None = None
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None


class Runner:
    def __init__(self, feature: Feature, socket_path: str, release: str, *, http: HttpClient | None = None,
                 orphan_seconds: float = 600, health_seconds: float = 5, poll_timeout: float = 60,
                 connect_seconds: float = 1) -> None:
        self.feature, self.socket_path, self.release = feature, socket_path, release
        self.http = http or HttpClient()
        self.orphan_seconds, self.health_seconds = orphan_seconds, health_seconds
        self.poll_timeout, self.connect_seconds = poll_timeout, connect_seconds
        self.subs: dict[str, _Subscription] = {}
        self._writer: asyncio.StreamWriter | None = None
        self._send_lock = asyncio.Lock()
        self._stopping = asyncio.Event()
        self.context = Context(http=self.http, release=release, wake=self.wake_where,
                               subscriptions=lambda: {key: sub.config for key, sub in self.subs.items()})

    async def run(self) -> int:
        await self.feature.start(self.context)
        health = asyncio.create_task(self._health_loop())
        try:
            return await self._connect_loop()
        finally:
            health.cancel()
            for sub in self.subs.values():
                if sub.task:
                    sub.task.cancel()
            await asyncio.gather(health, *(sub.task for sub in self.subs.values() if sub.task), return_exceptions=True)
            await self.feature.stop()
            self.http.close()

    def wake_where(self, match) -> int:
        """Read now each subscription whose config matches. Return the number woken."""
        woken = 0
        for sub in self.subs.values():
            if match(sub.config):
                sub.wake.set()
                woken += 1
        return woken

    async def _connect_loop(self) -> int:
        lost_at = time.monotonic()
        while not self._stopping.is_set():
            try:
                reader, writer = await asyncio.open_unix_connection(self.socket_path, limit=MAX_LINE + 1)
            except OSError:
                if time.monotonic() - lost_at > self.orphan_seconds:
                    _log(f"no core for {self.orphan_seconds:.0f} s, stopping")
                    return 0
                await asyncio.sleep(self.connect_seconds)
                continue
            try:
                refused = await self._session(reader, writer)
                if refused is not None:
                    _log(f"core refused this worker: {refused}")
                    return 3
            except (OSError, asyncio.IncompleteReadError, ContractError) as error:
                _log(f"core connection lost: {error}")
            finally:
                self._writer = None
                for sub in self.subs.values():
                    sub.synced = False
                writer.close()
            lost_at = time.monotonic()
        return 0

    async def _session(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> str | None:
        writer.write(encode({"t": "hello", "protocol": PROTOCOL, "feature": self.feature.manifest["feature"],
                             "release": self.release, "pid": os.getpid(), "manifest": self.feature.manifest}))
        await writer.drain()
        welcome = core_message(decode(await asyncio.wait_for(reader.readline(), timeout=10)))
        if welcome["t"] != "welcome":
            raise ContractError("the core must answer hello with welcome")
        if not welcome["ok"]:
            return welcome.get("reason", "no reason")
        self._writer = writer
        await self._send_health()
        while True:
            line = await reader.readline()
            if not line:
                raise asyncio.IncompleteReadError(b"", None)
            message = core_message(decode(line))
            if message["t"] == "subscribe":
                await self._subscribe(message["subs"])
            elif message["t"] == "wake":
                for key in message["subs"]:
                    if key in self.subs:
                        self.subs[key].wake.set()
            elif message["t"] == "drain":
                self._stopping.set()
                return None

    async def _subscribe(self, wanted: dict[str, dict[str, Any]]) -> None:
        for key in set(self.subs) - set(wanted):
            sub = self.subs.pop(key)
            if sub.task:
                sub.task.cancel()
        for key, config in wanted.items():
            sub = self.subs.get(key)
            if sub is None:
                sub = self.subs[key] = _Subscription(key, config)
                sub.task = asyncio.create_task(self._poll_loop(sub))
            elif not sub.synced and sub.records is not None:
                await self._publish(sub, list(sub.records.values()))

    async def _poll_loop(self, sub: _Subscription) -> None:
        failures = 0
        while True:
            try:
                poll = await asyncio.wait_for(self.feature.poll(sub.config, self.context), timeout=self.poll_timeout)
                if len(poll.records) > MAX_RECORDS:
                    raise ContractError(f"poll returned more than {MAX_RECORDS} records")
                records = [validate_record(record) for record in poll.records]
                if len({record["id"] for record in records}) != len(records):
                    raise ContractError("poll returned one record ID twice")
                sub.error, failures = None, 0
                await self._publish(sub, records)
                delay = max(0.05, float(poll.next_seconds))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                failures += 1
                sub.error = f"{type(error).__name__}: {error}"[:300]
                delay = min(300.0, 5.0 * 2 ** (failures - 1))
            sub.wake.clear()
            try:
                await asyncio.wait_for(sub.wake.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def _publish(self, sub: _Subscription, records: list[dict[str, Any]]) -> None:
        current = {record["id"]: record for record in records}
        previous, sub.records = sub.records, current
        if self._writer is None or self.subs.get(sub.key) is not sub:
            return
        if not sub.synced or previous is None:
            sent = await self._send({"t": "sync", "sub": sub.key, "records": records})
            sub.synced = sent
            return
        upsert = [record for identifier, record in current.items()
                  if identifier not in previous or canonical(previous[identifier]) != canonical(record)]
        remove = [identifier for identifier in previous if identifier not in current]
        if upsert or remove:
            sub.synced = await self._send({"t": "delta", "sub": sub.key, "upsert": upsert, "remove": remove})

    async def _health_loop(self) -> None:
        while True:
            await asyncio.sleep(self.health_seconds)
            await self._send_health()

    async def _send_health(self) -> None:
        errors = {key: sub.error for key, sub in self.subs.items() if sub.error}
        await self._send({"t": "health", "ok": not errors, "errors": errors, "rss_mb": _rss_mb()})

    async def _send(self, message: dict[str, Any]) -> bool:
        writer = self._writer
        if writer is None:
            return False
        try:
            async with self._send_lock:
                writer.write(encode(message))
                await writer.drain()
            return True
        except (OSError, ContractError) as error:
            _log(f"send failed: {error}")
            return False


def _rss_mb() -> float:
    try:
        with open("/proc/self/statm", encoding="ascii") as statm:
            return round(int(statm.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1048576, 1)
    except (OSError, ValueError, IndexError):
        return 0.0


def _log(text: str) -> None:
    print(f"ticker3 worker: {text}", file=sys.stderr, flush=True)
