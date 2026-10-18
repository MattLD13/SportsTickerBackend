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
        "situation": {"scoring_plays": [{
            "team": "NYR", "scorer": "Panarin", "strength": "PPG",
            "assists": ["Fox", "Zibanejad"], "home_score": 2, "away_score": 1,
        }]},
    }
    tracker.ingest([game_nhl_p2])
    nhl_alerts = tracker.recent()
    assert len(nhl_alerts) == 1
    assert nhl_alerts[0]["team_abbr"] == "NYR"
    assert nhl_alerts[0]["headline"] == "POWER PLAY GOAL"
    assert nhl_alerts[0]["player"] == "Panarin"
    assert nhl_alerts[0]["primary_assist"] == "Fox"
    assert nhl_alerts[0]["secondary_assist"] == "Zibanejad"

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
    assert soc_alert["player"] == "Saka"
    assert soc_alert["data"] == "38' HEADER"

    # 3. Generic ESPN scoring play detail, including baseball.
    game_mlb_p1 = {
        "kind": "scoreboard", "id": "mlb-1", "sport": "mlb", "state": "in", "status": "Mid 7th",
        "home_abbr": "BOS", "away_abbr": "NYY", "home_score": 2, "away_score": 2,
    }
    tracker.ingest([game_mlb_p1])
    game_mlb_p2 = {
        **game_mlb_p1,
        "away_score": 3,
        "situation": {"scoring_plays": [{"team": "NYY", "scorer": "Judge", "type": "HOME RUN"}]},
    }
    tracker.ingest([game_mlb_p2])
    mlb_alert = next(a for a in tracker.recent() if a["sport"] == "mlb")
    assert mlb_alert["player"] == "Judge"


def test_hockey_score_alert_hydrates_when_summary_detail_arrives_after_score() -> None:
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    baseline = {
        "kind": "scoreboard",
        "id": "nhl-late-detail",
        "sport": "nhl",
        "state": "in",
        "status": "P2 10:00",
        "home_abbr": "NYR",
        "away_abbr": "BOS",
        "home_score": 0,
        "away_score": 0,
    }
    tracker.ingest([baseline])
    tracker.ingest([{**baseline, "home_score": 1, "status": "P2 09:42"}])
    assert tracker.recent()[0]["player"] == ""

    tracker.ingest([{
        **baseline,
        "home_score": 1,
        "status": "P2 09:35",
        "situation": {
            "scoring_plays": [{
                "team": "NYR",
                "scorer": "RADDYSH",
                "type": "Goal",
                "strength": "even-strength",
                "assists": ["SMITS"],
                "home_score": 1,
                "away_score": 0,
            }],
        },
    }])

    alert = tracker.recent()[0]
    assert alert["headline"] == "GOAL"
    assert alert["player"] == "RADDYSH"
    assert alert["primary_assist"] == "SMITS"


def test_hockey_goal_alerts_match_each_goal_and_hydrate_assists() -> None:
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    baseline = {
        "kind": "scoreboard", "id": "nhl-goal-order", "sport": "nhl", "state": "in",
        "home_abbr": "NYR", "away_abbr": "BOS", "home_score": 0, "away_score": 0,
    }
    first_goal = {
        "team": "NYR", "scorer": "FIRST", "play_id": "goal-1",
        "home_score": 1, "away_score": 0,
    }
    tracker.ingest([baseline])
    tracker.ingest([{
        **baseline,
        "home_score": 1,
        "situation": {"scoring_plays": [first_goal]},
    }])
    assert tracker.recent()[0]["player"] == "FIRST"

    tracker.ingest([{
        **baseline,
        "home_score": 2,
        "situation": {"scoring_plays": [first_goal]},
    }])
    alerts = tracker.recent()
    assert len(alerts) == 2
    assert alerts[1]["player"] == ""

    first_goal_with_assists = {
        **first_goal,
        "assists": ["HELPERONE", "HELPERTWO"],
    }
    second_goal = {
        "team": "NYR", "scorer": "SECOND", "play_id": "goal-2",
        "assists": ["PASSERONE", "PASSERTWO"],
        "home_score": 2, "away_score": 0,
    }
    tracker.ingest([{
        **baseline,
        "home_score": 2,
        "situation": {"scoring_plays": [first_goal_with_assists, second_goal]},
    }])

    first_alert, second_alert = tracker.recent()
    assert first_alert["player"] == "FIRST"
    assert first_alert["primary_assist"] == "HELPERONE"
    assert first_alert["secondary_assist"] == "HELPERTWO"
    assert second_alert["player"] == "SECOND"
    assert second_alert["primary_assist"] == "PASSERONE"
    assert second_alert["secondary_assist"] == "PASSERTWO"
    assert first_alert["scoring_play_id"] == "goal-1"
    assert second_alert["scoring_play_id"] == "goal-2"


