"""Regression tests for provider isolation in the refresh scheduler."""

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from sports_ticker.application.scheduler import RefreshScheduler
from sports_ticker.domain import ContentItem
from sports_ticker.providers.contracts import ProviderHealth, ProviderResult


pytestmark = pytest.mark.critical


def test_failed_provider_does_not_block_snapshot_publication() -> None:
    """Publish healthy provider data when an unrelated provider is unavailable."""

    published = []

    def publish(ticker_id, settings, provider_data):
        published.append((ticker_id, dict(provider_data)))
        return True

    def failing_provider(settings):
        del settings
        raise RuntimeError("HTTP 429 Too Many Requests")

    scheduler = RefreshScheduler(
        publish,
        monotonic=lambda: 0.0,
        wall_clock=lambda: datetime(2026, 8, 21, 18, 52, tzinfo=timezone.utc),
    )
    scheduler.register_provider(
        "espn",
        5.0,
        lambda settings: {"content": "scores"},
    )
    scheduler.register_provider("racing", 15.0, failing_provider)
    scheduler.register_ticker("ticker-1", lambda ticker_id: {})

    result = scheduler.run_due(0.0)

    assert result == ("ticker-1",)
    assert published == [("ticker-1", {"espn": {"content": "scores"}})]
    assert scheduler.get_health("espn").last_error is None
    assert scheduler.get_health("racing").last_error == (
        "ticker-1: HTTP 429 Too Many Requests"
    )
    assert scheduler.get_health("racing").consecutive_failures == 1


def test_accepted_degraded_provider_result_publishes_and_reports_warning() -> None:
    published = []

    def publish(ticker_id, settings, provider_data):
        del settings
        published.append((ticker_id, dict(provider_data)))
        return True

    def espn_provider(settings):
        del settings
        return ProviderResult(
            content=(ContentItem(id="game", data={"sport": "nfl"}),),
            health=ProviderHealth(
                healthy=True,
                provider="espn",
                error="mlb: scoreboard unavailable",
            ),
        )

    scheduler = RefreshScheduler(
        publish,
        monotonic=lambda: 0.0,
        wall_clock=lambda: datetime(2026, 8, 21, 18, 52, tzinfo=timezone.utc),
    )
    scheduler.register_provider("espn", 5.0, espn_provider)
    scheduler.register_ticker("ticker-1", lambda ticker_id: {})

    result = scheduler.run_due(0.0)

    assert result == ("ticker-1",)
    assert published[0][1]["espn"].health.error == "mlb: scoreboard unavailable"
    assert scheduler.get_health("espn").last_error == (
        "ticker-1: mlb: scoreboard unavailable"
    )
    assert scheduler.get_health("espn").consecutive_failures == 0


def test_repeated_provider_errors_are_compact_for_many_tickers() -> None:
    def publish(ticker_id, settings, provider_data):
        del ticker_id, settings, provider_data
        return True

    def failing_provider(settings):
        del settings
        raise RuntimeError("HTTP 403 from scoreboard")

    scheduler = RefreshScheduler(
        publish,
        monotonic=lambda: 0.0,
        wall_clock=lambda: datetime(2026, 8, 21, 18, 52, tzinfo=timezone.utc),
    )
    scheduler.register_provider("espn", 5.0, failing_provider)
    for index in range(100):
        scheduler.register_ticker(f"ticker-{index}", lambda ticker_id: {})

    scheduler.run_due(0.0)

    assert scheduler.get_health("espn").last_error == (
        "100 tickers: HTTP 403 from scoreboard"
    )


def test_failed_refresh_keeps_compatible_cached_provider_data() -> None:
    """Keep last good data for a provider when its next refresh fails."""

    clock = [0.0]
    racing_fails = [False]
    published = []

    def publish(ticker_id, settings, provider_data):
        published.append((ticker_id, dict(provider_data)))
        return True

    def racing_provider(settings):
        del settings
        if racing_fails[0]:
            raise RuntimeError("OpenF1 unavailable")
        return {"session": "cached"}

    scheduler = RefreshScheduler(
        publish,
        monotonic=lambda: clock[0],
        wall_clock=lambda: datetime(2026, 8, 21, 18, 52, tzinfo=timezone.utc),
    )
    scheduler.register_provider("espn", 5.0, lambda settings: {"scores": 1})
    scheduler.register_provider("racing", 15.0, racing_provider)
    scheduler.register_ticker("ticker-1", lambda ticker_id: {})

    assert scheduler.run_due(0.0) == ("ticker-1",)

    racing_fails[0] = True
    clock[0] = 15.0
    assert scheduler.run_due(15.0) == ("ticker-1",)
    assert published[-1][1]["racing"] == {"session": "cached"}
    assert scheduler.get_health("racing").last_error == (
        "ticker-1: OpenF1 unavailable"
    )


def test_settings_key_is_frozen_once_per_provider_ticker_pass() -> None:
    """Reuse one immutable settings key across refresh and publication checks."""

    calls = []
    published = []

    def publish(ticker_id, settings, provider_data):
        published.append((ticker_id, dict(provider_data)))
        return True

    def settings_key(settings):
        calls.append(settings)
        return settings.timezone

    scheduler = RefreshScheduler(
        publish,
        monotonic=lambda: 0.0,
        wall_clock=lambda: datetime(2026, 8, 21, 18, 52, tzinfo=timezone.utc),
    )
    scheduler.register_provider(
        "espn",
        5.0,
        lambda settings: {"scores": 1},
        settings_key=settings_key,
    )
    scheduler.register_ticker("ticker-1", lambda ticker_id: {})

    assert scheduler.run_due(0.0) == ("ticker-1",)
    assert len(calls) == 1

    assert scheduler.run_due(5.0) == ("ticker-1",)
    assert len(calls) == 2
    assert len(published) == 2


