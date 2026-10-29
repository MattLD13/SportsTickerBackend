"""Check the publish rules of the engine without worker processes.

The supervisor has no worker connections in these tests, so a subscription goes nowhere.
Each test gives the engine worker messages directly, as the supervisor does.
"""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from sports_ticker.application.provider_keys import provider_settings_key
from sports_ticker.domain import ContentItem, DisplaySettings
from sports_ticker.providers.contracts import ProviderResult
from ticker3.contract.results import encode
from ticker3.core.engine import Engine

pytestmark = pytest.mark.critical


class Published:
    """Record each refresh that the engine asks for."""

    def __init__(self) -> None:
        self.calls = []

    def refresh(self, ticker_id, settings, data):
        self.calls.append((ticker_id, settings, dict(data)))


def engine(tmp_path, refresh, *, providers=("weather",), now=None):
    clock = now or [0.0]
    built = Engine(refresh, providers=list(providers), settings_key=provider_settings_key, builtins={},
                   socket_path=tmp_path / "t.sock", state_path=tmp_path / "state.json",
                   release_path=lambda name: tmp_path, initial_release="dev", log_directory=tmp_path / "logs",
                   monotonic=lambda: clock[0], wall_clock=lambda: datetime(2026, 10, 29, tzinfo=timezone.utc))
    built._wake = asyncio.Event()
    return built


def result(text):
    item = ContentItem(id="weather", family="weather", kind="weather", data={"summary": text})
    return {"t": "result", "result": encode(ProviderResult(content=(item,))), "started_ms": 0.0}


def summary(call):
    return call[2]["weather"].content[0].data["summary"]


def test_a_result_for_old_settings_does_not_publish(tmp_path):
    refresh = Published()
    settings = {"six": DisplaySettings(mode="weather", weather_city="Boston")}
    core = engine(tmp_path, refresh)
    core.register_ticker("six", lambda ticker_id: settings[ticker_id])
    core._pass()
    old_key = next(iter(core._wanted("weather")))
    settings["six"] = replace(settings["six"], weather_city="Denver")
    core._pass()
    new_key = next(iter(core._wanted("weather")))
    assert new_key != old_key
    core._deliver("weather", {**result("Boston"), "sub": old_key})
    core._pass()
    assert refresh.calls == []
    core._deliver("weather", {**result("Denver"), "sub": new_key})
    core._pass()
    assert [summary(call) for call in refresh.calls] == ["Denver"]


def test_paused_demand_keeps_the_last_good_data(tmp_path):
    refresh = Published()
    wanted = [True]
    core = engine(tmp_path, refresh)
    core.set_provider_demand(lambda names, tickers, now: {name: frozenset(tickers) if wanted[0] else frozenset() for name in names})
    core.register_ticker("mini", lambda ticker_id: DisplaySettings(mode="weather"))
    core._pass()
    key = next(iter(core._wanted("weather")))
    core._deliver("weather", {**result("first"), "sub": key})
    core._pass()
    wanted[0] = False
    core._pass()
    assert core._wanted("weather") == {}
    # A late result of the paused subscription is dropped, and no pass publishes again.
    core._deliver("weather", {**result("late"), "sub": key})
    core._pass()
    assert [summary(call) for call in refresh.calls] == ["first"]
    wanted[0] = True
    core._pass()
    assert list(core._wanted("weather")) == [key]


def test_demand_is_asked_once_for_the_complete_provider_set(tmp_path):
    asked = []
    core = engine(tmp_path, Published(), providers=("golf", "stock", "flights"))
    core.register_ticker("six", lambda ticker_id: DisplaySettings())

    def demand(names, tickers, now):
        asked.append((names, tuple(tickers)))
        return {name: frozenset(tickers) for name in names}

    core.set_provider_demand(demand)
    core._pass()
    assert asked == [(("golf", "stock", "flights"), ("six",))]


def test_status_is_ready_only_while_passes_complete(tmp_path):
    now = [0.0]
    core = engine(tmp_path, Published(), now=now)
    core._running = True
    assert not core.status()["ready"]
    core._pass()
    assert core.status()["ready"] and core.status()["cycles"] == 1
    now[0] = 91
    assert not core.status()["ready"]
    core._pass()
    assert core.status()["ready"]
    core._running = False
    assert not core.status()["ready"]
