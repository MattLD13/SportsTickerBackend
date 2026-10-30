from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from ticker.server.providers.stock_catalog import StockSymbolCatalog
from ticker.server.offline import create_offline_application

pytestmark = pytest.mark.critical


def test_stock_search_uses_provider_symbols_and_caches_bounded_results(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "private-test-key")
    calls = []
    class Client:
        def get_json(self, url, *, timeout):
            calls.append(parse_qs(urlparse(url).query))
            return {"result": [
                {"symbol": "AAP", "description": "Advance Auto Parts"},
                {"symbol": "AAPL", "description": "Apple Inc"},
                {"symbol": "AAPL", "description": "Duplicate"},
                {"symbol": "AAPL.L", "description": "Overseas Listing"},
                {"symbol": "BAD!", "description": "Invalid"},
                {"symbol": "NODESC"}, None,
            ]}
    now = [0]
    catalog = StockSymbolCatalog(Client(), clock=lambda: now[0])
    rows = catalog.search(" aapl ")
    assert rows[0] == {"symbol": "AAPL", "name": "Apple Inc"}
    assert len(rows) == 3
    rows[0]["name"] = "changed"
    assert catalog.search("AAPL")[0]["name"] == "Apple Inc"
    assert len(calls) == 1
    assert calls[0]["exchange"] == ["US"]
    assert calls[0]["q"] == ["AAPL"]
    assert "private-test-key" not in str(catalog.search("AAPL"))
    now[0] += 3601
    catalog.search("AAPL")
    assert len(calls) == 2
    assert catalog.search("") == []
    with pytest.raises(ValueError): catalog.search("x" * 61)


def test_stock_catalog_http_contract_and_failure_does_not_expose_provider_details(tmp_path, monkeypatch):
    app = create_offline_application(tmp_path / "fleet.sqlite3", [])
    try:
        app.extensions["ticker.stock_catalog"] = SimpleNamespace(search=lambda query: [{"symbol": "NVDA", "name": "NVIDIA Corp"}])
        client = app.test_client()
        assert client.get("/stocks?q=nvid").get_json() == {"stocks": [{"symbol": "NVDA", "name": "NVIDIA Corp"}]}
        monkeypatch.setenv("FINNHUB_API_KEY", "sensitive-key")
        class Broken:
            def get_json(self, url, *, timeout): raise RuntimeError(url)
        app.extensions["ticker.stock_catalog"] = StockSymbolCatalog(Broken())
        response = client.get("/stocks?q=NVDA")
        assert response.status_code == 503
        assert "sensitive-key" not in response.get_data(as_text=True)
        assert client.get("/stocks?q=" + "x" * 61).status_code == 400
    finally:
        app.extensions["ticker.application"].close()
