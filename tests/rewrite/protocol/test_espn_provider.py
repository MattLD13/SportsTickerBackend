"""Verify ESPN calendar reads and canonical scoreboard filtering."""

from datetime import datetime, timezone
from copy import deepcopy
from threading import Barrier
from urllib.parse import parse_qs, urlsplit

import pytest

from sports_ticker.domain import DisplaySettings
from sports_ticker.providers.espn import (
    EspnScoreboardProvider,
    _scoreboard_url_for_dates,
    _event_detail_url,
    _event_update,
    _event_scoring_details,
    _mlb_event_details,
    _mlb_statsapi_summary,
)


def _event(
    event_id: str,
    start: str,
    *,
    state: str = "pre",
    home_conference_id: str | None = None,
    away_conference_id: str | None = None,
) -> dict:
    home_team = {"abbreviation": "NYG", "color": "0B2265", "alternateColor": "A71930"}
    away_team = {"abbreviation": "DAL", "color": "041E42", "alternateColor": "869397"}
    if home_conference_id is not None:
        home_team["conferenceId"] = home_conference_id
    if away_conference_id is not None:
        away_team["conferenceId"] = away_conference_id
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
                        "team": home_team,
                    },
                    {
                        "homeAway": "away",
                        "score": "0",
                        "team": away_team,
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
        event_updates: dict[str, dict] | None = None,
        rankings: dict | None = None,
        ncaa_schools: list[dict] | None = None,
    ) -> None:
        self.responses = responses
        self.failures = failures or set()
        self.event_updates = event_updates or {}
        self.rankings = rankings or {"rankings": []}
        self.ncaa_schools = ncaa_schools or []
        self.urls: list[str] = []
        self.ranking_urls: list[str] = []
        self.ncaa_school_urls: list[str] = []

    def get_json(self, url: str, *, timeout: float):
        del timeout
        if "/rankings" in url:
            self.ranking_urls.append(url)
            return self.rankings
        if "/schools-index" in url:
            self.ncaa_school_urls.append(url)
            return self.ncaa_schools
        self.urls.append(url)
        if "/scoreboard/" in url:
            event_id = url.rstrip("/").rsplit("/", 1)[-1]
            payload = self.event_updates.get(event_id, {})
            header = payload.get("header", {}) if isinstance(payload, dict) else {}
            competitions = header.get("competitions", []) if isinstance(header, dict) else []
            competition = competitions[0] if competitions else None
            if isinstance(competition, dict):
                return {
                    "id": event_id,
                    "date": competition.get("date"),
                    "status": competition.get("status"),
                    "competitions": [competition],
                }
            return payload
        dates = parse_qs(urlsplit(url).query)["dates"][0]
        if dates in self.failures:
            raise RuntimeError(f"failed {dates}")
        return self.responses.get(dates, {"events": []})


@pytest.mark.parametrize(
    ("league", "team_id", "poll_id", "rank"),
    (("ncf_fbs", "30", "1", 14), ("ncf_fcs", "2329", "20", 11)),
)
def test_college_football_rankings_fill_scoreboard_sentinel(
    league: str,
    team_id: str,
    poll_id: str,
    rank: int,
) -> None:
    event = _event("ranked-game", "2026-08-16T15:00:00Z")
    competitor = event["competitions"][0]["competitors"][0]
    competitor["team"]["id"] = team_id
    competitor["curatedRank"] = {"current": 99}
    client = RecordingClient(
        {"20260816-20260817": {"events": [event]}},
        rankings={
            "rankings": [
                {"id": poll_id, "ranks": [{"current": rank, "team": {"id": team_id}}]}
            ]
        },
    )
    provider = EspnScoreboardProvider(
        {league: "https://example.test/football/college-football/scoreboard"},
        client=client,
        now=lambda: datetime(2026, 8, 16, 7, tzinfo=timezone.utc),
    )

    result = provider.fetch(_settings())

    assert result.content[0].data["home_rank"] == str(rank)
    assert len(client.ranking_urls) == 1


