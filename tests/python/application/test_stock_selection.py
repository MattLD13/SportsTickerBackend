from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from sports_ticker.domain import DisplaySettings
from sports_ticker.providers import live_sources
from sports_ticker.providers.market_sessions import MarketSession


def test_categories_select_leaders_at_open_and_close_and_momentum_intraday(tmp_path, monkeypatch):
    symbols = tuple(f"S{i}" for i in range(15))
    groups = (
        SimpleNamespace(id="stock_tech_ai", label="Tech", symbols=symbols),
        SimpleNamespace(id="stock_momentum", label="Momentum", symbols=("M",)),
    )
    monkeypatch.setattr(live_sources, "MARKET_GROUPS", groups)
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    now = [datetime(2026, 10, 20, 14, tzinfo=timezone.utc).timestamp()]
    market = [MarketSession(True, None)]
    gains = {symbol: index for index, symbol in enumerate(symbols + ("M",))}
    failed = set()
    calls = []

    class Quotes:
        def get_json(self, url, *, timeout):
            symbol = parse_qs(urlparse(url).query)["symbol"][0]
            calls.append(symbol)
            if symbol in failed:
                return {}
            return {"c": 100, "d": gains[symbol], "dp": gains[symbol], "t": now[0]}

    class ImmediateThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(live_sources, "Thread", ImmediateThread)
    source = live_sources.FinnhubStockSource(
        Quotes(), cache_path=tmp_path / "stocks.json", clock=lambda: now[0],
        monotonic_clock=lambda: now[0], sleeper=lambda _: None,
        market_session=lambda _: market[0],
    )
    settings = DisplaySettings(mode="stock")

    def selected(result, group):
        return [item["symbol"] for item in result["content"] if item["market_group"] == group]

    first = source.fetch(settings)
    tech = selected(first, "stock_tech_ai")
    assert tech == ["S14", "S13", "S12", "S11", "S10", "S9", "S8", "S7", "S1", "S0"]
    assert selected(first, "stock_momentum")[0] == "M"
    gains["S2"] = 50
    now[0] += 30
    intraday = source.fetch(settings)
    assert selected(intraday, "stock_tech_ai") == tech
    assert selected(intraday, "stock_momentum")[0] == "S2"
    assert next(item for item in intraday["content"] if item["symbol"] == "S2")["away_score"] == "+50.00%"

    market[0] = MarketSession(False, "2026-10-20")
    now[0] += 30
    failed.add("S14")
    partial_close = source.fetch(settings)
    assert selected(partial_close, "stock_tech_ai") == tech
    assert source._closed_session is None
    failed.clear()
    now[0] += 30
    close = source.fetch(settings)
    assert selected(close, "stock_tech_ai")[0] == "S2"
    count = len(calls)
    now[0] += 3600
    assert source.fetch(settings) == close
    assert len(calls) == count

    restarted = live_sources.FinnhubStockSource(
        Quotes(), cache_path=tmp_path / "stocks.json", clock=lambda: now[0],
        market_session=lambda _: market[0],
    )
    assert restarted.fetch(settings) == close
    assert len(calls) == count
    gains["S3"] = 75
    market[0] = MarketSession(True, None)
    now[0] += 86400
    assert selected(source.fetch(settings), "stock_tech_ai")[0] == "S3"
