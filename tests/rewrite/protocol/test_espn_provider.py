"""Verify ESPN calendar reads and canonical scoreboard filtering."""

from datetime import datetime, timezone
from threading import Barrier
from urllib.parse import parse_qs, urlsplit

import pytest

from sports_ticker.domain import DisplaySettings
from sports_ticker.providers.espn import (
    EspnScoreboardProvider,
    _scoreboard_url_for_dates,
    _summary_event,
    _summary_scoring_details,
)


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
    def __init__(
        self,
        responses: dict[str, dict],
        failures: set[str] | None = None,
        summary_responses: dict[str, dict] | None = None,
    ) -> None:
        self.responses = responses
        self.failures = failures or set()
        self.summary_responses = summary_responses or {}
        self.urls: list[str] = []

    def get_json(self, url: str, *, timeout: float):
        del timeout
        self.urls.append(url)
        if "/summary" in url:
            event_id = parse_qs(urlsplit(url).query)["event"][0]
            return self.summary_responses.get(event_id, {})
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


def test_espn_source_reads_once_for_any_number_of_tickers() -> None:
    client = RecordingClient({"20260816-20260817": {"events": []}})
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/football/nfl/scoreboard"},
        client=client,
        now=lambda: datetime(2026, 8, 16, 7, tzinfo=timezone.utc),
    )

    for ticker_index in range(100):
        provider.fetch_for_ticker(f"ticker-{ticker_index}", _settings())

    assert len(client.urls) == 1


def test_espn_scoreboard_leagues_read_concurrently() -> None:
    class BlockingClient(RecordingClient):
        def __init__(self) -> None:
            super().__init__({"20260816-20260817": {"events": []}})
            self.barrier = Barrier(3)

        def get_json(self, url: str, *, timeout: float):
            self.urls.append(url)
            self.barrier.wait(timeout=2)
            del timeout
            return {"events": []}

    client = BlockingClient()
    provider = EspnScoreboardProvider(
        {
            "nfl": "https://example.test/football/nfl/scoreboard",
            "mlb": "https://example.test/baseball/mlb/scoreboard",
            "nhl": "https://example.test/hockey/nhl/scoreboard",
        },
        client=client,
        now=lambda: datetime(2026, 8, 16, 7, tzinfo=timezone.utc),
    )

    result = provider.fetch(_settings())

    assert result.health.healthy is True
    assert len(client.urls) == 3


def test_espn_schedule_cache_refreshes_only_at_kickoff_or_during_live_play() -> None:
    client = RecordingClient(
        {
            "20260816-20260817": {
                "events": [_event("game-scheduled", "2026-08-16T18:00:00Z")]
            }
        }
    )
    current = [datetime(2026, 8, 16, 7, tzinfo=timezone.utc)]
    monotonic = [0.0]
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/football/nfl/scoreboard"},
        client=client,
        now=lambda: current[0],
        monotonic=lambda: monotonic[0],
    )

    provider.fetch_for_ticker("ticker-one", _settings())
    monotonic[0] = 6.0
    provider.fetch_for_ticker("ticker-two", _settings())
    assert len(client.urls) == 1

    current[0] = datetime(2026, 8, 16, 18, 1, tzinfo=timezone.utc)
    monotonic[0] = 12.0
    provider.fetch_for_ticker("ticker-three", _settings())

    assert len(client.urls) == 2


def test_espn_live_refresh_reads_one_summary_for_one_live_game_in_large_schedule() -> None:
    events = [_event("game-0", "2026-08-16T18:00:00Z")]
    events.extend(_event(f"game-{index}", "2026-08-16T19:00:00Z") for index in range(1, 100))
    live_competition = dict(events[0]["competitions"][0])
    live_competition["status"] = {
        "type": {"state": "in", "shortDetail": "Top 1st"}
    }
    live_competition["competitors"] = [
        {**dict(competitor), "score": "1"}
        if competitor["homeAway"] == "home"
        else dict(competitor)
        for competitor in live_competition["competitors"]
    ]
    client = RecordingClient(
        {"20260816-20260817": {"events": events}},
        summary_responses={
            "game-0": {
                "header": {"id": "game-0", "competitions": [live_competition]}
            }
        },
    )
    current = [datetime(2026, 8, 16, 7, tzinfo=timezone.utc)]
    monotonic = [0.0]
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/football/nfl/scoreboard"},
        client=client,
        now=lambda: current[0],
        monotonic=lambda: monotonic[0],
    )

    provider.fetch_for_ticker("ticker-one", _settings())
    current[0] = datetime(2026, 8, 16, 18, 1, tzinfo=timezone.utc)
    monotonic[0] = 6.0
    result = provider.fetch_for_ticker("ticker-two", _settings())

    assert sum("/scoreboard" in url for url in client.urls) == 1
    assert sum("/summary" in url for url in client.urls) == 1
    live_item = next(item for item in result.content if item.id == "game-0")
    assert live_item.data["state"] == "in"
    assert live_item.data["home_score"] == "1"