def test_missing_college_logos_use_cached_ncaa_school_index() -> None:
    event = _event("missing-logo-game", "2026-08-16T15:00:00Z")
    home = event["competitions"][0]["competitors"][0]["team"]
    away = event["competitions"][0]["competitors"][1]["team"]
    home.update({"id": "127991", "location": "Roosevelt"})
    away.update({"id": "102071", "location": "Lawrence Tech"})
    client = RecordingClient(
        {"20260816-20260817": {"events": [event]}},
        ncaa_schools=[
            {"slug": "roosevelt", "name": "Roosevelt", "long": "Roosevelt University"},
            {"slug": "lawrence-tech", "name": "Lawrence Tech", "long": "Lawrence Technological University"},
        ],
    )
    provider = EspnScoreboardProvider(
        {"ncf_fcs": "https://example.test/football/college-football/scoreboard"},
        client=client,
        now=lambda: datetime(2026, 8, 16, 7, tzinfo=timezone.utc),
    )

    result = provider.fetch(_settings())

    data = result.content[0].data
    assert data["home_logo"] == (
        "https://wsrv.nl/?url=https%3A%2F%2Fncaa-api.henrygd.me%2Flogo%2Froosevelt.svg%3Fdark%3Dtrue&output=png"
    )
    assert data["away_logo"] == (
        "https://wsrv.nl/?url=https%3A%2F%2Fncaa-api.henrygd.me%2Flogo%2Flawrence-tech.svg%3Fdark%3Dtrue&output=png"
    )
    assert len(client.ncaa_school_urls) == 1

    provider.fetch(_settings())

    assert len(client.ncaa_school_urls) == 1


def _settings() -> DisplaySettings:
    return DisplaySettings(timezone="America/New_York")


def test_cfb_conference_filters_preserve_team_ids_and_keep_mixed_games() -> None:
    hidden = _event(
        "cfb-hidden",
        "2026-08-16T15:00:00Z",
        home_conference_id="4",
        away_conference_id="4",
    )
    mixed = _event(
        "cfb-mixed",
        "2026-08-16T16:00:00Z",
        home_conference_id="4",
        away_conference_id="1",
    )
    client = RecordingClient(
        {"20260816-20260817": {"events": [hidden, mixed]}}
    )
    provider = EspnScoreboardProvider(
        {"ncf_fbs": "https://example.test/football/college-football/scoreboard?groups=80"},
        client=client,
        now=lambda: datetime(2026, 8, 16, 7, tzinfo=timezone.utc),
    )

    result = provider.fetch(
        DisplaySettings(
            timezone="America/New_York",
            active_conferences={"ncf_fbs:4": False},
            my_teams=("ncf_fbs:NYG",),
        )
    )

    assert [item.id for item in result.content] == ["cfb-mixed"]
    assert result.content[0].data["home_conference_id"] == "4"
    assert result.content[0].data["away_conference_id"] == "1"
    assert result.content[0].data["sport"] == "ncf_fbs"
    assert result.health.healthy is True

    hidden_result = provider.fetch(
        DisplaySettings(
            timezone="America/New_York",
            active_conferences={"ncf_fbs:4": False, "ncf_fbs:1": False},
        )
    )
    assert hidden_result.content == ()


def test_unchanged_controller_active_sports_map_controls_cfb_conferences() -> None:
    hidden = _event(
        "cfb-hidden-through-legacy-map",
        "2026-08-16T15:00:00Z",
        home_conference_id="4",
        away_conference_id="4",
    )
    visible = _event(
        "cfb-visible-through-legacy-map",
        "2026-08-16T16:00:00Z",
        home_conference_id="1",
        away_conference_id="1",
    )
    client = RecordingClient(
        {"20260816-20260817": {"events": [hidden, visible]}}
    )
    provider = EspnScoreboardProvider(
        {"ncf_fbs": "https://example.test/football/college-football/scoreboard?groups=80"},
        client=client,
        now=lambda: datetime(2026, 8, 16, 7, tzinfo=timezone.utc),
    )

    result = provider.fetch(
        DisplaySettings(
            timezone="America/New_York",
            active_sports={"ncf_fbs:4": False},
            my_teams=("ncf_fbs:TCU",),
        )
    )

    assert [item.id for item in result.content] == ["cfb-visible-through-legacy-map"]
    assert result.content[0].data["sport"] == "ncf_fbs"
    assert result.content[0].data["home_conference_id"] == "1"


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


