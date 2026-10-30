"""Keep shared sports lifecycle facts consistent across both device projections."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from ticker.shared.domain import ContentItem, DisplaySettings, TickerSnapshot
from ticker.server.projections import project_data_v2
from ticker.server.projections.device_data import project_device_data
from ticker.shared.sports_display import SportsDisplayProjector

pytestmark = pytest.mark.critical


@pytest.mark.parametrize("sport,state,status,phase", [
    ("nfl", "in", "Q1 END", "period_break"),
    ("nfl", "in", "OT END", "period_break"),
    ("nfl", "in", "Halftime", "halftime"),
    ("ncf_fbs", "in", "OT", "playing"),
    ("ncf_fcs", "in", "OT3", "playing"),
    ("nba", "in", "Q4 END", "period_break"),
    ("nba", "in", "OT2 END", "period_break"),
    ("march_madness", "in", "H1 END", "period_break"),
    ("march_madness", "half", "Halftime", "halftime"),
    ("nhl", "in", "P3 END", "period_break"),
    ("nhl", "in", "OT3 END", "period_break"),
    ("nhl", "in", "S/O", "shootout"),
    ("nhl", "post", "FINAL S/O", "final"),
    ("soccer_epl", "in", "45+3'", "playing"),
    ("soccer_epl", "in", "90+8'", "playing"),
    ("soccer_fa_cup", "in", "ET 120+2'", "playing"),
    ("soccer_champions_league", "half", "Half", "halftime"),
    ("soccer_champ", "in", "PEN", "shootout"),
    ("soccer_mls", "post", "Final PEN", "final"),
    ("nfl", "in", "Weather Delay", "paused"),
    ("nhl", "post", "Cancelled", "paused"),
    ("nba", "pre", "Postponed", "paused"),
    ("f1", "in", "Lap 58/58", "playing"),
    ("indycar", "in", "RED", "playing"),
    ("imsa", "post", "FINAL", "final"),
    ("wec", "pre", "12:00 PM", "scheduled"),
    ("golf", "", "Round 4", "unavailable"),
])
def test_game_lifecycle_clears_only_live_context_for_both_devices(sport, state, status, phase):
    situation = {
        "activeTeam": "AWY", "possession": "AWY", "downDist": "3RD & 4", "isRedZone": True,
        "powerPlay": True, "powerPlayTeam": "AWY", "emptyNet": True, "emptyNetSide": "HOM",
        "manpower": {"phase": "regulation", "powerPlayLabel": "5v3"},
        "shootout": {"away": ["goal"], "home": ["miss"]},
        "red_cards": [{"is_home": True}], "goal_events": [{"player": "SCORER"}],
    }
    data = {"sport": sport, "state": state, "status": status,
            "home_abbr": "HOM", "away_abbr": "AWY", "home_score": "3", "away_score": "2", "situation": situation}
    original = deepcopy(data)
    family = "racing" if sport in {"f1", "indycar", "imsa", "wec"} else "golf" if sport == "golf" else "sports"
    item = ContentItem("game", family, "scoreboard", True, data)
    snapshot = TickerSnapshot("ticker", 1, datetime(2026, 10, 17, tzinfo=timezone.utc), (item,), (), (), DisplaySettings())
    payload = project_data_v2(snapshot, {}, {})
    projected = payload["content"][family][0]["data"]
    assert projected["game_phase"] == phase
    assert projected["state"] == state and projected["status"] == status
    assert projected["home_score"] == "3" and projected["away_score"] == "2"
    for mini in (False, True):
        facts = project_device_data(payload, mini=mini)["content"][family][0]["data"]["situation"]
        if phase != "playing":
            assert "activeTeam" not in facts and "downDist" not in facts and "isRedZone" not in facts
            if sport == "nhl":
                assert facts["powerPlay"] is False and facts["emptyNet"] is False
                assert facts["manpower"]["powerPlayLabel"] == ""
        else:
            assert facts["activeTeam"] == "AWY"
        if sport.startswith("soccer") and not mini:
            assert facts["red_cards"] == situation["red_cards"]
            assert facts["goal_events"] == situation["goal_events"]
    assert data == original


@pytest.mark.parametrize("change,retained", [
    ({}, True),
    ({"possession": "1"}, False),
    ({"period": 3}, False),
    ({"score": "10"}, False),
    ({"status": "Halftime"}, False),
    ({"clock": "0:00"}, False),
])
def test_football_cache_never_crosses_possession_period_score_or_break(change, retained):
    projector = SportsDisplayProjector()

    def project(situation, **updates):
        event = {"status": {"period": updates.get("period", 2), "displayClock": updates.get("clock", "4:20"),
                            "type": {"shortDetail": updates.get("status", "2nd quarter")}},
                 "competitions": [{"situation": situation, "competitors": [
                     {"homeAway": "home", "team": {"id": "1", "abbreviation": "HOM"}},
                     {"homeAway": "away", "team": {"id": "2", "abbreviation": "AWY"}},
                 ]}]}
        data = {"sport": "nfl", "state": "in", "home_abbr": "HOM", "away_abbr": "AWY",
                "home_score": updates.get("score", "7"), "away_score": "3"}
        return projector.project(ContentItem("game", "sports", "scoreboard", True, data), event)

    project({"possession": "2", "down": 3, "distance": 4, "yardLine": 10})
    result = project({"possession": change["possession"]} if "possession" in change else {}, **change)
    assert bool(result.data["situation"].get("downDist")) is retained


@pytest.mark.parametrize("sport,state,detail,period,clock,expected", [
    ("nba", "in", "End of 1st", 1, "0:01", "Q1 END"),
    ("march_madness", "in", "End of 1st Half", 1, "0:01", "H1 END"),
    ("nfl", "in", "End of 4th Quarter", 4, "0:01", "Q4 END"),
    ("nhl", "in", "Intermission", 2, "0:01", "P2 END"),
    ("nba", "post", "End of 4th", 4, "0:00", "FINAL"),
    ("nhl", "post", "End of 3rd", 3, "0:00", "FINAL"),
    ("ncf_fbs", "in", "Overtime", 7, "0:00", "OT3"),
    ("nba", "pre", "Postponed", 0, "0:00", "Postponed"),
    ("soccer_epl", "in", "Penalties", 5, "120:00", "PEN"),
    ("soccer_epl", "post", "Final/Pens", 5, "120:00", "FINAL PEN"),
    ("soccer_epl", "post", "Final", 4, "120:00", "FINAL AET"),
])
def test_authoritative_status_precedes_lagging_clock_and_final_precedes_period_end(sport, state, detail, period, clock, expected):
    item = ContentItem("game", "sports", "scoreboard", True, {"sport": sport, "state": state, "status": detail})
    event = {"status": {"type": {"shortDetail": detail}, "period": period, "displayClock": clock}, "competitions": []}
    assert SportsDisplayProjector().project(item, event).data["status"] == expected


def test_fotmob_penalty_phase_precedes_the_old_extra_time_clock():
    from ticker.server.providers.fotmob import _match_status
    match = {"status": {"reason": {"short": "Pen"}, "liveTime": {"short": "120:00", "long": "120:00"}}}
    assert _match_status(match, "in", "UTC") == "PEN"