def test_espn_five_live_games_use_one_scoreboard_refresh() -> None:
    events = [_event(f"game-{index}", "2026-08-16T18:00:00Z") for index in range(5)]

    class ChangingClient(RecordingClient):
        def __init__(self) -> None:
            super().__init__({"20260816-20260817": {"events": events}})
            self.scoreboard_calls = 0

        def get_json(self, url: str, *, timeout: float):
            if "/summary" in url:
                raise AssertionError("five live games must use one scoreboard request")
            self.scoreboard_calls += 1
            del timeout
            self.urls.append(url)
            if self.scoreboard_calls == 1:
                return {"events": events}
            return {
                "events": [
                    _event(event["id"], event["date"], state="in")
                    for event in events
                ]
            }

    client = ChangingClient()
    current = [datetime(2026, 8, 16, 7, tzinfo=timezone.utc)]
    monotonic = [0.0]
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/football/nfl/scoreboard"},
        client=client,
        now=lambda: current[0],
        monotonic=lambda: monotonic[0],
    )

    provider.fetch_for_ticker("ticker-one", _settings())
    current[0] = datetime(2026, 8, 16, 18, 1, tzinfo=timezone.utc)
    monotonic[0] = 6.0
    result = provider.fetch_for_ticker("ticker-two", _settings())

    assert client.scoreboard_calls == 2
    assert sum("/summary" in url for url in client.urls) == 0
    assert {item.data["state"] for item in result.content} == {"in"}


@pytest.mark.parametrize("count", (5, 10, 100))
def test_espn_cold_dense_live_set_uses_one_scoreboard_without_summary_fanout(count: int) -> None:
    events = [_event(f"game-{index}", "2026-08-16T18:00:00Z", state="in") for index in range(count)]
    client = RecordingClient({"20260816-20260817": {"events": events}})
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/football/nfl/scoreboard"},
        client=client,
        now=lambda: datetime(2026, 8, 16, 18, 1, tzinfo=timezone.utc),
        monotonic=lambda: 0.0,
    )

    result = provider.fetch_for_ticker("ticker-one", _settings())

    assert len(result.content) == count
    assert sum("/scoreboard" in url for url in client.urls) == 1
    assert sum("/summary" in url for url in client.urls) == 0


def test_espn_sparse_summary_requests_deduplicate_event_ids() -> None:
    duplicate = _event("game-1", "2026-08-16T18:00:00Z", state="in")
    client = RecordingClient(
        {"20260816-20260817": {"events": [duplicate, dict(duplicate)]}},
        summary_responses={"game-1": {}},
    )
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/football/nfl/scoreboard"},
        client=client,
        now=lambda: datetime(2026, 8, 16, 18, 1, tzinfo=timezone.utc),
        monotonic=lambda: 0.0,
    )

    provider.fetch_for_ticker("ticker-one", _settings())

    assert sum("/summary" in url for url in client.urls) == 1


def test_espn_summary_merge_preserves_scoreboard_fields_and_live_state() -> None:
    fallback = _event("game-1", "2026-08-16T18:00:00Z", state="in")
    fallback["competitions"][0]["situation"] = {
        "possession": {"team": {"abbreviation": "NYG"}},
        "down": 2,
        "distance": 7,
    }
    fallback["competitions"][0]["competitors"][0]["team"]["logo"] = "scoreboard-logo"
    summary = {
        "header": {
            "competitions": [{
                "status": {"type": {"state": "pre", "shortDetail": "Scheduled"}},
                "competitors": [{
                    "homeAway": "home",
                    "score": "7",
                    "team": {"abbreviation": "NYG"},
                }],
            }],
        },
        "situation": {"clock": "08:00"},
    }

    merged = _summary_event(summary, fallback)
    competition = merged["competitions"][0]

    assert merged["status"]["type"]["state"] == "in"
    assert competition["situation"] == {
        "possession": {"team": {"abbreviation": "NYG"}},
        "down": 2,
        "distance": 7,
        "clock": "08:00",
    }
    assert competition["competitors"][0]["team"]["logo"] == "scoreboard-logo"
    assert competition["competitors"][0]["score"] == "7"


