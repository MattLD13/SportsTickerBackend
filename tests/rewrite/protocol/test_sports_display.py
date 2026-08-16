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


def test_finished_game_has_no_live_play_context() -> None:
    ended = SportsDisplayProjector().project(
        _item("ended", "nfl", "post"),
        _event("FINAL", {"possession": "2", "down": 3, "distance": 4, "isRedZone": True}, "post"),
    )

    assert ended.data["situation"] == {}


def test_soccer_clock_has_one_apostrophe_without_provider_spacing() -> None:
    event = _event("93'", {}, "in")
    event["status"]["displayClock"] = "93\u200e�\u200e'"

    soccer = SportsDisplayProjector().project(_item("soccer", "soccer_champ"), event)

    assert soccer.data["status"] == "93'"


@pytest.mark.parametrize(
    ("provider_clock", "status"),
    (
        ("45:00 + 1:12", "45'+1:12'"),
        ("90:00 + 1:18", "90'+1:18'"),
    ),
)
def test_soccer_clock_keeps_stoppage_minutes_and_seconds(provider_clock: str, status: str) -> None:
    """Keep the regulation minute and precise stoppage clock in one shared label."""

    assert normalize_soccer_clock(provider_clock) == status
