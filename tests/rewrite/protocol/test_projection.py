"""Validate the canonical version two display projection."""

from datetime import datetime, timezone
import pytest

from sports_ticker.domain import DisplaySettings, TickerSnapshot
from sports_ticker.providers.contracts import ProviderHealth
from sports_ticker.projections import project_data_v2, select_display_content
from ticker_core.protocol import TickerResponse

pytestmark = pytest.mark.critical


def test_provider_overlays_use_the_v2_event_envelope() -> None:
    snapshot = TickerSnapshot(
        ticker_id="ticker-1",
        revision=1,
        observed_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
        content=(),
        alerts=({"id": "alert-1", "headline": "TOUCHDOWN"},),
        news=({"id": "news-1", "text": "Giants prepare for Sunday matchup"},),
        effective_settings=DisplaySettings(),
    )

    data = project_data_v2(snapshot, ProviderHealth(provider="test"), {"stale": False})

    assert data["events"] == {
        "alerts": [
            {
                "event_id": "alert-1",
                "kind": "score_alert",
                "payload": {"id": "alert-1", "headline": "TOUCHDOWN"},
            }
        ],
        "news": [
            {
                "event_id": "news-1",
                "kind": "news",
                "payload": {"id": "news-1", "text": "Giants prepare for Sunday matchup"},
            }
        ],
    }
    response = TickerResponse.from_payload(data)
    assert response.news[0].id == "news-1"


def test_my_teams_filter_projection_matches_aliases() -> None:
    from sports_ticker.domain import ContentItem

    item_mls = ContentItem(
        id="mls-1",
        family="sports",
        kind="scoreboard",
        data={"sport": "soccer_mls", "home_abbr": "SEA", "away_abbr": "VAN", "home_score": "1", "away_score": "0"},
        is_shown=True,
    )
    item_nba = ContentItem(
        id="nba-1",
        family="sports",
        kind="scoreboard",
        data={"sport": "nba", "home_abbr": "NYK", "away_abbr": "BOS", "home_score": "100", "away_score": "98"},
        is_shown=True,
    )
    item_mlb = ContentItem(
        id="mlb-1",
        family="sports",
        kind="scoreboard",
        data={"sport": "mlb", "home_abbr": "LAD", "away_abbr": "SF", "home_score": "3", "away_score": "2"},
        is_shown=True,
    )

    settings = DisplaySettings(
        mode="sports",
        sports_filter="my_teams",
        my_teams=("soccer_mls:SEA", "nba:NY"),
    )
    snapshot = TickerSnapshot(
        ticker_id="ticker-1",
        revision=1,
        observed_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
        content=(item_mls, item_nba, item_mlb),
        alerts=(),
        news=(),
        effective_settings=settings,
    )

    data = project_data_v2(snapshot, ProviderHealth(provider="test"), {"stale": False})
    selected = select_display_content(data["content"], data["settings"])
    sports_content = selected["sports"]

    # Seattle Sounders (soccer_mls:SEA) -> visible
    assert sports_content[0]["id"] == "mls-1"
    assert sports_content[0]["is_shown"] is True

    # New York Knicks (nba:NY -> NYK alias) -> visible
    assert sports_content[1]["id"] == "nba-1"
    assert sports_content[1]["is_shown"] is True

    # Dodgers vs Giants (not followed) -> hidden
    assert sports_content[2]["id"] == "mlb-1"
    assert sports_content[2]["is_shown"] is False

