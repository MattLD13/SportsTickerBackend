"""Verify golf brand and current-day tournament filtering."""

from datetime import datetime, timezone

import pytest

from sports_ticker.domain import DisplaySettings
from sports_ticker.providers.golf_source import EspnGolfSource, _golf_brand, _is_current_golf_event
from sports_ticker.providers.sports_display import golf_short_name


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
    assert result["content"][0]["startTimeUTC"] == "2026-08-20T04:00:00+00:00"


def test_golf_source_includes_live_tournament() -> None:
    # Current time: 2026-08-21 14:00 EDT (18:00 UTC)
    now = datetime(2026, 8, 21, 18, 0, tzinfo=timezone.utc)
    settings = DisplaySettings(timezone="America/New_York")
    client = MockHttpClient(_sample_golf_payload(state="in", date="2026-08-20T04:00Z"))
    source = EspnGolfSource(client=client, now=lambda: now)

    result = source.fetch(settings)

    assert len(result["content"]) == 1
    assert result["content"][0]["id"] == "golf:401811963"


def test_golf_source_projects_presidents_cup_team_score_and_matches() -> None:
    now = datetime(2026, 9, 27, 18, 0, tzinfo=timezone.utc)
    settings = DisplaySettings(timezone="America/New_York")
    payload = {
        "events": [{
            "id": "401824815",
            "name": "Presidents Cup",
            "shortName": "Presidents Cup",
            "date": "2026-09-24T04:00Z",
            "endDate": "2026-09-28T03:59Z",
            "status": {"type": {"state": "in"}},
            "season": {"year": 2026},
            "competitions": [
                {
                    "type": {"id": "1"},
                    "status": {"type": {"state": "in", "shortDetail": "Round 0 - In Progress"}},
                    "competitors": [
                        {"type": "team", "team": {"abbreviation": "USA", "shortDisplayName": "USA"}, "score": "7.5"},
                        {"type": "team", "team": {"abbreviation": "INTL", "shortDisplayName": "International"}, "score": "10.5"},
                    ],
                },
                {
                    "type": {"id": "3"},
                    "status": {"type": {"state": "pre", "shortDetail": "Scheduled"}},
                    "competitors": [
                        {"type": "athlete", "team": {"abbreviation": "USA"}, "athlete": {"displayName": "Cameron Young"}, "score": ""},
                        {"type": "athlete", "team": {"abbreviation": "INTL"}, "athlete": {"displayName": "Ryo Hisatsune"}, "score": ""},
                    ],
                },
            ],
        }]
    }
    source = EspnGolfSource(client=MockHttpClient(payload), now=lambda: now)

    item = source.fetch(settings)["content"][0]

    assert item["golf"]["format"] == "match_play"
    assert item["status"] == "Match Play"
    assert item["golf"]["teams"] == [
        {"abbr": "USA", "name": "USA", "score": "7.5"},
        {"abbr": "INTL", "name": "International", "score": "10.5"},
    ]
    assert item["golf"]["matches"][0]["sides"] == [
        {"team": "USA", "player": "Cameron Young", "score": ""},
        {"team": "INTL", "player": "Ryo Hisatsune", "score": ""},
    ]
    assert item["golf"]["matches"][0]["type"] == "3"


def test_golf_source_reads_once_for_many_tickers_in_one_refresh() -> None:
    now = datetime(2026, 8, 21, 18, 0, tzinfo=timezone.utc)
    settings = DisplaySettings(timezone="America/New_York")
    client = MockHttpClient(_sample_golf_payload(state="in", date="2026-08-20T04:00Z"))
    source = EspnGolfSource(client=client, now=lambda: now)

    for _ in range(100):
        source.fetch(settings)

    assert client.calls == 1



@pytest.mark.parametrize(("name", "short"), [
    # Real PGA TOUR 2026 calendar labels from ESPN.
    ("Austin Championship pres. by Compliance Solutions", "Austin Championship"),
    ("the Memorial Tournament pres. by Workday", "Memorial"),
    ("PGA TOUR Q-School presented by Korn Ferry", "PGA TOUR Q-School"),
    ("Sony Open in Hawaii", "Sony Open"),
    ("Cognizant Classic in The Palm Beaches", "Cognizant Classic"),
    ("Zurich Classic of New Orleans", "Zurich Classic"),
    ("THE PLAYERS Championship", "PLAYERS Championship"),
    ("The RSM Classic", "RSM Classic"),
    ("Masters Tournament", "Masters"),
    ("The Open", "The Open"),
    ("The Sentry", "The Sentry"),
    ("Bank of Utah Championship", "Bank of Utah Championship"),
    ("U.S. Open", "U.S. Open"),
    ("", ""),
])
def test_golf_short_name_removes_words_that_do_not_identify_the_event(name, short) -> None:
    assert golf_short_name(name) == short


def test_golf_source_shows_the_short_event_name_and_keeps_the_brand() -> None:
    now = datetime(2026, 8, 21, 18, 0, tzinfo=timezone.utc)
    payload = _sample_golf_payload(state="in", date="2026-08-20T04:00Z")
    payload["events"][0]["name"] = "the Memorial Tournament pres. by Workday"
    payload["events"][0]["shortName"] = "the Memorial Tournament pres. by Workday"
    source = EspnGolfSource(client=MockHttpClient(payload), now=lambda: now)

    item = source.fetch(DisplaySettings(timezone="America/New_York"))["content"][0]

    assert item["away_abbr"] == "Memorial"
    assert item["golf"]["event_name"] == "Memorial"
    assert item["golf"]["brand"] == "pga"
