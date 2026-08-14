"""Verify canonical FotMob soccer status labels."""

from sports_ticker.providers.fotmob import _match_status


def test_fotmob_live_clock_has_one_apostrophe_without_hidden_spacing() -> None:
    match = {
        "status": {
            "started": True,
            "liveTime": {"short": "93\u200e�\u200e'"},
        }
    }

    assert _match_status(match, "in", "UTC") == "93'"
