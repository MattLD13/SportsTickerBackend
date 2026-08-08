import time

from sports_ticker.core import team_is_followed
from sports_ticker.services.score_alerts import ScoreAlertTracker, describe_score


def game(gid="1", sport="mlb", home=0, away=0, state="in", last_play=None):
    return {
        "type": "scoreboard", "id": gid, "sport": sport, "state": state,
        "status": "BOT 7", "home_abbr": "NYY", "away_abbr": "BOS",
        "home_score": home, "away_score": away, "last_play": last_play or {},
    }


# ── detection ────────────────────────────────────────────────────────────────

def test_a_score_increase_emits_one_alert():
    t = ScoreAlertTracker()
    assert t.ingest([game(home=3)]) == []        # first sighting has no before
    alerts = t.ingest([game(home=4)])
    assert len(alerts) == 1
    assert alerts[0]["team_abbr"] == "NYY"


def test_nothing_fires_without_a_live_increase():
    t = ScoreAlertTracker()
    t.ingest([game(home=4)])
    assert t.ingest([game(home=4)]) == []                    # unchanged
    assert t.ingest([game(home=3)]) == []                    # corrected down
    t.ingest([game(home=3, state="in")])
    assert t.ingest([game(home=4, state="post")]) == []      # game over


def test_the_extra_point_after_a_touchdown_is_suppressed():
    t = ScoreAlertTracker()
    t.ingest([game(sport="nfl", home=7)])
    assert t.ingest([game(sport="nfl", home=13)])[0]["headline"] == "TOUCHDOWN"
    assert t.ingest([game(sport="nfl", home=14)]) == []


def test_a_play_by_the_other_team_is_not_used_as_context():
    t = ScoreAlertTracker()
    t.ingest([game(home=3)])
    alerts = t.ingest([game(home=7, last_play={"text": "grand slam", "team": "BOS"})])
    assert alerts[0]["headline"] != "GRAND SLAM"


def test_the_live_delay_holds_an_alert_back_until_it_is_due():
    t = ScoreAlertTracker()
    t.ingest([game(home=3)])
    t.ingest([game(home=4)])
    t._alerts[0]["ts"] = time.time() - 10
    assert t.recent(delay=45) == []
    t._alerts[0]["ts"] = time.time() - 50
    assert len(t.recent(delay=45)) == 1


# ── naming the play ──────────────────────────────────────────────────────────

def test_describe_score_across_the_sports():
    cases = [
        ("mlb", 4, {"text": "Judge homered to left"}, "GRAND SLAM"),
        ("mlb", 1, {"text": "Soto homered to right"}, "SOLO HOME RUN"),
        ("mlb", 1, {}, "RUN SCORES"),
        ("nfl", 6, {"type": "Rushing Touchdown"}, "RUSHING TD"),
        ("nfl", 3, {"type": "Field Goal Good"}, "FIELD GOAL"),
        ("nhl", 1, {"strength": "pp"}, "POWER PLAY GOAL"),
        ("nhl", 1, {"goals_to_date": 3}, "HAT TRICK"),
        ("nba", 3, {}, "3-POINTER"),
        ("soccer_epl", 1, {"text": "Goal! Penalty converted"}, "PENALTY GOAL"),
        ("cricket", 4, {}, "+4"),
    ]
    for sport, delta, play, expected in cases:
        assert describe_score(sport, delta, play)[1] == expected, (sport, play)


def test_real_mlb_play_text():
    """Strings copied from an ESPN summary feed, not invented.

    ESPN writes the whole play as one sentence, so a clean hit and a runner who
    advanced on a throw share a line. That is what broke the first describer.
    """
    cases = [
        (4, "Durbin homered to left center (401 feet), Rafaela scored, Contreras scored and Yoshida scored.", "GRAND SLAM"),
        (3, "Neto homered to center (411 feet), Meckler and Schanuel scored.", "3-RUN HOME RUN"),
        (1, "Schanuel hit sacrifice fly to right, Meckler scored, Trout to third.", "SAC FLY"),
        # A hit with a fielding error on the same play is still the hit.
        (1, "Dingler singled to right, Torres scored on throwing error by right fielder Ward.", "RBI SINGLE"),
        # Here the run itself is charged to the error.
        (1, "Crow-Armstrong scored on throwing error by catcher Valenzuela.", "RUN ON ERROR"),
        # "double play" must not read as a double.
        (1, "Machado grounded into double play, shortstop to second to first, Tatis Jr. scored.", "RUN SCORES"),
    ]
    for runs, text, expected in cases:
        assert describe_score("mlb", runs, {"text": text})[1] == expected, text


