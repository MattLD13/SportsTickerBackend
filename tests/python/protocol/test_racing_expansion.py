"""Exercise official racing snapshots through the provider and V2 boundaries."""

from collections import deque
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from sports_ticker.domain import DisplaySettings, TickerSnapshot
from sports_ticker.leagues import LEAGUE_BY_ID
from sports_ticker.projections.data_api import project_data_v2
from sports_ticker.providers.racing import RacingProvider
from sports_ticker.providers.racing_endurance import RacingImageCatalog
from sports_ticker.providers.racing_live import LiveRacingSource


pytestmark = pytest.mark.critical
ROOT = Path(__file__).resolve().parents[2] / "fixtures/providers/racing"
SERIES = ("f1", "indycar", "nascar", "wec", "imsa")


def settings(sport: str) -> DisplaySettings:
    return DisplaySettings(active_sports={name: name == sport for name in SERIES}, timezone="America/New_York")


class JsonResponses:
    def __init__(self, filename):
        self.values = json.loads((ROOT / filename).read_text(encoding="utf-8"))
        self.urls = []

    def get_json(self, url, *, timeout):
        self.urls.append(url)
        return self.values[url]


class NoWeather:
    def fetch(self, *args):
        return {"available": False}


class ImsaSocket:
    """Replay public documents through the official DDP subscriptions."""

    def __init__(self):
        self.documents = json.loads((ROOT / "imsa-petit-lemans-2026.json").read_text(encoding="utf-8"))
        self.pending = deque()
        self.sent = []
        self.closed = False

    def send(self, value):
        message = json.loads(value)
        self.sent.append(message)
        if message["msg"] == "connect":
            self.pending.append({"msg": "connected"})
            self.pending.append({"msg": "ping", "id": "heartbeat"})
        if message["msg"] == "sub":
            collection = {
                "livetimingFeed": "feeds", "sessionInfo": "session_info", "entry": "session_entry",
                "sessionStatus": "session_status", "sessionClasses": "session_classes", "raceControl": "race_control",
            }.get(message["name"], message["name"])
            if collection in self.documents:
                self.pending.append({"msg": "added", "collection": collection, "id": collection,
                                     "fields": self.documents[collection]})
            self.pending.append({"msg": "ready", "subs": [message["id"]]})

    def recv(self):
        return json.dumps(self.pending.popleft())

    def close(self):
        self.closed = True


def source(client, now, socket=None):
    return LiveRacingSource(client, now=lambda: now, clock=lambda: now.timestamp(),
                            weather_source=NoWeather(),
                            **({"socket_factory": lambda *a, **kw: socket} if socket is not None else {}))


def projected(provider, sport, now):
    config = settings(sport)
    result = provider.fetch(config)
    assert result.health.healthy, result.health.error
    snapshot = TickerSnapshot("racing-six", 1, now, result.content, (), (), config)
    return project_data_v2(snapshot, result.health, {})["content"]["racing"]


def test_supported_racing_series_are_selectable():
    assert set(SERIES) <= LEAGUE_BY_ID.keys()


def test_removed_series_is_not_selectable_or_polled_from_a_saved_setting():
    assert "nbr24" not in LEAGUE_BY_ID

    class NoReads:
        def get_json(self, url, *, timeout):
            raise AssertionError("A removed series must not read a source")

    now = datetime(2026, 10, 23, tzinfo=timezone.utc)
    config = DisplaySettings(active_sports={**dict.fromkeys(SERIES, False), "nbr24": True})
    result = RacingProvider(source(NoReads(), now)).fetch(config)
    assert result.health.healthy
    assert not result.content


def test_cup_uses_the_race_specific_feed_and_retains_all_37_cars():
    now = datetime(2026, 10, 19, 1, tzinfo=timezone.utc)
    client = JsonResponses("cup-phoenix-2026.json")
    items = projected(RacingProvider(source(client, now)), "nascar", now)
    game = next(item["data"] for item in items if item["data"]["nascar"]["session_type"] == "Race")
    assert game["state"] == "post"
    drivers = game["nascar"]["drivers"]
    assert len(drivers) == 37
    assert (drivers[0]["car"], drivers[0]["name"]) == ("45", "Tyler Reddick")
    assert drivers[1]["gap"] == "+0.801s"
    assert len({d["car"] for d in drivers}) == 37
    assert all("/live-feed.json" not in url for url in client.urls)
    assert any("series_1/5633/live_feed.json" in url for url in client.urls)


