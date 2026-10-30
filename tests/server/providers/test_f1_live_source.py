"""Verify F1 with captured Austin Practice 2 timing responses."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from ticker.server.services.state_store import SnapshotStore
from ticker.shared.domain import DisplaySettings, TickerSnapshot
from ticker.server.projections.data_api import project_data_v2
from ticker.server.providers.racing import RacingProvider
from ticker.server.providers.racing_live import LiveRacingSource, _f1_short_event


pytestmark = pytest.mark.critical
_BASE = "https://sports.core.api.espn.com/v2/sports/racing/leagues/f1/events/600057446/competitions/401839119"
_SCOREBOARD = "https://site.web.api.espn.com/apis/site/v2/sports/racing/f1/scoreboard"
_NOW = datetime(2026, 10, 23, 21, 10, tzinfo=timezone.utc)
_SETTINGS = DisplaySettings(active_sports={"f1": True, "indycar": False, "nascar": False, "wec": False, "imsa": False})


class CapturedTiming:
    def __init__(self, filename: str = "f1_austin_practice_2026.json") -> None:
        path = Path(__file__).resolve().parents[2] / "fixtures/providers" / filename
        self.values = json.loads(path.read_text(encoding="utf-8"))
        self.urls: list[str] = []

    def get_json(self, url: str, *, timeout: float) -> object:
        assert timeout > 0
        self.urls.append(url)
        return self.values[url]

    def stat(self, driver_id: str, name: str) -> dict:
        categories = self.values[f"{_BASE}/competitors/{driver_id}/statistics"]["splits"]["categories"]
        return next(stat for category in categories for stat in category["stats"] if stat["name"] == name)


def test_f1_survives_the_adapter_snapshot_and_v2_projection() -> None:
    client = CapturedTiming()
    provider = RacingProvider(LiveRacingSource(client, now=lambda: _NOW, clock=lambda: _NOW.timestamp()))
    result = provider.fetch(_SETTINGS)

    assert result.health.healthy, result.health.error
    store = SnapshotStore()
    snapshot = store.replace(TickerSnapshot("f1-six", 0, _NOW, result.content, (), (), _SETTINGS))
    payload = project_data_v2(snapshot, result.health, {})
    item = payload["content"]["racing"][0]
    assert (item["family"], item["kind"]) == ("racing", "f1")
    assert payload["settings"]["active_sports"]["f1"] is True
    game = item["data"]
    assert game["state"] == "in"
    assert game["f1"]["session_name"] == "Practice 2"
    assert game["away_abbr"] == "United States GP"
    assert game["f1"]["event_name"] == game["f1"]["short_name"] == "United States GP"
    assert game["f1"]["time_to_go"] == "50:00"
    assert game["f1"]["flag"] == "GREEN"
    # ESPN entry order lists Verstappen fourth. Live timing lists him first.
    assert [(driver["pos"], driver["abbr"]) for driver in game["f1"]["drivers"]] == [(1, "VER"), (2, "RUS")]
    assert game["f1"]["drivers"][1]["gap"] == "+0.207"
    assert game["f1"]["updated_at"] == "2026-10-23T21:07:33Z"
    assert game["f1"]["weather"]["air_temp"] == "84"
    assert game["f1"]["weather"]["wind_mph"] == "11"
    assert game["f1"]["weather"]["wind_dir"] == "146"
    assert all("openf1" not in url for url in client.urls)


@pytest.mark.parametrize("name,expected", [
    ("MSC Cruises United States Grand Prix", "United States GP"),
    ("FORMULA 1 MSC CRUISES UNITED STATES GRAND PRIX 2026", "United States GP"),
    ("United States Grand Prix", "United States GP"),
    ("Pirelli British Grand Prix", "British GP"),
    ("Heineken Las Vegas Grand Prix", "Las Vegas GP"),
    ("Lenovo São Paulo Grand Prix", "São Paulo GP"),
])
def test_f1_event_labels_keep_the_location_without_sponsors(name: str, expected: str) -> None:
    assert _f1_short_event(name) == expected


def test_f1_refreshes_live_positions_and_caches_driver_identity() -> None:
    client = CapturedTiming()
    now = [_NOW]
    source = LiveRacingSource(client, now=lambda: now[0], clock=lambda: now[0].timestamp())
    source.fetch(_SETTINGS)
    initial_calls = len(client.urls)
    source.fetch(_SETTINGS)
    assert len(client.urls) == initial_calls
    now[0] += timedelta(seconds=16)
    client.stat("4665", "position")["value"] = 2
    client.stat("5503", "position")["value"] = 1

    game = source.fetch(_SETTINGS)["content"][0]

    assert game["f1"]["drivers"][0]["abbr"] == "RUS"
    assert client.urls.count(f"{_BASE}/competitors/4665/statistics") == 2
    assert client.urls.count("https://sports.core.api.espn.com/v2/sports/racing/athletes/4665") == 1


def test_f1_cached_timing_keeps_each_tickers_local_start_time() -> None:
    client = CapturedTiming()
    now = _NOW.replace(hour=20, minute=50)
    client.values[f"{_BASE}/status"]["type"]["state"] = "pre"
    source = LiveRacingSource(client, now=lambda: now, clock=lambda: now.timestamp())
    east = source.fetch(DisplaySettings(active_sports=dict(_SETTINGS.active_sports), timezone="America/New_York"))
    west = source.fetch(DisplaySettings(active_sports=dict(_SETTINGS.active_sports), timezone="America/Los_Angeles"))
    assert east["content"][0]["status"] == "5:00 PM"
    assert west["content"][0]["status"] == "2:00 PM"
    assert client.urls.count(_BASE) == 1


@pytest.mark.parametrize("now,state", [
    (_NOW, "pre"),
    (_NOW, "post"),
    (_NOW.replace(hour=22, minute=20), "in"),
])
def test_f1_uses_live_lifecycle_for_delays_and_early_finishes(now: datetime, state: str) -> None:
    client = CapturedTiming()
    client.values[f"{_BASE}/status"]["type"]["state"] = state
    game = LiveRacingSource(client, now=lambda: now).fetch(_SETTINGS)["content"][0]
    assert game["state"] == state
    if state == "post":
        assert game["status"] == "FINAL"
        assert game["f1"]["flag"] == "CHECKERED"
        assert game["f1"]["time_to_go"] == ""


def test_f1_flag_recovers_after_a_caution() -> None:
    client = CapturedTiming()
    now = [_NOW]
    source = LiveRacingSource(client, now=lambda: now[0], clock=lambda: now[0].timestamp())
    client.values[f"{_BASE}/status"]["flag"] = "YELLOW"
    first = source.fetch(_SETTINGS)["content"][0]
    assert first["f1"]["caution"] is True
    client.values[f"{_BASE}/status"]["flag"] = "GREEN"
    now[0] += timedelta(seconds=16)
    second = source.fetch(_SETTINGS)["content"][0]
    assert second["f1"]["caution"] is False
    assert second["f1"]["flag"] == "GREEN"


def test_f1_failure_reports_stale_data_and_respects_the_disabled_setting() -> None:
    client = CapturedTiming()
    now = [_NOW]
    provider = RacingProvider(LiveRacingSource(client, now=lambda: now[0], clock=lambda: now[0].timestamp()))
    first = provider.fetch(_SETTINGS)
    now[0] += timedelta(seconds=16)
    del client.values[f"{_BASE}/status"]

    failed = provider.fetch(_SETTINGS)

    assert failed.health.healthy is False
    assert failed.content == first.content
    assert "stale:" in failed.health.error
    count = len(client.urls)
    disabled = provider.fetch(DisplaySettings(active_sports={"f1": False, "indycar": False, "nascar": False, "wec": False, "imsa": False}))
    assert disabled.health.healthy
    assert disabled.content == ()
    assert len(client.urls) == count


def test_f1_race_uses_the_matching_competition_and_lap_count() -> None:
    client = CapturedTiming()
    competition = client.values[_SCOREBOARD]["events"][0]["competitions"][0]
    competition["type"]["abbreviation"] = "Race"
    client.values[f"{_BASE}/statistics"]["categories"][0]["stats"][0]["value"] = 56
    game = LiveRacingSource(client, now=lambda: _NOW).fetch(_SETTINGS)["content"][0]
    assert game["id"] == "f1_600057446_race"
    assert game["f1"]["total_laps"] == 56
    assert game["status"] == "Lap 3/56"


def test_f1_qualifying_formats_the_latest_completed_segment_time() -> None:
    client = CapturedTiming()
    competition = client.values[_SCOREBOARD]["events"][0]["competitions"][0]
    competition["type"]["abbreviation"] = "Qual"
    client.stat("4665", "qual2TimeMS")["value"] = 92012
    game = LiveRacingSource(client, now=lambda: _NOW).fetch(_SETTINGS)["content"][0]
    assert game["f1"]["drivers"][0]["best_time"] == "1:32.012"
    assert game["f1"]["drivers"][0]["gap"] == "1:32.012"


def test_completed_f1_practice_keeps_official_times_gaps_and_session_weather() -> None:
    client = CapturedTiming("f1_austin_practice1_2026.json")
    result = RacingProvider(LiveRacingSource(client, now=lambda: _NOW)).fetch(_SETTINGS)
    assert result.health.healthy, result.health.error
    game = result.content[0].data
    assert game["state"] == "post"
    drivers = game["f1"]["drivers"]
    assert [(driver["abbr"], driver["gap"]) for driver in drivers] == [("LEC", "1:36.052"), ("VER", "+0.084")]
    assert drivers[1]["best_time"] == "1:36.136"
    weather = game["f1"]["weather"]
    assert weather["observed_at"] == "2026-10-23T18:00"
    assert weather["air_temp"] == "82"
    assert weather["wind_mph"] == "7"
    assert weather["wind_dir"] == "155"


def test_f1_weather_caches_circuit_location_and_conditions() -> None:
    client = CapturedTiming()
    now = [_NOW]
    source = LiveRacingSource(client, now=lambda: now[0], clock=lambda: now[0].timestamp())
    source.fetch(_SETTINGS)
    now[0] += timedelta(seconds=16)
    source.fetch(_SETTINGS)
    assert sum("open-meteo.com" in url for url in client.urls) == 1
    now[0] += timedelta(seconds=300)
    source.fetch(_SETTINGS)
    assert sum("open-meteo.com" in url for url in client.urls) == 2
    assert sum("api.jolpi.ca" in url for url in client.urls) == 1


def test_f1_weather_outage_keeps_timing_and_reports_unavailable_conditions() -> None:
    client = CapturedTiming()
    weather_url = next(url for url in client.values if "open-meteo.com" in url)
    del client.values[weather_url]
    result = RacingProvider(LiveRacingSource(client, now=lambda: _NOW)).fetch(_SETTINGS)
    assert result.health.healthy, result.health.error
    game = result.content[0].data
    assert game["f1"]["drivers"][1]["gap"] == "+0.207"
    assert game["f1"]["weather"]["available"] is False
    assert game["f1"]["weather"]["error"]
