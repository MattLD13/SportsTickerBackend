"""Test score alert tracking, detail enrichment, and followed teams filtering."""

from sports_ticker.domain.models import DisplaySettings
from sports_ticker.providers.score_alerts import ScoreAlertTracker, alerts_for_settings


def test_score_alert_enrichment_details() -> None:
    tracker = ScoreAlertTracker(clock=lambda: 100.0)

    # 1. NHL goal with assists
    game_nhl_p1 = {"kind": "scoreboard", "id": "nhl-1", "sport": "nhl", "state": "in", "status": "P2 10:00", "home_abbr": "NYR", "away_abbr": "BOS", "home_score": 1, "away_score": 1}
    tracker.ingest([game_nhl_p1])
    assert tracker.recent() == ()

    game_nhl_p2 = {
        "kind": "scoreboard", "id": "nhl-1", "sport": "nhl", "state": "in", "status": "P2 08:30", "home_abbr": "NYR", "away_abbr": "BOS", "home_score": 2, "away_score": 1,
        "situation": {"scoring_plays": [{"team": "NYR", "scorer": "Panarin", "strength": "PPG", "assists": ["Fox", "Zibanejad"]}]},
    }
    tracker.ingest([game_nhl_p2])
    nhl_alerts = tracker.recent()
    assert len(nhl_alerts) == 1
    assert nhl_alerts[0]["team_abbr"] == "NYR"
    assert nhl_alerts[0]["headline"] == "GOAL"
    assert nhl_alerts[0]["detail"] == "PANARIN (FOX, ZIBANEJAD)"

    # 2. Soccer header goal
    game_soc_p1 = {"kind": "scoreboard", "id": "soc-1", "sport": "soccer_epl", "state": "in", "status": "35'", "home_abbr": "ARS", "away_abbr": "TOT", "home_score": 0, "away_score": 0}
    tracker.ingest([game_soc_p1])
    game_soc_p2 = {
        "kind": "scoreboard", "id": "soc-1", "sport": "soccer_epl", "state": "in", "status": "38'", "home_abbr": "ARS", "away_abbr": "TOT", "home_score": 1, "away_score": 0,
        "situation": {"goal_events": [{"is_home": True, "player": "Saka", "minute": "38'", "goal_type": "HEADER"}]},
    }
    tracker.ingest([game_soc_p2])
    soc_alerts = tracker.recent()
    soc_alert = next(a for a in soc_alerts if a["sport"] == "soccer_epl")
    assert soc_alert["detail"] == "SAKA 38' (HEADER)"


def test_score_alerts_filtering_and_team_matching() -> None:
    tracker = ScoreAlertTracker(clock=lambda: 300.0)

    tracker.ingest([
        {"kind": "scoreboard", "id": "g1", "sport": "nhl", "state": "in", "home_abbr": "NYR", "away_abbr": "BOS", "home_score": 0, "away_score": 0},
        {"kind": "scoreboard", "id": "nba-1", "sport": "nba", "state": "in", "home_abbr": "NYK", "away_abbr": "BOS", "home_score": 100, "away_score": 98},
        {"kind": "scoreboard", "id": "soc-1", "sport": "soccer_mls", "state": "in", "home_abbr": "SEA", "away_abbr": "VAN", "home_score": 0, "away_score": 0},
    ])
    tracker.ingest([
        {"kind": "scoreboard", "id": "g1", "sport": "nhl", "state": "in", "home_abbr": "NYR", "away_abbr": "BOS", "home_score": 1, "away_score": 0},
        {"kind": "scoreboard", "id": "nba-1", "sport": "nba", "state": "in", "home_abbr": "NYK", "away_abbr": "BOS", "home_score": 103, "away_score": 98},
        {"kind": "scoreboard", "id": "soc-1", "sport": "soccer_mls", "state": "in", "home_abbr": "SEA", "away_abbr": "VAN", "home_score": 1, "away_score": 0},
    ])
    raw_alerts = tracker.recent()
    assert len(raw_alerts) == 3

    # Followed NYR -> Included
    settings_followed = DisplaySettings(mode="sports", score_alerts=True, my_teams=("nhl:nyr", "nfl:dal"))
    assert len(alerts_for_settings(raw_alerts, settings_followed)) == 1

    # Followed only DAL -> Excluded
    settings_other = DisplaySettings(mode="sports", score_alerts=True, my_teams=("nfl:dal",))
    assert len(alerts_for_settings(raw_alerts, settings_other)) == 0

    # Score alerts disabled -> Excluded
    settings_disabled = DisplaySettings(mode="sports", score_alerts=False, my_teams=("nhl:nyr",))
    assert len(alerts_for_settings(raw_alerts, settings_disabled)) == 0

    # nba:NY matches NYK
    settings_nba_alias = DisplaySettings(mode="sports", score_alerts=True, my_teams=("nba:NY",))
    matched_nba = alerts_for_settings(raw_alerts, settings_nba_alias)
    assert len(matched_nba) == 1
    assert matched_nba[0]["team_abbr"] == "NYK"

    # soccer_mls:SEA matches soccer_mls
    settings_mls = DisplaySettings(mode="sports", score_alerts=True, my_teams=("soccer_mls:SEA",))
    matched_mls = alerts_for_settings(raw_alerts, settings_mls)
    assert len(matched_mls) == 1
    assert matched_mls[0]["team_abbr"] == "SEA"
