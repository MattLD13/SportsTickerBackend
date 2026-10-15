"""Prove Mini sprite projection and public immutable delivery through real V2 routes."""

from datetime import datetime, timezone
import hashlib
import io

from PIL import Image
import pytest

from sports_ticker.assets.mini_service import MiniSpriteService, SourceReply
from sports_ticker.bootstrap_v2 import create_backend_application
from sports_ticker.domain import ContentItem, DisplaySettings, TickerSnapshot


pytestmark = pytest.mark.critical


def test_mini_asset_contract_prepares_once_and_serves_checked_immutable_bytes(tmp_path):
    output = io.BytesIO()
    Image.new("RGBA", (25, 18), (240, 100, 0, 210)).save(output, format="PNG")
    calls = []

    def fetch(url, *_):
        calls.append(url)
        return SourceReply(output.getvalue(), '"team"')

    service = MiniSpriteService(tmp_path / "sprites", fetcher=fetch, clock=lambda: 1000)
    app = create_backend_application(tmp_path / "db.sqlite3", [], mini_sprites=service, clock=lambda: 1000)
    application = app.extensions["sports_ticker.backend_application"]
    client = app.test_client()
    try:
        for ticker_id, family in (("mini", "mini"), ("pi", "full")):
            application.create_ticker(ticker_id, pairing={"paired": True})
            application.register_device(ticker_id, profile={"product_family": family}, metadata={"mini_sprite_protocol": 1})
            application.snapshot_store.replace(TickerSnapshot(
                ticker_id=ticker_id, revision=1, observed_at=datetime.now(timezone.utc),
                effective_settings=DisplaySettings(), alerts=(), news=(), content=(ContentItem(
                    id="game", family="sports", kind="scoreboard", is_shown=True,
                    data={"sport": "nhl", "away_abbr": "NYR", "home_abbr": "BOS",
                          "away_logo": "https://a.espncdn.com/team.png", "home_logo": "https://a.espncdn.com/team.png"},
                ),),
            ))
        pending = client.get("/api/v2/tickers/mini/data").get_json()
        assert pending["content"]["sports"][0]["data"]["away_logo_asset"]["state"] == "pending"
        service.wait()
        data = client.get("/api/v2/tickers/mini/data").get_json()["content"]["sports"][0]["data"]
        asset = data["away_logo_asset"]
        assert asset["state"] == "ready" and len(calls) == 1
        response = client.get(asset["url"])
        assert response.status_code == 200 and len(response.data) == asset["length"] == 705
        assert hashlib.sha256(response.data).hexdigest() == asset["sha256"]
        assert response.headers["X-Content-SHA256"] == asset["sha256"]
        assert "immutable" in response.headers["Cache-Control"]
        assert client.get(asset["url"], headers={"If-None-Match": response.headers["ETag"]}).status_code == 304
        assert client.get("/api/v2/assets/mini-sports/not-a-hash.mts").status_code == 404
        full = client.get("/api/v2/tickers/pi/data").get_json()
        assert "away_logo_asset" not in full["content"]["sports"][0]["data"]
    finally:
        application.close()
