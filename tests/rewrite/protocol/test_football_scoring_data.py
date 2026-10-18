"""Replay captured scoring ledgers through football alerts and the V2 response."""
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from sports_ticker.domain import ContentItem, DisplaySettings, TickerSnapshot
from sports_ticker.projections import project_data_v2
from sports_ticker.providers.espn import _event_scoring_details
from sports_ticker.providers.score_alerts import ScoreAlertTracker
from ticker_core.protocol import TickerResponse

pytestmark = pytest.mark.critical
CAPTURE = Path(__file__).parents[1] / "debug/football_scoring_capture.json"


def captured(league):
    record = next(row for row in json.loads(CAPTURE.read_text(encoding="utf-8"))["records"] if row["league"] == league)
    teams = {row["homeAway"]: row["team"]["abbreviation"] for row in record["payload"]["header"]["competitions"][0]["competitors"]}
    game = {"id": league, "kind": "scoreboard", "sport": league, "state": "in", "status": "Q4 0:01",
            "home_abbr": teams["home"], "away_abbr": teams["away"], "home_score": 0, "away_score": 0}
    return game, _event_scoring_details(record["payload"], game)["scoring_plays"]


def test_captured_fcs_singular_yards_and_kickoff_return_use_the_scoring_player():
    record = json.loads(CAPTURE.with_name("fcs_scoring_capture.json").read_text(encoding="utf-8"))
    teams = {row["homeAway"]: row["team"]["abbreviation"] for row in record["payload"]["header"]["competitions"][0]["competitors"]}
    game = {"id": "live-fcs", "kind": "scoreboard", "sport": "ncf_fcs", "state": "in", "status": "Q3 7:14",
            "home_abbr": teams["home"], "away_abbr": teams["away"], "home_score": 0, "away_score": 0}
    plays = _event_scoring_details(record["payload"], game)["scoring_plays"]
    expected = [("Tanner Schmidt", 22), ("Jalen Washington", 1), ("Miequle Brock", 92),
                ("Que Tillman", 1), ("Danny Joiner", 13), ("Tanner Schmidt", 1), ("Ty Durham", 10)]
    assert [(play["scorer_full"], play["yards"]) for play in plays] == expected
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    tracker.ingest([game])
    for play in plays:
        tracker.ingest([{**game, "home_score": play["home_score"], "away_score": play["away_score"],
                         "situation": {"scoring_plays": plays}}])
    alerts = tracker.recent()
    assert [alert["player"] for alert in alerts] == [name for name, yards in expected]
    assert alerts[2]["kind"] == "kick_return_td" and alerts[2]["data"] == "92YD"
    assert alerts[2]["down_distance"] == "" and alerts[2]["is_red_zone"] is None


@pytest.mark.parametrize("league,expected", [
    ("nfl", [
        ("FIELD GOAL", "Jason Myers", "55YD FIELD GOAL", "Q1 6:31", "4&5", False),
        ("RUSH TD", "J.K. Dobbins", "RUSH 4YD", "Q2 12:52", "2&GOAL", True),
        ("RUSH TD", "RJ Harvey", "RUSH 1YD", "Q2 5:15", "1&GOAL", True),
        ("RUSH TD +2PT", "George Holani", "RUSH 1YD", "Q4 5:41", "1&GOAL", True),
        ("FIELD GOAL", "Jason Myers", "34YD FIELD GOAL", "Q4 0:03", "3&3", True),
        ("FIELD GOAL", "Wil Lutz", "53YD FIELD GOAL", "OT 4:53", "4&2", False),
    ]),
    ("ncf_fbs", [
        ("RUSH TD", "Mark Fletcher Jr.", "RUSH 7YD", "Q1 7:32", "1&GOAL", True),
        ("PASS TD", "Desirrio Riles", "23YD PASS Ashton Daniels", "Q2 13:52", "1&10", False),
        ("PASS TD", "Malachi Toney", "14YD PASS Darian Mensah", "Q2 8:19", "3&4", True),
        ("RUSH TD", "Ashton Daniels", "RUSH 2YD", "Q2 1:40", "1&GOAL", True),
    ]),
])
def test_captured_football_scores_keep_their_player_clock_yardage_and_drive(league, expected):
    game, plays = captured(league)
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    tracker.ingest([game])
    for index, (play, values) in enumerate(zip(plays, expected, strict=True)):
        game = {**game, "home_score": play["home_score"], "away_score": play["away_score"],
                "state": "post" if league == "nfl" and index == len(plays) - 1 else "in",
                "situation": {"scoring_plays": plays, "downDist": "4TH & 99", "isRedZone": False}}
        tracker.ingest([game])
        tracker.ingest([game])
        assert len(tracker.recent()) == index + 1
        alert = tracker.recent()[-1]
        assert tuple(alert[key] for key in ("headline", "player", "data", "status", "down_distance", "is_red_zone")) == values
        assert alert["scoring_play_id"] == play["play_id"]
        assert alert["home_score"] == play["home_score"] and alert["away_score"] == play["away_score"]
    snapshot = TickerSnapshot("football", 1, datetime(2026, 10, 17, tzinfo=timezone.utc),
                             (ContentItem(game["id"], "sports", "scoreboard", True, game),), tracker.recent(), (), DisplaySettings())
    response = TickerResponse.from_payload(project_data_v2(snapshot, {}, {}))
    assert len(response.alerts) == len(expected)
    assert response.alerts[-1].data["player"] == expected[-1][1]


