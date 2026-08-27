"""Verify canonical FotMob soccer display facts."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, Lock

import pytest

from sports_ticker.domain.models import DisplaySettings
from sports_ticker.providers.fotmob import (
    _DetailCacheEntry,
    FotMobSoccerProvider,
    _content_item,
    _match_state,
    _match_status,
    _needs_details,
    _situation,
)


_NOW = datetime(2026, 8, 16, 12, tzinfo=timezone.utc)


class _InlineExecutor:
    """Run optional detail work inline for deterministic request-count tests."""

    def submit(self, function, *args, **kwargs):
        return function(*args, **kwargs)


class _NoOpExecutor:
    """Record optional detail work without performing network I/O."""

    def __init__(self) -> None:
        self.submissions = 0

    def submit(self, function, *args, **kwargs):
        del function, args, kwargs
        self.submissions += 1


class _RecordingClient:
    def __init__(self, matches: list[dict]) -> None:
        self.matches = matches
        self.urls: list[str] = []
        self._lock = Lock()

    def get_json(self, url: str, *, timeout: float) -> dict:
        del timeout
        with self._lock:
            self.urls.append(url)
        if "matchDetails" in url:
            return {}
        return {"leagues": [{"primaryId": 130, "matches": self.matches}]}

    @property
    def match_requests(self) -> int:
        return sum("matchDetails" not in url for url in self.urls)

    @property
    def detail_requests(self) -> int:
        return sum("matchDetails" in url for url in self.urls)


def _live_match(match_id: int, score: int = 0) -> dict:
    return {
        "id": match_id,
        "status": {
            "started": True,
            "finished": False,
            "cancelled": False,
            "utcTime": "2026-08-16T16:00:00Z",
            "liveTime": {"short": "53'"},
        },
        "home": {"id": f"home-{match_id}", "longName": "Seattle Sounders FC", "score": score},
        "away": {"id": f"away-{match_id}", "longName": "Vancouver Whitecaps", "score": 0},
    }


def _final_match(match_id: int) -> dict:
    match = _live_match(match_id)
    match["status"].update(
        {
            "started": True,
            "finished": True,
            "reason": {"short": "FT"},
        }
    )
    return match


def test_fotmob_normalizes_first_half_stoppage_clock() -> None:
    """Normalize elapsed minutes over 45 to 45'+X' during first half."""
    match = {
        "status": {
            "started": True,
            "halfs": {"firstHalfStarted": "17.08.2026 21:01:24"},
            "liveTime": {
                "short": "46\u200e\u2019\u200e",
                "long": "46:15",
                "maxTime": 45,
                "basePeriod": 45,
            },
        }
    }
    assert _match_status(match, "in", "UTC") == "45'+1:15'"


def test_fotmob_live_clock_has_one_apostrophe_without_hidden_spacing() -> None:
    match = {
        "status": {
            "started": True,
            "liveTime": {"short": "93\u200e\u200e'"},
        }
    }

    assert _match_status(match, "in", "UTC") == "90'+3'"


def test_fotmob_prefers_the_precise_stoppage_clock() -> None:
    """Use the long clock when it contains stoppage minutes and seconds."""

    match = {
        "status": {
            "started": True,
            "liveTime": {"short": "45+1'", "long": "45:00 + 1:12"},
        }
    }

    assert _match_status(match, "in", "UTC") == "45'+1:12'"


def test_fotmob_normalizes_second_half_stoppage_clock() -> None:
    match = {
        "status": {
            "started": True,
            "liveTime": {"short": "98'", "long": "98:00"},
        }
    }

    assert _match_status(match, "in", "UTC") == "90'+8:00'"


def test_fotmob_reads_halftime_from_live_time_when_reason_is_empty() -> None:
    match = {
        "id": "5071271",
        "status": {
            "started": True,
            "finished": False,
            "cancelled": False,
            "reason": {},
            "liveTime": {"short": "HT", "long": "Half-Time"},
        },
        "home": {"id": "1", "longName": "Atlanta United", "score": 1},
        "away": {"id": "2", "longName": "Charlotte FC", "score": 0},
    }

    item = _content_item("soccer_mls", match, None, timezone_name="UTC")

    assert _match_state(match) == "half"
    assert item.data["state"] == "half"
    assert item.data["status"] == "Half"


def test_fotmob_soccer_events_match_the_v1_renderer_contract() -> None:
    detail = {
        "content": {
            "matchFacts": {
                "events": {
                    "events": [
                        {"type": "Goal", "isHome": False, "time": 13, "player": {"name": "Alex Morgan"}},
                        {"type": "Goal", "isHome": True, "time": 45, "overloadTime": 2, "subType": "Own goal", "player": {"name": "Jamie Smith"}},
                        {"type": "Card", "isHome": False, "time": 71, "card": "Red", "player": {"name": "Taylor Reed"}},
                    ]
                }
            }
        }
    }

    situation = _situation(detail)

    assert situation["goal_events"] == [
        {"is_home": False, "player": "MORGAN", "time": "13'", "own_goal": False},
        {"is_home": True, "player": "SMITH", "time": "45+2'", "own_goal": True},
    ]
    assert situation["red_cards"] == [
        {"is_home": False, "player": "REED", "time": "71'", "own_goal": False}
    ]


def test_fotmob_keeps_final_match_details_until_the_display_window_closes() -> None:
    match = {"status": {"started": True, "finished": True, "reason": {"short": "FT"}}}

    assert _needs_details(match)


def test_fotmob_fetches_pregame_details_for_team_colors() -> None:
    match = {
        "id": "5836754",
        "status": {"started": False, "utcTime": "2026-08-15T23:30:00Z"},
        "home": {"id": "1", "longName": "Atlanta United", "score": 0},
        "away": {"id": "2", "longName": "Charlotte FC", "score": 0},
    }
    detail = {"general": {"teamColors": {"darkMode": {"home": "#80000A", "away": "#00AEEF"}}}}

    item = _content_item("soccer_mls", match, detail, timezone_name="UTC")

    assert _needs_details(match)
    assert item.data["home_color"] == "#80000A"
    assert item.data["away_color"] == "#00AEEF"


def test_fotmob_replaces_the_last_live_details_with_one_final_snapshot() -> None:
    class Client:
        calls = 0

        def get_json(self, url: str, *, timeout: float) -> dict:
            del url, timeout
            self.calls += 1
            return {"revision": self.calls}

    client = Client()
    provider = FotMobSoccerProvider({"soccer_champ": 48}, client=client)
    live = {"id": "5836754", "status": {"started": True}}
    final = {"id": "5836754", "status": {"started": True, "finished": True}}

    assert provider._details_for(live) == {"revision": 1}
    assert provider._details_for(final) == {"revision": 2}
    assert provider._details_for(final) == {"revision": 2}
    assert client.calls == 2


def test_fotmob_reuses_pregame_details_until_the_match_starts() -> None:
    class Client:
        calls = 0

        def get_json(self, url: str, *, timeout: float) -> dict:
            del url, timeout
            self.calls += 1
            return {"revision": self.calls}

    client = Client()
    provider = FotMobSoccerProvider({"soccer_mls": 130}, client=client)
    pregame = {"id": "5836754", "status": {"started": False}}
    live = {"id": "5836754", "status": {"started": True}}

    assert provider._details_for(pregame) == {"revision": 1}
    assert provider._details_for(pregame) == {"revision": 1}
    assert provider._details_for(live) == {"revision": 2}
    assert client.calls == 2


def test_fotmob_emits_score_alerts_for_followed_teams() -> None:
    class Client:
        score = 0

        def get_json(self, url: str, *, timeout: float) -> dict:
            del timeout
            if "matchDetails" in url:
                return {}
            return {
                "leagues": [
                    {
                        "primaryId": 130,
                        "matches": [
                            {
                                "id": 5071275,
                                "status": {
                                    "started": True,
                                    "finished": False,
                                    "cancelled": False,
                                    "liveTime": {"short": "53'"},
                                },
                                "home": {"id": "130394", "longName": "Seattle Sounders FC", "score": self.score},
                                "away": {"id": "307691", "longName": "Vancouver Whitecaps", "score": 0},
                            }
                        ],
                    }
                ]
            }

    client = Client()
    clock = [0.0]
    provider = FotMobSoccerProvider(
        {"soccer_mls": 130},
        client=client,
        now=lambda: _NOW,
        monotonic=lambda: clock[0],
    )
    settings = DisplaySettings(mode="sports", score_alerts=True, my_teams=("soccer_mls:SEA",))

    # First poll: initial score 0-0 -> no alerts
    result1 = provider.fetch_for_ticker("ticker-1", settings)
    assert len(result1.alerts) == 0

    # Second poll: Seattle scores 1-0 -> emits alert
    client.score = 1
    clock[0] = 5.0
    result2 = provider.fetch_for_ticker("ticker-1", settings)
    assert len(result2.alerts) == 1
    alert = result2.alerts[0]
    assert alert["team_abbr"] == "SEA"
    assert alert["headline"] == "GOAL"
    assert alert["home_score"] == 1


def test_fotmob_ticker_source_is_shared_across_one_hundred_tickers() -> None:
    client = _RecordingClient([_live_match(1)])
    provider = FotMobSoccerProvider(
        {"soccer_mls": 130},
        client=client,
        now=lambda: _NOW,
        monotonic=lambda: 0.0,
        detail_executor=_NoOpExecutor(),
    )
    settings = DisplaySettings(active_sports={"soccer_mls": True})

    for index in range(100):
        provider.fetch_for_ticker(f"ticker-{index}", settings)

    assert client.match_requests == 2


def test_fotmob_ticker_source_expires_after_five_seconds() -> None:
    client = _RecordingClient([_live_match(1)])
    clock = [0.0]
    provider = FotMobSoccerProvider(
        {"soccer_mls": 130},
        client=client,
        now=lambda: _NOW,
        monotonic=lambda: clock[0],
        detail_executor=_NoOpExecutor(),
    )
    settings = DisplaySettings(active_sports={"soccer_mls": True})

    provider.fetch_for_ticker("ticker-1", settings)
    clock[0] = 4.99
    provider.fetch_for_ticker("ticker-2", settings)
    assert client.match_requests == 2

    clock[0] = 5.0
    provider.fetch_for_ticker("ticker-3", settings)
    assert client.match_requests == 4


def test_fotmob_raw_date_cache_ignores_ticker_projection_settings() -> None:
    client = _RecordingClient([_live_match(1)])
    provider = FotMobSoccerProvider(
        {"soccer_mls": 130, "soccer_epl": 47},
        client=client,
        now=lambda: _NOW,
        monotonic=lambda: 0.0,
        detail_executor=_NoOpExecutor(),
    )
    base = DisplaySettings(active_sports={"soccer_mls": True, "soccer_epl": False})
    variants = (
        DisplaySettings(
            active_sports={"soccer_mls": True, "soccer_epl": False},
            my_teams=("soccer_mls:SEA",),
            score_alerts=False,
            live_delay_mode=True,
            live_delay_seconds=120,
            sports_filter="my_teams",
        ),
        DisplaySettings(
            active_sports={"soccer_mls": True, "soccer_epl": False},
            mode="weather",
        ),
    )

    provider.fetch_for_ticker("ticker-1", base)
    for index, settings in enumerate(variants, start=2):
        provider.fetch_for_ticker(f"ticker-{index}", settings)
    assert client.match_requests == 2

    provider.fetch_for_ticker(
        "ticker-4",
        DisplaySettings(active_sports={"soccer_mls": True, "soccer_epl": False}, timezone="UTC"),
    )
    assert client.match_requests == 2

    provider.fetch_for_ticker(
        "ticker-5",
        DisplaySettings(active_sports={"soccer_mls": True, "soccer_epl": True}),
    )
    assert client.match_requests == 2


def test_fotmob_raw_date_cache_filters_one_hundred_varied_active_selections() -> None:
    class VariedClient:
        def __init__(self) -> None:
            self.urls: list[str] = []
            self._lock = Lock()

        def get_json(self, url: str, *, timeout: float) -> dict:
            del timeout
            with self._lock:
                self.urls.append(url)
            if "matchDetails" in url:
                return {}
            return {
                "leagues": [
                    {"primaryId": 130, "matches": [_live_match(1)]},
                    {"primaryId": 47, "matches": [_live_match(2)]},
                    {"primaryId": 87, "matches": [_live_match(3)]},
                ]
            }

        @property
        def match_requests(self) -> int:
            return sum("matchDetails" not in url for url in self.urls)

    client = VariedClient()
    provider = FotMobSoccerProvider(
        {"soccer_mls": 130, "soccer_epl": 47, "soccer_laliga": 87},
        client=client,
        now=lambda: _NOW,
        monotonic=lambda: 0.0,
        detail_executor=_NoOpExecutor(),
    )
    masks = (
        {"soccer_mls": True, "soccer_epl": False, "soccer_laliga": False},
        {"soccer_mls": False, "soccer_epl": True, "soccer_laliga": False},
        {"soccer_mls": True, "soccer_epl": True, "soccer_laliga": True},
    )

    def fetch(index: int):
        settings = DisplaySettings(
            active_sports=masks[index % len(masks)],
            timezone="UTC" if index % 2 else "",
        )
        return index, provider.fetch_for_ticker(f"ticker-{index}", settings)

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(fetch, range(100)))

    for index, result in results:
        assert {item.data["sport"] for item in result.content} == {
            sport for sport, enabled in masks[index % len(masks)].items() if enabled
        }

    assert client.match_requests == 2


def test_fotmob_raw_date_cache_backs_off_failed_dates_until_expiry() -> None:
    class FailingDateClient(_RecordingClient):
        fail_first_date = True

        def get_json(self, url: str, *, timeout: float) -> dict:
            if self.fail_first_date and "date=20260816" in url:
                with self._lock:
                    self.urls.append(url)
                raise RuntimeError("first date unavailable")
            return super().get_json(url, timeout=timeout)

    client = FailingDateClient([_live_match(1)])
    clock = [0.0]
    provider = FotMobSoccerProvider(
        {"soccer_mls": 130, "soccer_epl": 47},
        client=client,
        now=lambda: _NOW,
        monotonic=lambda: clock[0],
        detail_executor=_NoOpExecutor(),
    )
    settings = DisplaySettings(active_sports={"soccer_mls": True, "soccer_epl": False})

    first = provider.fetch_for_ticker("ticker-1", settings)
    assert first.health.healthy is False
    assert client.match_requests == 2

    provider.fetch_for_ticker(
        "ticker-2",
        DisplaySettings(active_sports={"soccer_mls": True, "soccer_epl": True}, timezone="UTC"),
    )
    assert client.match_requests == 2

    client.fail_first_date = False
    clock[0] = 5.0
    recovered = provider.fetch_for_ticker("ticker-3", settings)
    assert recovered.health.healthy
    assert client.match_requests == 4


def test_fotmob_reads_the_two_match_dates_concurrently() -> None:
    class BarrierClient(_RecordingClient):
        def __init__(self) -> None:
            super().__init__([_live_match(1)])
            self.barrier = Barrier(2)

        def get_json(self, url: str, *, timeout: float) -> dict:
            result = super().get_json(url, timeout=timeout)
            if "matchDetails" not in url:
                self.barrier.wait(timeout=1.0)
            return result

    client = BarrierClient()
    provider = FotMobSoccerProvider(
        {"soccer_mls": 130},
        client=client,
        now=lambda: _NOW,
        monotonic=lambda: 0.0,
        detail_executor=_NoOpExecutor(),
    )

    result = provider.fetch_for_ticker("ticker-1", DisplaySettings())

    assert result.health.healthy
    assert client.match_requests == 2


@pytest.mark.parametrize("live_count", [1, 5, 10, 100])
def test_fotmob_live_detail_requests_scale_only_for_sparse_sets(live_count: int) -> None:
    matches = [_live_match(index) for index in range(1, live_count + 1)]
    client = _RecordingClient(matches)
    provider = FotMobSoccerProvider(
        {"soccer_mls": 130},
        client=client,
        now=lambda: _NOW,
        monotonic=lambda: 0.0,
        detail_executor=_InlineExecutor(),
    )

    result = provider.fetch_for_ticker("ticker-1", DisplaySettings())

    assert result.health.healthy
    assert client.match_requests == 2
    assert client.detail_requests == (1 if live_count == 1 else 0)


def test_fotmob_caps_pregame_and_final_detail_warming_per_source_window() -> None:
    client = _RecordingClient([_final_match(index) for index in range(1, 21)])
    executor = _NoOpExecutor()
    provider = FotMobSoccerProvider(
        {"soccer_mls": 130},
        client=client,
        now=lambda: _NOW,
        detail_executor=executor,
    )

    provider.fetch_for_ticker("ticker-1", DisplaySettings())
    assert executor.submissions == 8


def test_fotmob_detail_failure_does_not_invalidate_fresh_scores() -> None:
    class FailingDetailClient(_RecordingClient):
        def get_json(self, url: str, *, timeout: float) -> dict:
            if "matchDetails" in url:
                raise RuntimeError("details unavailable")
            return super().get_json(url, timeout=timeout)

    client = FailingDetailClient([_live_match(1, score=2)])
    provider = FotMobSoccerProvider(
        {"soccer_mls": 130},
        client=client,
        now=lambda: _NOW,
        monotonic=lambda: 0.0,
        detail_executor=_InlineExecutor(),
    )

    result = provider.fetch_for_ticker("ticker-1", DisplaySettings())

    assert result.health.healthy
    assert result.content[0].data["home_score"] == "2"


def test_fotmob_direct_fetch_keeps_fresh_source_semantics() -> None:
    client = _RecordingClient([_live_match(1)])
    provider = FotMobSoccerProvider(
        {"soccer_mls": 130},
        client=client,
        now=lambda: _NOW,
        monotonic=lambda: 0.0,
        detail_executor=_NoOpExecutor(),
    )

    provider.fetch(DisplaySettings())
    provider.fetch(DisplaySettings())

    assert client.match_requests == 4


def test_fotmob_score_alert_uses_canonical_soccer_event_time() -> None:
    from sports_ticker.providers.score_alerts import ScoreAlertTracker

    tracker = ScoreAlertTracker(clock=lambda: 0.0)
    base = {
        "kind": "scoreboard",
        "id": "match-1",
        "sport": "soccer_mls",
        "state": "in",
        "home_score": 0,
        "away_score": 0,
        "home_abbr": "SEA",
        "away_abbr": "VAN",
        "situation": {"goal_events": []},
    }
    updated = {
        **base,
        "home_score": 1,
        "situation": {
            "goal_events": [
                {"is_home": True, "player": "SMITH", "time": "45+2'", "own_goal": False}
            ]
        },
    }

    tracker.ingest([base])
    tracker.ingest([updated])

    assert tracker.recent()[0]["detail"] == "SMITH 45+2'"


def test_fotmob_partial_date_failure_preserves_alert_memory_and_recovery_baseline() -> None:
    class PartialClient:
        fail_first_date = False
        score = 0

        def get_json(self, url: str, *, timeout: float) -> dict:
            del timeout
            if "matchDetails" in url:
                return {}
            if self.fail_first_date and "date=20260816" in url:
                raise RuntimeError("first date unavailable")
            return {
                "leagues": [
                    {
                        "primaryId": 130,
                        "matches": [_live_match(1, score=self.score)],
                    }
                ]
            }

    client = PartialClient()
    clock = [0.0]
    provider = FotMobSoccerProvider(
        {"soccer_mls": 130},
        client=client,
        now=lambda: _NOW,
        monotonic=lambda: clock[0],
        detail_executor=_NoOpExecutor(),
    )
    settings = DisplaySettings(mode="sports", score_alerts=True, my_teams=("soccer_mls:SEA",))

    provider.fetch_for_ticker("ticker-1", settings)
    client.score = 1
    client.fail_first_date = True
    clock[0] = 5.0
    partial = provider.fetch_for_ticker("ticker-1", settings)

    tracker = provider._score_alerts_by_ticker["ticker-1"]
    assert partial.health.healthy is False
    assert partial.alerts == ()
    assert tracker._scores["soccer_mls:1"][0:2] == (0, 0)

    client.fail_first_date = False
    clock[0] = 10.0
    recovery = provider.fetch_for_ticker("ticker-1", settings)
    assert recovery.alerts == ()

    client.score = 2
    clock[0] = 15.0
    resumed = provider.fetch_for_ticker("ticker-1", settings)
    assert len(resumed.alerts) == 1
    assert resumed.alerts[0]["home_score"] == 2


def test_fotmob_dense_live_snapshot_drops_stale_details() -> None:
    clock = [0.0]
    provider = FotMobSoccerProvider(
        {"soccer_mls": 130},
        now=lambda: _NOW,
        monotonic=lambda: clock[0],
        detail_executor=_NoOpExecutor(),
    )
    provider._details["1"] = _DetailCacheEntry(
        fetched_at=0.0,
        state="in",
        payload={"general": {"teamColors": {"darkMode": {"home": "#80000A"}}}},
    )
    records = tuple(("soccer_mls", _live_match(index)) for index in range(1, 6))

    clock[0] = 5.0

    assert provider._detail_snapshot(records) == {}

