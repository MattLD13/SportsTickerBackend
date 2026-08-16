"""Verify canonical FotMob soccer display facts."""

from sports_ticker.providers.fotmob import (
    FotMobSoccerProvider,
    _content_item,
    _match_state,
    _match_status,
    _needs_details,
    _situation,
)


def test_fotmob_live_clock_has_one_apostrophe_without_hidden_spacing() -> None:
    match = {
        "status": {
            "started": True,
            "liveTime": {"short": "93\u200e�\u200e'"},
        }
    }

    assert _match_status(match, "in", "UTC") == "93'"


def test_fotmob_prefers_the_precise_stoppage_clock() -> None:
    """Use the long clock when it contains stoppage minutes and seconds."""

    match = {
        "status": {
            "started": True,
            "liveTime": {"short": "45+1'", "long": "45:00 + 1:12"},
        }
    }

    assert _match_status(match, "in", "UTC") == "45'+1:12'"


def test_fotmob_reads_halftime_from_live_time_when_reason_is_empty() -> None:
    match = {
        "id": "5071271",
        "status": {
            "started": True,
            "finished": False,
            "cancelled": False,
            "reason": {},
            "liveTime": {"short": "HT", "long": "Half-Time"},
        },
        "home": {"id": "1", "longName": "Atlanta United", "score": 1},
        "away": {"id": "2", "longName": "Charlotte FC", "score": 0},
    }

    item = _content_item("soccer_mls", match, None, timezone_name="UTC")

    assert _match_state(match) == "half"
    assert item.data["state"] == "half"
    assert item.data["status"] == "Half"


def test_fotmob_soccer_events_match_the_v1_renderer_contract() -> None:
    detail = {
        "content": {
            "matchFacts": {
                "events": {
                    "events": [
                        {"type": "Goal", "isHome": False, "time": 13, "player": {"name": "Alex Morgan"}},
                        {"type": "Goal", "isHome": True, "time": 45, "overloadTime": 2, "subType": "Own goal", "player": {"name": "Jamie Smith"}},
                        {"type": "Card", "isHome": False, "time": 71, "card": "Red", "player": {"name": "Taylor Reed"}},
                    ]
                }
            }
        }
    }

    situation = _situation(detail)

    assert situation["goal_events"] == [
        {"is_home": False, "player": "MORGAN", "time": "13'", "own_goal": False},
        {"is_home": True, "player": "SMITH", "time": "45+2'", "own_goal": True},
    ]
    assert situation["red_cards"] == [
        {"is_home": False, "player": "REED", "time": "71'", "own_goal": False}
    ]


def test_fotmob_keeps_final_match_details_until_the_display_window_closes() -> None:
    match = {"status": {"started": True, "finished": True, "reason": {"short": "FT"}}}

    assert _needs_details(match)


def test_fotmob_fetches_pregame_details_for_team_colors() -> None:
    match = {
        "id": "5836754",
        "status": {"started": False, "utcTime": "2026-08-15T23:30:00Z"},
        "home": {"id": "1", "longName": "Atlanta United", "score": 0},
        "away": {"id": "2", "longName": "Charlotte FC", "score": 0},
    }
    detail = {"general": {"teamColors": {"darkMode": {"home": "#80000A", "away": "#00AEEF"}}}}

    item = _content_item("soccer_mls", match, detail, timezone_name="UTC")

    assert _needs_details(match)
    assert item.data["home_color"] == "#80000A"
    assert item.data["away_color"] == "#00AEEF"


def test_fotmob_replaces_the_last_live_details_with_one_final_snapshot() -> None:
    class Client:
        calls = 0

        def get_json(self, url: str, *, timeout: float) -> dict:
            del url, timeout
            self.calls += 1
            return {"revision": self.calls}

    client = Client()
    provider = FotMobSoccerProvider({"soccer_champ": 48}, client=client)
    live = {"id": "5836754", "status": {"started": True}}
    final = {"id": "5836754", "status": {"started": True, "finished": True}}

    assert provider._details_for(live) == {"revision": 1}
    assert provider._details_for(final) == {"revision": 2}
    assert provider._details_for(final) == {"revision": 2}
    assert client.calls == 2


def test_fotmob_reuses_pregame_details_until_the_match_starts() -> None:
    class Client:
        calls = 0

        def get_json(self, url: str, *, timeout: float) -> dict:
            del url, timeout
            self.calls += 1
            return {"revision": self.calls}

    client = Client()
    provider = FotMobSoccerProvider({"soccer_mls": 130}, client=client)
    pregame = {"id": "5836754", "status": {"started": False}}
    live = {"id": "5836754", "status": {"started": True}}

    assert provider._details_for(pregame) == {"revision": 1}
    assert provider._details_for(pregame) == {"revision": 1}
    assert provider._details_for(live) == {"revision": 2}
    assert client.calls == 2
