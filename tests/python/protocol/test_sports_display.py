"""Verify shared ownership facts in the backend sports contract."""

import pytest

from sports_ticker.domain import ContentItem
from sports_ticker.providers.sports_display import SportsDisplayProjector, normalize_soccer_clock


def _event(detail: str, situation: dict, state: str = "in") -> dict:
    return {
        "status": {"type": {"state": state, "shortDetail": detail}, "period": 2},
        "competitions": [{"situation": situation, "competitors": [
            {"homeAway": "home", "team": {"id": "1", "abbreviation": "HOM"}},
            {"homeAway": "away", "team": {"id": "2", "abbreviation": "AWY"}},
        ]}],
    }


def _item(identifier: str, sport: str, state: str = "in") -> ContentItem:
    return ContentItem(identifier, "sports", "scoreboard", True, {
        "sport": sport, "state": state, "status": "", "home_abbr": "HOM", "away_abbr": "AWY",
    })


def test_active_team_belongs_to_the_backend_sports_contract() -> None:
    projector = SportsDisplayProjector()
    football = projector.project(_item("football", "nfl"), _event("2nd quarter", {"possession": "2"}))
    baseball_top = projector.project(_item("top", "mlb"), _event("Top 5th", {"balls": 3, "strikes": 1, "outs": 2}))
    baseball_bottom = projector.project(_item("bottom", "mlb"), _event("Bottom 5th", {"balls": 1, "strikes": 0, "outs": 0}))

    assert football.data["situation"]["activeTeam"] == "AWY"
    assert baseball_top.data["situation"]["activeTeam"] == "AWY"
    assert baseball_bottom.data["situation"]["activeTeam"] == "HOM"


def test_baseball_projects_live_player_names_from_scoreboard_situation() -> None:
    event = _event(
        "Top 5th",
        {
            "balls": 2,
            "strikes": 1,
            "outs": 1,
            "batter": {"athlete": {"displayName": "Aaron Judge"}},
            "pitcher": {"athlete": {"displayName": "Garrett Whitlock"}},
        },
    )

    baseball = SportsDisplayProjector().project(_item("baseball", "mlb"), event)

    assert baseball.data["situation"]["batter_name"] == "Aaron Judge"
    assert baseball.data["situation"]["pitcher_name"] == "Garrett Whitlock"


def test_baseball_projects_next_batter_when_between_innings() -> None:
    event = _event(
        "Mid 4th",
        {
            "balls": 0,
            "strikes": 0,
            "outs": 0,
            "dueUp": [{"athlete": {"displayName": "Vaughn Grissom"}}],
        },
    )

    baseball = SportsDisplayProjector().project(_item("baseball", "mlb"), event)

    assert baseball.data["situation"]["batter_name"] == "Vaughn Grissom"


def test_baseball_projects_scoreboard_batter_stats() -> None:
    event = _event(
        "Top 5th",
        {
            "balls": 1,
            "strikes": 2,
            "outs": 1,
            "batter": {
                "athlete": {"displayName": "Austin Wells"},
                "summary": "2-4, R",
            },
            "pitcher": {"athlete": {"displayName": "Garrett Acton"}},
        },
    )

    baseball = SportsDisplayProjector().project(_item("baseball", "mlb"), event)

    assert baseball.data["situation"]["batter_h"] == "2"
    assert baseball.data["situation"]["batter_ab"] == "4"


@pytest.mark.parametrize(
    ("possession", "yard_line", "expected"),
    (("2", 80, False), ("2", 20, True), ("1", 20, False), ("1", 80, True)),
)
def test_football_red_zone_only_marks_the_opponents_end_zone(
    possession: str, yard_line: int, expected: bool
) -> None:
    football = SportsDisplayProjector().project(
        _item("football", "nfl"),
        _event(
            "2nd quarter",
            {"possession": possession, "yardLine": yard_line, "isRedZone": True},
        ),
    )

    assert football.data["situation"]["isRedZone"] is expected


def test_college_football_projects_external_team_rankings() -> None:
    event = _event("2nd quarter", {})
    event["competitions"][0]["competitors"][0]["curatedRank"] = {"current": 12}
    event["competitions"][0]["competitors"][1]["curatedRank"] = {"current": 4}

    football = SportsDisplayProjector().project(
        _item("college", "ncf_fbs"),
        event,
        football_rankings={"1": "8", "2": "7"},
    )

    assert football.data["home_rank"] == "8"
    assert football.data["away_rank"] == "7"


