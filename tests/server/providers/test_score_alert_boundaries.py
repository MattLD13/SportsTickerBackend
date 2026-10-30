"""Check observable alert behavior independently of either candidate."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ticker.shared.domain import DisplaySettings, TickerSnapshot
from ticker.server.projections import project_data_v2
from ticker.server.providers.score_alerts import ScoreAlertTracker
from ticker.server.providers.espn_events import _team
from ticker.six.assets import AssetPlanner, AssetRequest, LogoAssetView
from ticker.six.app.updates import delta_asset_source
from ticker.six.ui.score_alert import ScoreAlert
from ticker.six.platform import AssetCoordinator
from ticker.six.protocol import TickerResponse, display_delta
from ticker.six.ui import load_default_font_set
from ticker.six.runtime import TickerRuntime, FrameKind

pytestmark = pytest.mark.critical


def baseline(sport="nfl"):
    return {"kind": "scoreboard", "id": "independent-game", "sport": sport,
            "state": "in", "status": "Q2 03:21", "home_abbr": "DAL", "away_abbr": "NYG",
            "home_score": 0, "away_score": 0,
            "home_logo": "https://assets.example/dal.png", "away_logo": "https://assets.example/nyg.png"}


def touchdown(game, score=6, play_id="td-1"):
    return {**game, "home_score": score, "situation": {"scoring_plays": [
        {"play_id": play_id, "team": game["home_abbr"], "type": "Touchdown", "event_type": "Rushing Touchdown",
         "text": "Runner 4 Yd Rush", "scorer_full": "Actual Runner", "yards": 4,
         "home_score": score, "away_score": game["away_score"], "period": 2, "clock": "03:21"}]}}


@pytest.mark.parametrize("sport", ["nfl", "ncf_fbs", "ncf_fcs"])
def test_touchdown_then_unenriched_extra_point_is_one_takeover(sport):
    now = [100.0]
    tracker = ScoreAlertTracker(clock=lambda: now[0])
    game = baseline(sport)
    tracker.ingest([game])
    scored = touchdown(game)
    tracker.ingest([scored])
    first = deepcopy(tracker.recent()[0])
    now[0] = 106.0
    tracker.ingest([{**game, "home_score": 7}])
    tracker.ingest([{**game, "home_score": 7}])
    alerts = tracker.recent()
    assert len(alerts) == 1, [(a["headline"], a.get("player")) for a in alerts]
    assert alerts[0]["id"] == first["id"]
    assert alerts[0]["ts"] == first["ts"]
    assert alerts[0]["player"] == "Actual Runner"
    assert alerts[0]["team_logo"] == game["home_logo"]


def test_later_touchdown_and_field_goal_still_alert():
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    game = baseline()
    tracker.ingest([game])
    tracker.ingest([touchdown(game)])
    tracker.ingest([{**game, "home_score": 7}])
    tracker.ingest([touchdown(game, 13, "td-2")])
    tracker.ingest([{**game, "home_score": 14}])
    tracker.ingest([{**game, "home_score": 17, "situation": {"scoring_plays": [
        {"play_id": "fg-1", "team": "DAL", "type": "Field Goal", "scorer_full": "Actual Kicker",
         "home_score": 17, "away_score": 0, "yards": 43}]}}])
    alerts = tracker.recent()
    assert len(alerts) == 3, [a["headline"] for a in alerts]
    assert alerts[-1]["kind"] == "field_goal"
    assert alerts[-1]["player"] == "Actual Kicker"


def test_conversion_without_preceding_observed_touchdown_is_not_dropped():
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    game = {**baseline(), "home_score": 6}
    tracker.ingest([game])
    tracker.ingest([{**game, "home_score": 7}])
    assert len(tracker.recent()) == 1
    assert tracker.recent()[0]["kind"] == "extra_point"


def test_opponent_score_change_and_stale_poll_cannot_replay_the_same_touchdown():
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    game = baseline()
    tracker.ingest([game])
    tracker.ingest([touchdown(game)])
    first = deepcopy(tracker.recent()[0])
    tracker.ingest([{**game, "home_score": 6, "away_score": 3}])
    tracker.ingest([{**game, "home_score": 0, "away_score": 3}])
    tracker.ingest([{**game, "home_score": 6, "away_score": 3}])
    home = [a for a in tracker.recent() if a["side"] == "home"]
    assert len(home) == 1
    assert home[0]["id"] == first["id"]
    assert home[0]["player"] == "Actual Runner"


@pytest.mark.parametrize("prime", [False, True])
def test_initial_score_baseline_cannot_replay_after_a_correction(prime):
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    game = {**baseline(), "home_score": 7}
    (tracker.prime if prime else tracker.ingest)([game])
    tracker.ingest([{**game, "home_score": 6}])
    tracker.ingest([game])
    assert tracker.recent() == ()
    tracker.ingest([{**game, "home_score": 10}])
    assert len(tracker.recent()) == 1
    assert tracker.recent()[0]["kind"] == "field_goal"


def test_football_score_memory_leaves_with_its_game():
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    game = baseline()
    tracker.ingest([game])
    tracker.ingest([touchdown(game)])
    assert game["id"] in tracker._football_scores
    tracker.ingest([])
    assert not tracker._football_scores


@pytest.mark.parametrize("initial", ["baseline", "prime", "alerted", "generic-alerted"])
@pytest.mark.parametrize("delayed", [False, True])
def test_distinct_touchdown_after_correction_gets_a_fresh_identity(initial, delayed):
    clock = [100.0]
    tracker = ScoreAlertTracker(clock=lambda: clock[0])
    game = baseline()
    if initial == "baseline":
        tracker.ingest([{**game, "home_score": 6}])
    elif initial == "prime":
        tracker.prime([{**game, "home_score": 6}])
    else:
        tracker.ingest([game])
        tracker.ingest([touchdown(game) if initial == "alerted" else {**game, "home_score": 6}])
    original = deepcopy(tracker.recent())
    tracker.ingest([game])
    clock[0] = 102.0
    tracker.ingest([{**game, "away_score": 3}])
    if delayed:
        tracker.ingest([{**game, "home_score": 6, "away_score": 3}])
    later = touchdown({**game, "away_score": 3}, play_id="new-distinct-td")
    later["situation"]["scoring_plays"][0]["scorer_full"] = "Later Runner"
    clock[0] = 104.0
    tracker.ingest([later])
    tracker.ingest([later])
    home = [a for a in tracker.recent() if a["side"] == "home"]
    assert len(home) == (2 if original else 1)
    assert home[-1]["scoring_play_id"] == "new-distinct-td"
    assert home[-1]["player"] == "Later Runner"
    assert home[-1]["ts"] == 104.0
    if original:
        assert home[0]["id"] == original[0]["id"]
        assert home[0]["ts"] == original[0]["ts"]
        assert home[0]["player"] == original[0]["player"]
        assert home[-1]["id"] != home[0]["id"]
    tracker.ingest([{**later, "home_score": 7}])
    assert len([a for a in tracker.recent() if a["side"] == "home"]) == len(home)


def test_enriched_conversion_identity_cannot_replay_after_score_recovery():
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    game = baseline()
    tracker.ingest([game])
    tracker.ingest([touchdown(game)])
    tracker.ingest([{**game, "home_score": 7}])
    enriched = touchdown(game, score=7)
    enriched["situation"]["scoring_plays"][0]["conversion_type"] = "extra_point"
    tracker.ingest([enriched])
    tracker.ingest([{**game, "home_score": 6}])
    tracker.ingest([enriched])
    assert len(tracker.recent()) == 1
    assert tracker.recent()[0]["points"] == 7


def test_primed_converted_touchdown_does_not_replay_its_extra_point():
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    game = baseline()
    enriched = touchdown(game, score=7)
    enriched["situation"]["scoring_plays"][0]["conversion_type"] = "extra_point"
    tracker.prime([enriched])
    tracker.ingest([{**game, "home_score": 6}])
    tracker.ingest([enriched])
    assert tracker.recent() == ()


def test_standalone_conversion_remembers_the_parent_touchdown_identity():
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    game = baseline()
    tracker.ingest([{**game, "home_score": 6}])
    converted = touchdown(game, score=7)
    converted["situation"]["scoring_plays"][0]["conversion_type"] = "extra_point"
    tracker.ingest([converted])
    assert tracker.recent()[0]["kind"] == "extra_point"
    tracker.ingest([game])
    tracker.ingest([converted])
    assert len(tracker.recent()) == 1


@pytest.mark.parametrize("prime", [False, True])
def test_baseline_seeds_all_past_play_ids_without_consuming_future_plays(prime):
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    game = baseline()
    old = touchdown(game, score=7, play_id="past-td")
    future = touchdown({**game, "away_score": 3}, score=14, play_id="future-td")
    old_play = old["situation"]["scoring_plays"][0]
    future_play = future["situation"]["scoring_plays"][0]
    baseline_game = {**game, "home_score": 10, "situation": {"scoring_plays": [
        old_play, {"play_id": "past-fg", "team": "DAL", "type": "Field Goal", "home_score": 10, "away_score": 0},
        future_play]}}
    (tracker.prime if prime else tracker.ingest)([baseline_game])
    tracker.ingest([game])
    tracker.ingest([old])
    assert tracker.recent() == ()
    tracker.ingest([future])
    home = [a for a in tracker.recent() if a["side"] == "home"]
    assert len(home) == 1 and home[0]["scoring_play_id"] == "future-td"
    assert [a["kind"] for a in tracker.recent() if a["side"] == "away"] == ["field_goal"]


def test_turnover_detail_cannot_split_a_touchdown_and_conversion():
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    game = {**baseline(), "situation": {"football_plays": []}}
    tracker.ingest([game])
    scored = touchdown(game)
    scored["situation"]["football_plays"] = []
    tracker.ingest([scored])
    first = deepcopy(tracker.recent()[0])
    tracker.ingest([{**game, "home_score": 7, "situation": {"football_plays": [
        {"event_id": "late-pick", "football_kind": "interception", "team": "DAL",
         "is_scoring": False, "scorer_full": "Actual Defender"}]}}])
    alerts = tracker.recent()
    assert len(alerts) == 2
    scoring = [a for a in alerts if a["points"] > 0]
    assert len(scoring) == 1
    assert scoring[0]["id"] == first["id"] and scoring[0]["ts"] == first["ts"]
    assert scoring[0]["player"] == "Actual Runner" and scoring[0]["home_score"] == 7
    assert alerts[-1]["kind"] == "interception"


@pytest.mark.parametrize("source", [
    {"logo": "", "logos": [{"href": "https://assets.example/dal.png"}]},
    {"logos": [{"href": ""}, {"href": "https://assets.example/dal.png"}]},
    {"logo": "https://assets.example/dal.png"},
])
def test_espn_team_selects_a_usable_logo(source):
    team = _team({"team": {"abbreviation": "DAL", **source}})
    assert team["logo"] == "https://assets.example/dal.png"


@pytest.mark.parametrize("sport", ["nhl", "mlb", "soccer_epl"])
def test_other_sports_keep_separate_consecutive_scores(sport):
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    game = baseline(sport)
    tracker.ingest([game])
    tracker.ingest([{**game, "home_score": 1}])
    tracker.ingest([{**game, "home_score": 2}])
    assert len(tracker.recent()) == 2


@pytest.mark.parametrize("shape", ["parsed", "raw", "delta"])
def test_v2_alert_logo_is_planned_when_game_is_absent(shape):
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    game = baseline()
    tracker.ingest([game])
    tracker.ingest([touchdown(game)])
    snapshot = TickerSnapshot("boundary", 1, datetime(2026, 10, 19, tzinfo=timezone.utc),
        (), tracker.recent(), (), DisplaySettings())
    raw = project_data_v2(snapshot, {}, {})
    response = TickerResponse.from_payload(raw)
    source = {"parsed": response, "raw": raw, "delta": tuple(a.data for a in response.alerts)}[shape]
    assert AssetRequest(game["home_logo"], "logo", (24, 24)) in AssetPlanner().plan(source).requests


@pytest.mark.parametrize("started", [False, True])
def test_enriched_alert_updates_queued_or_visible_data_without_restarting(started):
    clock = [0.0]
    runtime = TickerRuntime(monotonic=lambda: clock[0], wall_clock=lambda: datetime(2026, 10, 19, tzinfo=timezone.utc))
    alert = {"id": "td-one", "sport": "nfl", "headline": "RUSH TD", "home_score": 6,
             "player": "Actual Runner", "team_logo": ""}
    def response(item):
        snapshot = TickerSnapshot("boundary", 1, datetime(2026, 10, 19, tzinfo=timezone.utc),
            (), (item,), (), DisplaySettings())
        return TickerResponse.from_payload(project_data_v2(snapshot, {}, {"pairing": {"paired": True}}))
    runtime.accept_response(response(alert))
    if started:
        assert runtime.next_frame().kind is FrameKind.SCORE_ALERT
    clock[0] = 2.0
    updated = {**alert, "home_score": 7, "team_logo": "https://assets.example/dal.png"}
    runtime.accept_response(response(updated))
    frame = runtime.next_frame()
    assert frame.kind is FrameKind.SCORE_ALERT
    assert frame.alert["home_score"] == 7
    assert frame.alert["team_logo"] == updated["team_logo"]
    assert frame.alert_elapsed == (2.0 if started else 0.0)
    clock[0] = 8.0 if started else 10.0
    assert runtime.next_frame().kind is not FrameKind.SCORE_ALERT


def test_display_delta_prepares_and_renders_alert_logo_without_a_game_card(tmp_path):
    tracker = ScoreAlertTracker(clock=lambda: 100.0)
    game = {**baseline(), "home_abbr": "NYG", "away_abbr": "DAL",
            "home_logo": "https://assets.example/nyg.png"}
    tracker.ingest([game])
    def response(alerts):
        snapshot = TickerSnapshot("boundary", 1, datetime(2026, 10, 19, tzinfo=timezone.utc),
            (), alerts, (), DisplaySettings())
        return TickerResponse.from_payload(project_data_v2(snapshot, {}, {}))
    previous = response(())
    tracker.ingest([touchdown(game)])
    current = response(tracker.recent())
    delta = display_delta(previous, current)
    source = delta_asset_source(delta)
    assert not delta.changed
    assert source[0]["data"] == "RUSH 4YD"
    logo_bytes = (Path(__file__).parents[2] / "fixtures/render_baseline/nfl-nyg.png").read_bytes()
    with_asset = AssetCoordinator(tmp_path, fetch=lambda url: logo_bytes)
    without_asset = AssetCoordinator(tmp_path / "empty", fetch=lambda url: None)
    try:
        futures = with_asset.prefetch_payload(source)
        assert futures
        assert all(future.result() is not None for future in futures)
        assert with_asset.image(game["home_logo"], "logo", (24, 24)) is not None
        fonts = load_default_font_set()
        alert = current.alerts[0].data
        actual = ScoreAlert(fonts, LogoAssetView(with_asset)).frame(alert, 4.0)
        missing = ScoreAlert(fonts, LogoAssetView(without_asset)).frame(alert, 4.0)
        assert actual.size == (384, 32)
        assert actual.crop((0, 0, 36, 32)).tobytes() != missing.crop((0, 0, 36, 32)).tobytes()
    finally:
        with_asset.close()
        without_asset.close()
