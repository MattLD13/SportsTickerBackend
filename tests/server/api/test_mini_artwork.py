"""Check album preparation, bounded RAM ownership, and the Mini music contract."""
import hashlib
import io
from datetime import datetime, timezone

import pytest
from PIL import Image

from ticker.server.mini_assets.mini_artwork import HEADER, WIRE_BYTES, MiniArtworkService
from ticker.server.mini_assets.mini_service import SourceReply
from ticker.shared.domain import ContentItem, DisplaySettings, TickerSnapshot
from ticker.server.store.device_credentials import device_token_hash
from ticker.server.offline import create_offline_application

pytestmark = pytest.mark.critical


def test_music_cover_uses_real_projection_and_checked_memory_only_bytes(tmp_path):
    calls = []

    def fetch(url, *_):
        calls.append(url)
        source = io.BytesIO()
        Image.new("RGB", (90, 60), (240, 80 + len(calls) * 12, 32)).save(source, format="JPEG")
        return SourceReply(source.getvalue())

    service = MiniArtworkService(fetcher=fetch, clock=lambda: 100)
    app = create_offline_application(tmp_path / "fleet.db", [], mini_artwork=service, clock=lambda: 100)
    application = app.extensions["ticker.application"]
    client = app.test_client()
    try:
        tokens = {"mini": "a" * 64, "six": "b" * 64}
        for identity, family in (("mini", "mini"), ("six", "full")):
            application.create_ticker(identity, display_settings=DisplaySettings(mode="music"),
                                      pairing={"paired": True}, credential_hash=device_token_hash(tokens[identity]))
            application.register_device(identity, profile={"product_family": family, "capabilities": {"modes": ["sports", "music"]}})
            application.snapshot_store.replace(TickerSnapshot(identity, 1, datetime.now(timezone.utc), (
                ContentItem("track", "music", "spotify", True, {
                    "id": "track", "name": "Song", "artist": "Artist", "is_playing": True,
                    "cover": "https://i.scdn.co/image/album", "duration": 200.0, "progress": 93.0, "fetch_ts": 100.0,
                    "last_cover": "https://i.scdn.co/image/previous",
                    "next_covers": [f"https://i.scdn.co/image/next{index}" for index in range(4)],
                }),), (), (), DisplaySettings(mode="music")))
        headers = {"X-Device-Token": tokens["mini"]}
        first = client.get("/data", headers=headers)
        assert first.status_code == 200
        assert first.get_json()["content"]["music"][0]["data"]["cover_asset"]["state"] == "pending"
        service.wait()
        payload = client.get("/data", headers=headers).get_json()
        music = payload["content"]["music"][0]["data"]
        asset = music["cover_asset"]
        assert len(music["next_cover_assets"]) == 3
        assert music["last_cover_asset"]["state"] == "ready"
        assert all(value["state"] == "ready" for value in music["next_cover_assets"])
        assert len({value["asset_id"] for value in [asset, music["last_cover_asset"], *music["next_cover_assets"]]}) == 5
        assert asset["accent_rgb"][0] > asset["accent_rgb"][1] > asset["accent_rgb"][2]
        assert music["duration"] == 200.0 and music["progress"] == 93.0
        assert asset["width"] == asset["height"] == 32 and asset["length"] == WIRE_BYTES == 2064
        response = client.get(asset["url"])
        assert response.status_code == 200 and len(response.data) == 2064
        assert HEADER.unpack_from(response.data) == (b"MTA1", 1, 1, 32, 32, 2048, 0, 0, 0)
        assert hashlib.sha256(response.data).hexdigest() == asset["sha256"] == asset["asset_id"]
        assert client.get(asset["url"], headers={"If-None-Match": response.headers["ETag"]}).status_code == 304
        assert "cover_asset" not in client.get("/data", headers={"X-Device-Token": tokens["six"]}).get_json()["content"]["music"][0]["data"]
        assert calls == ["https://i.scdn.co/image/album", *[f"https://i.scdn.co/image/next{index}" for index in range(3)],
                         "https://i.scdn.co/image/previous"]
        assert client.get("/assets/artwork/invalid.mta").status_code == 404
    finally:
        application.close()


def test_artwork_cache_bounds_failures_and_rejects_untrusted_sources():
    def fetch(url, *_):
        source = io.BytesIO()
        color = (10, 40, 90) if url.endswith("a") else (120, 70, 20)
        Image.new("RGB", (32, 32), color).save(source, format="PNG")
        return SourceReply(source.getvalue())

    service = MiniArtworkService(fetcher=fetch, max_entries=1, clock=lambda: 100)
    try:
        for url in ("http://i.scdn.co/image/a", "https://evil.test/a", "https://i.scdn.co:bad/image/a", "https://name@i.scdn.co/a", ""):
            assert service.reference(url) == {"state": "unavailable"}
        service.reference("https://i.scdn.co/image/a"); service.wait()
        first = service.reference("https://i.scdn.co/image/a")
        service.reference("https://i.scdn.co/image/b"); service.wait()
        second = service.reference("https://i.scdn.co/image/b")
        assert first["asset_id"] != second["asset_id"]
        assert service.read(first["asset_id"]) is None
        assert service.read(second["asset_id"]) is not None
    finally:
        service.close()