def test_college_football_uses_external_ranking_when_scoreboard_has_no_rank() -> None:
    event = _event("2nd quarter", {})
    event["competitions"][0]["competitors"][0]["team"]["id"] = "2329"
    event["competitions"][0]["competitors"][0]["curatedRank"] = {"current": 99}

    football = SportsDisplayProjector().project(
        _item("college", "ncf_fcs"),
        event,
        football_rankings={"2329": "11"},
    )

    assert football.data["home_rank"] == "11"


def test_finished_game_has_no_live_play_context() -> None:
    ended = SportsDisplayProjector().project(
        _item("ended", "nfl", "post"),
        _event("FINAL", {"possession": "2", "down": 3, "distance": 4, "isRedZone": True}, "post"),
    )

    assert ended.data["situation"] == {}


@pytest.mark.parametrize("clock", ("0:00", "00:00", "0.0", "0", "0:00.0"))
def test_basketball_zero_clock_uses_period_end_label(clock: str) -> None:
    event = _event("1st quarter", {})
    event["status"].update({"period": 1, "displayClock": clock})

    basketball = SportsDisplayProjector().project(_item("basketball", "nba"), event)

    assert basketball.data["status"] == "Q1 END"


def test_basketball_numeric_zero_clock_uses_period_end_label() -> None:
    event = _event("1st quarter", {})
    event["status"].update({"period": 1, "clock": 0.0})

    basketball = SportsDisplayProjector().project(_item("basketball", "nba"), event)

    assert basketball.data["status"] == "Q1 END"


def test_college_basketball_zero_clock_keeps_half_label() -> None:
    event = _event("2nd half", {})
    event["status"].update({"period": 2, "displayClock": "0.0"})

    basketball = SportsDisplayProjector().project(
        _item("basketball", "march_madness"), event
    )

    assert basketball.data["status"] == "H2 END"


@pytest.mark.parametrize(
    ("sport", "period", "expected"),
    (
        ("nfl", 1, "Q1 END"),
        ("ncf_fbs", 4, "Q4 END"),
        ("nfl", 6, "OT2 END"),
        ("nba", 5, "OT END"),
        ("nba", 6, "OT2 END"),
        ("nba", 7, "OT3 END"),
        ("nhl", 3, "P3 END"),
        ("nhl", 4, "OT END"),
        ("nhl", 5, "OT2 END"),
        ("nhl", 6, "OT3 END"),
        ("march_madness", 3, "OT END"),
        ("march_madness", 4, "OT2 END"),
        ("march_madness", 5, "OT3 END"),
    ),
)
def test_timed_sports_zero_clock_uses_the_period_end_label(
    sport: str, period: int, expected: str
) -> None:
    event = _event("period", {})
    event["status"].update({"period": period, "displayClock": "0.0"})

    projected = SportsDisplayProjector().project(_item("end", sport), event)

    assert projected.data["status"] == expected


def test_zero_clock_does_not_create_period_end_for_countup_or_inning_sports() -> None:
    soccer_event = _event("1st half", {})
    soccer_event["status"].update({"period": 1, "displayClock": "0.0"})
    baseball_event = _event("Top 5th", {})
    baseball_event["status"].update({"period": 5, "displayClock": "0:00"})

    soccer = SportsDisplayProjector().project(
        _item("soccer", "soccer_epl"), soccer_event
    )
    baseball = SportsDisplayProjector().project(
        _item("baseball", "mlb"), baseball_event
    )

    assert "END" not in soccer.data["status"]
    assert baseball.data["status"] == "Top 5th"


@pytest.mark.parametrize(
    ("sport", "period", "expected"),
    (
        ("nfl", 5, "FINAL OT"),
        ("ncf_fbs", 6, "FINAL OT2"),
        ("nba", 7, "FINAL OT3"),
        ("march_madness", 3, "FINAL OT"),
        ("march_madness", 4, "FINAL OT2"),
        ("march_madness", 5, "FINAL OT3"),
        ("nhl", 4, "FINAL OT"),
        ("nhl", 5, "FINAL OT2"),
        ("nhl", 6, "FINAL OT3"),
    ),
)
def test_final_status_keeps_overtime_number(
    sport: str, period: int, expected: str
) -> None:
    event = _event("Final", {}, state="post")
    event["status"]["period"] = period

    projected = SportsDisplayProjector().project(_item("final", sport, "post"), event)

    assert projected.data["status"] == expected