def test_football_score_alert_uses_the_scoring_play() -> None:
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    baseline = {
        "kind": "scoreboard", "id": "nfl-detail", "sport": "nfl", "state": "in",
        "home_abbr": "NYG", "away_abbr": "DAL", "home_score": 0, "away_score": 0,
    }
    tracker.ingest([baseline])
    tracker.ingest([{
        **baseline,
        "home_score": 7,
        "situation": {"scoring_plays": [{
            "team": "NYG", "scorer": "WILLIAMS", "type": "Touchdown",
            "event_type": "Rushing Touchdown", "text": "Williams 1 Yd Rush",
            "yards": 1, "home_score": 7, "away_score": 0,
        }]},
    }])

    alert = tracker.recent()[0]
    assert alert["headline"] == "RUSH TD"
    assert alert["player"] == "WILLIAMS"
    assert alert["data"] == "RUSH 1YD"


def test_football_turnover_alerts_include_player_context_and_deduplicate() -> None:
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    baseline = {
        "kind": "scoreboard", "id": "nfl-turnovers", "sport": "nfl", "state": "in",
        "home_abbr": "NYG", "away_abbr": "DAL", "home_score": 7, "away_score": 7,
        "situation": {"football_plays": []},
    }
    tracker.ingest([baseline])
    current = {
        **baseline,
        "situation": {"football_plays": [
            {
                "event_id": "pick-1", "football_kind": "interception", "team": "NYG",
                "scorer": "THOMAS", "interceptor": "THOMAS", "passer": "PRESCOTT", "return_yards": 12,
                "is_scoring": False,
            },
            {
                "event_id": "fumble-1", "football_kind": "fumble", "team": "DAL",
                "scorer": "LAWRENCE", "fumbler": "LAMB", "recoverer": "LAWRENCE", "forced_by": "THOMAS",
                "is_scoring": False,
            },
        ]},
    }
    tracker.ingest([current])

    alerts = tracker.recent()
    assert len(alerts) == 2
    assert alerts[0]["headline"] == "INTERCEPTION"
    assert alerts[0]["player"] == "THOMAS"
    assert alerts[0]["data"] == "INTERCEPTION 12YD RET"
    assert alerts[0]["points"] == 0
    assert alerts[0]["event_id"] == "nfl-turnovers:football:pick-1"
    assert alerts[1]["headline"] == "FUMBLE"
    assert alerts[1]["player"] == "LAWRENCE"
    assert alerts[1]["data"] == "FUMBLE"
    assert alerts[1]["team_abbr"] == "DAL"
    assert len(
        alerts_for_settings(
            alerts,
            DisplaySettings(mode="sports", score_alerts=True, my_teams=("nfl:nyg",)),
        )
    ) == 2

    tracker.ingest([current])
    assert len(tracker.recent()) == 2


