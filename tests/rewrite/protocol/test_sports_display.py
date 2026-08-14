"""Verify shared ownership facts in the backend sports contract."""

from sports_ticker.domain import ContentItem
from sports_ticker.providers.sports_display import SportsDisplayProjector


def _event(detail: str, situation: dict) -> dict:
    return {
        "status": {"type": {"state": "in", "shortDetail": detail}, "period": 2},
        "competitions": [{"situation": situation, "competitors": [
            {"homeAway": "home", "team": {"id": "1", "abbreviation": "HOM"}},
            {"homeAway": "away", "team": {"id": "2", "abbreviation": "AWY"}},
        ]}],
    }


def _item(identifier: str, sport: str) -> ContentItem:
    return ContentItem(identifier, "sports", "scoreboard", True, {
        "sport": sport, "state": "in", "status": "", "home_abbr": "HOM", "away_abbr": "AWY",
    })


def test_active_team_belongs_to_the_backend_sports_contract() -> None:
    projector = SportsDisplayProjector()
    football = projector.project(_item("football", "nfl"), _event("2nd quarter", {"possession": "2"}))
    baseball_top = projector.project(_item("top", "mlb"), _event("Top 5th", {"balls": 3, "strikes": 1, "outs": 2}))
    baseball_bottom = projector.project(_item("bottom", "mlb"), _event("Bottom 5th", {"balls": 1, "strikes": 0, "outs": 0}))

    assert football.data["situation"]["activeTeam"] == "AWY"
    assert baseball_top.data["situation"]["activeTeam"] == "AWY"
    assert baseball_bottom.data["situation"]["activeTeam"] == "HOM"