def test_espn_raw_reads_share_across_active_masks_and_timezones() -> None:
    live_nfl = _event("nfl-live", "2026-08-16T18:00:00Z", state="in")
    pre_mlb = _event("mlb-pre", "2026-08-16T19:00:00Z")

    class LeagueClient(RecordingClient):
        def get_json(self, url: str, *, timeout: float):
            self.urls.append(url)
            del timeout
            return {"events": [live_nfl] if "/football/" in url else [pre_mlb]}

    client = LeagueClient({"20260816-20260817": {}})
    monotonic = [0.0]
    provider = EspnScoreboardProvider(
        {
            "nfl": "https://example.test/football/nfl/scoreboard",
            "mlb": "https://example.test/baseball/mlb/scoreboard",
        },
        client=client,
        now=lambda: datetime(2026, 8, 16, 7, tzinfo=timezone.utc),
        monotonic=lambda: monotonic[0],
    )

    nfl_only = DisplaySettings(
        timezone="America/New_York",
        active_sports={"nfl": True, "mlb": False},
    )
    both_leagues = DisplaySettings(
        timezone="UTC",
        active_sports={"nfl": True, "mlb": True},
    )
    nfl_result = provider.fetch_for_ticker("ticker-nfl", nfl_only)
    both_result = provider.fetch_for_ticker("ticker-both", both_leagues)

    assert {item.data["sport"] for item in nfl_result.content} == {"nfl"}
    assert {item.data["sport"] for item in both_result.content} == {"nfl", "mlb"}
    assert sum("/scoreboard" in url and "/scoreboard/" not in url for url in client.urls) == 2
    assert sum("/scoreboard/" in url for url in client.urls) == 1


def test_espn_raw_failure_backoff_is_shared_across_ticker_views() -> None:
    client = RecordingClient({}, failures={"20260816-20260817"})
    monotonic = [0.0]
    provider = EspnScoreboardProvider(
        {
            "nfl": "https://example.test/football/nfl/scoreboard",
            "mlb": "https://example.test/baseball/mlb/scoreboard",
        },
        client=client,
        now=lambda: datetime(2026, 8, 16, 7, tzinfo=timezone.utc),
        monotonic=lambda: monotonic[0],
    )

    provider.fetch_for_ticker(
        "ticker-nfl",
        DisplaySettings(active_sports={"nfl": True, "mlb": False}),
    )
    provider.fetch_for_ticker(
        "ticker-both",
        DisplaySettings(active_sports={"nfl": True, "mlb": True}, timezone="UTC"),
    )
    assert sum("/scoreboard" in url for url in client.urls) == 2

    monotonic[0] = 4.99
    provider.fetch_for_ticker(
        "ticker-nfl-2",
        DisplaySettings(active_sports={"nfl": True, "mlb": False}),
    )
    assert sum("/scoreboard" in url for url in client.urls) == 2

    monotonic[0] = 5.0
    provider.fetch_for_ticker(
        "ticker-nfl-3",
        DisplaySettings(active_sports={"nfl": True, "mlb": False}),
    )
    assert sum("/scoreboard" in url for url in client.urls) == 3


def test_espn_malformed_scoreboard_is_unhealthy_with_other_league_success() -> None:
    malformed = _event("", "2026-08-16T18:00:00Z")
    valid = _event("mlb-valid", "2026-08-16T19:00:00Z")
    client = RecordingClient(
        {"20260816-20260817": {"events": [malformed, valid]}}
    )
    provider = EspnScoreboardProvider(
        {
            "nfl": "https://example.test/football/nfl/scoreboard",
            "mlb": "https://example.test/baseball/mlb/scoreboard",
        },
        client=client,
        now=lambda: datetime(2026, 8, 16, 7, tzinfo=timezone.utc),
    )

    result = provider.fetch_for_ticker("ticker-1", DisplaySettings())

    assert result.health.healthy is False
    assert "nfl event: event id is missing" in (result.health.error or "")


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