@pytest.mark.parametrize(
    ("period", "detail", "clock", "expected"),
    (
        (4, "Overtime", "5:00", "OT 5:00"),
        (5, "2nd Overtime", "12:34", "OT2 12:34"),
        (6, "3rd Overtime", "17:02", "OT3 17:02"),
    ),
)
def test_hockey_overtime_period_labels_follow_provider_period(
    period: int, detail: str, clock: str, expected: str
) -> None:
    event = _event(detail, {})
    event["status"].update({"period": period, "displayClock": clock})

    hockey = SportsDisplayProjector().project(_item("hockey", "nhl"), event)

    assert hockey.data["status"] == expected


def test_hockey_period_end_uses_end_label() -> None:
    event = _event("End of 1st", {}, "in")
    event["status"]["period"] = 1
    event["status"]["displayClock"] = "0:00"

    hockey = SportsDisplayProjector().project(_item("hockey", "nhl"), event)

    assert hockey.data["status"] == "P1 END"


def test_hockey_shootout_uses_shootout_label_not_overtime_number() -> None:
    event = _event("2nd OT", {}, "in")
    event["status"]["period"] = 5
    event["status"]["displayClock"] = "0:00"
    event["competitions"][0]["situation"]["lastPlay"] = {
        "period": {"number": 5, "displayValue": "SO"},
    }

    hockey = SportsDisplayProjector().project(_item("hockey", "nhl"), event)

    assert hockey.data["status"] == "S/O"


def test_hockey_second_overtime_stays_overtime_without_shootout_marker() -> None:
    event = _event("2nd OT", {}, "in")
    event["status"]["period"] = 5
    event["status"]["displayClock"] = "0:00"

    hockey = SportsDisplayProjector().project(_item("hockey", "nhl"), event)

    assert hockey.data["status"] == "OT2 END"


def test_soccer_clock_has_one_apostrophe_without_provider_spacing() -> None:
    event = _event("93'", {}, "in")
    event["status"]["displayClock"] = "93\u200e\u200e'"

    soccer = SportsDisplayProjector().project(_item("soccer", "soccer_champ"), event)

    assert soccer.data["status"] == "90'+3'"


def test_soccer_clock_keeps_stoppage_minutes_and_seconds() -> None:
    """Keep the regulation minute and precise stoppage clock in one shared label."""
    cases = (
        ("45:00 + 1:12", "45'+1:12'"),
        ("45+1'", "45'+1'"),
        ("90:00 + 1:18", "90'+1:18'"),
        ("90+8'", "90'+8'"),
        ("98:00", "90'+8:00'"),
        ("98:15", "90'+8:15'"),
        ("98'", "90'+8'"),
        ("122:30", "120'+2:30'"),
        ("34'", "34'"),
        ("34:12", "34'"),
    )
    for provider_clock, expected in cases:
        assert normalize_soccer_clock(provider_clock) == expected


def test_soccer_clock_handles_first_half_stoppage_with_period() -> None:
    """Normalize elapsed minutes over 45 to added time when in first half."""

    assert normalize_soccer_clock("49:00", period=1) == "45'+4:00'"
    assert normalize_soccer_clock("49'", period=1) == "45'+4'"
    assert normalize_soccer_clock("49'", period=2) == "49'"
    assert normalize_soccer_clock("49'") == "49'"


def test_espn_soccer_first_half_stoppage_projection() -> None:
    event = {
        "status": {"type": {"state": "in", "shortDetail": "46'"}, "period": 1, "displayClock": "46:20"},
        "competitions": [{"situation": {}, "competitors": [
            {"homeAway": "home", "team": {"id": "1", "abbreviation": "HOM"}},
            {"homeAway": "away", "team": {"id": "2", "abbreviation": "AWY"}},
        ]}],
    }

    soccer = SportsDisplayProjector().project(_item("soccer", "soccer_epl"), event)
    assert soccer.data["status"] == "45'+1:20'"


def test_nhl_shootout_status_uses_explicit_shootout_marker() -> None:
    event = _event("Shootout", {})
    event["status"]["period"] = 5
    event["competitions"][0]["status"] = {
        "type": {"state": "in", "shortDetail": "Shootout"}
    }

    hockey = SportsDisplayProjector().project(_item("hockey-so", "nhl"), event)

    assert hockey.data["status"] == "S/O"