def test_espn_summary_merge_preserves_final_state() -> None:
    fallback = _event("game-1", "2026-08-16T18:00:00Z", state="post")
    summary = {
        "header": {
            "competitions": [{
                "status": {"type": {"state": "pre", "shortDetail": "Scheduled"}},
            }],
        },
    }

    merged = _summary_event(summary, fallback)

    assert merged["status"]["type"]["state"] == "post"


def test_espn_summary_failure_keeps_scoreboard_healthy() -> None:
    events = [
        _event("nfl-1", "2026-08-16T18:00:00Z", state="in"),
        _event("mlb-1", "2026-08-16T18:00:00Z", state="in"),
    ]
    phase = ["baseline", "failed", "recovered"]

    def summary(event_id: str) -> dict:
        if phase[0] == "failed" and event_id == "mlb-1":
            raise RuntimeError("summary unavailable")
        score = "14" if phase[0] != "baseline" and event_id == "nfl-1" else "0"
        event = next(item for item in events if item["id"] == event_id)
        competition = dict(event["competitions"][0])
        competition["competitors"] = [
            {**dict(competitor), "score": score if competitor["homeAway"] == "home" else "0"}
            for competitor in competition["competitors"]
        ]
        competition["status"] = {"type": {"state": "in", "shortDetail": "Q1 08:00"}}
        return {"header": {"competitions": [competition]}}

    class SummaryClient(RecordingClient):
        def get_json(self, url: str, *, timeout: float):
            del timeout
            self.urls.append(url)
            if "/summary" in url:
                event_id = parse_qs(urlsplit(url).query)["event"][0]
                return summary(event_id)
            event = events[0] if "/football/" in url else events[1]
            return {"events": [event]}

    client = SummaryClient({})
    current = [datetime(2026, 8, 16, 18, 1, tzinfo=timezone.utc)]
    monotonic = [0.0]
    provider = EspnScoreboardProvider(
        {
            "nfl": "https://example.test/football/nfl/scoreboard",
            "mlb": "https://example.test/baseball/mlb/scoreboard",
        },
        client=client,
        now=lambda: current[0],
        monotonic=lambda: monotonic[0],
    )
    settings = DisplaySettings(
        active_sports={"nfl": True, "mlb": True},
        my_teams=("nfl:NYG",),
    )

    provider.fetch_for_ticker("ticker-one", settings)
    phase[0] = "failed"
    monotonic[0] = 6.0
    failed = provider.fetch_for_ticker("ticker-one", settings)
    phase[0] = "recovered"
    monotonic[0] = 12.0
    recovered = provider.fetch_for_ticker("ticker-one", settings)

    assert failed.health.healthy is True
    assert len(failed.alerts) == 1
    assert failed.alerts[0]["home_score"] == 14
    assert len(recovered.alerts) == 1
    assert recovered.alerts[0]["id"] == failed.alerts[0]["id"]


def test_espn_failed_scoreboard_poll_does_not_advance_alert_memory() -> None:
    events = [
        _event("nfl-1", "2026-08-16T18:00:00Z", state="in"),
        _event("mlb-1", "2026-08-16T18:00:00Z", state="in"),
    ]
    scores = [0, 14, 14]
    scoreboard_pass = [0]

    class PartialClient(RecordingClient):
        def get_json(self, url: str, *, timeout: float):
            del timeout
            self.urls.append(url)
            if "/summary" in url:
                return {}
            if scoreboard_pass[0] == 1 and "/baseball/" in url:
                raise RuntimeError("scoreboard unavailable")
            score = scores[scoreboard_pass[0]]
            event = events[0] if "/football/" in url else events[1]
            return {"events": [{
                **dict(event),
                "competitions": [{
                    **dict(event["competitions"][0]),
                    "competitors": [
                        {
                            **dict(competitor),
                            "score": str(score if competitor["homeAway"] == "home" else 0),
                        }
                        for competitor in event["competitions"][0]["competitors"]
                    ],
                }],
            }]}

    client = PartialClient({})
    provider = EspnScoreboardProvider(
        {
            "nfl": "https://example.test/football/nfl/scoreboard",
            "mlb": "https://example.test/baseball/mlb/scoreboard",
        },
        client=client,
        now=lambda: datetime(2026, 8, 16, 18, 1, tzinfo=timezone.utc),
    )
    settings = DisplaySettings(
        active_sports={"nfl": True, "mlb": True},
        my_teams=("nfl:NYG",),
    )

    provider.fetch(settings)
    scoreboard_pass[0] = 1
    failed = provider.fetch(settings)
    scoreboard_pass[0] = 2
    recovered = provider.fetch(settings)

    assert failed.health.healthy is False
    assert failed.alerts == ()
    assert len(recovered.alerts) == 1
    assert recovered.alerts[0]["home_score"] == 14


