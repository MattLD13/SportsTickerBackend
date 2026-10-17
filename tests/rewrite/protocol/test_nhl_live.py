"""Verify current NHL manpower reads, freshness, and display ownership."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from sports_ticker.application.state_store import SnapshotStore
from sports_ticker.domain import ContentItem, DisplaySettings, TickerSnapshot
from sports_ticker.projections import project_data_v2
from sports_ticker.providers.contracts import ProviderHealth
from sports_ticker.providers.espn import EspnScoreboardProvider
from sports_ticker.providers.nhl_live import NhlLiveSituationSource, nhl_team_key, _game_events
from sports_ticker.providers.sports_display import nhl_manpower_situation, nhl_goal_display, nhl_shootout_display
from ticker_core.protocol import TickerResponse


_CAPTURE = Path(__file__).parents[1] / "debug" / "nhl_live_manpower.json"
pytestmark = pytest.mark.critical


class NhlClient:
    def __init__(self) -> None:
        self.live_games = [{
            "id": 2026020100,
            "gameState": "LIVE",
            "awayTeam": {"abbrev": "COL"},
            "homeTeam": {"abbrev": "DAL"},
        }]
        self.game = json.loads(_CAPTURE.read_text())
        self.fail_game = False
        self.fail_score = False

    def get_json(self, url: str, *, timeout: float):
        del timeout
        if url.endswith("/score/now"):
            if self.fail_score:
                raise OSError("score read failed")
            return {"games": self.live_games}
        assert url.endswith(f"/{self.live_games[0]['id']}/play-by-play")
        if self.fail_game:
            raise OSError("game read failed")
        return deepcopy(self.game)


def test_current_nhl_situation_replaces_historical_play_strength() -> None:
    client = NhlClient()
    client.game["summary"]["iceSurface"]["homeTeam"]["penaltyBox"].append({
        "playerId": 9999999, "sweaterNumber": 24, "secondsRemaining": 420,
    })
    source = NhlLiveSituationSource(client=client, background=False, monotonic=lambda: 0.0)
    facts = source.snapshot()[("COL", "DAL")]
    assert client.game["plays"][-1]["situationCode"] == "1551"
    assert facts["situationCode"] == "1541"
    projected = nhl_manpower_situation(facts, home_abbr="DAL", away_abbr="COL")
    assert projected["powerPlay"] is True
    assert projected["powerPlayTeam"] == "COL"
    assert projected["manpower"]["label"] == "5v4"
    assert projected["manpower"]["scrollLabel"] == "1:47 #55"
    assert projected["manpower"]["penaltyNumbers"] == [55]

    # A new normal situation clears the old power play despite the historical play.
    client.game.pop("situation")
    client.game["plays"][-1]["situationCode"] = "1541"
    normal = nhl_manpower_situation(source.snapshot()[("COL", "DAL")], home_abbr="DAL", away_abbr="COL")
    assert normal["powerPlay"] is False
    assert normal["powerPlayTeam"] == ""
    assert normal["manpower"]["label"] == ""
    assert normal["manpower"]["awaySkaters"] == 5
    assert normal["manpower"]["penaltyNumbers"] == []


def test_current_pp_and_empty_net_survive_faceoffs_without_historical_inference() -> None:
    client = NhlClient()
    client.game["clock"]["running"] = False
    client.game["plays"].append({"eventId": 9999999, "sortOrder": 9999, "typeDescKey": "faceoff", "situationCode": "1551"})
    source = NhlLiveSituationSource(client=client, background=False, monotonic=lambda: 0.0)
    for code, away_pp, home_pp, pp, en, label in (
        ("1541", True, False, True, False, "1:47 #55"),
        ("0651", False, False, False, True, "6v5"),
    ):
        client.game["situation"]["situationCode"] = code
        client.game["situation"]["awayTeam"]["situationDescriptions"] = ["PP"] if away_pp else []
        client.game["situation"]["homeTeam"]["situationDescriptions"] = ["PP"] if home_pp else []
        result = nhl_manpower_situation(source.snapshot()[("COL", "DAL")], home_abbr="DAL", away_abbr="COL")
        assert result["powerPlay"] is pp
        assert result["emptyNet"] is en
        assert result["manpower"]["scrollLabel"] == label


def test_staggered_penalty_clocks_survive_projection_and_remove_expired_players() -> None:
    replay = json.loads(_CAPTURE.with_name("nhl_staggered_penalties_replay.json").read_text())
    facts = deepcopy(replay["facts"])

    class Source:
        def snapshot(self):
            return {("CGY", "ANA"): facts}

    provider = EspnScoreboardProvider({}, nhl_situation_source=Source())
    store = SnapshotStore(clock=lambda: 0.0)
    for stage, label, numbers in (
        ("staggered", "0:10 #72 | 2:00 #17", [72, 17]),
        ("shared", "1:30 #17/#72", [17, 72]),
        ("expired", "1:50 #17", [17]),
        ("normal", "", []),
    ):
        facts = deepcopy(replay["facts"])
        facts["penaltyBox"]["away"].append({"jerseyNumber": 55, "secondsRemaining": 500, "kind": "MIS"})
        facts["penaltyBox"]["home"] = [{"jerseyNumber": 9, "secondsRemaining": 10, "kind": "MIN"}]
        if stage == "shared":
            facts["powerPlaySecondsRemaining"] = 90
            for penalty in facts["penaltyBox"]["away"][:2]:
                penalty["secondsRemaining"] = 90
        elif stage == "expired":
            facts.update(situationCode="1451", powerPlaySecondsRemaining=110)
            facts["penaltyBox"]["away"][0]["secondsRemaining"] = 0
            facts["penaltyBox"]["away"][1]["secondsRemaining"] = 110
        elif stage == "normal":
            facts.update(situationCode="1551", homePowerPlay=False, powerPlaySecondsRemaining=None)
        item = ContentItem("penalties", "sports", "scoreboard", True, replay["item"])
        item = provider._enrich_nhl_live_items((item,))[0]
        stored = store.replace(TickerSnapshot("penalties", 0, datetime(2026, 10, 13, tzinfo=timezone.utc), (item,), (), (), DisplaySettings()))
        payload = project_data_v2(stored, ProviderHealth(), {"stale": False})
        response = TickerResponse.from_payload(payload)
        manpower = response.content[0].data["situation"]["manpower"]
        assert manpower["scrollLabel"] == label
        assert list(manpower["penaltyNumbers"]) == numbers
        assert [penalty["jerseyNumber"] for penalty in manpower["penalties"]] == numbers


def test_complete_nhl_goal_and_shootout_ledgers_reach_the_v2_contract() -> None:
    for name, expected_goals, expected_attempts in (
        ("nhl_goal_ledger", 8, None),
        ("nhl_shootout_ledger", 4, {"away": ["goal", "miss", "miss", "miss", "goal"], "home": ["miss", "goal", "miss", "miss", "miss"]}),
        ("nhl_shootout_failed_attempt", 0, {"away": ["goal", "miss"], "home": ["goal", "goal", "goal"]}),
    ):
        client = NhlClient()
        client.game = json.loads(_CAPTURE.with_name(f"{name}.json").read_text())
        client.game["gameState"] = "LIVE"
        client.live_games[0].update(id=client.game["id"], awayTeam=client.game["awayTeam"], homeTeam=client.game["homeTeam"])
        source = NhlLiveSituationSource(client=client, background=False, monotonic=lambda: 0.0)
        facts = next(iter(source.snapshot().values()))
        goals = nhl_goal_display(facts)
        assert len(goals) == expected_goals
        if expected_attempts is None:
            assert facts["shootout"] is None
        else:
            assert {side: facts["shootout"][side] for side in ("away", "home")} == expected_attempts
        assert all("#" in goal["playerLabel"] and len(goal["playerLabel"].split("#")[0]) == 3 for goal in goals)
        if name == "nhl_goal_ledger":
            assert goals[-1]["playerLabel"] == "TAV#91"
            assert sum(goal["side"] == "home" for goal in goals) == 5
        provider = EspnScoreboardProvider({}, nhl_situation_source=source)
        item = ContentItem("ledger", "sports", "scoreboard", True, {
            "sport": "nhl", "state": "in", "status": "OT2 0:00",
            "away_abbr": client.game["awayTeam"]["abbrev"], "home_abbr": client.game["homeTeam"]["abbrev"],
            "situation": {},
        })
        enriched = provider._enrich_nhl_live_items((item,))[0]
        assert len(enriched.data["situation"]["hockeyGoals"]) == expected_goals
        if expected_attempts is not None:
            assert enriched.data["status"] == "S/O"
            shootout = enriched.data["situation"]["shootout"]
            assert {side: shootout[side] for side in ("away", "home")} == {side: tuple(values) for side, values in expected_attempts.items()}
            assert len(shootout["displayRounds"]) == 3


def test_current_nhl_phase_controls_standard_counts_and_visibility() -> None:
    cases = (
        ("REG", 2, False, "LIVE", "regulation", 5),
        ("OT", 2, False, "LIVE", "overtime", 3),
        ("OT", 3, False, "LIVE", "overtime", 5),
        ("SO", 2, False, "LIVE", "shootout", None),
        ("REG", 2, True, "LIVE", "intermission", None),
        ("REG", 2, False, "OFF", "inactive", None),
    )
    for period, game_type, intermission, state, phase, count in cases:
        client = NhlClient()
        client.game.pop("situation")
        client.game.update(gameType=game_type, gameState=state)
        client.game["periodDescriptor"]["periodType"] = period
        client.game["clock"]["inIntermission"] = intermission
        source = NhlLiveSituationSource(client=client, background=False, monotonic=lambda: 0.0)
        facts = source.snapshot()[("COL", "DAL")]
        result = nhl_manpower_situation(facts, home_abbr="DAL", away_abbr="COL")
        assert result["manpower"]["phase"] == phase
        assert result["manpower"]["awaySkaters"] == count
        assert result["manpower"]["label"] == ""
        assert result["powerPlay"] is False


def test_nhl_shootout_rounds_align_across_live_sudden_death_and_completion() -> None:
    game = json.loads(_CAPTURE.with_name("nhl_shootout_ledger.json").read_text())
    shots = [play for play in game["plays"] if play.get("periodDescriptor", {}).get("periodType") == "SO" and play.get("typeDescKey") in {"goal", "shot-on-goal", "missed-shot", "failed-shot-attempt"}]
    for count, state, label, next_side, away, home in (
        (0, "active", "R1-3", "", ["pending"] * 3, ["pending"] * 3),
        (3, "active", "R1-3", "away", ["goal", "pending", "pending"], ["miss", "goal", "pending"]),
        (6, "active", "R2-4", "home", ["miss", "miss", "pending"], ["goal", "miss", "pending"]),
        (7, "active", "R2-4", "away", ["miss", "miss", "pending"], ["goal", "miss", "miss"]),
        (10, "complete", "R3-5", "", ["miss", "miss", "goal"], ["miss", "miss", "miss"]),
    ):
        replay = {**game, "gameState": "OFF" if state == "complete" else "LIVE", "plays": shots[:count]}
        if count:
            replay["plays"] = list(reversed(replay["plays"])) + [shots[0]]
        facts = _game_events(replay)
        display = nhl_shootout_display(facts)
        assert display is not None
        assert display["state"] == state
        assert display["roundLabel"] == label
        assert display["nextSide"] == next_side
        assert [row["away"] for row in display["displayRounds"]] == away
        assert [row["home"] for row in display["displayRounds"]] == home
        assert len(display["away"]) + len(display["home"]) == count
        assert display["stage"] == ("sudden_death" if count >= 6 else "initial")
        item = ContentItem("shootout", "sports", "scoreboard", True, {"sport": "nhl", "state": "in", "situation": {"shootout": display}})
        store = SnapshotStore(clock=lambda: 0.0)
        stored = store.replace(TickerSnapshot("shootout", 0, datetime(2026, 10, 13, tzinfo=timezone.utc), (item,), (), (), DisplaySettings()))
        response = TickerResponse.from_payload(project_data_v2(stored, ProviderHealth(), {"stale": False}))
        assert response.content[0].data["situation"]["shootout"]["roundLabel"] == label

    early = json.loads(_CAPTURE.with_name("nhl_shootout_failed_attempt.json").read_text())
    display = nhl_shootout_display(_game_events(early))
    assert display is not None
    assert display["state"] == "complete"
    assert display["displayRounds"][2]["away"] == "not_taken"
    assert display["nextSide"] == ""


def test_failed_game_reads_do_not_renew_or_preserve_old_manpower() -> None:
    client = NhlClient()
    now = [0.0]
    source = NhlLiveSituationSource(client=client, background=False, monotonic=lambda: now[0])
    assert source.snapshot()
    client.fail_game = True
    for tick in (8.0, 16.0, 25.0):
        now[0] = tick
        assert source.snapshot() == {}
    client.fail_game = False
    assert source.snapshot()
    client.fail_score = True
    now[0] = 50.0
    assert source.snapshot() == {}


def test_situation_cache_drops_finished_games_and_rejects_wrong_identity() -> None:
    client = NhlClient()
    source = NhlLiveSituationSource(client=client, background=False, monotonic=lambda: 0.0)
    assert source.snapshot()
    client.game["id"] = 2026029999
    assert source.snapshot() == {}
    client.game["id"] = 2026020100
    assert source.snapshot()
    client.live_games = []
    assert source.snapshot() == {}


def test_nhl_team_join_normalizes_provider_abbreviations() -> None:
    for espn, nhl in (("NJ", "NJD"), ("LA", "LAK"), ("SJ", "SJS"), ("TB", "TBL"), ("WSH", "WSH"), ("VGK", "VGK"), ("UTA", "UTA")):
        assert nhl_team_key(espn) == nhl_team_key(nhl)


def test_nhl_manpower_replaces_stale_facts_through_snapshot_api_and_pi() -> None:
    client = NhlClient()
    client.live_games[0]["homeTeam"]["abbrev"] = "LAK"
    source = NhlLiveSituationSource(client=client, background=False, monotonic=lambda: 0.0)
    provider = EspnScoreboardProvider({}, nhl_situation_source=source)
    store = SnapshotStore(clock=lambda: 0.0)
    item = ContentItem("live-nhl", "sports", "scoreboard", True, {
        "sport": "nhl", "state": "in", "status": "P3 14:57",
        "startTimeUTC": "2026-10-14T00:45:00Z",
        "away_abbr": "COL", "home_abbr": "LA",
        "situation": {
            "emptyNet": True, "emptyNetSide": "LA",
            "powerPlay": True, "powerPlayTeam": "LA",
            "manpower": {"label": "6v4"},
            "scoring_plays": [{"id": "goal-1"}],
        },
    })
    for mode, expected_label, expected_team in (
        ("power_play", "5v4", "COL"),
        ("normal", "", ""),
        ("failed", "", ""),
        ("wrong_date", "", ""),
        ("shootout", "", ""),
        ("espn_shootout", "", ""),
    ):
        client.fail_game = mode == "failed"
        client.game = json.loads(_CAPTURE.read_text())
        if mode == "normal":
            client.game.pop("situation")
        if mode == "wrong_date":
            client.game["startTimeUTC"] = "2026-10-15T00:30:00Z"
        if mode == "shootout":
            client.game["periodDescriptor"]["periodType"] = "SO"
        current_item = item
        if mode == "espn_shootout":
            current_data = dict(item.data)
            current_data["status"] = "S/O"
            current_item = ContentItem(item.id, item.family, item.kind, item.is_shown, current_data)
        enriched = provider._enrich_nhl_live_items((current_item,))[0]
        store.replace(TickerSnapshot(
            "review", 0, datetime(2026, 10, 14, tzinfo=timezone.utc),
            (enriched,), (), (), DisplaySettings(),
        ))
        stored = store.get("review")
        assert stored is not None
        payload = project_data_v2(stored, ProviderHealth(), {"stale": False})
        situation = payload["content"]["sports"][0]["data"]["situation"]
        assert situation["manpower"]["label"] == expected_label
        assert situation["manpower"]["powerPlayLabel"] == ("PP" if mode == "power_play" else "")
        assert situation["powerPlayTeam"] == expected_team
        assert situation["emptyNet"] is False
        assert situation["emptyNetSide"] == ""
        assert situation["scoring_plays"] == [{"id": "goal-1"}]
        response = TickerResponse.from_payload(payload)
        assert response.content[0].data["situation"]["manpower"]["label"] == expected_label


@pytest.mark.parametrize("away,home,away_pp,home_pp,phase,expected", [
    (5, 4, True, False, "regulation", "PP"),
    (5, 3, True, False, "regulation", "5v3"),
    (3, 5, False, True, "regulation", "5v3"),
    (4, 5, False, True, "regulation", "PP"),
    (4, 3, True, False, "overtime", "PP"),
    (3, 4, False, True, "overtime", "PP"),
    (5, 5, False, False, "regulation", ""),
    (4, 4, False, False, "regulation", ""),
    (5, 3, True, False, "shootout", ""),
])
def test_power_play_header_uses_advantaged_team_first(away, home, away_pp, home_pp, phase, expected) -> None:
    source = {"phase": phase, "situationCode": f"1{away}{home}1", "awayPowerPlay": away_pp, "homePowerPlay": home_pp}
    situation = nhl_manpower_situation(source, home_abbr="NYI", away_abbr="NYR")
    assert situation["manpower"]["powerPlayLabel"] == expected