def test_nhl_second_overtime_is_not_mistaken_for_a_shootout() -> None:
    event = _event("2nd OT", {})
    event["status"]["period"] = 5
    event["status"]["type"]["state"] = "in"

    hockey = SportsDisplayProjector().project(_item("hockey-ot2", "nhl"), event)

    assert hockey.data["status"] == "OT2"


def test_nhl_manpower_projects_counts_and_hides_unneeded_labels() -> None:
    cases = (
        ("regulation", "1551", False, False, "even_strength", "", "", ""),
        ("overtime", "1331", False, False, "even_strength", "", "", ""),
        ("overtime", "1441", False, False, "even_strength", "", "", ""),
        ("overtime", "1551", False, False, "even_strength", "", "", ""),
        ("regulation", "1441", False, False, "reduced_strength", "4v4", "", ""),
        ("regulation", "1331", False, False, "reduced_strength", "3v3", "", ""),
        ("regulation", "1451", False, True, "power_play", "4v5", "HOM", ""),
        ("regulation", "1531", True, False, "power_play", "5v3", "AWY", ""),
        ("overtime", "1431", True, False, "power_play", "4v3", "AWY", ""),
        ("regulation", "0651", False, False, "empty_net", "6v5", "", "AWY"),
        ("regulation", "1560", False, False, "empty_net", "5v6", "", "HOM"),
        ("regulation", "0641", True, False, "empty_net", "6v4", "AWY", "AWY"),
        ("regulation", "0541", False, False, "empty_net", "5v4", "", "AWY"),
        ("regulation", "0660", False, False, "empty_net", "6v6", "", ""),
        ("regulation", "1541", False, False, "unequal_strength", "5v4", "", ""),
        ("regulation", "1991", True, False, "unavailable", "", "", ""),
        ("regulation", "bad", True, False, "unavailable", "", "", ""),
        ("shootout", "1331", True, False, "inactive", "", "", ""),
        ("intermission", "1541", True, False, "inactive", "", "", ""),
        ("unavailable", "1541", True, False, "unavailable", "", "", ""),
    )
    for phase, code, away_pp, home_pp, state, label, pp_team, en_team in cases:
        situation = SportsDisplayProjector().project(
            _item("hockey", "nhl"),
            _event("2nd period", {
                "phase": phase,
                "situationCode": code,
                "awayPowerPlay": away_pp,
                "homePowerPlay": home_pp,
                "powerPlay": True,
                "emptyNet": True,
                "homePenaltyBoxCount": 2,
                "awayPenaltyBoxCount": 2,
            }),
        ).data["situation"]
        assert situation["manpower"]["state"] == state, (phase, code)
        assert situation["manpower"]["label"] == label, (phase, code)
        assert situation["powerPlayTeam"] == pp_team
        assert situation["emptyNetSide"] == en_team
        assert situation["powerPlay"] == bool(pp_team)
        if state not in {"inactive", "unavailable"}:
            assert situation["manpower"]["awaySkaters"] == int(code[1])
            assert situation["manpower"]["homeSkaters"] == int(code[2])



@pytest.mark.critical
@pytest.mark.parametrize("league", ["ncf_fbs", "ncf_fcs"])
@pytest.mark.parametrize("period,expected", [(5, "OT"), (6, "OT2"), (8, "OT4")])
def test_college_overtime_is_active_without_a_game_clock(league, period, expected) -> None:
    event = _event("OT", {}, "in")
    event["status"].update(period=period, displayClock="0:00")
    assert SportsDisplayProjector().project(_item("college-ot", league), event).data["status"] == expected


@pytest.mark.critical
def test_captured_ecu_uab_overtime_stays_active() -> None:
    from pathlib import Path
    import json
    record = json.loads((Path(__file__).parents[2] / "fixtures/display/fbs_untimed_overtime.json").read_text())
    game = SportsDisplayProjector().project(_item(record["event_id"], "ncf_fbs"), record["event"])
    assert record["event"]["status"]["type"]["state"] == "in"
    assert game.data["status"] == "OT"


@pytest.mark.critical
@pytest.mark.parametrize("league", ["ncf_fbs", "ncf_fcs"])
def test_college_overtime_uses_final_only_after_provider_completion(league) -> None:
    event = _event("Final/2OT", {}, "post")
    event["status"].update(period=6, displayClock="0:00")
    assert SportsDisplayProjector().project(_item("college-final", league), event).data["status"] == "FINAL OT2"