def test_football_pick_six_detail_uses_returner_and_quarterback() -> None:
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    baseline = {
        "kind": "scoreboard", "id": "nfl-pick-six", "sport": "nfl", "state": "in",
        "home_abbr": "NYG", "away_abbr": "DAL", "home_score": 0, "away_score": 0,
    }
    tracker.ingest([baseline])
    tracker.ingest([{
        **baseline,
        "home_score": 6,
        "situation": {"scoring_plays": [{
            "team": "NYG", "scorer": "THOMAS", "type": "Touchdown",
            "event_type": "Interception Return Touchdown", "football_kind": "interception",
            "home_score": 6, "away_score": 0,
            "scorer": "THOMAS", "interceptor": "THOMAS", "passer": "PRESCOTT", "return_yards": 12,
        }]},
    }])

    alert = tracker.recent()[0]
    assert alert["headline"] == "INTERCEPTION TD"
    assert alert["player"] == "THOMAS"
    assert alert["data"] == "INTERCEPTION 12YD RET"


def test_basketball_scores_never_create_alerts() -> None:
    sports = ("nba", "wnba", "ncb", "ncw", "march_madness", "mens_basketball")
    cases = (
        ("in", "Q3 04:00", 22, 18, "Jump Shot", 2),
        ("in", "Q4 08:33", 24, 18, "Jump Shot", 2),
        ("in", "Q4 00:30", 24, 25, "Three Point Jumper", 3),
        ("in", "Q4 00:10", 26, 25, "Dunk", 2),
        ("in", "OT 00:05", 26, 28, "Three Point Jumper", 3),
        ("post", "FINAL", 30, 28, "Dunk", 2),
        ("final", "FINAL", 30, 28, "Dunk", 2),
    )
    for sport in sports:
        tracker = ScoreAlertTracker(clock=lambda: 100.0)
        baseline = {
            "kind": "scoreboard", "id": f"{sport}-disabled", "sport": sport,
            "state": "in", "status": "Q3 04:00", "home_abbr": "CLE",
            "away_abbr": "NY", "home_score": 20, "away_score": 18,
        }
        tracker.ingest([baseline])
        for state, status, home, away, play_type, points in cases:
            tracker.ingest([{
                **baseline,
                "state": state, "status": status,
                "home_score": home, "away_score": away,
                "situation": {"scoring_plays": [{
                    "team": "CLE", "scorer": "MOBLEY", "type": play_type,
                    "score_value": points, "period": "4th",
                }]},
            }])
            assert tracker.recent() == (), (sport, state, status, play_type)


def test_mlb_score_alert_detail_shows_player_stats_and_last_pitch() -> None:
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    baseline = {
        "kind": "scoreboard", "id": "mlb-detail", "sport": "mlb", "state": "in",
        "home_abbr": "PIT", "away_abbr": "SF", "home_score": 4, "away_score": 0,
    }
    tracker.ingest([baseline])
    tracker.ingest([{
        **baseline,
        "away_score": 1,
        "situation": {
            "scoring_plays": [{
                "team": "SF", "scorer": "Lee", "type": "Double",
                "player_h": "2", "player_ab": "4", "player_avg": ".298",
            }],
            "last_pitch_speed": "96",
            "last_pitch_type": "Slider",
        },
    }])

    assert tracker.recent()[0]["player"] == "Lee"
    assert tracker.recent()[0]["data"] == "2/4 .298 96 Slider"


def test_mlb_home_run_detail_shows_statcast_metrics() -> None:
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    baseline = {
        "kind": "scoreboard", "id": "mlb-home-run-detail", "sport": "mlb", "state": "in",
        "home_abbr": "HOU", "away_abbr": "CWS", "home_score": 0, "away_score": 0,
    }
    tracker.ingest([baseline])
    tracker.ingest([{
        **baseline,
        "home_score": 2,
        "situation": {"scoring_plays": [{
            "team": "HOU", "scorer": "Altuve", "type": "Home Run",
            "home_run_distance": 353, "exit_velocity": 93.9, "launch_angle": 37,
        }]},
    }])

    alert = tracker.recent()[0]
    assert alert["headline"] == "2-RUN HOME RUN"
    assert alert["player"] == "Altuve"
    assert alert["data"] == "353FT 94EV 37LA"


