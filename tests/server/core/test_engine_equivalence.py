"""Prove that the Ticker 3 engine gives the same display data as the old scheduler.

`tests/fixtures/engine/golden_views.json` holds the data views that the old scheduler made
from the replay providers. The replay providers return recorded real provider results.
The test runs the Ticker 3 engine with the same providers and compares the full view and
the device view of each ticker.
"""
import json
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from ticker.shared.domain import DisplaySettings
from ticker.server.store import PairingState, TickerRepository

pytestmark = [pytest.mark.critical, pytest.mark.skipif(sys.platform == "win32", reason="Workers use Unix sockets")]

REPOSITORY = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
GOLDEN = REPOSITORY / "tests" / "fixtures" / "engine" / "golden_views.json"
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
# The schedule shows the local time. The application clock stays at the minute of the recording.
RECORDED_AT = datetime(2026, 10, 29, 19, 6, 30, tzinfo=timezone.utc).timestamp()


def seed(path: Path) -> None:
    repository = TickerRepository(path)
    for ticker_id, settings in TICKERS.items():
        repository.create_ticker(ticker_id, settings, name=ticker_id, pairing=PairingState(paired=True))
    repository.close()


def without_volatile(data: dict) -> dict:
    for *parents, key in VOLATILE:
        section = data
        for parent in parents:
            section = section.get(parent, {})
        section.pop(key, None)
    return data


def views(app) -> dict:
    application = app.extensions["ticker.application"]
    return {f"{ticker_id}:{'device' if device_view else 'full'}": without_volatile(
                json.loads(json.dumps(application.project_data(ticker_id, device_view=device_view), default=str)))
            for ticker_id in TICKERS for device_view in (False, True)}


def ready(app) -> bool:
    application = app.extensions["ticker.application"]
    snapshots = {ticker_id: application.get_snapshot(ticker_id) for ticker_id in TICKERS}
    if any(snapshot is None for snapshot in snapshots.values()):
        return False
    families = {item.family for item in snapshots["sports0001"].content}
    return {"sports", "golf"} <= families and any(item.family == "weather" for item in snapshots["weather001"].content) \
        and any(item.family in ("airports", "flights") for item in snapshots["airport001"].content)


def wait(app, seconds=40.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if ready(app):
            # Let each provider of the last pass land.
            time.sleep(0.5)
            return
        time.sleep(0.1)
    raise AssertionError("the engine did not publish every ticker in time")


@pytest.fixture
def environment(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "client")
    monkeypatch.setenv("SPOTIFY_CALLBACK_URI", "https://example.com/spotify/callback")
    monkeypatch.setenv("SPOTIFY_APP_RETURN_URI", "sportsticker://spotify")
    monkeypatch.setenv("SPOTIFY_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("TICKER3_REPLAY_DIR", str(REPOSITORY / "tests" / "fixtures" / "engine"))
    monkeypatch.delenv("TICKER_ENV_FILE", raising=False)
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        yield Path(directory)


def test_engine_gives_the_recorded_data_of_the_old_scheduler(environment, monkeypatch):
    expected = {view: without_volatile(data) for view, data in json.loads(GOLDEN.read_text()).items()}
    path = environment / "data" / "ticker.sqlite3"
    path.parent.mkdir()
    seed(path)

    release = environment / "releases" / "replay"
    release.mkdir(parents=True)
    for package in ("ticker",):
        (release / package).symlink_to(REPOSITORY / package, target_is_directory=True)
    shutil.copy(HERE / "replay_provider.py", release / "replay_provider.py")
    monkeypatch.setenv("TICKER3_RELEASES", str(environment / "releases"))
    monkeypatch.setenv("TICKER3_RELEASE", "replay")
    monkeypatch.setenv("TICKER3_SOCKET", str(environment / "t3.sock"))
    from ticker.server.main import create_application, start_engine
    app = create_application(path, worker_arguments=("--factory", "replay_provider:create", "--health-seconds", "0.2"),
                             supervisor_options={"adopt_seconds": 0, "watch_seconds": 0.05}, clock=lambda: RECORDED_AT)
    stop = start_engine(app)
    try:
        wait(app)
        actual = views(app)
        engine = app.extensions["ticker3.engine"]
        assert all(status["connected"] for status in engine.workers().values())
        health = app.test_client().get("/health").get_json()
        assert health["status"] == "ok" and health["runtime"]["ready"] and health["runtime"]["cycles"] >= 2
        assert set(health["scheduler"]["providers"]) == {"espn", "fotmob", "weather", "golf", "racing", "stock",
                                                         "flights", "music", "news", "clock"}
        assert all(provider["healthy"] for provider in health["scheduler"]["providers"].values())
    finally:
        app.extensions["ticker3.engine"].stop(stop_workers=True)
        stop()

    assert set(actual) == set(expected)
    for view in expected:
        assert actual[view] == expected[view], view
    # The proof must cover real display data, not empty screens.
    assert len(expected["sports0001:full"]["content"]["sports"]) >= 10
    assert expected["weather001:device"]["content"]["weather"]
