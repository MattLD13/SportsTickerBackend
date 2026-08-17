"""Test score alert tracking, detail enrichment, and followed teams filtering."""

from sports_ticker.domain.models import DisplaySettings
from sports_ticker.providers.score_alerts import ScoreAlertTracker, alerts_for_settings


def test_score_alert_nhl_assists_detail() -> None:
    now = 100.0
    tracker = ScoreAlertTracker(clock=lambda: now)

    game_p1 = {
        "kind": "scoreboard",
        "id": "nhl-1",
        "sport": "nhl",
        "state": "in",
        "status": "P2 10:00",
        "home_abbr": "NYR",
        "away_abbr": "BOS",
        "home_score": 1,
        "away_score": 1,
    }
    tracker.ingest([game_p1])
    assert tracker.recent() == ()

    # Score changes with scoring_plays in situation
    game_p2 = {
        "kind": "scoreboard",
        "id": "nhl-1",
        "sport": "nhl",
        "state": "in",
        "status": "P2 08:30",
        "home_abbr": "NYR",
        "away_abbr": "BOS",
        "home_score": 2,
        "away_score": 1,
        "situation": {
            "scoring_plays": [
                {
                    "team": "NYR",
                    "scorer": "Panarin",
                    "strength": "PPG",
                    "assists": ["Fox", "Zibanejad"],
                }
            ]
        },
    }
    tracker.ingest([game_p2])
    alerts = tracker.recent()
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["team_abbr"] == "NYR"
    assert alert["headline"] == "GOAL"
    assert alert["detail"] == "PANARIN (FOX, ZIBANEJAD)"


def test_score_alert_soccer_goal_types_detail() -> None:
    now = 200.0
    tracker = ScoreAlertTracker(clock=lambda: now)

    game_p1 = {
        "kind": "scoreboard",
        "id": "soc-1",
        "sport": "soccer_epl",
        "state": "in",
        "status": "35'",
        "home_abbr": "ARS",
        "away_abbr": "TOT",
        "home_score": 0,
        "away_score": 0,
    }
    tracker.ingest([game_p1])

    # Header goal
    game_p2 = {
        "kind": "scoreboard",
        "id": "soc-1",
        "sport": "soccer_epl",
        "state": "in",
        "status": "38'",
        "home_abbr": "ARS",
        "away_abbr": "TOT",
        "home_score": 1,
        "away_score": 0,
        "situation": {
            "goal_events": [
                {
                    "is_home": True,
                    "player": "Saka",
                    "minute": "38'",
                    "goal_type": "HEADER",
                }
            ]
        },
    }
    tracker.ingest([game_p2])
    alerts = tracker.recent()
    assert len(alerts) == 1
    assert alerts[0]["detail"] == "SAKA 38' (HEADER)"


def test_score_alerts_filtering_for_followed_teams() -> None:
    now = 300.0
    tracker = ScoreAlertTracker(clock=lambda: now)

    tracker.ingest([
        {
            "kind": "scoreboard", "id": "g1", "sport": "nhl", "state": "in",
            "home_abbr": "NYR", "away_abbr": "BOS", "home_score": 0, "away_score": 0,
        }
    ])
    tracker.ingest([
        {
            "kind": "scoreboard", "id": "g1", "sport": "nhl", "state": "in",
            "home_abbr": "NYR", "away_abbr": "BOS", "home_score": 1, "away_score": 0,
        }
    ])
    raw_alerts = tracker.recent()
    assert len(raw_alerts) == 1

    # Followed NYR -> Included
    settings_followed = DisplaySettings(mode="sports", score_alerts=True, my_teams=("nhl:nyr", "nfl:dal"))
    assert len(alerts_for_settings(raw_alerts, settings_followed)) == 1

    # Followed only DAL -> Excluded
    settings_other = DisplaySettings(mode="sports", score_alerts=True, my_teams=("nfl:dal",))
    assert len(alerts_for_settings(raw_alerts, settings_other)) == 0

    # Score alerts disabled -> Excluded
    settings_disabled = DisplaySettings(mode="sports", score_alerts=False, my_teams=("nhl:nyr",))
    assert len(alerts_for_settings(raw_alerts, settings_disabled)) == 0
