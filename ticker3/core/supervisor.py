"""Start, watch, replace, and roll back feature worker processes.

Each worker runs in its own process session, so it keeps running when the core
restarts. The core listens on one Unix socket. A worker connects and sends hello.

Rules:
- A worker of the active release becomes the active connection. Its records go to the hub.
- If the active worker exits, or sends no health for `heartbeat_seconds`, it restarts with backoff.
- If the active release crashes `crash_limit` times in `crash_window` seconds, it is marked bad.
  The previous release then becomes active.
- `deploy()` starts the new release next to the active one. The new release becomes
  active after it syncs every wanted subscription. The old worker then gets `drain`.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ticker3.contract import ContractError
from ticker3.contract.messages import worker_message
from ticker3.contract.wire import MAX_LINE, decode, encode

from .hub import Hub

BACKOFF = (0.5, 1, 2, 4, 8, 16, 30, 60)


@dataclass(frozen=True)
class WorkerSpec:
    """The feature module that a worker process runs."""

    feature: str
    module: str


@dataclass
class _Connection:
    feature: str
    release: str
    pid: int
    writer: asyncio.StreamWriter
    manifest: dict[str, Any]
    role: str
    last_health_at: float
    health: dict[str, Any] | None = None
    records: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


@dataclass
class _Feature:
    spec: WorkerSpec
    active: str
    previous: str | None = None
    bad: list[str] = field(default_factory=list)
    connection: _Connection | None = None
    candidate: _Connection | None = None
    candidate_release: str | None = None
    trial: asyncio.Future | None = None
    children: dict[int, asyncio.subprocess.Process] = field(default_factory=dict)
    crashes: deque = field(default_factory=deque)
    restarts: int = 0
    next_start_at: float = 0.0
    started_pid: int | None = None
    started_at: float = 0.0
    lost_pid: int | None = None
    lost_at: float = 0.0
    adopt_pid: int | None = None


class Supervisor:
    def __init__(self, hub: Hub, socket_path: Path, state_path: Path, specs: list[WorkerSpec],
                 release_path: Callable[[str], Path], *, initial_release: str, log_directory: Path,
                 python: str = sys.executable, clock: Callable[[], float] = time.monotonic,
                 heartbeat_seconds: float = 20, start_seconds: float = 30, trial_seconds: float = 90,
                 adopt_seconds: float = 10, crash_limit: int = 3, crash_window: float = 1800,
                 watch_seconds: float = 0.25, worker_arguments: tuple[str, ...] = ()) -> None:
        self.hub, self.socket_path, self.state_path = hub, Path(socket_path), Path(state_path)
        self.release_path, self.log_directory, self.python, self.clock = release_path, Path(log_directory), python, clock
        self.heartbeat_seconds, self.start_seconds, self.trial_seconds = heartbeat_seconds, start_seconds, trial_seconds
        self.adopt_seconds, self.crash_limit, self.crash_window = adopt_seconds, crash_limit, crash_window
        self.watch_seconds, self.worker_arguments = watch_seconds, worker_arguments
        saved = _read(self.state_path).get("features", {})
        self.features = {}
        for spec in specs:
            record = saved.get(spec.feature, {})
            self.features[spec.feature] = _Feature(spec, record.get("active", initial_release), record.get("previous"),
                                                   list(record.get("bad", [])), adopt_pid=record.get("pid"))
        self.events: deque[dict[str, Any]] = deque(maxlen=200)
        self._expected_exits: set[int] = set()
        self._crashed: set[int] = set()
        self._server: asyncio.base_events.Server | None = None
        self._watch: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        self._started_at = 0.0
        hub.on_wanted = self._push_wanted

    # Lifecycle

    async def start(self) -> None:
        if len(os.fsencode(self.socket_path)) > 100:
            raise ValueError(f"the worker socket path {self.socket_path} is longer than 100 bytes. Set a shorter TICKER3_SOCKET.")
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_directory.mkdir(parents=True, exist_ok=True)
        self.socket_path.unlink(missing_ok=True)
        self._server = await asyncio.start_unix_server(self._accept, path=str(self.socket_path), limit=MAX_LINE + 1)
        os.chmod(self.socket_path, 0o600)
        self._started_at = self.clock()
        self._save()
        self._watch = asyncio.create_task(self._watch_loop())

    async def stop(self, *, stop_workers: bool = False) -> None:
        """Stop the core side. Workers keep running unless `stop_workers` is set."""
        if self._watch:
            self._watch.cancel()
        if self._server:
            self._server.close()
        for feature in self.features.values():
            for connection in (feature.connection, feature.candidate):
                if connection is not None:
                    if stop_workers:
                        self._expected_exits.add(connection.pid)
                        await self._send(connection, {"t": "drain"})
                    connection.writer.close()
            if stop_workers:
                for pid in list(feature.children):
                    self._expected_exits.add(pid)
                    _signal(pid, signal.SIGTERM)
        if stop_workers:
            children = [process for feature in self.features.values() for process in feature.children.values()]
            try:
                await asyncio.wait_for(asyncio.gather(*(process.wait() for process in children)), timeout=5)
            except asyncio.TimeoutError:
                # A worker with a blocked event loop cannot handle SIGTERM.
                for process in children:
                    _signal(process.pid, signal.SIGKILL)
                await asyncio.gather(*(process.wait() for process in children), return_exceptions=True)
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, *( [self._watch] if self._watch else []), return_exceptions=True)
        self.socket_path.unlink(missing_ok=True)

    async def deploy(self, name: str, release: str) -> bool:
        """Start `release` next to the active release and promote it after it syncs. Return True on success."""
        feature = self.features[name]
        if feature.trial is not None:
            raise RuntimeError(f"a deployment of {name} is already running")
        if release == feature.active:
            return True
        if release in feature.bad:
            raise RuntimeError(f"release {release} of {name} is marked bad")
        feature.candidate_release = release
        feature.trial = asyncio.get_running_loop().create_future()
        self._event(name, "deploy_started", release=release)
        await self._spawn(feature, release)
        try:
            return await asyncio.wait_for(asyncio.shield(feature.trial), timeout=self.trial_seconds)
        except asyncio.TimeoutError:
            self._fail_trial(feature, "the release did not sync in time")
            return False
        finally:
            feature.trial = None
            feature.candidate_release = None

    def status(self) -> dict[str, Any]:
        now = self.clock()
        result = {}
        for name, feature in self.features.items():
            connection = feature.connection
            health = connection.health if connection else None
            result[name] = {
                "active": feature.active, "previous": feature.previous, "bad": feature.bad,
                "connected": connection is not None, "pid": connection.pid if connection else None,
                "healthy": bool(health and health["ok"]), "errors": health["errors"] if health else {},
                "rss_mb": health["rss_mb"] if health else None, "restarts": feature.restarts,
                "recent_crashes": len([at for at in feature.crashes if now - at <= self.crash_window]),
                "deploying": feature.candidate_release,
            }
        return result

    # Connections

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connection = None
        try:
            hello = worker_message(decode(await asyncio.wait_for(reader.readline(), timeout=10)))
            if hello["t"] != "hello":
                raise ContractError("the first worker message must be hello")
            connection, reason = self._admit(hello, writer)
            if connection is None:
                writer.write(encode({"t": "welcome", "ok": False, "reason": reason}))
                await writer.drain()
                return
            writer.write(encode({"t": "welcome", "ok": True}))
            await writer.drain()
            feature = self.features[connection.feature]
            if connection.role == "active":
                feature.connection = connection
                feature.adopt_pid = connection.pid
                self._save()
                self.hub.register(connection.manifest)
                self._event(connection.feature, "worker_connected", release=connection.release, pid=connection.pid)
            else:
                feature.candidate = connection
                self._event(connection.feature, "candidate_connected", release=connection.release, pid=connection.pid)
            await self._send(connection, {"t": "subscribe", "subs": self.hub.wanted(connection.feature)})
            while line := await reader.readline():
                self._receive(connection, worker_message(decode(line)))
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, ContractError, ValueError) as error:
            if connection is not None:
                self._event(connection.feature, "worker_protocol_error", error=str(error)[:200])
        finally:
            writer.close()
            if connection is not None:
                self._lost(connection)

    def _admit(self, hello: dict[str, Any], writer: asyncio.StreamWriter) -> tuple[_Connection | None, str]:
        feature = self.features.get(hello["feature"])
        if feature is None:
            return None, f"feature {hello['feature']} is not configured"
        if hello["release"] in feature.bad:
            return None, f"release {hello['release']} is marked bad"
        now = self.clock()
        if hello["release"] == feature.active:
            if feature.connection is not None:
                return None, "an active worker of this feature is connected"
            role = "active"
        elif hello["release"] == feature.candidate_release:
            if feature.candidate is not None:
                return None, "a candidate worker of this feature is connected"
            role = "candidate"
        else:
            return None, f"release {hello['release']} is not active"
        return _Connection(hello["feature"], hello["release"], hello["pid"], writer, hello["manifest"], role, now), ""

    def _receive(self, connection: _Connection, message: dict[str, Any]) -> None:
        feature = self.features[connection.feature]
        if message["t"] == "health":
            connection.health, connection.last_health_at = message, self.clock()
            if connection.role == "candidate":
                self._check_trial(feature)
            return
        if message["t"] not in ("sync", "delta"):
            return
        if connection.role == "active" and feature.connection is connection:
            self.hub.apply(connection.feature, message)
        elif connection.role == "candidate" and feature.candidate is connection:
            records = {record["id"]: record for record in connection.records.get(message["sub"], [])}
            if message["t"] == "sync":
                records = {record["id"]: record for record in message["records"]}
            elif message["sub"] in connection.records:
                for identifier in message["remove"]:
                    records.pop(identifier, None)
                records.update((record["id"], record) for record in message["upsert"])
            else:
                return
            connection.records[message["sub"]] = list(records.values())
            self._check_trial(feature)

    def _lost(self, connection: _Connection) -> None:
        feature = self.features[connection.feature]
        if feature.connection is connection:
            feature.connection = None
            feature.lost_pid, feature.lost_at = connection.pid, self.clock()
            self._event(connection.feature, "worker_disconnected", release=connection.release, pid=connection.pid)
            if not _alive(connection.pid):
                self._crash(feature, connection.pid, "the worker process stopped")
        elif feature.candidate is connection:
            feature.candidate = None
            self._fail_trial(feature, "the candidate disconnected")

    # Deployments

    def _check_trial(self, feature: _Feature) -> None:
        candidate = feature.candidate
        if candidate is None or feature.trial is None or feature.trial.done() or candidate.health is None:
            return
        wanted = self.hub.wanted(feature.spec.feature)
        if not set(wanted) <= set(candidate.records):
            return
        old = feature.connection
        self.hub.register(candidate.manifest)
        for key, records in candidate.records.items():
            self.hub.apply(feature.spec.feature, {"t": "sync", "sub": key, "records": records})
        candidate.role, candidate.records = "active", {}
        feature.connection, feature.candidate = candidate, None
        feature.previous, feature.active = feature.active, candidate.release
        feature.crashes.clear()
        feature.restarts = 0
        self._save()
        self._event(feature.spec.feature, "deploy_promoted", release=candidate.release, previous=feature.previous)
        if old is not None:
            old.role = "draining"
            self._expected_exits.add(old.pid)
            self._spawn_task(self._drain(old))
        feature.trial.set_result(True)

    def _fail_trial(self, feature: _Feature, reason: str) -> None:
        release = feature.candidate_release
        if release is None:
            return
        candidate, feature.candidate = feature.candidate, None
        for pid, process in list(feature.children.items()):
            if process.returncode is None and getattr(process, "release", None) == release:
                self._expected_exits.add(pid)
                _signal(pid, signal.SIGKILL)
        if candidate is not None:
            candidate.writer.close()
        if release not in feature.bad:
            feature.bad.append(release)
        self._save()
        self._event(feature.spec.feature, "deploy_failed", release=release, reason=reason)
        if feature.trial is not None and not feature.trial.done():
            feature.trial.set_result(False)

    async def _drain(self, connection: _Connection) -> None:
        await self._send(connection, {"t": "drain"})
        for _ in range(40):
            if not _alive(connection.pid):
                return
            await asyncio.sleep(0.25)
        _signal(connection.pid, signal.SIGKILL)

    # Processes

    async def _spawn(self, feature: _Feature, release: str) -> None:
        root = self.release_path(release)
        log = open(self.log_directory / f"{feature.spec.feature}.log", "ab")
        try:
            process = await asyncio.create_subprocess_exec(
                self.python, "-m", "ticker3.sdk.run", "--feature", feature.spec.module, "--socket", str(self.socket_path),
                "--release", release, *self.worker_arguments,
                cwd=root, env={**os.environ, "PYTHONPATH": str(root)}, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL, stderr=log, start_new_session=True)
        finally:
            log.close()
        process.release = release
        feature.children[process.pid] = process
        if release == feature.active:
            feature.started_pid, feature.started_at = process.pid, self.clock()
        self._event(feature.spec.feature, "worker_started", release=release, pid=process.pid)
        self._spawn_task(self._reap(feature, process))

    async def _reap(self, feature: _Feature, process: asyncio.subprocess.Process) -> None:
        code = await process.wait()
        feature.children.pop(process.pid, None)
        if process.pid in self._expected_exits:
            self._expected_exits.discard(process.pid)
            return
        if (getattr(process, "release", None) == feature.candidate_release and feature.trial is not None
                and not feature.trial.done()):
            self._fail_trial(feature, f"the candidate exited with code {code}")
            return
        if getattr(process, "release", None) == feature.active:
            self._crash(feature, process.pid, f"the worker exited with code {code}")

    def _crash(self, feature: _Feature, pid: int, reason: str) -> None:
        if pid in self._crashed:
            return
        self._crashed.add(pid)
        now = self.clock()
        feature.crashes.append(now)
        while feature.crashes and now - feature.crashes[0] > self.crash_window:
            feature.crashes.popleft()
        feature.restarts += 1
        feature.next_start_at = now + BACKOFF[min(len(feature.crashes) - 1, len(BACKOFF) - 1)]
        self._event(feature.spec.feature, "worker_crashed", release=feature.active, pid=pid, reason=reason)
        if len(feature.crashes) >= self.crash_limit and feature.previous and feature.previous not in feature.bad:
            bad, feature.active, feature.previous = feature.active, feature.previous, None
            feature.bad.append(bad)
            feature.crashes.clear()
            feature.next_start_at = now
            self._save()
            self._event(feature.spec.feature, "rolled_back", release=feature.active, bad=bad)
            if feature.connection is not None and feature.connection.release == bad:
                self._expected_exits.add(feature.connection.pid)
                _signal(feature.connection.pid, signal.SIGKILL)

    async def _watch_loop(self) -> None:
        while True:
            await asyncio.sleep(self.watch_seconds)
            now = self.clock()
            for feature in self.features.values():
                connection = feature.connection
                if connection is not None:
                    if now - connection.last_health_at > self.heartbeat_seconds:
                        self._event(feature.spec.feature, "worker_silent", pid=connection.pid)
                        _signal(connection.pid, signal.SIGKILL)
                        connection.writer.close()
                        self._crash(feature, connection.pid, "the worker sent no health")
                    continue
                if now < feature.next_start_at:
                    continue
                if (now - self._started_at < self.adopt_seconds and feature.adopt_pid is not None
                        and _alive(feature.adopt_pid)):
                    # A worker from before the core restart is running. It connects again by itself.
                    continue
                if feature.lost_pid is not None and now - feature.lost_at < 5 and _alive(feature.lost_pid):
                    # A running worker that lost its connection connects again by itself.
                    continue
                running = [pid for pid, process in feature.children.items()
                           if process.returncode is None and getattr(process, "release", None) == feature.active]
                if running:
                    if now - feature.started_at > self.start_seconds:
                        for pid in running:
                            _signal(pid, signal.SIGKILL)
                    continue
                await self._spawn(feature, feature.active)

    # Helpers

    def _push_wanted(self, name: str, subs: dict[str, dict[str, Any]]) -> None:
        feature = self.features.get(name)
        if feature is None:
            return
        for connection in (feature.connection, feature.candidate):
            if connection is not None:
                self._spawn_task(self._send(connection, {"t": "subscribe", "subs": subs}))

    async def _send(self, connection: _Connection, message: dict[str, Any]) -> None:
        try:
            connection.writer.write(encode(message))
            await connection.writer.drain()
        except (OSError, ContractError):
            connection.writer.close()

    def _spawn_task(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _event(self, feature: str, kind: str, **detail: Any) -> None:
        self.events.append({"at": time.time(), "feature": feature, "event": kind, **detail})

    def _save(self) -> None:
        state = {"features": {name: {"active": feature.active, "previous": feature.previous, "bad": feature.bad[-20:],
                                     "pid": feature.connection.pid if feature.connection else feature.adopt_pid}
                              for name, feature in self.features.items()}}
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".next")
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(temporary, self.state_path)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _signal(pid: int, number: int) -> None:
    try:
        os.killpg(pid, number)
    except (ProcessLookupError, PermissionError):
        pass


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
