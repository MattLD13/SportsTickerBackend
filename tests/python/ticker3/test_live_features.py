"""Run the real feature workers against the real upstreams. Set TICKER3_LIVE=1 to run."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

from ticker3.core.hub import App, Hub
from ticker3.core.supervisor import Supervisor, WorkerSpec

pytestmark = pytest.mark.skipif(os.environ.get("TICKER3_LIVE") != "1" or sys.platform == "win32",
                                reason="Set TICKER3_LIVE=1 to read the real upstreams")
REPOSITORY = Path(__file__).resolve().parents[3]


def test_real_workers_fill_screens_and_racing_gets_track_weather_through_the_core():
    async def scenario(directory: Path):
        from ticker3.features import racing, sports, weather
        hub = Hub()
        for module in (weather, sports, racing):
            hub.register(module.MANIFEST)
        hub.set_playlist("t", [App("f1", "racing", {}), App("s", "sports", {"leagues": ["nfl", "nba"]})])
        hub.set_playlist("u", [App("w", "weather", {"latitude": 40.7128, "longitude": -74.006})])
        specs = [WorkerSpec(name, f"ticker3.features.{name}") for name in ("weather", "sports", "racing")]
        supervisor = Supervisor(hub, directory / "core.sock", directory / "state.json", specs, lambda release: REPOSITORY,
                                initial_release="dev", log_directory=directory / "logs", adopt_seconds=0, watch_seconds=0.1)
        await supervisor.start()
        try:
            for _ in range(300):
                screens = {screen["id"]: screen for screen in hub.composition("t").screens}
                if "weather.temp" in screens.get("f1/session", {}).get("values", {}) and hub.composition("u").screens:
                    break
                await asyncio.sleep(0.1)
            session = screens["f1/session"]["values"]
            assert session["weather.temp"].endswith("°") and session["weather.icon"]
            assert any(identifier.startswith("s/nfl-") for identifier in screens)
            assert hub.composition("u").screens[0]["values"]["temp"].endswith("°")
            assert len(hub.wanted("weather")) == 2
            status = supervisor.status()
            assert all(status[name]["connected"] for name in ("weather", "sports", "racing"))
            print({name: (status[name]["rss_mb"], status[name]["errors"]) for name in status})
            print(session)
        finally:
            await supervisor.stop(stop_workers=True)

    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        asyncio.run(asyncio.wait_for(scenario(Path(directory)), 90))