def test_real_nfl_plays_use_the_type_not_the_player_name():
    """A surname must never decide the headline.

    An earlier version looked for "pick" in the description, so every touchdown
    pass thrown by Kenny Pickett, and every one caught by George Pickens, came
    out as PICK SIX.
    """
    cases = [
        ("Rushing Touchdown", "Saquon Barkley 5 Yd Run", "RUSHING TD"),
        ("Passing Touchdown", "George Pickens 38 Yd pass from Dak Prescott", "PASSING TD"),
        ("Passing Touchdown", "Shedrick Jackson 25 Yd pass from Kenny Pickett", "PASSING TD"),
        ("Pass Interception Return", "Alohi Gilman 84 Yd Interception Return", "PICK SIX"),
        ("Sack Opp Fumble Recovery", "Tyler Nubin 27 Yd Fumble Recovery", "FUMBLE RETURN TD"),
    ]
    for play_type, text, expected in cases:
        assert describe_score("nfl", 7, {"type": play_type, "text": text})[1] == expected, text


def test_team_is_followed():
    teams = {"mlb:NYY", "BOS", "LV"}
    assert team_is_followed(teams, "mlb", "NYY")
    assert not team_is_followed(teams, "nfl", "NYY")   # league-qualified
    assert team_is_followed(teams, "nfl", "BOS")       # bare, unambiguous
    assert not team_is_followed(teams, "nfl", "LV")    # bare, ambiguous


def test_walkoff():
    """The home side takes the lead in the bottom of the ninth or later.

    Three things must hold together: the home side scored, it was level or
    behind and is now ahead, and the visitors have no at-bat left.
    """
    def run(frames):
        t = ScoreAlertTracker()
        out = []
        for home, away, status, state in frames:
            out += t.ingest([dict(game(home=home, away=away, state=state),
                                  status=status,
                                  last_play={'text': 'Goldschmidt homered to left',
                                             'team': 'NYY'})])
        return [a['headline'] for a in out]

    # The play still says how it happened, so the two are combined.
    assert run([(2, 3, 'Bot 9th', 'in'), (4, 3, 'Bot 9th', 'in')]) == ['WALK-OFF HOME RUN']
    assert run([(3, 3, 'Bot 10th', 'in'), (7, 3, 'Bot 10th', 'in')]) == ['WALK-OFF SLAM']

    # A walk-off ends the game as it lands, so the feed often flips the score
    # and the state in the same poll. The live check must not eat it.
    assert run([(3, 3, 'Bot 9th', 'in'), (4, 3, 'FINAL', 'post')]) == ['WALK-OFF HOME RUN']

    # Not walk-offs: only ties it, already ahead, too early, or the visitors.
    assert run([(2, 3, 'Bot 9th', 'in'), (3, 3, 'Bot 9th', 'in')]) == ['SOLO HOME RUN']
    assert run([(5, 3, 'Bot 9th', 'in'), (6, 3, 'Bot 9th', 'in')]) == ['SOLO HOME RUN']
    assert run([(3, 3, 'Bot 8th', 'in'), (4, 3, 'Bot 8th', 'in')]) == ['SOLO HOME RUN']
    # The visitors scoring is never a walk-off. It reads RUN SCORES rather than
    # SOLO HOMER because the attached play belongs to the home side, so it is
    # correctly ignored as context for the other team's run.
    assert run([(3, 3, 'Top 9th', 'in'), (3, 4, 'Top 9th', 'in')]) == ['RUN SCORES']

    # It earns the long hold.
    t = ScoreAlertTracker()
    t.ingest([dict(game(home=3, away=3), status='Bot 9th')])
    alert = t.ingest([dict(game(home=4, away=3), status='Bot 9th')])[0]
    assert alert['kind'] == 'walk_off' and alert['big'] is True


def test_home_run_stats():
    """The distance is already in the play text, so it costs no extra request."""
    from sports_ticker.services.score_alerts import home_run_stats

    play = {'text': 'Judge homered to left center (441 feet), Soto scored.',
            'team': 'NYY', 'athlete': 'A. Judge', 'season_hr': 41}
    assert home_run_stats(play) == {'distance_ft': 441, 'season_hr': 41}
    assert home_run_stats({'text': 'Donovan singled to right'}) == {}

    t = ScoreAlertTracker()
    t.ingest([game(home=2, away=3)])
    alert = t.ingest([game(home=4, away=3, last_play=play)])[0]
    assert alert['headline'] == '2-RUN HOME RUN'
    assert alert['detail'] == 'JUDGE - 441 FT - 41ST HR'