@pytest.mark.parametrize("field,value", [("series_id", 3), ("race_id", 5689)])
def test_cup_rejects_another_series_or_race(field, value):
    now = datetime(2026, 10, 19, 1, tzinfo=timezone.utc)
    client = JsonResponses("cup-phoenix-2026.json")
    client.values["https://cf.nascar.com/live/feeds/series_1/5633/live_feed.json"][field] = value
    result = RacingProvider(source(client, now)).fetch(settings("nascar"))
    assert not result.health.healthy
    assert not result.content


def test_cup_results_expire_at_the_display_reset():
    now = datetime(2026, 10, 19, 8, tzinfo=timezone.utc)
    client = JsonResponses("cup-phoenix-2026.json")
    assert source(client, now).fetch(settings("nascar"))["content"] == []
    assert len(client.urls) == 1


def test_wec_retains_all_35_cars_with_class_positions_and_official_finish_gaps():
    now = datetime(2026, 10, 18, 16, 30, tzinfo=timezone.utc)
    client = JsonResponses("wec-barcelona-2026.json")
    items = projected(RacingProvider(source(client, now)), "wec", now)
    game = items[0]["data"]
    assert game["state"] == "post"
    assert game["wec"]["short_name"] == "WEC Barcelona"
    drivers = game["wec"]["drivers"]
    assert len(drivers) == 35
    assert [(d["car"], d["gap"]) for d in drivers[:3]] == [("8", "Leader"), ("7", "+0.583"), ("50", "+39.725")]
    assert {d["class"] for d in drivers} == {"HYPERCAR", "LMGT3"}
    assert sum(d["class_pos"] == 1 for d in drivers) == 2
    assert drivers[0]["car_illustration"]


def test_wec_rejects_wrong_session_identity():
    now = datetime(2026, 10, 18, 16, 30, tzinfo=timezone.utc)
    client = JsonResponses("wec-barcelona-2026.json")
    next(value for url, value in client.values.items() if url.endswith("/bootstrap"))["sessionInfo"]["sid"] = 1
    result = RacingProvider(source(client, now)).fetch(settings("wec"))
    assert not result.health.healthy
    assert not result.content


def test_wec_does_not_show_last_weekends_race():
    now = datetime(2026, 10, 23, 20, tzinfo=timezone.utc)
    client = JsonResponses("wec-barcelona-2026.json")
    assert source(client, now).fetch(settings("wec"))["content"] == []
    assert len(client.urls) == 1


def test_imsa_reads_ready_documents_and_retains_all_54_cars():
    now = datetime(2026, 10, 4, 3, tzinfo=timezone.utc)
    socket = ImsaSocket()
    items = projected(RacingProvider(source(JsonResponses("cup-phoenix-2026.json"), now, socket)), "imsa", now)
    game = items[0]["data"]
    assert game["state"] == "post"
    drivers = game["imsa"]["drivers"]
    assert len(drivers) == 54
    assert [(d["car"], d["gap"]) for d in drivers[:3]] == [("6", "Leader"), ("24", "+1.205"), ("40", "+8.630")]
    official = json.loads((ROOT / "imsa-official-finish-2026.json").read_text(encoding="utf-8"))
    assert [d["car"] for d in drivers] == [str(d["number"]) for d in official["classification"]]
    assert {d["class"] for d in drivers} == {"GTP", "LMP2", "GTDPRO", "GTD"}
    assert sum(d["class_pos"] == 1 for d in drivers) == 4
    assert socket.closed
    assert {"msg": "pong", "id": "heartbeat"} in socket.sent
    assert "sessionResults" not in [m.get("name") for m in socket.sent]


def test_imsa_does_not_reload_or_show_old_standings():
    now = datetime(2026, 10, 23, 20, tzinfo=timezone.utc)
    socket = ImsaSocket()
    result = source(JsonResponses("cup-phoenix-2026.json"), now, socket).fetch(settings("imsa"))
    assert result["content"] == []
    assert [m.get("name") for m in socket.sent if m["msg"] == "sub"] == ["livetimingFeed", "sessionInfo"]
    assert socket.closed


