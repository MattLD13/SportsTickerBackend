"""Verify canonical FotMob soccer display facts."""

from sports_ticker.providers.fotmob import _match_status, _situation


def test_fotmob_live_clock_has_one_apostrophe_without_hidden_spacing() -> None:
    match = {
        "status": {
            "started": True,
            "liveTime": {"short": "93\u200e�\u200e'"},
        }
    }

    assert _match_status(match, "in", "UTC") == "93'"


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