@pytest.mark.parametrize("state", ["in", "post"])
def test_late_final_football_detail_hydrates_once_without_next_drive_facts(state):
    game, plays = captured("nfl")
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    tracker.ingest([{**game, "home_score": 14, "away_score": 14}])
    scored = {**game, "state": state, "home_score": 17, "away_score": 14,
              "situation": {"scoring_plays": plays[:-1], "downDist": "1ST & 10", "isRedZone": True,
                            "football_plays": [{"football_kind": "interception", "is_scoring": True,
                                                "team": "DEN", "scorer_full": "OLD RETURNER"}]}}
    tracker.ingest([scored])
    first = tracker.recent()[0]
    assert first["headline"] == "FIELD GOAL" and first["player"] == "" and first["data"] == ""
    assert first["down_distance"] == "" and first["is_red_zone"] is None
    scored["situation"]["scoring_plays"] = plays
    tracker.ingest([scored])
    tracker.ingest([scored])
    final = tracker.recent()[0]
    assert len(tracker.recent()) == 1
    assert final["id"] == first["id"] and final["ts"] == first["ts"]
    assert final["player"] == "Wil Lutz" and final["data"] == "53YD FIELD GOAL"
    assert final["status"] == "OT 4:53" and final["down_distance"] == "4&2"
    assert final["is_red_zone"] is False


@pytest.mark.parametrize("old,new,conversion,expected_kind,expected_player", [
    (0, 6, "extra_point", "passing_td", "RECEIVER"),
    (0, 7, "extra_point", "passing_td", "RECEIVER"),
    (6, 7, "extra_point", "extra_point", "KICKER"),
    (0, 8, "two_point", "passing_td", "RECEIVER"),
    (6, 8, "two_point", "two_point", "CONVERTER"),
])
def test_grouped_touchdown_and_conversion_keep_the_correct_scoring_player(old, new, conversion, expected_kind, expected_player):
    game = {"id": "game", "kind": "scoreboard", "sport": "nfl", "state": "in",
            "home_abbr": "HOM", "away_abbr": "AWY", "home_score": old, "away_score": 0}
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    tracker.ingest([game])
    play = {"play_id": "touchdown", "team": "HOM", "type": "Touchdown", "event_type": "Passing Touchdown",
            "scorer_full": "RECEIVER", "conversion_type": conversion,
            "conversion_player_full": "KICKER" if conversion == "extra_point" else "CONVERTER",
            "home_score": 7 if conversion == "extra_point" else 8, "away_score": 0}
    tracker.ingest([{**game, "home_score": new, "situation": {"scoring_plays": [play]}}])
    alert = tracker.recent()[0]
    assert alert["kind"] == expected_kind and alert["player"] == expected_player


@pytest.mark.parametrize("sport", ["nfl", "mlb", "nhl", "soccer_epl"])
def test_final_score_transition_alerts_once_and_score_corrections_do_not_replay(sport):
    game = {"id": "game", "kind": "scoreboard", "sport": sport, "state": "in",
            "home_abbr": "HOM", "away_abbr": "AWY", "home_score": 1, "away_score": 1}
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    tracker.ingest([game])
    final = {**game, "state": "post", "home_score": 2}
    tracker.ingest([final])
    tracker.ingest([final])
    assert len(tracker.recent()) == 1
    tracker.ingest([game])
    tracker.ingest([final])
    assert len(tracker.recent()) == 1


@pytest.mark.parametrize("text,accepted", [
    ("Runner 4 Yd Rush (Kick failed)", True),
    ("Runner 4 Yd Rush (No Play)", False),
    ("Touchdown overturned after review", False),
    ("Kicker 42 Yd Field Goal missed", False),
    ("Two-point conversion failed", False),
])
def test_failed_or_reversed_play_cannot_supply_scoring_detail(text, accepted):
    game, _plays = captured("nfl")
    payload = {"scoringPlays": [{"id": "candidate", "team": {"abbreviation": game["home_abbr"]},
                                "text": text, "homeScore": 6, "awayScore": 0}],
               "header": {"competitions": [{"competitors": []}]}}
    assert bool(_event_scoring_details(payload, game).get("scoring_plays")) is accepted


def test_unknown_two_point_score_does_not_invent_a_safety():
    game, _plays = captured("nfl")
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    tracker.ingest([game])
    tracker.ingest([{**game, "home_score": 2}])
    assert tracker.recent()[0]["kind"] == "score"
    assert tracker.recent()[0]["headline"] == "+2 POINTS"
