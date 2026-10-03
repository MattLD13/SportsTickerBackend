"""Verify NHL trade news against the dated league tracker."""

from datetime import datetime, timezone

import pytest

from sports_ticker.providers.news_transactions import NhlTradeTrackerSource


pytestmark = pytest.mark.critical


_TRACKER = """
**OCTOBER 1:** Philadelphia Flyers acquire forward David Goyette from the Seattle Kraken for forward Devin Kaplan. | **[Goyette traded to Flyers by Kraken](https://www.nhl.com/flyers/news/flyers-acquire-david-goyette-from-seattle)**
**SEPTEMBER 28:** Toronto Maple Leafs acquire forward Kirill Marchenko from the Columbus Blue Jackets for a second-round pick. | **[Marchenko traded to Maple Leafs](https://www.nhl.com/news/marchenko-traded)**
"""


class TrackerClient:
    """Return one stable NHL trade tracker sample."""

    def __init__(self, text: str = _TRACKER) -> None:
        self.text = text
        self.calls = 0
        self.url = ""

    def get_text(self, url: str, *, timeout: float) -> str:
        del timeout
        self.calls += 1
        self.url = url
        return self.text


_TEAM_NAMES = {
    "Philadelphia Flyers": "PHI",
    "Seattle Kraken": "SEA",
    "Toronto Maple Leafs": "TOR",
    "Columbus Blue Jackets": "CBJ",
}


def _source(client: TrackerClient | None = None) -> NhlTradeTrackerSource:
    return NhlTradeTrackerSource(
        lambda league: _TEAM_NAMES if league == "nhl" else {},
        client=client or TrackerClient(),
        clock=lambda: 100.0,
        cache_seconds=300.0,
        max_age_days=2,
    )


def test_tracker_confirms_recent_trade_with_both_teams_and_official_link() -> None:
    client = TrackerClient()
    source = _source(client)
    now = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)

    trade = source.confirm_trade(
        "nhl",
        ("David Goyette",),
        ("SEA", "PHI"),
        now=now,
    )

    assert trade is not None
    assert trade.from_abbr == "SEA"
    assert trade.to_abbr == "PHI"
    assert trade.occurred_at.isoformat() == "2026-10-01"
    assert trade.source_url == "https://www.nhl.com/flyers/news/flyers-acquire-david-goyette-from-seattle"
    assert "2026-27-nhl-trades" in client.url


def test_tracker_rejects_old_and_unrelated_articles() -> None:
    source = _source()
    now = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)

    assert source.confirm_trade("nhl", ("Kirill Marchenko",), ("TOR", "CBJ"), now=now) is None
    assert source.confirm_trade("nhl", ("Dylan Larkin",), ("DET", "NYR"), now=now) is None
    assert source.confirm_trade("nba", ("David Goyette",), ("SEA", "PHI"), now=now) is None
