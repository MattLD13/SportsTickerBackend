from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sports_ticker.application.provider_demand import ProviderDemand
from sports_ticker.application.schedule import ScheduleService
from sports_ticker.application.state_store import SnapshotStore
from sports_ticker.domain import DisplaySettings
from sports_ticker.fleet import TickerRepository
from sports_ticker.providers.market_sessions import us_equity_session
from sports_ticker.providers import stock_source

pytestmark = pytest.mark.critical


def test_demand_uses_schedule_horizon_without_device_presence(tmp_path):
    now = datetime(2026, 5, 5, 3, 55, tzinfo=timezone.utc)
    settings = DisplaySettings(mode="weather", timezone="America/New_York")
    with TickerRepository(tmp_path / "fleet.sqlite3") as repository:
        repository.create_ticker("mini", settings)
        schedules = ScheduleService(repository, SnapshotStore(), clock=lambda: now.timestamp())
        schedules.create_block("mini", days_of_week=[1], start_minute=3, end_minute=4, mode="flights")
        demand = ProviderDemand(repository, schedules)
        active = demand(("flights", "stock", "golf"), {"mini": settings}, now)
        assert active == {"flights": frozenset({"mini"}), "stock": frozenset(), "golf": frozenset()}
        assert demand(("flights",), {"mini": settings}, now + timedelta(seconds=91))["flights"] == frozenset({"mini"})
        assert demand(("espn",), {"mini": settings}, now + timedelta(days=1))["espn"] == frozenset({"mini"})


@pytest.mark.parametrize(("mode", "provider", "other_provider"), [
    ("stock", "stock", "flights"),
    ("airports", "flights", "stock"),
])
def test_app_mode_override_keeps_selected_provider_demand_without_device_presence(
    tmp_path, mode, provider, other_provider
):
    now = datetime(2026, 5, 5, 3, 55, tzinfo=timezone.utc)
    settings = DisplaySettings(mode=mode, timezone="America/New_York")
    with TickerRepository(tmp_path / f"{mode}.sqlite3") as repository:
        repository.create_ticker("mini", settings)
        schedules = ScheduleService(repository, SnapshotStore(), clock=lambda: now.timestamp())
        schedules.set_schedule_override("mini", True, settings=settings)
        demand = ProviderDemand(repository, schedules)

        active = demand((provider, other_provider), {"mini": settings}, now)
        assert active[provider] == frozenset({"mini"})
        assert active[other_provider] == frozenset()


def test_demand_resolves_once_per_ticker_and_reads_fresh_state_each_pass(tmp_path, monkeypatch):
    now = datetime(2026, 5, 5, 12, tzinfo=timezone.utc)
    settings = DisplaySettings(mode="stock")
    with TickerRepository(tmp_path / "demand.sqlite3") as repository:
        repository.create_ticker("six", settings)
        schedules = ScheduleService(repository, SnapshotStore(), clock=lambda: now.timestamp())
        calls = []
        modes_within = schedules.modes_within

        def measured(*args, **kwargs):
            calls.append(args[0])
            return modes_within(*args, **kwargs)

        monkeypatch.setattr(schedules, "modes_within", measured)
        policy = ProviderDemand(repository, schedules)
        providers = ("golf", "stock", "flights", "espn")
        before = policy(providers, {"six": settings}, now)
        assert calls == ["six"]
        assert before == {"golf": frozenset(), "stock": frozenset({"six"}), "flights": frozenset(), "espn": frozenset({"six"})}
        schedules.create_block("six", days_of_week=[now.weekday()], start_minute=0, end_minute=1440, mode="flights")
        after = policy(providers, {"six": settings}, now)
        assert calls == ["six", "six"]
        assert after["stock"] == frozenset()
        assert after["flights"] == frozenset({"six"})


@pytest.mark.parametrize("timestamp,opened", [
    ("2026-07-03T15:00:00+00:00", False),
    ("2026-04-03T15:00:00+00:00", False),
    ("2026-03-09T13:30:00+00:00", True),
    ("2026-03-09T13:29:00+00:00", False),
    ("2026-11-02T14:30:00+00:00", True),
    ("2026-11-27T17:59:00+00:00", True),
    ("2026-11-27T18:00:00+00:00", False),
    ("2026-11-28T16:00:00+00:00", False),
])
def test_market_holidays_early_closes_and_dst(timestamp, opened):
    assert us_equity_session(datetime.fromisoformat(timestamp).timestamp()).open is opened


def test_closed_market_fetches_once_and_retains_close_after_restart(tmp_path, monkeypatch):
    clock = [datetime(2026, 11, 27, 18, 1, tzinfo=timezone.utc).timestamp()]
    calls = []

    class ImmediateThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)

    class Quotes:
        def get_json(self, url, *, timeout):
            calls.append(url.split("?")[0])
            return {"c": 100, "d": 1, "dp": 1, "pc": 99, "t": clock[0]}

    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    monkeypatch.setattr(stock_source, "Thread", ImmediateThread)
    monkeypatch.setattr(stock_source, "MARKET_GROUPS", (SimpleNamespace(id="test", label="Test", symbols=("AAA",)),))
    source = stock_source.FinnhubStockSource(Quotes(), cache_path=tmp_path / "close.json", clock=lambda: clock[0],
                                           monotonic_clock=lambda: clock[0], sleeper=lambda duration: None)
    for _ in range(240):
        result = source.fetch(DisplaySettings(mode="stock"))
        clock[0] += 30
    assert len(calls) == 1
    assert result["content"][0]["home_score"] == "100.00"
    restarted = stock_source.FinnhubStockSource(Quotes(), cache_path=tmp_path / "close.json", clock=lambda: clock[0])
    assert restarted.fetch(DisplaySettings(mode="stock"))["content"][0]["home_score"] == "100.00"
    assert len(calls) == 1
