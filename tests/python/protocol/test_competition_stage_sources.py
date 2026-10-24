"""Audit stage metadata through each supported sports provider boundary."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from sports_ticker.domain import DisplaySettings, TickerSnapshot
from sports_ticker.leagues import LEAGUES
from sports_ticker.projections import project_data_v2
from sports_ticker.projections.device_data import project_device_data
from sports_ticker.providers.fotmob import _content_item as soccer_item
from sports_ticker.providers.golf import GolfProvider
from sports_ticker.providers.live_sources import EspnGolfSource
from sports_ticker.providers.sports_display import project_sports_display
from sports_ticker.providers.racing import RacingProvider
from sports_ticker.providers.racing_live import LiveRacingSource
from ticker_core.protocol import TickerResponse


FIXTURES = Path(__file__).parents[2] / "fixtures/providers"
SOURCES = json.loads((FIXTURES / "competition_stage_sources.json").read_text(encoding="utf-8"))
REGULAR_SERIES = {"f1", "indycar", "imsa", "wec", "nbr24"}
pytestmark = pytest.mark.critical


class RecordedClient:
    def __init__(self, url, payload):
        self.url, self.payload = url, payload

    def get_json(self, url, *, timeout):
        assert url == self.url
        return deepcopy(self.payload)


def assert_stage_at_device_boundary(item, stage):
    assert type(item.data["competition_stage"]) is int
    assert item.data["competition_stage"] == stage
    snapshot = TickerSnapshot("audit", 1, datetime(2026, 10, 23, tzinfo=timezone.utc),
                              (item,), (), (), DisplaySettings())
    payload = project_data_v2(snapshot, {}, {})
    for mini in (False, True):
        parsed = TickerResponse.from_payload(project_device_data(payload, mini=mini))
        assert parsed.content[0].data["competition_stage"] == stage


@pytest.mark.parametrize("case", SOURCES["soccer"], ids=lambda case: case["name"])
def test_recorded_soccer_rounds_reach_the_device_contract(case):
    item = soccer_item(case["league"], case["match"], None, timezone_name="UTC")
    assert_stage_at_device_boundary(item, case["expected"])


@pytest.mark.parametrize("case", SOURCES["golf"], ids=lambda case: case["name"])
def test_recorded_pga_events_reach_the_device_contract(case):
    event = case["event"]
    now = datetime.fromisoformat(event["date"].replace("Z", "+00:00")) + timedelta(hours=12)
    client = RecordedClient("https://site.web.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard", {"events": [event]})
    provider = GolfProvider(EspnGolfSource(client=client, now=lambda: now))
    result = provider.fetch(DisplaySettings(timezone="UTC"))
    assert result.health.healthy, result.health.error
    assert len(result.content) == 1
    assert_stage_at_device_boundary(result.content[0], case["expected"])


@pytest.mark.parametrize("case", SOURCES["nascar"], ids=lambda case: case["name"])
def test_recorded_cup_schedule_metadata_reaches_the_device_contract(case):
    race = deepcopy(case["race"])
    start = datetime.fromisoformat(race["date_scheduled"]).replace(tzinfo=timezone.utc)
    now = start.replace(hour=0, minute=0, second=0)
    race["schedule"] = [{"run_type": 3, "start_time_utc": start.isoformat()}]

    class Client:
        def get_json(self, url, *, timeout):
            if url == case["source"]:
                return {"series_1": [race]}
            if "nascar-premier/scoreboard" in url:
                return {"events": [{"id": str(race["race_id"]), "name": race["race_name"],
                    "date": start.isoformat(), "competitions": [{"venue": {"fullName": race["track_name"]}}]}]}
            if "live-feed.json" in url:
                return {}
            raise AssertionError(url)

    settings = DisplaySettings(timezone="UTC", active_sports={**dict.fromkeys((league.id for league in LEAGUES), False), "nascar": True})
    result = RacingProvider(LiveRacingSource(client=Client(), now=lambda: now, clock=lambda: 1)).fetch(settings)
    assert result.health.healthy, result.health.error
    assert len(result.content) == 1
    assert_stage_at_device_boundary(result.content[0], case["expected"])


@pytest.mark.parametrize("sport", sorted(REGULAR_SERIES))
def test_nonplayoff_series_keep_stage_zero_at_the_projection(sport):
    for state, status in (("pre", "Qualifying"), ("in", "Final lap"), ("post", "FINAL")):
        assert project_sports_display({"sport": sport, "state": state, "status": status})["competition_stage"] == 0


def test_stage_audit_covers_every_supported_sport():
    rounds = json.loads((FIXTURES / "postseason_rounds.json").read_text(encoding="utf-8"))
    covered = {case["sport"] for case in rounds} | {case["league"] for case in SOURCES["soccer"]}
    covered |= REGULAR_SERIES | {"golf", "nascar"}
    assert {league.id for league in LEAGUES} <= covered