def test_espn_live_refresh_reads_one_event_scoreboard_for_one_live_game_in_large_schedule() -> None:
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
        event_updates={
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

    assert sum("/scoreboard" in url and "/scoreboard/" not in url for url in client.urls) == 1
    assert sum("/scoreboard/" in url for url in client.urls) == 1
    live_item = next(item for item in result.content if item.id == "game-0")
    assert live_item.data["state"] == "in"
    assert live_item.data["home_score"] == "1"


def test_espn_mlb_live_refresh_reads_summary_details_for_dense_slate() -> None:
    events = [_event(f"mlb-{index}", "2026-08-16T18:00:00Z", state="in") for index in range(4)]

    class MlbSummaryClient(RecordingClient):
        def get_json(self, url: str, *, timeout: float):
            del timeout
            self.urls.append(url)
            if "/summary?event=" in url:
                event_id = parse_qs(urlsplit(url).query)["event"][0]
                event = next(item for item in events if item["id"] == event_id)
                return {
                    "header": {
                        "id": event_id,
                        "competitions": event["competitions"],
                    },
                    "plays": [{
                        "team": {"abbreviation": "DAL"},
                        "alternativeType": {"text": "Single"},
                        "shortText": "A single scored one run.",
                        "scoringPlay": True,
                        "scoreValue": 1,
                    }],
                }
            return {"events": events}

    client = MlbSummaryClient({})
    provider = EspnScoreboardProvider(
        {"mlb": "https://example.test/baseball/mlb/scoreboard"},
        client=client,
        now=lambda: datetime(2026, 8, 16, 18, 1, tzinfo=timezone.utc),
    )

    result = provider.fetch_for_ticker(
        "ticker-mlb",
        DisplaySettings(active_sports={"mlb": True}),
    )

    assert sum("/summary?event=" in url for url in client.urls) == 4
    live_item = next(item for item in result.content if item.id == "mlb-0")
    assert live_item.data["situation"]["scoring_plays"][0]["type"] == "Single"


def test_espn_fastcast_updates_live_game_without_an_event_http_request() -> None:
    scheduled = _event("game-1", "2026-08-16T18:00:00Z")
    live = deepcopy(scheduled)
    live["status"] = {"type": {"state": "in", "shortDetail": "Q2 08:00"}}
    live["competitions"][0]["competitors"][0]["score"] = "7"

    class FastcastStub:
        def __init__(self) -> None:
            self.payload = {"events": [scheduled]}
            self.event_times: dict[str, float] = {}
            self.started = False

        def start(self) -> None:
            self.started = True

        def close(self) -> None:
            self.started = False

        def prime(self, league: str, payload: dict) -> None:
            del league
            self.payload = deepcopy(payload)
            self.event_times = {
                str(event.get("id") or "").strip(): 0.0
                for event in self.payload.get("events", [])
                if str(event.get("id") or "").strip()
            }

        def snapshot(self, league: str):
            del league
            return deepcopy(self.payload)

        def active(self, league: str) -> bool:
            del league
            return self.started

        def event_updated_at(self, league: str, event_id: str) -> float | None:
            del league
            return self.event_times.get(event_id)

        def prime_event(
            self,
            league: str,
            event: dict,
            *,
            if_updated_at: float | None = None,
        ) -> None:
            del league, if_updated_at
            event_id = str(event.get("id") or "").strip()
            self.event_times[event_id] = 6.0
            self.payload = {
                "events": [
                    event if str(item.get("id") or "").strip() == event_id else item
                    for item in self.payload.get("events", [])
                ]
            }

    fastcast = FastcastStub()
    client = RecordingClient({"20260816-20260817": {"events": [scheduled]}})
    current = [datetime(2026, 8, 16, 7, tzinfo=timezone.utc)]
    monotonic = [0.0]
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/football/nfl/scoreboard"},
        client=client,
        fastcast=fastcast,
        now=lambda: current[0],
        monotonic=lambda: monotonic[0],
    )

    provider.fetch_for_ticker("ticker-one", _settings())
    fastcast.payload = {"events": [live]}
    fastcast.event_times["game-1"] = 6.0
    current[0] = datetime(2026, 8, 16, 18, 1, tzinfo=timezone.utc)
    monotonic[0] = 6.0
    result = provider.fetch_for_ticker("ticker-two", _settings())

    live_item = next(item for item in result.content if item.id == "game-1")
    assert live_item.data["state"] == "in"
    assert live_item.data["home_score"] == "7"
    assert len(client.urls) == 1
    assert all("/scoreboard/" not in url for url in client.urls)


