"""Validate the canonical version two display projection."""

from datetime import datetime, timezone

from sports_ticker.domain import DisplaySettings, TickerSnapshot
from sports_ticker.providers.contracts import ProviderHealth
from sports_ticker.projections import project_data_v2
from ticker_core.protocol import TickerResponse


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
