"""Prove Mini sprite projection and public immutable delivery through real V2 routes."""

import hashlib
import io
from datetime import datetime, timezone

import pytest
from PIL import Image

from ticker.server.mini_assets.mini_service import MiniSpriteService, SourceReply
from ticker.shared.domain import ContentItem, DisplaySettings, TickerSnapshot
from ticker.server.store.device_credentials import device_token_hash
from ticker.server.offline import create_offline_application

pytestmark = pytest.mark.critical


def test_mini_asset_contract_prepares_once_and_serves_checked_immutable_bytes(tmp_path):
    output = io.BytesIO()
    Image.new("RGBA", (25, 18), (240, 100, 0, 210)).save(output, format="PNG")
    calls = []

    def fetch(url, *_):
        calls.append(url)
        return SourceReply(output.getvalue(), '"team"')

    service = MiniSpriteService(tmp_path / "sprites", fetcher=fetch, clock=lambda: 1000)
    app = create_offline_application(tmp_path / "db.sqlite3", [], mini_sprites=service, clock=lambda: 1000)
    application = app.extensions["ticker.application"]
    client = app.test_client()
    try:
        tokens = {"mini": "a" * 64, "pi": "b" * 64}
        for ticker_id, family in (("mini", "mini"), ("pi", "full")):
            application.create_ticker(ticker_id, pairing={"paired": True}, credential_hash=device_token_hash(tokens[ticker_id]))
            application.register_device(ticker_id, profile={"product_family": family}, metadata={"mini_sprite_protocol": 1})
            application.snapshot_store.replace(TickerSnapshot(
                ticker_id=ticker_id, revision=1, observed_at=datetime.now(timezone.utc),
                effective_settings=DisplaySettings(), alerts=(), news=(), content=(ContentItem(
                    id="game", family="sports", kind="scoreboard", is_shown=True,
                    data={"sport": "nhl", "away_abbr": "NYR", "home_abbr": "BOS",
                          "away_logo": "https://a.espncdn.com/team.png", "home_logo": "https://a.espncdn.com/team.png"},
                ),),
            ))
        pending = client.get("/data", headers={"X-Device-Token": "a" * 64}).get_json()
        assert pending["content"]["sports"][0]["data"]["away_logo_asset"]["state"] == "pending"
        service.wait()
        data = client.get("/data", headers={"X-Device-Token": "a" * 64}).get_json()["content"]["sports"][0]["data"]
        compact = client.post("/poll", json={}, headers={"X-Device-Token": "a" * 64}).get_json()["content"]["sports"][0]["data"]
        assert compact["away_logo_asset"]["asset_id"] == data["away_logo_asset"]["asset_id"]
        assert compact["away_logo_asset"]["sha256"] == data["away_logo_asset"]["sha256"]
        assert "away_logo" not in compact
        assert "url" not in compact["away_logo_asset"]
        asset = data["away_logo_asset"]
        assert asset["state"] == "ready" and len(calls) == 1
        response = client.get(asset["url"])
        assert response.status_code == 200 and len(response.data) == asset["length"] == 705
        assert hashlib.sha256(response.data).hexdigest() == asset["sha256"]
        assert response.headers["X-Content-SHA256"] == asset["sha256"]
        assert "immutable" in response.headers["Cache-Control"]
        assert client.get(asset["url"], headers={"If-None-Match": response.headers["ETag"]}).status_code == 304
        assert client.get("/assets/sprites/not-a-hash.mts").status_code == 404
        full = client.get("/data", headers={"X-Device-Token": tokens["pi"]}).get_json()
        assert "away_logo_asset" not in full["content"]["sports"][0]["data"]
    finally:
        application.close()


def test_mini_stock_logos_use_shared_immutable_sprites_without_changing_six(tmp_path):
    output = io.BytesIO()
    Image.new("RGBA", (32, 32), (40, 180, 90, 255)).save(output, format="PNG")
    calls = []
    def fetch(url, *_):
        calls.append(url)
        return SourceReply(output.getvalue())

    service = MiniSpriteService(tmp_path / "sprites", fetcher=fetch, clock=lambda: 1000)
    app = create_offline_application(tmp_path / "db.sqlite3", [], mini_sprites=service, clock=lambda: 1000)
    application = app.extensions["ticker.application"]
    client = app.test_client()
    try:
        settings = DisplaySettings(mode="stock", active_sports={"stock_tech_ai": True})
        tokens = {"mini": "a" * 64, "six": "b" * 64}
        for ticker_id, family in (("mini", "mini"), ("six", "full")):
            application.create_ticker(ticker_id, display_settings=settings, pairing={"paired": True},
                                      credential_hash=device_token_hash(tokens[ticker_id]))
            application.register_device(ticker_id, profile={"product_family": family, "capabilities": {"modes": ["sports", "stock"]}}, metadata={"mini_sprite_protocol": 1})
            application.snapshot_store.replace(TickerSnapshot(ticker_id, 1, datetime.now(timezone.utc), (
                ContentItem("stock:AAPL", "stock", "stock", True, {
                    "type": "stock_ticker", "sport": "stock", "symbol": "AAPL", "market_group": "stock_tech_ai",
                    "home_score": "212.48", "away_score": "+1.25%",
                    "home_logo": "https://financialmodelingprep.com/image-stock/AAPL.png",
                }),), (), (), settings))
        headers = {"X-Device-Token": tokens["mini"]}
        client.get("/data", headers=headers)
        service.wait()
        for method, route, options in ((client.get, "/data", {}), (client.post, "/poll", {"json": {}})):
            response = method(route, headers=headers, **options)
            assert response.status_code == 200
            stock = response.get_json()["content"]["stock"][0]["data"]
            asset = stock["home_logo_asset"]
            assert asset["state"] == "ready"
            assert asset["width"] == asset["height"] == 18
            body = client.get(asset["url"]).data
            assert len(body) == 705 and hashlib.sha256(body).hexdigest() == asset["sha256"]
        six = client.get("/data", headers={"X-Device-Token": tokens["six"]}).get_json()["content"]["stock"][0]["data"]
        assert "home_logo_asset" not in six
        assert six["home_logo"] == "https://financialmodelingprep.com/image-stock/AAPL.png"
        assert calls == ["https://financialmodelingprep.com/image-stock/AAPL.png"]
    finally:
        application.close()
