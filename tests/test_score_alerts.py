import time

import pytest

from sports_ticker.core import team_is_followed
from sports_ticker.services.score_alerts import (
    ScoreAlertTracker,
    describe_score,
    normalize_last_play,
)


def game(gid="1", sport="mlb", home=0, away=0, state="in", last_play=None, **extra):
    g = {
        "type": "scoreboard", "id": gid, "sport": sport, "state": state,
        "status": "BOT 7",
        "home_abbr": "NYY", "away_abbr": "BOS",
        "home_score": home, "away_score": away,
        "last_play": last_play or {},
    }
    g.update(extra)
    return g


# ── detection ────────────────────────────────────────────────────────────────

def test_first_sighting_never_alerts():
    tracker = ScoreAlertTracker()
    assert tracker.ingest([game(home=5)]) == []


def test_score_increase_emits_one_alert():
    tracker = ScoreAlertTracker()
    tracker.ingest([game(home=3)])
    alerts = tracker.ingest([game(home=4)])
    assert len(alerts) == 1
    assert alerts[0]["team_abbr"] == "NYY"
    assert alerts[0]["side"] == "home"
    assert alerts[0]["points"] == 1


def test_unchanged_and_decreasing_scores_are_silent():
    tracker = ScoreAlertTracker()
    tracker.ingest([game(home=4)])
    assert tracker.ingest([game(home=4)]) == []
    # A stat correction walking a run back is not a scoring play.
    assert tracker.ingest([game(home=3)]) == []


def test_finished_games_do_not_alert():
    tracker = ScoreAlertTracker()
    tracker.ingest([game(home=3, state="in")])
    assert tracker.ingest([game(home=4, state="post")]) == []


def test_alert_ids_are_stable_and_unique():
    tracker = ScoreAlertTracker()
    tracker.ingest([game(home=3)])
    first = tracker.ingest([game(home=4)])[0]
    second = tracker.ingest([game(home=5)])[0]
    assert first["id"] != second["id"]


def test_extra_point_after_touchdown_is_suppressed():
    tracker = ScoreAlertTracker()
    tracker.ingest([game(sport="nfl", home=7)])
    td = tracker.ingest([game(sport="nfl", home=13)])
    assert td[0]["headline"] == "TOUCHDOWN"
    assert tracker.ingest([game(sport="nfl", home=14)]) == []


def test_play_from_the_other_team_is_not_used_as_context():
    tracker = ScoreAlertTracker()
    tracker.ingest([game(home=3)])
    alerts = tracker.ingest([game(
        home=7,
        last_play={"text": "grand slam", "team": "BOS"},
    )])
    # BOS ran the last play; NYY scored. The prose must not be borrowed.
    assert alerts[0]["headline"] != "GRAND SLAM"


def test_stale_games_are_evicted():
    tracker = ScoreAlertTracker()
    tracker.ingest([game(gid="1"), game(gid="2")])
    tracker.ingest([game(gid="1")])
    assert set(tracker._scores) == {"1"}


def test_recent_filters_by_age():
    tracker = ScoreAlertTracker()
    tracker.ingest([game(home=3)])
    tracker.ingest([game(home=4)])
    assert len(tracker.recent(max_age=60)) == 1
    assert tracker.recent(max_age=0) == []


# ── live delay ───────────────────────────────────────────────────────────────

def _aged_tracker(age_seconds):
    """A tracker holding one alert raised ``age_seconds`` ago."""
    tracker = ScoreAlertTracker()
    tracker.ingest([game(home=3)])
    tracker.ingest([game(home=4)])
    tracker._alerts[0]['ts'] = time.time() - age_seconds
    return tracker


def test_delay_withholds_an_alert_until_the_content_catches_up():
    # Scored 10s ago on a board running 45s behind: the viewer's stream has not
    # reached the play yet, so announcing it would spoil it.
    assert _aged_tracker(10).recent(delay=45) == []


def test_delay_releases_the_alert_once_it_is_due():
    assert len(_aged_tracker(50).recent(delay=45)) == 1


def test_delayed_alerts_still_expire():
    # Released at ts+45, so at ts+200 it is 155s stale and long past showing.
    assert _aged_tracker(200).recent(max_age=45, delay=45) == []


def test_no_delay_is_unchanged():
    assert len(_aged_tracker(5).recent(delay=0)) == 1
    assert len(_aged_tracker(5).recent()) == 1


@pytest.mark.parametrize("bad", [None, "", -30])
def test_bad_delay_values_fall_back_to_live(bad):
    assert len(_aged_tracker(5).recent(delay=bad)) == 1


# ── description ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sport,delta,play,expected", [
    ("mlb", 4, {"text": "Aaron Judge homered to left"}, "GRAND SLAM"),
    ("mlb", 1, {"text": "Juan Soto homered to right"}, "SOLO HOMER"),
    ("mlb", 2, {"text": "Soto homered to right"}, "2-RUN HOMER"),
    ("mlb", 1, {"text": "sacrifice fly to center"}, "SAC FLY"),
    ("mlb", 1, {}, "RUN SCORES"),
    ("nfl", 6, {"type": "Rushing Touchdown"}, "RUSHING TD"),
    ("nfl", 6, {"type": "Passing Touchdown"}, "PASSING TD"),
    ("nfl", 6, {"type": "Interception Return Touchdown"}, "PICK SIX"),
    ("nfl", 3, {"type": "Field Goal Good"}, "FIELD GOAL"),
    ("nfl", 2, {"type": "Safety"}, "SAFETY"),
    ("nhl", 1, {"strength": "pp"}, "POWER PLAY GOAL"),
    ("nhl", 1, {"strength": "sh"}, "SHORTHANDED GOAL"),
    ("nhl", 1, {"modifier": "empty-net"}, "EMPTY NET GOAL"),
    ("nhl", 1, {"goals_to_date": 3}, "HAT TRICK"),
    ("nhl", 1, {}, "GOAL"),
    ("nba", 3, {}, "3-POINTER"),
    ("nba", 2, {"text": "makes dunk"}, "SLAM DUNK"),
    ("nba", 1, {}, "FREE THROW"),
    ("soccer_epl", 1, {"text": "Goal! Penalty converted"}, "PENALTY GOAL"),
    ("soccer_epl", 1, {}, "GOAL"),
])
def test_describe_score(sport, delta, play, expected):
    assert describe_score(sport, delta, play)[1] == expected


