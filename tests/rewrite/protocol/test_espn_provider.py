"""Verify ESPN calendar reads and canonical scoreboard filtering."""

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from sports_ticker.domain import DisplaySettings
from sports_ticker.providers.espn import EspnScoreboardProvider, _scoreboard_url_for_dates


def _event(event_id: str, start: str, *, state: str = "pre") -> dict:
    return {
        "id": event_id,
        "date": start,
        "status": {"type": {"state": state, "shortDetail": "Scheduled"}},
        "competitions": [
            {
                "competitors": [
                    {
                        "homeAway": "home",
                        "score": "0",
                        "team": {"abbreviation": "NYG", "color": "0B2265", "alternateColor": "A71930"},
                    },
                    {
                        "homeAway": "away",
                        "score": "0",
                        "team": {"abbreviation": "DAL", "color": "041E42", "alternateColor": "869397"},
                    },
                ]
            }
        ],
    }


class RecordingClient:
    def __init__(self, responses: dict[str, dict], failures: set[str] | None = None) -> None:
        self.responses = responses
        self.failures = failures or set()
        self.urls: list[str] = []

    def get_json(self, url: str, *, timeout: float):
        del timeout
        self.urls.append(url)
        dates = parse_qs(urlsplit(url).query)["dates"][0]
        if dates in self.failures:
            raise RuntimeError(f"failed {dates}")
        return self.responses.get(dates, {"events": []})


def _settings() -> DisplaySettings:
    return DisplaySettings(timezone="America/New_York")


def test_espn_after_three_requests_current_date_and_accepts_event() -> None:
    client = RecordingClient(
        {
            "20260816-20260817": {
                "events": [_event("game-current", "2026-08-16T15:00:00Z")]
            }
        }
    )
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/football/nfl/scoreboard"},
        client=client,
        now=lambda: datetime(2026, 8, 16, 7, tzinfo=timezone.utc),
    )

    result = provider.fetch(_settings())

    assert len(client.urls) == 1
    assert parse_qs(urlsplit(client.urls[0]).query)["dates"] == ["20260816-20260817"]
    assert [item.id for item in result.content] == ["game-current"]
    assert result.health.healthy is True


def test_espn_after_three_keeps_next_local_day_event_inside_window() -> None:
    client = RecordingClient(
        {
            "20260816-20260817": {
                "events": [_event("game-next", "2026-08-17T06:00:00Z")]
            }
        }
    )
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/football/nfl/scoreboard"},
        client=client,
        now=lambda: datetime(2026, 8, 16, 7, tzinfo=timezone.utc),
    )

    result = provider.fetch(_settings())

    assert [item.id for item in result.content] == ["game-next"]
    assert result.health.healthy is True


def test_espn_before_three_requests_prior_and_current_local_dates() -> None:
    client = RecordingClient(
        {
            "20260815-20260816": {
                "events": [
                    _event("game-prior", "2026-08-15T23:00:00Z"),
                    _event("game-current", "2026-08-16T05:00:00Z"),
                ]
            },
        }
    )
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/football/nfl/scoreboard"},
        client=client,
        now=lambda: datetime(2026, 8, 16, 6, 59, tzinfo=timezone.utc),
    )

    result = provider.fetch(_settings())

    assert len(client.urls) == 1
    assert parse_qs(urlsplit(client.urls[0]).query)["dates"] == ["20260815-20260816"]
    assert {item.id for item in result.content} == {"game-prior", "game-current"}


def test_espn_date_query_preserves_existing_parameters() -> None:
    url = _scoreboard_url_for_dates(
        "https://example.test/football/college-football/scoreboard?groups=80&limit=100&dates=19990101",
        (datetime(2026, 8, 16, tzinfo=timezone.utc).date(),),
    )
    query = parse_qs(urlsplit(url).query)

    assert query == {"groups": ["80"], "limit": ["100"], "dates": ["20260816"]}


def test_espn_overlapping_date_payloads_do_not_duplicate_events() -> None:
    duplicate = _event("same-game", "2026-08-16T05:00:00Z")
    client = RecordingClient(
        {"20260815-20260816": {"events": [duplicate, duplicate]}}
    )
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/football/nfl/scoreboard"},
        client=client,
        now=lambda: datetime(2026, 8, 16, 6, tzinfo=timezone.utc),
    )

    result = provider.fetch(_settings())

    assert [item.id for item in result.content] == ["same-game"]


def test_espn_empty_date_response_is_healthy_and_empty() -> None:
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/football/nfl/scoreboard"},
        client=RecordingClient({"20260816-20260817": {"events": []}}),
        now=lambda: datetime(2026, 8, 16, 7, tzinfo=timezone.utc),
    )

    result = provider.fetch(_settings())

    assert result.content == ()
    assert result.health.healthy is True


def test_espn_failed_date_requests_return_unhealthy_stale_contract() -> None:
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/football/nfl/scoreboard"},
        client=RecordingClient({}, failures={"20260816-20260817"}),
        now=lambda: datetime(2026, 8, 16, 7, tzinfo=timezone.utc),
    )

    result = provider.fetch(_settings())

    assert result.content == ()
    assert result.health.healthy is False
    assert result.health.error is not None
    assert result.health.error.startswith("stale:")


def test_espn_missing_event_id_is_unhealthy() -> None:
    client = RecordingClient(
        {"20260816-20260817": {"events": [_event("", "2026-08-16T15:00:00Z")]}}
    )
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/football/nfl/scoreboard"},
        client=client,
        now=lambda: datetime(2026, 8, 16, 7, tzinfo=timezone.utc),
    )

    result = provider.fetch(_settings())

    assert result.content == ()
    assert result.health.healthy is False
    assert result.health.error is not None
    assert "nfl event: event id is missing" in result.health.error
