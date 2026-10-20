from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from sports_ticker.bootstrap_v2 import create_backend_application
from sports_ticker.domain import DisplaySettings, TickerSnapshot
from sports_ticker.fleet import TickerRepository
from sports_ticker.markets import MARKET_GROUPS, MARKET_OPTIONS, selected_market_groups
from sports_ticker.production import _provider_settings_key
from sports_ticker.projections.data_api import project_data_v2, select_display_content
from sports_ticker.providers import live_sources
from sports_ticker.providers.market_sessions import MarketSession
from sports_ticker.providers.normalization import normalize_settings
from sports_ticker.providers.stocks import StockProvider

pytestmark = pytest.mark.critical


def test_custom_symbols_validate_normalize_and_persist_per_ticker(tmp_path):
    settings = normalize_settings({"custom_stock_symbols": [" nvda ", "BRK.B", "NVDA", "aapl"],
                                   "active_sports": {"stock_custom": True}, "mode": "stock"})
    assert settings.custom_stock_symbols == ("NVDA", "BRK.B", "AAPL")
    assert [group.id for group in selected_market_groups(settings.active_sports)] == ["stock_custom"]
    assert len(MARKET_OPTIONS) == len(MARKET_GROUPS) + 1
    assert sum(group.id == "stock_custom" for group in MARKET_OPTIONS) == 1
    with TickerRepository(tmp_path / "fleet.sqlite3") as repo:
        repo.create_ticker("one", settings)
        repo.create_ticker("two", {"custom_stock_symbols": ["MSFT"]})
    with TickerRepository(tmp_path / "fleet.sqlite3") as repo:
        assert repo.get_ticker("one").display_settings == settings
        assert repo.get_ticker("two").display_settings.custom_stock_symbols == ("MSFT",)
    key = _provider_settings_key("stock")
    assert key(settings) != key(DisplaySettings(custom_stock_symbols=("MSFT",)))


@pytest.mark.parametrize("symbols", ["AAPL", None, [123], [""], ["AAPL/../../"], ["AAPL NVDA"], [f"S{i}" for i in range(31)]])
def test_custom_symbols_reject_invalid_settings(symbols):
    with pytest.raises(ValueError, match="custom_stock_symbols"):
        DisplaySettings(custom_stock_symbols=symbols)


def test_custom_source_shares_quotes_but_keeps_lists_and_order_separate(tmp_path, monkeypatch):
    monkeypatch.setattr(live_sources, "MARKET_GROUPS", (SimpleNamespace(id="stock_tech_ai", label="Tech", symbols=("AAPL",)),))
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    now = [datetime(2026, 10, 20, 21, tzinfo=timezone.utc).timestamp()]
    calls = []

    class ImmediateThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)

    class Quotes:
        def get_json(self, url, *, timeout):
            symbol = parse_qs(urlparse(url).query)["symbol"][0]
            calls.append(symbol)
            return {"c": 100, "d": 2, "dp": 2, "t": now[0]}

    monkeypatch.setattr(live_sources, "Thread", ImmediateThread)
    source = live_sources.FinnhubStockSource(Quotes(), cache_path=tmp_path / "quotes.json", clock=lambda: now[0],
        monotonic_clock=lambda: now[0], sleeper=lambda _: None,
        market_session=lambda _: MarketSession(False, "2026-10-20"))
    first = DisplaySettings(mode="stock", custom_stock_symbols=("NVDA", "AAPL"), active_sports={"stock_custom": True})
    second = DisplaySettings(mode="stock", custom_stock_symbols=("MSFT",), active_sports={"stock_custom": True})
    provider = StockProvider(source)

    def projected(settings):
        result = provider.fetch(settings)
        assert result.health.healthy
        snapshot = TickerSnapshot("one", 1, datetime.now(timezone.utc), result.content, (), (), settings)
        payload = project_data_v2(snapshot, {}, {})
        payload["content"] = select_display_content(payload["content"], payload["settings"])
        return payload, [item["data"]["symbol"] for item in payload["content"]["stock"]]

    payload, symbols = projected(first)
    assert symbols == ["NVDA", "AAPL"]
    assert calls.count("AAPL") == 1
    assert payload["settings"]["custom_stock_symbols"] == ["NVDA", "AAPL"]
    now[0] += 30
    assert projected(second)[1] == ["MSFT"]
    assert "MSFT" in calls
    assert projected(first)[1] == ["NVDA", "AAPL"]
    count = len(calls)
    now[0] += 60
    assert projected(first)[1] == ["NVDA", "AAPL"]
    assert len(calls) == count
    edited = DisplaySettings(mode="stock", custom_stock_symbols=("AAPL",), active_sports={"stock_custom": True})
    assert projected(edited)[1] == ["AAPL"]


def test_custom_list_patch_and_api_round_trip(tmp_path):
    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        client = app.test_client()
        registration = client.post("/api/v2/devices/register", json={"device_id": "one"},
                                   headers={"X-Device-Token": "a" * 64}).get_json()
        pairing = client.post("/api/v2/pairings/exchange", json={"pairing_code": registration["pairing_code"]}).get_json()
        headers = {"Authorization": f"Bearer {pairing['controller_token']}"}
        endpoint = "/api/v2/tickers/one"
        settings = {"mode": "stock", "active_sports": {"stock_custom": True}, "custom_stock_symbols": ["nvda", "AAPL"]}
        response = client.patch(endpoint, json={"display_settings": settings}, headers=headers)
        assert response.status_code == 200
        assert response.get_json()["display_settings"]["custom_stock_symbols"] == ["NVDA", "AAPL"]
        data = client.get(endpoint + "/data", headers=headers).get_json()
        assert data["settings"]["custom_stock_symbols"] == ["NVDA", "AAPL"]
        invalid = client.patch(endpoint, json={"display_settings": {"custom_stock_symbols": ["INVALID!"]}}, headers=headers)
        assert invalid.status_code == 400
        assert client.get(endpoint + "/data", headers=headers).get_json()["settings"]["custom_stock_symbols"] == ["NVDA", "AAPL"]
    finally:
        app.extensions["sports_ticker.backend_application"].close()


def test_custom_projection_keeps_more_than_ten_stocks_in_saved_order():
    symbols = tuple(f"S{index}" for index in range(15))
    settings = DisplaySettings(mode="stock", custom_stock_symbols=symbols, active_sports={"stock_custom": True})

    class Source:
        def fetch(self, _settings):
            return {"content": [{"id": f"stock:{symbol}", "type": "stock_ticker", "sport": "stock",
                "market_group": "stock_custom", "symbol": symbol, "home_abbr": symbol,
                "home_score": "100.00", "away_score": "+1.00%", "situation": {"change": "+1.00"}}
                for symbol in reversed((*symbols, "FOREIGN"))]}

    result = StockProvider(Source()).fetch(settings)
    snapshot = TickerSnapshot("one", 1, datetime.now(timezone.utc), result.content, (), (), settings)
    payload = project_data_v2(snapshot, {}, {})
    selected = select_display_content(payload["content"], payload["settings"])
    assert [item["data"]["symbol"] for item in selected["stock"]] == list(symbols)
    from sports_ticker.projections.device_data import project_device_data
    mini = project_device_data({**payload, "content": selected}, mini=True)
    assert [item["data"]["symbol"] for item in mini["content"]["stock"]] == list(symbols)