def test_mlb_score_alert_does_not_infer_home_run_from_runs_scored() -> None:
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    tracker.ingest([
        {
            "kind": "scoreboard",
            "id": "mlb-single",
            "sport": "mlb",
            "state": "in",
            "home_abbr": "BOS",
            "away_abbr": "NYY",
            "home_score": 0,
            "away_score": 0,
        },
        {
            "kind": "scoreboard",
            "id": "mlb-sacrifice-fly",
            "sport": "mlb",
            "state": "in",
            "home_abbr": "BOS",
            "away_abbr": "NYY",
            "home_score": 0,
            "away_score": 0,
        },
    ])
    tracker.ingest([
        {
            "kind": "scoreboard",
            "id": "mlb-single",
            "sport": "mlb",
            "state": "in",
            "home_abbr": "BOS",
            "away_abbr": "NYY",
            "home_score": 0,
            "away_score": 2,
            "situation": {
                "scoring_plays": [{
                    "team": "NYY",
                    "type": "Single",
                    "score_value": 2,
                }],
            },
        },
        {
            "kind": "scoreboard",
            "id": "mlb-sacrifice-fly",
            "sport": "mlb",
            "state": "in",
            "home_abbr": "BOS",
            "away_abbr": "NYY",
            "home_score": 0,
            "away_score": 1,
            "situation": {
                "scoring_plays": [{
                    "team": "NYY",
                    "type": "Sacrifice Fly",
                    "score_value": 1,
                }],
            },
        },
    ])

    alerts = tracker.recent()
    assert [alert["headline"] for alert in alerts] == ["RBI SINGLE", "SAC FLY"]


def test_mlb_score_alert_distinguishes_scoring_play_results() -> None:
    cases = (
        ("single", {"type": "Single", "rbi": 1, "score_value": 1}, "RBI SINGLE"),
        ("double", {"type": "Double", "rbi": 1, "score_value": 1}, "RBI DOUBLE"),
        ("sac-fly", {"type": "Sacrifice Fly", "rbi": 1, "score_value": 1}, "SAC FLY"),
        ("walk-off", {"type": "Single", "rbi": 1, "score_value": 1, "walk_off": True}, "WALK OFF RBI SINGLE"),
        ("home-run", {"type": "Home Run", "score_value": 1}, "HOME RUN"),
        ("two-run-home-run", {"type": "Home Run", "score_value": 2}, "2-RUN HOME RUN"),
    )

    for game_id, play, expected in cases:
        tracker = ScoreAlertTracker(clock=lambda: 100.0)
        baseline = {
            "kind": "scoreboard",
            "id": f"mlb-{game_id}",
            "sport": "mlb",
            "state": "in",
            "home_abbr": "BOS",
            "away_abbr": "NYY",
            "home_score": 4 if game_id == "walk-off" else 0,
            "away_score": 4 if game_id == "walk-off" else 0,
        }
        tracker.ingest([baseline])
        updated = {
            **baseline,
            "home_score": 5 if game_id == "walk-off" else baseline["home_score"],
            "away_score": 1 if game_id != "walk-off" else baseline["away_score"],
            "situation": {"scoring_plays": [{"team": "BOS" if game_id == "walk-off" else "NYY", "scorer": "Judge", **play}]},
        }
        tracker.ingest([updated])

        assert tracker.recent()[0]["headline"] == expected


def test_mlb_score_alert_uses_verified_home_run_type() -> None:
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    baseline = {
        "kind": "scoreboard",
        "id": "mlb-home-run",
        "sport": "mlb",
        "state": "in",
        "home_abbr": "BOS",
        "away_abbr": "NYY",
        "home_score": 0,
        "away_score": 0,
    }
    tracker.ingest([baseline])
    tracker.ingest([
        {
            **baseline,
            "away_score": 2,
            "situation": {
                "scoring_plays": [{
                    "team": "NYY",
                    "type": "Home Run",
                    "score_value": 2,
                }],
            },
        }
    ])

    assert tracker.recent()[0]["headline"] == "2-RUN HOME RUN"


