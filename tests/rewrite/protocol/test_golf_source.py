"""Verify golf brand and current-day tournament filtering."""

from datetime import datetime, timezone
from sports_ticker.domain import DisplaySettings
from sports_ticker.providers.live_sources import EspnGolfSource, _golf_brand, _is_current_golf_event


class MockHttpClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def get_json(self, url: str, *, timeout: float):
        del url, timeout
        self.calls += 1
        return self.payload


def _sample_golf_payload(*, state: str = "pre", date: str = "2026-08-20T04:00Z", end_date: str = "2026-08-24T03:59Z") -> dict:
    return {
        "events": [
            {
                "id": "401811963",
                "name": "BMW Championship",
                "date": date,
                "endDate": end_date,
                "status": {"type": {"state": state, "shortDetail": "8/20 - 12:00 AM EDT"}},
                "competitions": [
                    {
                        "date": date,
                        "endDate": end_date,
                        "status": {"type": {"state": state, "shortDetail": "8/20 - 12:00 AM EDT"}},
                        "competitors": [
                            {
                                "score": "E",
                                "athlete": {"displayName": "Justin Thomas"},
                                "linescores": [],
                            }
                        ],
                    }
                ],
            }
        ]
    }


def test_golf_source_assigns_masters_or_pga_brand() -> None:
    assert _golf_brand("Masters Tournament") == "masters"
    assert _golf_brand("PGA Championship") == "pga"


def test_golf_source_excludes_future_tournament_before_start_day() -> None:
    # Current time: 2026-08-19 14:40 EDT (18:40 UTC)
    now = datetime(2026, 8, 19, 18, 40, tzinfo=timezone.utc)
    settings = DisplaySettings(timezone="America/New_York")
    client = MockHttpClient(_sample_golf_payload(state="pre", date="2026-08-20T04:00Z"))
    source = EspnGolfSource(client=client, now=lambda: now)

    result = source.fetch(settings)

    assert result == {"content": []}


def test_golf_source_includes_pre_tournament_on_start_day() -> None:
    # Current time: 2026-08-20 07:00 EDT (11:00 UTC)
    now = datetime(2026, 8, 20, 11, 0, tzinfo=timezone.utc)
    settings = DisplaySettings(timezone="America/New_York")
    client = MockHttpClient(_sample_golf_payload(state="pre", date="2026-08-20T04:00Z"))
    source = EspnGolfSource(client=client, now=lambda: now)

    result = source.fetch(settings)

    assert len(result["content"]) == 1
    assert result["content"][0]["id"] == "golf:401811963"


def test_golf_source_includes_live_tournament() -> None:
    # Current time: 2026-08-21 14:00 EDT (18:00 UTC)
    now = datetime(2026, 8, 21, 18, 0, tzinfo=timezone.utc)
    settings = DisplaySettings(timezone="America/New_York")
    client = MockHttpClient(_sample_golf_payload(state="in", date="2026-08-20T04:00Z"))
    source = EspnGolfSource(client=client, now=lambda: now)

    result = source.fetch(settings)

    assert len(result["content"]) == 1
    assert result["content"][0]["id"] == "golf:401811963"


def test_golf_source_reads_once_for_many_tickers_in_one_refresh() -> None:
    now = datetime(2026, 8, 21, 18, 0, tzinfo=timezone.utc)
    settings = DisplaySettings(timezone="America/New_York")
    client = MockHttpClient(_sample_golf_payload(state="in", date="2026-08-20T04:00Z"))
    source = EspnGolfSource(client=client, now=lambda: now)

    for _ in range(100):
        source.fetch(settings)

    assert client.calls == 1