def test_espn_stale_fastcast_game_uses_one_targeted_http_refresh() -> None:
    scheduled = _event("game-1", "2026-08-16T18:00:00Z")
    fastcast_live = deepcopy(scheduled)
    fastcast_live["status"] = {"type": {"state": "in", "shortDetail": "Q2 08:00"}}
    fastcast_live["competitions"][0]["competitors"][0]["score"] = "7"
    http_live = deepcopy(fastcast_live)
    http_live["status"] = {"type": {"state": "in", "shortDetail": "Q2 07:00"}}
    http_live["competitions"][0]["competitors"][0]["score"] = "8"

    class FastcastStub:
        def __init__(self) -> None:
            self.payload = {"events": [scheduled]}
            self.event_times: dict[str, float] = {}
            self.started = False

        def start(self) -> None:
            self.started = True

        def close(self) -> None:
            self.started = False

        def prime(self, league: str, payload: dict) -> None:
            del league
            self.payload = deepcopy(payload)
            self.event_times = {
                str(event.get("id") or "").strip(): 0.0
                for event in self.payload.get("events", [])
                if str(event.get("id") or "").strip()
            }

        def snapshot(self, league: str):
            del league
            return deepcopy(self.payload)

        def active(self, league: str) -> bool:
            del league
            return self.started

        def event_updated_at(self, league: str, event_id: str) -> float | None:
            del league
            return self.event_times.get(event_id)

        def prime_event(
            self,
            league: str,
            event: dict,
            *,
            if_updated_at: float | None = None,
        ) -> None:
            del league, if_updated_at
            event_id = str(event.get("id") or "").strip()
            self.event_times[event_id] = 6.0
            self.payload = {
                "events": [
                    event if str(item.get("id") or "").strip() == event_id else item
                    for item in self.payload.get("events", [])
                ]
            }

    fastcast = FastcastStub()
    client = RecordingClient(
        {"20260816-20260817": {"events": [scheduled]}},
        event_updates={
            "game-1": {
                "header": {
                    "id": "game-1",
                    "competitions": [http_live["competitions"][0]],
                }
            }
        },
    )
    current = [datetime(2026, 8, 16, 7, tzinfo=timezone.utc)]
    monotonic = [0.0]
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/football/nfl/scoreboard"},
        client=client,
        fastcast=fastcast,
        now=lambda: current[0],
        monotonic=lambda: monotonic[0],
    )

    provider.fetch_for_ticker("ticker-one", _settings())
    fastcast.payload = {"events": [fastcast_live]}
    current[0] = datetime(2026, 8, 16, 18, 1, tzinfo=timezone.utc)
    monotonic[0] = 6.0
    result = provider.fetch_for_ticker("ticker-two", _settings())

    live_item = next(item for item in result.content if item.id == "game-1")
    assert live_item.data["home_score"] == "8"
    assert sum("/scoreboard" in url and "/scoreboard/" not in url for url in client.urls) == 1
    assert sum("/scoreboard/" in url for url in client.urls) == 1

    monotonic[0] = 7.0
    next_result = provider.fetch_for_ticker("ticker-three", _settings())
    next_live_item = next(item for item in next_result.content if item.id == "game-1")
    assert next_live_item.data["home_score"] == "8"
    assert sum("/scoreboard/" in url for url in client.urls) == 1


def test_espn_five_live_games_use_one_scoreboard_refresh() -> None:
    events = [_event(f"game-{index}", "2026-08-16T18:00:00Z") for index in range(5)]

    class ChangingClient(RecordingClient):
        def __init__(self) -> None:
            super().__init__({"20260816-20260817": {"events": events}})
            self.scoreboard_calls = 0

        def get_json(self, url: str, *, timeout: float):
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
    assert all("/summary" not in url for url in client.urls)
    assert {item.data["state"] for item in result.content} == {"in"}


@pytest.mark.parametrize("count", (5, 10, 100))
def test_espn_cold_dense_live_set_uses_one_scoreboard_request(count: int) -> None:
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
    assert all("/summary" not in url for url in client.urls)


def test_espn_sparse_event_scoreboard_requests_deduplicate_event_ids() -> None:
    duplicate = _event("game-1", "2026-08-16T18:00:00Z", state="in")
    client = RecordingClient(
        {"20260816-20260817": {"events": [duplicate, dict(duplicate)]}},
        event_updates={"game-1": {}},
    )
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/football/nfl/scoreboard"},
        client=client,
        now=lambda: datetime(2026, 8, 16, 18, 1, tzinfo=timezone.utc),
        monotonic=lambda: 0.0,
    )

    provider.fetch_for_ticker("ticker-one", _settings())

    assert sum("/scoreboard/" in url for url in client.urls) == 1


