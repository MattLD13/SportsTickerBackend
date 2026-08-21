"""Regression tests for provider isolation in the refresh scheduler."""

from datetime import datetime, timezone

import pytest

from sports_ticker.application.scheduler import RefreshScheduler


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
