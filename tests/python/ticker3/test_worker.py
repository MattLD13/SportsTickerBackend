import asyncio
import tempfile
import threading
from pathlib import Path

import pytest

from backend_ops.worker_contract import decode_result, encode
from sports_ticker.domain import DisplaySettings
from sports_ticker.providers.contracts import ProviderHealth, ProviderResult
from ticker3.contract.messages import worker_message
from ticker3.contract.wire import decode, encode as encode_line
from ticker3.worker.runner import ProviderWorker

pytestmark = pytest.mark.critical

A, B = "0123456789abcdef", "fedcba9876543210"


def config(ticker, **settings):
    return {"ticker": ticker, "settings": encode(DisplaySettings(**settings))}


class Provider:
    def __init__(self):
        self.calls, self.healthy, self.lock = [], True, threading.Lock()

    def _result(self, ticker):
        if not self.healthy:
            return ProviderResult(health=ProviderHealth(healthy=False, provider="news", error="upstream down"))
        return {"content": [{"id": f"headline-{ticker}", "type": "news", "sport": "news", "headline": f"For {ticker}"}]}

    def fetch_for_ticker(self, ticker, settings):
        with self.lock:
            self.calls.append(("fetch_for_ticker", ticker))
        return self._result(ticker)


class BatchProvider(Provider):
    def __init__(self):
        super().__init__()
        self.versions = {"nfl": "1", "nba": "1"}
        self.changed = threading.Event()

    def fetch_batch_for_tickers(self, settings_by_ticker, *, live_only=False):
        with self.lock:
            self.calls.append(("batch", tuple(sorted(settings_by_ticker)), live_only))
        return {ticker: self._result(ticker) for ticker in settings_by_ticker}

    def wait_for_changes(self, after, timeout):
        # Like the Fastcast source, an empty cursor gets the current versions at once.
        if after and self.changed.wait(timeout):
            self.changed.clear()
        return dict(self.versions)


class FakeCore:
    def __init__(self, path):
        self.path, self.messages, self.connections = path, asyncio.Queue(), []

    async def start(self):
        self.server = await asyncio.start_unix_server(self._accept, path=self.path)

    async def _accept(self, reader, writer):
        await self.messages.put(worker_message(decode(await reader.readline())))
        writer.write(encode_line({"t": "welcome", "ok": True}))
        await writer.drain()
        self.connections.append(writer)
        try:
            while line := await reader.readline():
                await self.messages.put(worker_message(decode(line)))
        finally:
            writer.close()

    async def send(self, message):
        self.connections[-1].write(encode_line(message))
        await self.connections[-1].drain()

    async def next(self, kind, test=lambda message: True):
        while True:
            message = await asyncio.wait_for(self.messages.get(), timeout=10)
            if message["t"] == kind and test(message):
                return message


def run(scenario):
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        asyncio.run(asyncio.wait_for(scenario(str(Path(directory) / "core.sock")), 30))


def test_worker_reads_new_subscriptions_at_once_and_then_at_its_interval():
    async def scenario(path):
        core, provider = FakeCore(path), Provider()
        await core.start()
        worker = ProviderWorker("news", provider, path, "r1", interval=0.3, health_seconds=0.05)
        task = asyncio.create_task(worker.run())
        hello = await core.next("hello")
        assert (hello["provider"], hello["release"]) == ("news", "r1")
        await core.send({"t": "subscribe", "subs": {A: config("t1")}})
        first = await core.next("result")
        result = decode_result(first["result"])
        assert first["sub"] == A and result.content[0].data["headline"] == "For t1"
        await core.next("result")
        health = await core.next("health", lambda message: message["job"]["refresh_calls"] >= 2)
        assert health["ok"] and health["job"]["consecutive_failures"] == 0
        await core.send({"t": "drain"})
        assert await task == 0
    run(scenario)


def test_unhealthy_reads_send_no_result_and_pause_with_the_old_recovery_rule():
    async def scenario(path):
        core, provider = FakeCore(path), Provider()
        provider.healthy = False
        await core.start()
        task = asyncio.create_task(ProviderWorker("news", provider, path, "r1", interval=0.05, health_seconds=0.05).run())
        await core.next("hello")
        await core.send({"t": "subscribe", "subs": {A: config("t1")}})
        health = await core.next("health", lambda message: message["recovery"].get("news", {}).get("open_circuits"))
        assert health["errors"] == {A: "upstream down"} and not health["ok"]
        assert health["job"]["consecutive_failures"] >= 3 and health["job"]["last_error"] == "t1: upstream down"
        calls = len(provider.calls)
        await asyncio.sleep(0.3)
        assert len(provider.calls) == calls == 3
        assert all(message["t"] != "result" for message in list(core.messages._queue))
        await core.send({"t": "drain"})
        await task
    run(scenario)


def test_batch_provider_reads_all_tickers_in_one_call_and_fastcast_changes_start_a_live_pass():
    async def scenario(path):
        core, provider = FakeCore(path), BatchProvider()
        await core.start()
        task = asyncio.create_task(ProviderWorker("espn", provider, path, "r1", interval=60, health_seconds=0.05).run())
        await core.next("hello")
        await core.send({"t": "subscribe", "subs": {A: config("t1", active_sports={"nfl": True, "nba": False}),
                                                    B: config("t2", active_sports={"nfl": False, "nba": True})}})
        results = {(await core.next("result"))["sub"], (await core.next("result"))["sub"]}
        assert results == {A, B}
        assert provider.calls == [("batch", ("t1", "t2"), False)]
        await asyncio.sleep(0.2)
        provider.versions = {"nfl": "2", "nba": "1"}
        provider.changed.set()
        live = await core.next("result")
        assert live["sub"] == A
        assert provider.calls[-1] == ("batch", ("t1",), True)
        await core.send({"t": "drain"})
        await task
    run(scenario)


def test_a_new_core_connection_reads_every_kept_subscription_again():
    async def scenario(path):
        core, provider = FakeCore(path), Provider()
        await core.start()
        task = asyncio.create_task(ProviderWorker("news", provider, path, "r1", interval=60, health_seconds=0.05,
                                                  connect_seconds=0.05).run())
        await core.next("hello")
        await core.send({"t": "subscribe", "subs": {A: config("t1")}})
        await core.next("result")
        await core.send({"t": "subscribe", "subs": {A: config("t1"), B: config("t2")}})
        assert (await core.next("result"))["sub"] == B
        assert provider.calls == [("fetch_for_ticker", "t1"), ("fetch_for_ticker", "t2")]
        core.connections[-1].close()
        await core.next("hello")
        await core.send({"t": "subscribe", "subs": {A: config("t1"), B: config("t2")}})
        again = {(await core.next("result"))["sub"], (await core.next("result"))["sub"]}
        assert again == {A, B} and len(provider.calls) == 4
        await core.send({"t": "drain"})
        await task
    run(scenario)
