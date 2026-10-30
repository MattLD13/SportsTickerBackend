import asyncio
import os
import signal
import sys
import tempfile
from pathlib import Path

import pytest

from ticker.server.contract.results import decode_result, encode
from ticker.shared.domain import DisplaySettings
from ticker.server.core.supervisor import Supervisor, WorkerSpec

pytestmark = [pytest.mark.critical, pytest.mark.skipif(sys.platform == "win32", reason="Workers use Unix sockets")]

REPOSITORY = Path(__file__).resolve().parents[3]
PROVIDER = '''
import os, time

BEHAVIOR = {behavior!r}

class Demo:
    def fetch_for_ticker(self, ticker_id, settings):
        if BEHAVIOR == "crash":
            os._exit(1)
        if BEHAVIOR == "silent":
            time.sleep(3600)
        return {{"content": [{{"id": "item", "type": "news", "sport": "news", "headline": {release!r} + ":" + ticker_id}}]}}

def create(name, database_path=None):
    if BEHAVIOR == "crash_on_start":
        raise SystemExit(1)
    return Demo()
'''
KEY = "0123456789abcdef"
CONFIG = {"ticker": "x", "settings": encode(DisplaySettings())}


class Lab:
    """Run a supervisor for the provider news with releases made in a temporary folder."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.wanted = {KEY: CONFIG}
        self.values = []

    def release(self, name: str, behavior: str = "good") -> str:
        root = self.directory / "releases" / name
        root.mkdir(parents=True)
        for package in ("shared", "server", "six"):
            (root / package).symlink_to(REPOSITORY / package, target_is_directory=True)
        (root / "demo_provider.py").write_text(PROVIDER.format(behavior=behavior, release=name), encoding="utf-8")
        return name

    def deliver(self, provider, message):
        if message["t"] == "result":
            self.values.append(decode_result(message["result"]).content[0].data["headline"])

    def supervisor(self, **options) -> Supervisor:
        settings = dict(heartbeat_seconds=1.5, start_seconds=5, trial_seconds=10, adopt_seconds=0, crash_limit=3,
                        watch_seconds=0.05, worker_arguments=("--factory", "demo_provider:create", "--interval", "0.2",
                                                              "--health-seconds", "0.2", "--connect-seconds", "0.1"))
        settings.update(options)
        supervisor = Supervisor(self.directory / "core.sock", self.directory / "supervisor.json", [WorkerSpec("news")],
                                lambda release: self.directory / "releases" / release, initial_release="r1",
                                log_directory=self.directory / "logs", wanted=lambda name: dict(self.wanted),
                                deliver=self.deliver, **settings)
        return supervisor


def run(scenario):
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        lab = Lab(Path(directory))
        asyncio.run(asyncio.wait_for(scenario(lab), 60))


async def until(check, seconds=10.0):
    deadline = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < deadline:
        value = check()
        if value:
            return value
        await asyncio.sleep(0.05)
    raise AssertionError("condition did not become true")


def value(lab):
    return lab.values[-1] if lab.values else None


async def started(lab, supervisor):
    await supervisor.start()
    await until(lambda: value(lab))


def test_worker_starts_restarts_after_a_crash_and_keeps_sending_results():
    async def scenario(lab):
        lab.release("r1")
        supervisor = lab.supervisor()
        await started(lab, supervisor)
        assert value(lab) == "r1:x"
        first = supervisor.status()["news"]["pid"]
        os.killpg(first, signal.SIGKILL)
        await until(lambda: supervisor.status()["news"]["pid"] not in (None, first))
        count = len(lab.values)
        await until(lambda: len(lab.values) > count)
        assert value(lab) == "r1:x" and supervisor.status()["news"]["restarts"] == 1
        await supervisor.stop(stop_workers=True)
    run(scenario)


def test_deploy_swaps_releases_without_a_gap():
    async def scenario(lab):
        lab.release("r1")
        lab.release("r2")
        supervisor = lab.supervisor()
        await started(lab, supervisor)
        old = supervisor.status()["news"]["pid"]
        assert await supervisor.deploy("news", "r2")
        assert value(lab) == "r2:x"
        status = supervisor.status()["news"]
        assert status["active"] == "r2" and status["previous"] == "r1" and status["pid"] != old
        await until(lambda: not _alive(old))
        switched = lab.values.index("r2:x")
        assert set(lab.values[:switched]) == {"r1:x"} and set(lab.values[switched:]) == {"r2:x"}
        await supervisor.stop(stop_workers=True)
    run(scenario)


def test_failed_deploy_keeps_the_active_release_and_marks_the_new_one_bad():
    async def scenario(lab):
        lab.release("r1")
        lab.release("r2", "crash")
        supervisor = lab.supervisor()
        await started(lab, supervisor)
        old = supervisor.status()["news"]["pid"]
        assert not await supervisor.deploy("news", "r2")
        status = supervisor.status()["news"]
        assert status["active"] == "r1" and status["bad"] == ["r2"] and status["pid"] == old
        assert set(lab.values) == {"r1:x"}
        with pytest.raises(RuntimeError, match="marked bad"):
            await supervisor.deploy("news", "r2")
        await supervisor.stop(stop_workers=True)
    run(scenario)


def test_crash_loop_after_a_deploy_rolls_back_to_the_previous_release():
    async def scenario(lab):
        lab.release("r1")
        lab.release("r2")
        supervisor = lab.supervisor()
        await started(lab, supervisor)
        assert await supervisor.deploy("news", "r2")
        for _ in range(3):
            pid = await until(lambda: supervisor.status()["news"]["pid"])
            os.killpg(pid, signal.SIGKILL)
            await until(lambda: supervisor.status()["news"]["pid"] != pid)
        await until(lambda: supervisor.status()["news"]["active"] == "r1")
        await until(lambda: value(lab) == "r1:x")
        assert supervisor.status()["news"]["bad"] == ["r2"]
        assert "rolled_back" in [event["event"] for event in supervisor.events]
        await supervisor.stop(stop_workers=True)
    run(scenario)


def test_silent_worker_is_replaced():
    async def scenario(lab):
        lab.release("r1", "silent")
        supervisor = lab.supervisor(heartbeat_seconds=1.0, busy_seconds=1.0)
        await supervisor.start()
        first = await until(lambda: supervisor.status()["news"]["pid"])
        await until(lambda: supervisor.status()["news"]["pid"] not in (None, first))
        events = [event for event in supervisor.events if event["event"] == "worker_silent"]
        assert events and "provider read took" in events[0]["reason"]
        await supervisor.stop(stop_workers=True)
    run(scenario)


def test_workers_survive_a_core_restart_and_the_new_core_adopts_them():
    async def scenario(lab):
        lab.release("r1")
        first = lab.supervisor()
        await started(lab, first)
        pid = first.status()["news"]["pid"]
        await first.stop()
        assert _alive(pid)
        lab.values.clear()
        second = lab.supervisor(adopt_seconds=5)
        await second.start()
        await until(lambda: value(lab) == "r1:x")
        assert second.status()["news"]["pid"] == pid and second.features["news"].children == {}
        await second.stop()
        os.killpg(pid, signal.SIGKILL)
    run(scenario)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as stat:
            return stat.read().split()[2] != "Z"
    except OSError:
        return False