def test_score_alerts_filtering_and_team_matching() -> None:
    tracker = ScoreAlertTracker(clock=lambda: 300.0)

    tracker.ingest([
        {"kind": "scoreboard", "id": "g1", "sport": "nhl", "state": "in", "home_abbr": "NYR", "away_abbr": "BOS", "home_score": 0, "away_score": 0},
        {"kind": "scoreboard", "id": "nba-1", "sport": "nba", "state": "in", "home_abbr": "NYK", "away_abbr": "BOS", "home_score": 100, "away_score": 102},
        {"kind": "scoreboard", "id": "soc-1", "sport": "soccer_mls", "state": "in", "home_abbr": "SEA", "away_abbr": "VAN", "home_score": 0, "away_score": 0},
    ])
    tracker.ingest([
        {"kind": "scoreboard", "id": "g1", "sport": "nhl", "state": "in", "home_abbr": "NYR", "away_abbr": "BOS", "home_score": 1, "away_score": 0},
        {"kind": "scoreboard", "id": "nba-1", "sport": "nba", "state": "in", "home_abbr": "NYK", "away_abbr": "BOS", "home_score": 103, "away_score": 102},
        {"kind": "scoreboard", "id": "soc-1", "sport": "soccer_mls", "state": "in", "home_abbr": "SEA", "away_abbr": "VAN", "home_score": 1, "away_score": 0},
    ])
    raw_alerts = tracker.recent()
    assert len(raw_alerts) == 2

    # Followed NYR -> Included
    settings_followed = DisplaySettings(mode="sports", score_alerts=True, my_teams=("nhl:nyr", "nfl:dal"))
    assert len(alerts_for_settings(raw_alerts, settings_followed)) == 1

    # Followed only DAL -> Excluded
    settings_other = DisplaySettings(mode="sports", score_alerts=True, my_teams=("nfl:dal",))
    assert len(alerts_for_settings(raw_alerts, settings_other)) == 0

    # Score alerts disabled -> Excluded
    settings_disabled = DisplaySettings(mode="sports", score_alerts=False, my_teams=("nhl:nyr",))
    assert len(alerts_for_settings(raw_alerts, settings_disabled)) == 0

    # Basketball alerts stay disabled for followed teams.
    settings_nba_alias = DisplaySettings(mode="sports", score_alerts=True, my_teams=("nba:NY",))
    matched_nba = alerts_for_settings(raw_alerts, settings_nba_alias)
    assert matched_nba == ()

    # soccer_mls:SEA matches soccer_mls
    settings_mls = DisplaySettings(mode="sports", score_alerts=True, my_teams=("soccer_mls:SEA",))
    matched_mls = alerts_for_settings(raw_alerts, settings_mls)
    assert len(matched_mls) == 1
    assert matched_mls[0]["team_abbr"] == "SEA"


def test_cfb_score_alerts_follow_conference_filters() -> None:
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    tracker.ingest([
        {
            "kind": "scoreboard",
            "id": "cfb-1",
            "sport": "ncf_fbs",
            "state": "in",
            "home_abbr": "TCU",
            "away_abbr": "UNC",
            "home_score": 0,
            "away_score": 0,
            "home_conference_id": "4",
            "away_conference_id": "1",
        }
    ])
    tracker.ingest([
        {
            "kind": "scoreboard",
            "id": "cfb-1",
            "sport": "ncf_fbs",
            "state": "in",
            "home_abbr": "TCU",
            "away_abbr": "UNC",
            "home_score": 7,
            "away_score": 0,
            "home_conference_id": "4",
            "away_conference_id": "1",
        }
    ])
    alerts = tracker.recent()

    assert len(alerts_for_settings(
        alerts,
        DisplaySettings(
            my_teams=("ncf_fbs:TCU",),
            active_conferences={"ncf_fbs:4": False},
        ),
    )) == 1
    assert alerts_for_settings(
        alerts,
        DisplaySettings(
            my_teams=("ncf_fbs:TCU",),
            active_conferences={"ncf_fbs:4": False, "ncf_fbs:1": False},
        ),
    ) == ()