def test_grand_slam_needs_the_runs_to_agree():
    # "homered" alone with one run in is a solo shot, whatever the phrasing.
    assert describe_score("mlb", 1, {"text": "homered"})[1] == "SOLO HOMER"


def test_unknown_sport_falls_back_to_the_delta():
    assert describe_score("cricket", 4, {})[1] == "+4"


# ── last-play normalization ──────────────────────────────────────────────────

def test_normalize_last_play_resolves_the_team():
    play = normalize_last_play(
        {
            "text": "Judge homered",
            "type": {"text": "Home Run"},
            "team": {"id": "10"},
            "athletesInvolved": [{"shortName": "A. Judge"}],
        },
        home_abbr="NYY", away_abbr="BOS", home_id="10", away_id="2",
    )
    assert play["team"] == "NYY"
    assert play["type"] == "Home Run"
    assert play["athlete"] == "A. Judge"


def test_normalize_last_play_tolerates_junk():
    assert normalize_last_play(None) == {}
    assert normalize_last_play({})["text"] == ""


# ── followed-team matching ───────────────────────────────────────────────────

def test_team_is_followed():
    teams = {"mlb:NYY", "BOS", "LV"}
    assert team_is_followed(teams, "mlb", "NYY")
    assert not team_is_followed(teams, "nfl", "NYY")   # league-qualified
    assert team_is_followed(teams, "nfl", "BOS")       # bare abbr, unambiguous
    assert not team_is_followed(teams, "nfl", "LV")    # bare abbr, ambiguous
    assert not team_is_followed(teams, "mlb", "")
    assert not team_is_followed(set(), "mlb", "NYY")


# ── real ESPN play text ──────────────────────────────────────────────────────
# Every string below is copied from an ESPN MLB summary feed, not invented.
# ESPN writes the whole play as one sentence, so a clean hit and a runner who
# advanced on a throw appear in the same line. That is what broke the first
# version of the describer.

REAL_PLAYS = [
    # (runs, ESPN text, expected headline)
    (4, "Durbin homered to left center (401 feet), Rafaela scored, Contreras scored and Yoshida scored.", "GRAND SLAM"),
    (4, "Hicks homered to right (402 feet), Palacios scored, Walls scored and Aranda scored.", "GRAND SLAM"),
    (3, "Neto homered to center (411 feet), Meckler and Schanuel scored.", "3-RUN HOMER"),
    (2, "Serven homered to left center (391 feet), Butler scored.", "2-RUN HOMER"),
    (1, "Pozo homered to left center (397 feet).", "SOLO HOMER"),
    (1, "Schanuel hit sacrifice fly to right, Meckler scored, Trout to third.", "SAC FLY"),
    (1, "Mesa Jr. hit sacrifice bunt to first, Walls scored.", "SAC BUNT"),
    (2, "Soderstrom singled to center, Bolte and White scored, Heim to second.", "2-RUN SINGLE"),
    (2, "Martinez singled to center, DeLauter scored and Ramirez scored, Lowe to second.", "2-RUN SINGLE"),
    (1, "Suarez walked, McLain scored, Bleday to second, Stewart to third.", "WALKED IN"),

    # A hit plus a fielding error on the same play is still the hit.
    (1, "Dingler singled to right, Torres scored on throwing error by right fielder Ward, Dingler to second.", "RBI SINGLE"),
    (2, "C. Montgomery singled to center, Vargas scored on error and Grichuk scored on throwing error.", "2-RUN SINGLE"),
    (1, "Gilbert singled to right, Susac scored on fielding error by right fielder Nimmo.", "RBI SINGLE"),

    # The run itself is charged to the error here, so the error is the story.
    (1, "Crow-Armstrong scored on throwing error by catcher Valenzuela, Suzuki stole second.", "RUN ON ERROR"),

    # A runner who takes a base on a throw did not score on it.
    (1, "Baldwin grounded into fielder's choice to second, Thomas scored, Jarvis safe at second on fielding error.", "RUN SCORES"),

    # "double play" must not read as a double.
    (1, "Machado grounded into double play, shortstop to second to first, Tatis Jr. scored, Rengifo out at second.", "RUN SCORES"),
    (1, "Butler grounded into double play, second to shortstop to first, Heim scored, Muncy out at second.", "RUN SCORES"),
    (1, "Machado grounded out to shortstop, Cronenworth scored, Rengifo to second, Tatis Jr. to third.", "RUN SCORES"),
]


@pytest.mark.parametrize("runs,text,expected", REAL_PLAYS)
def test_describer_on_real_espn_play_text(runs, text, expected):
    assert describe_score('mlb', runs, {'text': text})[1] == expected
