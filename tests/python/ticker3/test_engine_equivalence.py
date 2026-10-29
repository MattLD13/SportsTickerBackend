"""Prove that the Ticker 3 engine gives the same V2 output as the old scheduler.

Both backends read the same replay providers, which return recorded real
provider results. The test compares the V2 data that the /data route and the
device stream send, for the full view and the device view of each ticker.
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from sports_ticker.domain import DisplaySettings
from sports_ticker.fleet import PairingState, TickerRepository

pytestmark = [pytest.mark.critical, pytest.mark.skipif(sys.platform == "win32", reason="Workers use Unix sockets")]

REPOSITORY = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
TICKERS = {
    "sports0001": DisplaySettings(mode="sports", my_teams=("nfl:nyg", "nba:nyk", "nhl:nyr")),
    "weather001": DisplaySettings(mode="weather", weather_city="New York", weather_lat=40.7128, weather_lon=-74.006),
    "airport001": DisplaySettings(mode="airports", airport_code_iata="EWR", airport_code_icao="KEWR",
                                  airport_name="Newark Liberty International"),
    "clock00001": DisplaySettings(mode="clock"),
}
# Only these fields may differ: a publish counter, latency diagnostics, and the read time.
# A provider stamps each result with its read time, so two runs of one backend differ there too.
VOLATILE = (("snapshot", "revision"), ("snapshot", "timing"), ("snapshot", "observed_at"))


def seed(path: Path) -> None:
    repository = TickerRepository(path)
    for ticker_id, settings in TICKERS.items():
        repository.create_ticker(ticker_id, settings, name=ticker_id, pairing=PairingState(paired=True))
    repository.close()


def views(app) -> dict:
    application = app.extensions["sports_ticker.backend_application"]
    result = {}
    for ticker_id in TICKERS:
        for device_view in (False, True):
            data = json.loads(json.dumps(application.project_data(ticker_id, device_view=device_view), default=str))
            for section, key in VOLATILE:
                data.get(section, {}).pop(key, None)
            result[f"{ticker_id}:{'device' if device_view else 'full'}"] = data
    return result


def ready(app) -> bool:
    store = app.extensions["sports_ticker.snapshot_store"]
    snapshots = {ticker_id: store.get(ticker_id) for ticker_id in TICKERS}
    if any(snapshot is None for snapshot in snapshots.values()):
        return False
    families = {item.family for item in snapshots["sports0001"].content}
    return {"sports", "golf"} <= families and any(item.family == "weather" for item in snapshots["weather001"].content) \
        and any(item.family in ("airports", "flights") for item in snapshots["airport001"].content)


def wait(app, step, seconds=40.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        step()
        if ready(app):
            # One more step lets each provider of the last pass land.
            time.sleep(0.5)
            step()
            return
        time.sleep(0.1)
    raise AssertionError("the backend did not publish every ticker in time")


@pytest.fixture
def environment(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "client")
    monkeypatch.setenv("SPOTIFY_CALLBACK_URI", "https://example.com/callback")
    monkeypatch.setenv("SPOTIFY_APP_RETURN_URI", "sportsticker://spotify")
    monkeypatch.setenv("SPOTIFY_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("TICKER3_REPLAY_DIR", str(REPOSITORY / "tests" / "fixtures" / "ticker3"))
    monkeypatch.delenv("TICKER_WORKER_DIRECTORY", raising=False)
    monkeypatch.delenv("TICKER_ENV_FILE", raising=False)
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        yield Path(directory)


def test_new_engine_gives_the_same_v2_data_as_the_old_scheduler(environment, monkeypatch):
    sys.path.insert(0, str(HERE))
    import replay_provider

    old_path, new_path = environment / "old" / "ticker.sqlite3", environment / "new" / "ticker.sqlite3"
    for path in (old_path, new_path):
        path.parent.mkdir()
        seed(path)

    # The old backend makes each provider through the provider factory. The clock has no upstream, so it stays real.
    from sports_ticker.providers.clock import ClockProvider
    monkeypatch.setattr("sports_ticker.providers.factory.create_provider",
                        lambda name, **options: ClockProvider() if name == "clock" else replay_provider.create(name))
    from sports_ticker.production import create_production_application
    old = create_production_application(old_path)
    runtime = old.extensions["sports_ticker.runtime"]
    try:
        wait(old, runtime.run_once)
        expected = views(old)
    finally:
        old.extensions["sports_ticker.public_demo_data"].close()
        old.extensions["sports_ticker.backend_application"].close()

    release = environment / "releases" / "replay"
    release.mkdir(parents=True)
    for package in ("ticker3", "sports_ticker", "backend_ops", "ticker_core"):
        (release / package).symlink_to(REPOSITORY / package, target_is_directory=True)
    shutil.copy(HERE / "replay_provider.py", release / "replay_provider.py")
    monkeypatch.setenv("TICKER3_RELEASES", str(environment / "releases"))
    monkeypatch.setenv("TICKER3_RELEASE", "replay")
    monkeypatch.setenv("TICKER3_SOCKET", str(environment / "t3.sock"))
    from ticker3.server import create_application, start_engine
    new = create_application(new_path, worker_arguments=("--factory", "replay_provider:create", "--health-seconds", "0.2"),
                             supervisor_options={"adopt_seconds": 0, "watch_seconds": 0.05})
    stop = start_engine(new)
    try:
        wait(new, lambda: None)
        actual = views(new)
        engine = new.extensions["ticker3.engine"]
        assert all(status["connected"] for status in engine.workers().values())
        health = new.test_client().get("/api/v2/health").get_json()
        assert health["status"] == "ok" and health["runtime"]["ready"] and health["runtime"]["cycles"] >= 2
        assert set(health["scheduler"]["providers"]) == {"espn", "fotmob", "weather", "golf", "racing", "stock",
                                                         "flights", "music", "news", "clock"}
        assert all(provider["healthy"] for provider in health["scheduler"]["providers"].values())
    finally:
        new.extensions["ticker3.engine"].stop(stop_workers=True)
        stop()

    assert set(actual) == set(expected)
    for view in expected:
        assert actual[view] == expected[view], view
    # The proof must cover real display data, not empty screens.
    assert len(expected["sports0001:full"]["content"]["sports"]) >= 10
    assert expected["weather001:device"]["content"]["weather"]