def test_ready_score_publishes_while_another_provider_is_blocked() -> None:
    blocked, release, ready = Event(), Event(), Event()
    published = []

    def slow(settings):
        blocked.set()
        assert release.wait(5)
        return {"weather": 1}

    scheduler = RefreshScheduler(lambda ticker, settings, data: published.append(dict(data)),
                                 monotonic=lambda: 0.0, executor=ThreadPoolExecutor(max_workers=2))
    scheduler.set_wake(ready.set)
    scheduler.register_provider("weather", 300, slow)
    scheduler.register_provider("espn", 5, lambda settings: {"score": 7})
    scheduler.register_ticker("one", lambda _: {})
    try:
        assert scheduler.run_due(0) == ()
        assert blocked.wait(2)
        assert ready.wait(2)
        assert scheduler.run_due(0) == ("one",)
        assert published == [{"espn": {"score": 7}}]
        assert not release.is_set()
        release.set()
    finally:
        release.set()
        scheduler.close()


def test_source_notifications_coalesce_and_keep_the_http_deadline() -> None:
    calls, published = [], []
    scheduler = RefreshScheduler(lambda ticker, settings, data: published.append((ticker, dict(data))), monotonic=lambda: 0.0)
    scheduler.register_provider("espn", 5, lambda settings: calls.append("http") or {"score": 0},
                                refresh_changed=lambda settings: calls.append("live") or {"score": 7})
    scheduler.register_ticker("nfl", lambda _: {"active_sports": {"nfl": True, "nba": False}})
    scheduler.register_ticker("nba", lambda _: {"active_sports": {"nfl": False, "nba": True}})
    scheduler.run_due(0)
    calls.clear()
    published.clear()
    scheduler.request_refresh("espn", {"nfl"})
    scheduler.request_refresh("espn", {"nfl"})
    assert scheduler.run_due(1) == ("nfl",)
    assert calls == ["live"]
    assert published[0][1]["espn"] == {"score": 7}
    assert scheduler.run_due(2) == ()
    assert scheduler.run_due(5) == ("nfl", "nba")
    assert calls == ["live", "http", "http"]
    scheduler.request_refresh("espn", {"nfl"})
    assert scheduler.run_due(10) == ("nfl", "nba")
    assert calls[-2:] == ["http", "http"]


def test_settings_changed_during_read_cannot_publish_an_old_result() -> None:
    started, release, ready = Event(), Event(), Event()
    settings = [{"timezone": "UTC"}]
    published = []

    def read(value):
        started.set()
        assert release.wait(5)
        return {"zone": value.timezone}

    scheduler = RefreshScheduler(lambda ticker, settings, data: published.append(dict(data)),
                                 monotonic=lambda: 0.0, executor=ThreadPoolExecutor(max_workers=1))
    scheduler.set_wake(ready.set)
    scheduler.register_provider("espn", 5, read)
    scheduler.register_ticker("one", lambda _: settings[0])
    try:
        scheduler.run_due(0)
        assert started.wait(2)
        settings[0] = {"timezone": "America/New_York"}
        release.set()
        assert ready.wait(2)
        assert scheduler.run_due(1) == ()
        assert published == []
        ready.clear()
        scheduler.run_due(1)
        assert ready.wait(2)
        assert scheduler.run_due(1) == ("one",)
        assert published == [{"espn": {"zone": "America/New_York"}}]
    finally:
        release.set()
        scheduler.close()


def test_source_change_during_a_pending_read_remains_queued() -> None:
    started, release = Event(), Event()
    published = []

    def read(settings):
        started.set()
        assert release.wait(5)
        return {"score": 0}

    scheduler = RefreshScheduler(lambda ticker, settings, data: published.append(dict(data)),
                                 monotonic=lambda: 0.0, executor=ThreadPoolExecutor(max_workers=1))
    scheduler.register_provider("espn", 5, read, refresh_changed=lambda settings: {"score": 7})
    scheduler.register_ticker("one", lambda _: {})
    try:
        scheduler.run_due(0)
        assert started.wait(2)
        scheduler.request_refresh("espn", {"nfl"})
        assert scheduler.run_due(1) == ()
        release.set()
        scheduler._pending["espn"][0].result(timeout=2)
        assert scheduler.run_due(1) == ("one",)
        assert published[-1]["espn"]["score"] == 0
        scheduler.run_due(1)
        scheduler._pending["espn"][0].result(timeout=2)
        assert scheduler.run_due(1) == ("one",)
        assert published[-1]["espn"]["score"] == 7
    finally:
        release.set()
        scheduler.close()


def test_background_scheduler_uses_one_batch_and_keeps_ticker_results_separate() -> None:
    ready = Event()
    batches, published = [], []

    def batch(selected, *, live_only):
        batches.append((tuple(selected), live_only))
        return {key: {"ticker": key} for key in selected}

    def individual(settings):
        raise AssertionError("The batch path must not call the per-ticker reader")

    scheduler = RefreshScheduler(lambda ticker, settings, data: published.append((ticker, dict(data))),
                                 monotonic=lambda: 0.0, executor=ThreadPoolExecutor(max_workers=1))
    scheduler.set_wake(ready.set)
    scheduler.register_provider("espn", 5, individual, refresh_batch=batch)
    scheduler.register_ticker("one", lambda _: {})
    scheduler.register_ticker("two", lambda _: {})
    try:
        assert scheduler.run_due(0) == ()
        assert ready.wait(2)
        assert scheduler.run_due(1) == ("one", "two")
        assert batches == [(("one", "two"), False)]
        assert published == [("one", {"espn": {"ticker": "one"}}), ("two", {"espn": {"ticker": "two"}})]
    finally:
        scheduler.close()
