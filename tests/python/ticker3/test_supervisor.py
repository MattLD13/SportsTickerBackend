import asyncio
import os
import signal
import sys
import tempfile
from pathlib import Path

import pytest

from ticker3.contract.settings import subscription_key
from ticker3.core.hub import App, Hub
from ticker3.core.supervisor import Supervisor, WorkerSpec

pytestmark = [pytest.mark.critical, pytest.mark.skipif(sys.platform == "win32", reason="Workers use Unix sockets")]

REPOSITORY = Path(__file__).resolve().parents[3]
FEATURE = '''
import os, time
from ticker3.sdk.feature import Feature, Poll

BEHAVIOR = {behavior!r}

class Demo(Feature):
    manifest = {{"feature": "demo", "title": "Demo", "version": {version!r},
                "settings": {{"fields": {{"name": {{"type": "string", "default": "x"}}}}}},
                "templates": [{{"id": "demo.card", "version": 1, "panels": {{"w64h32": {{"box": [64, 32], "flow": "page",
                    "parts": [{{"part": "text", "at": [0, 0], "font": "tiny", "value": "{{v}}"}}]}}}}}}]}}

    async def poll(self, config, context):
        if BEHAVIOR == "crash":
            os._exit(1)
        if BEHAVIOR == "silent":
            time.sleep(3600)
        return Poll([{{"id": "item", "template": "demo.card", "values": {{"v": {version!r} + ":" + config["name"]}}}}], 0.2)

def create():
    if BEHAVIOR == "crash_on_start":
        raise SystemExit(1)
    return Demo()
'''
KEY = subscription_key({"name": "x"})


class Lab:
    def __init__(self, directory: Path):
        self.directory = directory
        self.screens = []

    def release(self, name: str, behavior: str = "good") -> str:
        root = self.directory / "releases" / name
        root.mkdir(parents=True)
        (root / "ticker3").symlink_to(REPOSITORY / "ticker3", target_is_directory=True)
        (root / "demo_feature.py").write_text(FEATURE.format(behavior=behavior, version=name), encoding="utf-8")
        return name

    def supervisor(self, hub=None, **options) -> Supervisor:
        hub = hub or Hub(on_screens=lambda ticker, composition: self.screens.append(composition))
        settings = dict(heartbeat_seconds=1.5, start_seconds=5, trial_seconds=10, adopt_seconds=0, crash_limit=3,
                        watch_seconds=0.05, worker_arguments=("--health-seconds", "0.2", "--connect-seconds", "0.1"))
        settings.update(options)
        supervisor = Supervisor(hub, self.directory / "core.sock", self.directory / "supervisor.json",
                                [WorkerSpec("demo", "demo_feature")], lambda release: self.directory / "releases" / release,
                                initial_release="r1", log_directory=self.directory / "logs", **settings)
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


def shown(lab):
    """Return the value of each composition after the first data arrived. None marks a gap."""
    values = [composition.screens[0]["values"]["v"] if composition.screens else None for composition in lab.screens]
    return values[next(index for index, item in enumerate(values) if item):]


def value(hub):
    screens = hub.composition("t").screens
    return screens[0]["values"]["v"] if screens else None


async def started(lab, supervisor, hub):
    await supervisor.start()
    await until(lambda: "demo" in hub.manifests)
    hub.set_playlist("t", [App("a", "demo", {})])
    await until(lambda: value(hub))


def test_worker_starts_restarts_after_a_crash_and_keeps_showing_data():
    async def scenario(lab):
        lab.release("r1")
        supervisor = lab.supervisor()
        hub = supervisor.hub
        await started(lab, supervisor, hub)
        assert value(hub) == "r1:x"
        first = supervisor.status()["demo"]["pid"]
        os.killpg(first, signal.SIGKILL)
        await until(lambda: supervisor.status()["demo"]["pid"] not in (None, first))
        assert value(hub) == "r1:x"
        assert supervisor.status()["demo"]["restarts"] == 1
        assert None not in shown(lab)
        await supervisor.stop(stop_workers=True)
    run(scenario)


def test_deploy_swaps_releases_without_a_gap():
    async def scenario(lab):
        lab.release("r1")
        lab.release("r2")
        supervisor = lab.supervisor()
        hub = supervisor.hub
        await started(lab, supervisor, hub)
        old = supervisor.status()["demo"]["pid"]
        assert await supervisor.deploy("demo", "r2")
        assert value(hub) == "r2:x"
        assert hub.manifests["demo"]["version"] == "r2"
        status = supervisor.status()["demo"]
        assert status["active"] == "r2" and status["previous"] == "r1" and status["pid"] != old
        await until(lambda: not _alive(old))
        assert shown(lab) == ["r1:x", "r2:x"]
        await supervisor.stop(stop_workers=True)
    run(scenario)


def test_failed_deploy_keeps_the_active_release_and_marks_the_new_one_bad():
    async def scenario(lab):
        lab.release("r1")
        lab.release("r2", "crash")
        supervisor = lab.supervisor()
        hub = supervisor.hub
        await started(lab, supervisor, hub)
        old = supervisor.status()["demo"]["pid"]
        assert not await supervisor.deploy("demo", "r2")
        status = supervisor.status()["demo"]
        assert status["active"] == "r1" and status["bad"] == ["r2"] and status["pid"] == old
        assert value(hub) == "r1:x"
        with pytest.raises(RuntimeError, match="marked bad"):
            await supervisor.deploy("demo", "r2")
        await supervisor.stop(stop_workers=True)
    run(scenario)


def test_crash_loop_after_a_deploy_rolls_back_to_the_previous_release():
    async def scenario(lab):
        lab.release("r1")
        lab.release("r2")
        supervisor = lab.supervisor()
        hub = supervisor.hub
        await started(lab, supervisor, hub)
        assert await supervisor.deploy("demo", "r2")
        for _ in range(3):
            pid = await until(lambda: supervisor.status()["demo"]["pid"])
            os.killpg(pid, signal.SIGKILL)
            await until(lambda: supervisor.status()["demo"]["pid"] != pid)
        await until(lambda: supervisor.status()["demo"]["active"] == "r1")
        await until(lambda: value(hub) == "r1:x")
        assert supervisor.status()["demo"]["bad"] == ["r2"]
        events = [event["event"] for event in supervisor.events]
        assert "rolled_back" in events
        await supervisor.stop(stop_workers=True)
    run(scenario)


def test_silent_worker_is_replaced():
    async def scenario(lab):
        lab.release("r1", "silent")
        supervisor = lab.supervisor(heartbeat_seconds=1.0)
        hub = supervisor.hub
        await supervisor.start()
        first = await until(lambda: supervisor.status()["demo"]["pid"])
        hub.set_playlist("t", [App("a", "demo", {})])
        await until(lambda: supervisor.status()["demo"]["pid"] not in (None, first))
        assert "worker_silent" in [event["event"] for event in supervisor.events]
        await supervisor.stop(stop_workers=True)
    run(scenario)


def test_workers_survive_a_core_restart_and_the_new_core_adopts_them():
    async def scenario(lab):
        lab.release("r1")
        first = lab.supervisor()
        await started(lab, first, first.hub)
        pid = first.status()["demo"]["pid"]
        await first.stop()
        assert _alive(pid)
        hub = Hub()
        hub.register(first.hub.manifests["demo"])
        hub.set_playlist("t", [App("a", "demo", {})])
        second = lab.supervisor(hub, adopt_seconds=5)
        await second.start()
        await until(lambda: value(hub) == "r1:x")
        assert second.status()["demo"]["pid"] == pid
        assert second.features["demo"].children == {}
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
