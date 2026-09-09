import pytest

from sports_ticker.domain import DisplaySettings
from sports_ticker.projections import select_display_content
from ticker_core.protocol import TickerResponse
from ticker_core.runtime import classify_content
from ticker_core.modes import DisplayMode, display_mode

pytestmark = pytest.mark.critical


def test_user_modes_have_one_explicit_owner():
    assert tuple(DisplayMode) == (
        DisplayMode.SPORTS,
        DisplayMode.WEATHER,
        DisplayMode.MUSIC,
        DisplayMode.FLIGHTS,
        DisplayMode.AIRPORTS,
        DisplayMode.STOCK,
        DisplayMode.CLOCK,
    )
    with pytest.raises(ValueError):
        display_mode("nascar_full")
    with pytest.raises(ValueError):
        DisplaySettings(mode="removed_mode")
    with pytest.raises(ValueError):
        DisplaySettings(sports_filter="removed_filter")


def test_sports_filter_marks_cards_without_removing_them_from_the_app_feed() -> None:
    content = {
        "sports": [
            {"id": "live", "family": "sports", "kind": "scoreboard", "is_shown": True, "data": {"sport": "nfl", "state": "in", "away_abbr": "NYG", "home_abbr": "DAL"}},
            {"id": "scheduled", "family": "sports", "kind": "scoreboard", "is_shown": True, "data": {"sport": "nfl", "state": "pre", "away_abbr": "PHI", "home_abbr": "WAS"}},
        ]
    }
    live_only = select_display_content(content, {"mode": "sports", "sports_filter": "live"})
    my_teams = select_display_content(content, {"mode": "sports", "sports_filter": "my_teams", "my_teams": ["nfl:WAS"]})
    pinned = select_display_content(content, {"mode": "sports", "pinned_content_id": "scheduled"})

    assert [item["is_shown"] for item in live_only["sports"]] == [True, False]
    assert [item["is_shown"] for item in my_teams["sports"]] == [False, True]
    assert [item["is_shown"] for item in pinned["sports"]] == [False, True]

    response = TickerResponse.from_payload({
        "api_version": "v2",
        "snapshot": {"ticker_id": "ticker-1", "revision": 1, "observed_at": "2026-08-11T00:00:00+00:00", "stale": False},
        "settings": {"mode": "sports", "sports_presentation": "pinned", "pinned_content_id": "scheduled", "brightness": 100, "scroll_speed": 0.05, "inverted": False},
        "content": pinned,
        "events": {"alerts": [], "news": []},
        "health": {"provider": "test", "healthy": True, "error": None},
        "meta": {"pairing": {"paired": True, "code": None}},
    })
    classified = classify_content(response.content, "sports", sports_presentation="pinned", pinned_content_id="scheduled")

    assert [item.id for item in classified.static] == ["scheduled"]
