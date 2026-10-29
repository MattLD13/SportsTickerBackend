import asyncio
import tempfile
from pathlib import Path

import pytest

from ticker3.contract.messages import worker_message
from ticker3.contract.wire import decode, encode
from ticker3.sdk.feature import Feature, Poll
from ticker3.sdk.runner import Runner

pytestmark = pytest.mark.critical

KEY = "0123456789abcdef"
MANIFEST = {"feature": "demo", "title": "Demo", "version": "1",
            "settings": {"fields": {"city": {"type": "string", "default": "x"}}},
            "templates": [{"id": "demo.card", "version": 1, "panels": {"w64h32": {
                "box": [64, 32], "flow": "page", "parts": [{"part": "text", "at": [0, 0], "font": "tiny", "value": "{v}"}]}}}]}


class Demo(Feature):
    manifest = MANIFEST

    def __init__(self):
        self.answers = asyncio.Queue()
        self.polls = 0

    async def poll(self, config, context):
        self.polls += 1
        answer = await self.answers.get()
        if isinstance(answer, Exception):
            raise answer
        return Poll(answer, next_seconds=3600)


def record(identifier, value):
    return {"id": identifier, "template": "demo.card", "values": {"v": value}}


class FakeCore:
    """Accept worker connections and expose each message the worker sends."""

    def __init__(self, path, *, refuse=None):
        self.path, self.refuse = path, refuse
        self.messages = asyncio.Queue()
        self.connections = []

    async def start(self):
        self.server = await asyncio.start_unix_server(self._accept, path=self.path)

    async def _accept(self, reader, writer):
        hello = worker_message(decode(await reader.readline()))
        await self.messages.put(hello)
        writer.write(encode({"t": "welcome", "ok": self.refuse is None, **({"reason": self.refuse} if self.refuse else {})}))
        await writer.drain()
        self.connections.append(writer)
        try:
            while line := await reader.readline():
                await self.messages.put(worker_message(decode(line)))
        finally:
            writer.close()

    async def send(self, message):
        self.connections[-1].write(encode(message))
        await self.connections[-1].drain()

    async def next(self, kind):
        while True:
            message = await asyncio.wait_for(self.messages.get(), timeout=5)
            if message["t"] == kind:
                return message


def run(scenario):
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        asyncio.run(scenario(str(Path(directory) / "core.sock")))


def test_worker_syncs_then_sends_only_changes():
    async def scenario(path):
        core, feature = FakeCore(path), Demo()
        await core.start()
        runner = Runner(feature, path, "r1", health_seconds=0.05)
        task = asyncio.create_task(runner.run())
        hello = await core.next("hello")
        assert hello["release"] == "r1" and hello["manifest"]["feature"] == "demo"
        await core.send({"t": "subscribe", "subs": {KEY: {"city": "x"}}})
        await feature.answers.put([record("a", "1"), record("b", "2")])
        sync = await core.next("sync")
        assert [item["id"] for item in sync["records"]] == ["a", "b"]
        await core.send({"t": "wake", "subs": [KEY]})
        await feature.answers.put([record("a", "1"), record("c", "3")])
        delta = await core.next("delta")
        assert [item["id"] for item in delta["upsert"]] == ["c"] and delta["remove"] == ["b"]
        await core.send({"t": "drain"})
        assert await asyncio.wait_for(task, 5) == 0
    run(scenario)


def test_failed_read_keeps_records_and_reports_health():
    async def scenario(path):
        core, feature = FakeCore(path), Demo()
        await core.start()
        task = asyncio.create_task(Runner(feature, path, "r1", health_seconds=0.05).run())
        await core.next("hello")
        await core.send({"t": "subscribe", "subs": {KEY: {"city": "x"}}})
        await feature.answers.put([record("a", "1")])
        await core.next("sync")
        await core.send({"t": "wake", "subs": [KEY]})
        await feature.answers.put(RuntimeError("upstream down"))
        while True:
            health = await core.next("health")
            if not health["ok"]:
                break
        assert health["errors"] == {KEY: "RuntimeError: upstream down"}
        await core.send({"t": "drain"})
        await asyncio.wait_for(task, 5)
    run(scenario)


def test_worker_resyncs_kept_records_after_the_core_returns():
    async def scenario(path):
        core, feature = FakeCore(path), Demo()
        await core.start()
        task = asyncio.create_task(Runner(feature, path, "r1", health_seconds=0.05, connect_seconds=0.05).run())
        await core.next("hello")
        await core.send({"t": "subscribe", "subs": {KEY: {"city": "x"}}})
        await feature.answers.put([record("a", "1")])
        await core.next("sync")
        core.connections[-1].close()
        await core.next("hello")
        await core.send({"t": "subscribe", "subs": {KEY: {"city": "x"}}})
        sync = await core.next("sync")
        assert [item["id"] for item in sync["records"]] == ["a"]
        assert feature.polls == 1
        await core.send({"t": "drain"})
        await asyncio.wait_for(task, 5)
    run(scenario)


def test_refused_worker_stops_and_orphan_worker_stops():
    async def scenario(path):
        core = FakeCore(path, refuse="release is marked bad")
        await core.start()
        assert await asyncio.wait_for(Runner(Demo(), path, "r1").run(), 5) == 3
        core.server.close()
        await core.server.wait_closed()
        orphan = Runner(Demo(), path + ".missing", "r1", orphan_seconds=0.2, connect_seconds=0.05)
        assert await asyncio.wait_for(orphan.run(), 5) == 0
    run(scenario)


def test_invalid_records_become_a_health_error_not_a_message():
    async def scenario(path):
        core, feature = FakeCore(path), Demo()
        await core.start()
        task = asyncio.create_task(Runner(feature, path, "r1", health_seconds=0.05).run())
        await core.next("hello")
        await core.send({"t": "subscribe", "subs": {KEY: {"city": "x"}}})
        await feature.answers.put([{"id": "bad id", "template": "demo.card"}])
        while True:
            message = await core.next("health")
            assert message["t"] != "sync"
            if not message["ok"]:
                break
        assert "record id" in message["errors"][KEY]
        await core.send({"t": "drain"})
        await asyncio.wait_for(task, 5)
    run(scenario)