def test_espn_event_update_preserves_scoreboard_fields_and_live_state() -> None:
    fallback = _event("game-1", "2026-08-16T18:00:00Z", state="in")
    fallback["competitions"][0]["situation"] = {
        "possession": {"team": {"abbreviation": "NYG"}},
        "down": 2,
        "distance": 7,
    }
    fallback["competitions"][0]["competitors"][0]["team"]["logo"] = "scoreboard-logo"
    update = {
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

    merged = _event_update(update, fallback)
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


def test_espn_event_update_keeps_mlb_players_when_fastcast_sends_empty_objects() -> None:
    fallback = _event("game-1", "2026-08-16T18:00:00Z", state="in")
    players = {
        "batter": {"athlete": {"displayName": "Aaron Judge"}},
        "pitcher": {"athlete": {"displayName": "Garrett Whitlock"}},
    }
    fallback["competitions"][0]["situation"] = players
    update = {
        "header": {"competitions": [{"status": {"type": {"state": "in"}}}]},
        "situation": {"batter": {}, "pitcher": {}, "balls": 2},
    }

    merged = _event_update(update, fallback)

    assert merged["competitions"][0]["situation"]["batter"] == players["batter"]
    assert merged["competitions"][0]["situation"]["pitcher"] == players["pitcher"]


def test_espn_event_update_keeps_mlb_names_when_fastcast_sends_matching_ids() -> None:
    fallback = _event("game-1", "2026-08-16T18:00:00Z", state="in")
    fallback["competitions"][0]["situation"] = {
        "batter": {"playerId": "10", "athlete": {"displayName": "Aaron Judge"}},
        "pitcher": {"playerId": "20", "athlete": {"displayName": "Garrett Whitlock"}},
    }
    update = {
        "header": {"competitions": [{"status": {"type": {"state": "in"}}}]},
        "situation": {"batter": {"playerId": "10"}, "pitcher": {"playerId": "20"}},
    }

    merged = _event_update(update, fallback)
    situation = merged["competitions"][0]["situation"]

    assert situation["batter"]["athlete"]["displayName"] == "Aaron Judge"
    assert situation["pitcher"]["athlete"]["displayName"] == "Garrett Whitlock"


def test_espn_event_update_preserves_final_state() -> None:
    fallback = _event("game-1", "2026-08-16T18:00:00Z", state="post")
    update = {
        "header": {
            "competitions": [{
                "status": {"type": {"state": "pre", "shortDetail": "Scheduled"}},
            }],
        },
    }

    merged = _event_update(update, fallback)

    assert merged["status"]["type"]["state"] == "post"


def test_espn_event_scoreboard_failure_keeps_scoreboard_healthy() -> None:
    events = [
        _event("nfl-1", "2026-08-16T18:00:00Z", state="in"),
        _event("mlb-1", "2026-08-16T18:00:00Z", state="in"),
    ]
    phase = ["baseline", "failed", "recovered"]

    def event_scoreboard(event_id: str) -> dict:
        if phase[0] == "failed" and event_id == "mlb-1":
            raise RuntimeError("event scoreboard unavailable")
        score = "14" if phase[0] != "baseline" and event_id == "nfl-1" else "0"
        event = next(item for item in events if item["id"] == event_id)
        competition = dict(event["competitions"][0])
        competition["competitors"] = [
            {**dict(competitor), "score": score if competitor["homeAway"] == "home" else "0"}
            for competitor in competition["competitors"]
        ]
        competition["status"] = {"type": {"state": "in", "shortDetail": "Q1 08:00"}}
        return {
            "id": event_id,
            "date": next(item for item in events if item["id"] == event_id)["date"],
            "status": competition["status"],
            "competitions": [competition],
        }

    class SummaryClient(RecordingClient):
        def get_json(self, url: str, *, timeout: float):
            del timeout
            self.urls.append(url)
            if "/scoreboard/" in url:
                event_id = url.rstrip("/").rsplit("/", 1)[-1]
                return event_scoreboard(event_id)
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


def test_espn_partial_scoreboard_failure_keeps_cached_league_and_fresh_league() -> None:
    nfl_events = [_event(f"nfl-{index}", "2026-08-16T18:00:00Z", state="in") for index in range(5)]
    mlb_events = [_event(f"mlb-{index}", "2026-08-16T18:00:00Z", state="in") for index in range(5)]
    phase = [0]

    class PartialClient(RecordingClient):
        def get_json(self, url: str, *, timeout: float):
            del timeout
            self.urls.append(url)
            if phase[0] == 1 and "/baseball/" in url:
                raise RuntimeError("scoreboard unavailable")
            source = nfl_events if "/football/" in url else mlb_events
            if phase[0] == 1 and source is nfl_events:
                source = [
                    {
                        **dict(event),
                        "competitions": [{
                            **dict(event["competitions"][0]),
                            "competitors": [
                                {
                                    **dict(competitor),
                                    "score": "14" if competitor["homeAway"] == "home" else "0",
                                }
                                for competitor in event["competitions"][0]["competitors"]
                            ],
                        }],
                    }
                    for event in source
                ]
            return {"events": source}

    client = PartialClient({})
    monotonic = [0.0]
    provider = EspnScoreboardProvider(
        {
            "nfl": "https://example.test/football/nfl/scoreboard",
            "mlb": "https://example.test/baseball/mlb/scoreboard",
        },
        client=client,
        now=lambda: datetime(2026, 8, 16, 18, 1, tzinfo=timezone.utc),
        monotonic=lambda: monotonic[0],
    )
    settings = DisplaySettings(
        active_sports={"nfl": True, "mlb": True},
        my_teams=("nfl:NYG",),
    )

    provider.fetch_for_ticker("ticker-one", settings)
    phase[0] = 1
    monotonic[0] = 6.0
    result = provider.fetch_for_ticker("ticker-one", settings)

    items = {item.id: item for item in result.content}
    assert result.health.healthy is True
    assert result.health.error == "mlb: scoreboard unavailable"
    assert items["nfl-0"].data["home_score"] == "14"
    assert items["mlb-0"].data["home_score"] == "0"
    assert len(result.alerts) == 5


def test_espn_partial_scoreboard_poll_publishes_healthy_alerts_only() -> None:
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
    monotonic = [0.0]
    provider = EspnScoreboardProvider(
        {
            "nfl": "https://example.test/football/nfl/scoreboard",
            "mlb": "https://example.test/baseball/mlb/scoreboard",
        },
        client=client,
        now=lambda: datetime(2026, 8, 16, 18, 1, tzinfo=timezone.utc),
        monotonic=lambda: monotonic[0],
    )
    settings = DisplaySettings(
        active_sports={"nfl": True, "mlb": True},
        my_teams=("nfl:NYG",),
    )

    provider.fetch_for_ticker("ticker-one", settings)
    scoreboard_pass[0] = 1
    monotonic[0] = 60.0
    failed = provider.fetch_for_ticker("ticker-one", settings)
    scoreboard_pass[0] = 2
    monotonic[0] = 120.0
    recovered = provider.fetch_for_ticker("ticker-one", settings)

    assert failed.health.healthy is True
    assert failed.health.error == "mlb: scoreboard unavailable"
    assert {alert["sport"] for alert in failed.alerts} == {"nfl"}
    assert {alert["sport"] for alert in recovered.alerts} == {"nfl"}


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


def test_espn_event_updates_do_not_reset_discovery_age() -> None:
    event = _event("game-1", "2026-08-16T18:00:00Z")
    client = RecordingClient(
        {"20260816-20260817": {"events": [event]}},
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


def test_espn_event_scoring_details_normalize_team_and_scorer() -> None:
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

    details = _event_scoring_details(
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


def test_espn_mlb_scoring_details_use_summary_play_type_and_run_count() -> None:
    payload = {
        "header": {
            "competitions": [{
                "competitors": [
                    {"homeAway": "home", "team": {"id": "10", "abbreviation": "BOS"}},
                    {"homeAway": "away", "team": {"id": "20", "abbreviation": "NYY"}},
                ]
            }]
        },
        "plays": [{
            "team": {"id": "20"},
            "participants": [{"type": "batter", "athlete": {"id": "123"}}],
            "alternativeType": {"text": "Single"},
            "type": {"text": "Play Result"},
            "shortText": "Wells singled to left, two runs scored.",
            "scoringPlay": True,
            "scoreValue": 2,
        }],
        "boxscore": {
            "players": [{
                "statistics": [{
                    "keys": ["atBats"],
                    "athletes": [{
                        "athlete": {"id": "123", "displayName": "Austin Wells"},
                        "stats": ["1"],
                    }],
                }],
            }],
        },
    }

    details = _event_scoring_details(
        payload,
        {"sport": "mlb", "home_abbr": "BOS", "away_abbr": "NYY"},
    )

    assert details["scoring_plays"] == [{
        "team": "NYY",
        "scorer": "WELLS",
        "player": "WELLS",
        "type": "Single",
        "text": "Wells singled to left, two runs scored.",
        "score_value": 2,
    }]


def test_espn_mlb_event_details_use_live_situation_names_without_boxscore_rows() -> None:
    details = _mlb_event_details({
        "situation": {
            "batter": {
                "athlete": {"displayName": "Austin Wells"},
            },
            "pitcher": {
                "athlete": {"fullName": "Garrett Acton"},
            },
            "balls": 2,
            "strikes": 1,
            "outs": 0,
        },
    })

    assert details["batter_name"] == "Austin Wells"
    assert details["pitcher_name"] == "Garrett Acton"


def test_espn_mlb_event_details_keep_scoreboard_batter_stats_without_boxscore() -> None:
    details = _mlb_event_details({
        "competitions": [{
            "situation": {
                "batter": {
                    "athlete": {"displayName": "Austin Wells"},
                    "summary": "2-4, R",
                },
                "pitcher": {
                    "athlete": {"displayName": "Garrett Acton"},
                },
                "balls": 1,
                "strikes": 2,
                "outs": 1,
            },
        }],
    })

    assert details["batter_h"] == "2"
    assert details["batter_ab"] == "4"


def test_espn_mlb_event_details_use_due_up_and_last_play_between_innings() -> None:
    details = _mlb_event_details({
        "situation": {
            "balls": 0,
            "strikes": 0,
            "outs": 0,
            "dueUp": [{"playerId": "10"}],
            "lastPlay": {"id": "play-1"},
        },
        "plays": [{
            "id": "play-1",
            "participants": [
                {"type": "pitcher", "athlete": {"id": "20", "displayName": "Gerrit Cole"}},
                {"type": "batter", "athlete": {"id": "30", "displayName": "Aaron Judge"}},
            ],
        }],
        "boxscore": {"players": [{"statistics": [
            {"keys": ["atBats"], "athletes": [{"athlete": {"id": "10", "displayName": "Vaughn Grissom"}, "stats": ["0"]}]},
            {"keys": ["pitches"], "athletes": [{"athlete": {"id": "20", "displayName": "Gerrit Cole"}, "stats": ["47"]}]},
        ]}]},
    })

    assert details["batter_name"] == "Vaughn Grissom"
    assert details["pitcher_name"] == "Gerrit Cole"
    assert details["batter_ab"] == "0"
    assert details["pitcher_pitches"] == "47"


def test_espn_mlb_uses_summary_event_detail_url() -> None:
    assert _event_detail_url(
        "mlb", "https://example.test/baseball/mlb/scoreboard?dates=20260829"
    ) == "https://example.test/baseball/mlb/summary?event={}"
    assert _event_detail_url(
        "nfl", "https://example.test/football/nfl/scoreboard"
    ) == "https://example.test/football/nfl/scoreboard/{}"


def test_espn_mlb_summary_retries_api_host_when_web_host_has_no_boxscore() -> None:
    class SummaryClient:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get_json(self, url: str, *, timeout: float):
            del timeout
            self.urls.append(url)
            if "site.web.api.espn.com" in url:
                return {"header": {"id": "game-1", "competitions": [{
                    "situation": {"batter": {"playerId": "10", "summary": "1-2"}},
                }]}}
            return {
                "header": {"id": "game-1", "competitions": [{}]},
                "boxscore": {"players": [{"statistics": [{
                    "keys": ["pitches"],
                    "athletes": [{
                        "athlete": {"id": "20", "displayName": "Gerrit Cole"},
                        "stats": ["47"],
                    }],
                }]}]},
                "situation": {"pitcher": {"playerId": "20"}},
            }

    client = SummaryClient()
    provider = EspnScoreboardProvider(
        {"mlb": "https://site.web.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"},
        client=client,
    )

    event = provider._read_event_payload(
        "mlb",
        "game-1",
        "https://site.web.api.espn.com/apis/site/v2/sports/baseball/mlb/summary?event=game-1",
    )

    assert len(client.urls) == 2
    assert "site.api.espn.com" in client.urls[1]
    assert _mlb_event_details(event)["pitcher_pitches"] == "47"


def test_espn_mlb_statsapi_feed_supplies_live_player_stats() -> None:
    summary = _mlb_statsapi_summary({
        "liveData": {
            "plays": {
                "currentPlay": {
                    "about": {"atBatIndex": 7},
                    "count": {"balls": 1, "strikes": 2},
                    "matchup": {
                        "batter": {"id": 10, "fullName": "Austin Wells"},
                        "pitcher": {"id": 20, "fullName": "Gerrit Cole"},
                    },
                    "pitchData": {"startSpeed": 96.4},
                    "details": {"type": {"code": "FF", "description": "Four-Seam Fastball"}},
                },
            },
            "linescore": {"outs": 1, "offense": {"first": {"id": 30}}},
            "boxscore": {"teams": {"home": {"players": {
                "ID10": {"person": {"id": 10, "fullName": "Austin Wells"}, "stats": {
                    "batting": {"hits": 2, "atBats": 4, "avg": ".250"},
                }},
                "ID20": {"person": {"id": 20, "fullName": "Gerrit Cole"}, "stats": {
                    "pitching": {"numberOfPitches": 47},
                }},
            }}, "away": {"players": {}}}},
        },
    }, "game-1")

    details = _mlb_event_details(summary)

    assert details["batter_name"] == "Austin Wells"
    assert details["batter_h"] == "2"
    assert details["batter_ab"] == "4"
    assert details["batter_avg"] == ".250"
    assert details["pitcher_name"] == "Gerrit Cole"
    assert details["pitcher_pitches"] == "47"
    assert details["last_pitch_type"] == "4S Fastball"