def test_car_catalog_preserves_leading_zero_identity_and_rejects_wrong_number():
    catalog = RacingImageCatalog()
    assert catalog.image("wec", "7", "HYPERCAR", 2026) != catalog.image("wec", "007", "HYPERCAR", 2026)
    assert catalog.image("imsa", "4", "GTDPRO", 2026) != catalog.image("imsa", "04", "GTD", 2026)
    catalog.entries["wec"]["hypercar"]["7"] = "https://example.com/car-wec-6-side.png"
    assert catalog.image("wec", "7", "HYPERCAR", 2026) == ""
    assert catalog.image("wec", "8", "HYPERCAR", 2027) == ""


def test_indycar_requires_the_correct_series_date_and_practice_number():
    now = datetime(2026, 8, 15, 15, tzinfo=timezone.utc)
    live = source(JsonResponses("cup-phoenix-2026.json"), now)
    heartbeat = {"Series": "I", "SessionType": "P", "SessionName": "Practice 2", "startTimeUTC": now.isoformat()}
    matches = live._indycar_timing_matches_session
    assert matches(heartbeat, "practice2", "Practice 2", now, now + timedelta(hours=1))
    assert not matches(heartbeat, "practice1", "Practice 1", now, now + timedelta(hours=1))
    assert not matches({**heartbeat, "Series": "L"}, "practice2", "Practice 2", now, now + timedelta(hours=1))
    assert not matches({**heartbeat, "startTimeUTC": (now - timedelta(days=7)).isoformat()}, "practice2", "Practice 2", now, now + timedelta(hours=1))


def test_current_indy_development_test_never_appears_as_indycar():
    now = datetime(2026, 10, 23, 20, tzinfo=timezone.utc)
    captured = json.loads((ROOT / "indy-other-series-2026.json").read_text(encoding="utf-8"))

    class CurrentIndy:
        def get_json(self, url, *, timeout):
            if "timingscoring-ris.json" in url:
                return captured
            raise ValueError("No scheduled IndyCar event")

    result = RacingProvider(source(CurrentIndy(), now)).fetch(settings("indycar"))
    assert result.health.healthy
    assert not result.content


def test_circuit_weather_rejects_a_street_and_keeps_wind_bearing():
    from sports_ticker.providers.racing_weather import CircuitWeatherSource

    class WeatherClient:
        def get_json(self, url, *, timeout):
            if "nominatim" in url:
                return [{"type": "residential", "lat": 47.068, "lon": 8.188},
                        {"type": "raceway", "lat": 34.146, "lon": -83.815}]
            assert "latitude=34.146" in url and "longitude=-83.815" in url
            return {"current": {"time": "2026-10-23T20:00", "temperature_2m": 74.2,
                                "wind_speed_10m": 11.3, "wind_direction_10m": 247}}

    weather = CircuitWeatherSource(WeatherClient()).fetch("ROAD ATLANTA")
    assert weather["available"]
    assert (weather["air_temp"], weather["wind_mph"], weather["wind_dir"]) == ("74", "11", "247")


def test_one_series_failure_does_not_freeze_a_healthy_series():
    class SplitSource:
        failed = False

        def fetch(self, config):
            sport = next(name for name in SERIES if config.active_sports[name])
            if sport == "wec" and self.failed:
                raise ValueError("WEC unavailable")
            return {"content": [{"id": sport, "sport": sport, "type": "racing", "state": "in",
                                 sport: {"drivers": [], "flag": "RED" if self.failed else "GREEN"}}]}

    split = SplitSource()
    provider = RacingProvider(split)
    config = DisplaySettings(active_sports={**dict.fromkeys(SERIES, False), "f1": True, "wec": True})
    assert len(provider.fetch(config).content) == 2
    split.failed = True
    result = provider.fetch(config)
    assert result.health.healthy
    assert not result.health.diagnostic["series"]["wec"]["healthy"]
    by_kind = {item.kind: item.data for item in result.content}
    assert by_kind["f1"]["f1"]["flag"] == "RED"
    assert by_kind["wec"]["wec"]["flag"] == "GREEN"