def test_espn_discovery_refresh_finds_new_games_after_sixty_seconds() -> None:
    first = [_event("game-1", "2026-08-16T18:00:00Z")]
    second = first + [_event("game-2", "2026-08-16T19:00:00Z")]

    class ChangingClient(RecordingClient):
        def __init__(self) -> None:
            super().__init__({})
            self.responses = iter((first, second))

        def get_json(self, url: str, *, timeout: float):
            del timeout
            self.urls.append(url)
            return {"events": next(self.responses)}

    client = ChangingClient()
    monotonic = [0.0]
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/football/nfl/scoreboard"},
        client=client,
        now=lambda: datetime(2026, 8, 16, 7, tzinfo=timezone.utc),
        monotonic=lambda: monotonic[0],
    )

    provider.fetch_for_ticker("ticker-one", _settings())
    monotonic[0] = 60.0
    result = provider.fetch_for_ticker("ticker-two", _settings())

    assert len(client.urls) == 2
    assert {item.id for item in result.content} == {"game-1", "game-2"}


def test_espn_summary_updates_do_not_reset_discovery_age() -> None:
    event = _event("game-1", "2026-08-16T18:00:00Z")
    client = RecordingClient(
        {"20260816-20260817": {"events": [event]}},
        summary_responses={"game-1": {}},
    )
    current = [datetime(2026, 8, 16, 7, tzinfo=timezone.utc)]
    monotonic = [0.0]
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/football/nfl/scoreboard"},
        client=client,
        now=lambda: current[0],
        monotonic=lambda: monotonic[0],
    )
    key = ("America/New_York", "nfl", datetime(2026, 8, 16, 7, tzinfo=timezone.utc).date())

    provider.fetch_for_ticker("ticker-one", _settings())
    original_discovery_at = provider._league_schedules[key].discovery_at
    current[0] = datetime(2026, 8, 16, 18, 1, tzinfo=timezone.utc)
    monotonic[0] = 6.0
    provider.fetch_for_ticker("ticker-two", _settings())

    assert provider._league_schedules[key].discovery_at == original_discovery_at


def test_espn_source_cache_timestamp_starts_after_network_completion() -> None:
    monotonic = [0.0]

    class SlowClient(RecordingClient):
        def get_json(self, url: str, *, timeout: float):
            del timeout
            self.urls.append(url)
            monotonic[0] = 6.0
            return {"events": []}

    client = SlowClient({})
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/football/nfl/scoreboard"},
        client=client,
        now=lambda: datetime(2026, 8, 16, 7, tzinfo=timezone.utc),
        monotonic=lambda: monotonic[0],
    )

    provider.fetch_for_ticker("ticker-one", _settings())
    monotonic[0] = 6.5
    provider.fetch_for_ticker("ticker-two", _settings())

    assert len(client.urls) == 1


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


def test_espn_summary_scoring_details_normalize_team_and_scorer() -> None:
    payload = {
        "header": {
            "competitions": [{
                "competitors": [
                    {"homeAway": "home", "team": {"id": "10", "abbreviation": "BOS"}},
                    {"homeAway": "away", "team": {"id": "20", "abbreviation": "NYY"}},
                ]
            }]
        },
        "scoringPlays": [{
            "team": {"id": "20"},
            "athlete": {"displayName": "Aaron Judge"},
            "scoringType": {"displayName": "Home Run"},
            "shortText": "Aaron Judge homers to left field",
        }],
    }

    details = _summary_scoring_details(
        payload,
        {"home_abbr": "BOS", "away_abbr": "NYY"},
    )

    assert details["scoring_plays"] == [{
        "team": "NYY",
        "scorer": "JUDGE",
        "player": "JUDGE",
        "type": "Home Run",
        "text": "Aaron Judge homers to left field",
    }]
