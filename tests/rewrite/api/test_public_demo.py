"""Protect the public ticker demonstration route."""

from __future__ import annotations

import base64
import json
from io import BytesIO

from PIL import Image
import pytest

from sports_ticker.bootstrap_v2 import create_backend_application

pytestmark = pytest.mark.critical


@pytest.fixture(autouse=True)
def prepared_public_assets(monkeypatch):
    """Keep pixel boundary tests independent of external logo downloads."""
    from sports_ticker.dashboard_v2 import routes
    monkeypatch.setattr(routes._PreviewAssets, "prefetch", lambda self, content: None)
    monkeypatch.setattr(routes, "time", lambda: 1792168467.0)
    monkeypatch.setattr(routes, "_SAMPLE_STARTED", 1792168355.0)


def _close(app):
    assets = app.extensions.get("sports_ticker.dashboard_preview_assets")
    if assets:
        assets.close()
    app.extensions["sports_ticker.backend_application"].close()


def test_public_frames_match_hardware_and_follow_renderer_changes(tmp_path, monkeypatch) -> None:
    """Prove that web frames use live renderers instead of stored main images."""
    from copy import deepcopy
    from datetime import datetime
    from sports_ticker.dashboard_v2 import routes
    from sports_ticker.dashboard_v2.preview import PreviewRenderer, layout_case, layout_library
    from ticker_core.bootstrap import create_default_frame_builder
    from ticker_core.features.sports import SportsRenderer
    from ticker_core.rendering.fonts import load_default_font_set
    from ticker_core.runtime import Content, FrameDecision, FrameKind

    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        from PIL import ImageFont
        fonts = load_default_font_set()
        for name in ("normal", "medium", "big", "huge", "clock", "tiny", "micro", "nano"):
            assert getattr(fonts, name).layout_engine == ImageFont.Layout.BASIC
        client = app.test_client()
        with app.app_context():
            assets = routes._preview_assets()
        builder, viewport = create_default_frame_builder(assets)
        try:
            for name in ("FB16", "HK07", "MD04", "MD10", "MD20"):
                row = layout_case(name)
                game = deepcopy(row["game"])
                if row["mode"] == "sports":
                    game["sports_presentation"] = "pinned"
                now = datetime.fromisoformat(row.get("example_time", layout_library()["example_time"]))
                item = Content(str(game.get("id") or "public-demo"), game.get("type", "scoreboard"), game.get("sport", row["mode"]), game)
                expected = builder.build(FrameDecision(FrameKind.STATIC, 1/30, 100, False, now, row["mode"], content=item))
                response = client.get(f"/api/v2/demo/frame.png?case={name}")
                assert Image.open(BytesIO(response.data)).convert("RGB").tobytes() == expected.convert("RGB").tobytes(), name
        finally:
            viewport.close()

        original = SportsRenderer.render_full
        def changed_layout(self, *args, **kwargs):
            image = original(self, *args, **kwargs)
            image.putpixel((383, 31), (255, 0, 255))
            return image
        monkeypatch.setattr(SportsRenderer, "render_full", changed_layout)
        assets.renderer.close()
        assets.renderer = PreviewRenderer(assets)
        response = client.get("/api/v2/demo/frame.png?case=HK07")
        assert Image.open(BytesIO(response.data)).getpixel((383, 31)) == (255, 0, 255)
        assert client.get("/api/v2/demo/frame.png?case=HK07", headers={"If-None-Match": response.headers["ETag"]}).status_code == 304
        for query in ("mode=invalid", "case=unknown", "case=SY05"):
            assert client.get("/api/v2/demo/frame.png?" + query).status_code == 404
        assert client.get("/api/v2/demo/frame.png?case=HK07&presentation=invalid").status_code == 400
    finally:
        _close(app)


def test_public_scroll_matches_real_card_viewport(tmp_path) -> None:
    """Keep real pane widths, dividers, and seamless repetition."""
    from datetime import datetime
    from time import monotonic, sleep
    from sports_ticker.dashboard_v2 import routes
    from sports_ticker.dashboard_v2.preview import case_items, layout_case, layout_library
    from ticker_core.bootstrap import create_default_frame_builder
    from ticker_core.context import RenderContext
    from ticker_core.runtime import Content

    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        with app.app_context():
            assets = routes._preview_assets()
        _, viewport = create_default_frame_builder(assets)
        try:
            row = layout_case("HK07")
            games = case_items(row, "rotation")
            items = tuple(Content(str(index), game.get("type", "scoreboard"), game["sport"], game) for index, game in enumerate(games))
            now = datetime.fromisoformat(layout_library()["example_time"])
            viewport.update(items, RenderContext(now), "sports")
            deadline = monotonic() + 5
            while viewport.status["pending"] and monotonic() < deadline:
                viewport.install_completed()
                sleep(.001)
            assert viewport.status["pending"] == 0
            response = app.test_client().get("/api/v2/demo/frame.png?case=HK07&presentation=rotation")
            strip = Image.open(BytesIO(response.data)).convert("RGB")
            assert strip.width == viewport.layout.width
            for offset in (0, 1, strip.width - 1):
                expected = viewport.frame(offset)
                image = Image.new("RGB", (384, 32))
                for x in range(384):
                    image.paste(strip.crop(((offset+x) % strip.width, 0, (offset+x) % strip.width+1, 32)), (x, 0))
                assert image.tobytes() == expected.tobytes()
        finally:
            viewport.close()
    finally:
        _close(app)


def test_public_demo_stays_available_without_controller_access(tmp_path) -> None:
    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        client = app.test_client()
        client.post(
            "/api/v2/devices/register",
            json={"device_id": "private-pi", "name": "Private", "metadata": {}},
        )

        for route in ("/", "/demo", "/demo/portfolio"):
            response = client.get(route)
            assert response.status_code == 200
            assert b"data-ticker-demo" in response.data
            assert b"data-layout-explorer" not in response.data
            assert b"layout-explorer.css" not in response.data
            assert b"layout-explorer.js" not in response.data
            assert b"private-pi" not in response.data
        portfolio_page = client.get("/demo/portfolio").get_data(as_text=True)
        assert "demo-portfolio" in portfolio_page
        assert "demo-page-head" not in portfolio_page
        assert "demo-page-foot" not in portfolio_page
        assert b'href="#fleet"' in client.get("/").data
        home_page = client.get("/").data
        for section in ("demo", "fleet", "modes", "coverage", "hardware"):
            assert f'id="{section}"'.encode() in home_page
        assert b'href="/demo/layouts"' in home_page
        assert b"Explore big + Mini layouts" not in client.get("/demo").data
        assert b'"id": "music", "kind": "frame"' in client.get("/").data

        for asset in ("style.css", "led.js", "ticker-demo.js", "mr-blue-sky-cover.png"):
            response = client.get(f"/dashboard/static/{asset}")
            assert response.status_code == 200

        demo_script = client.get("/dashboard/static/ticker-demo.js").get_data(as_text=True)
        assert "/api/v2/demo/frame.png" in demo_script
        assert "drawMusicFrame" not in demo_script
        assert "drawClockFrame" not in demo_script
        assert "/api/spotify/now" not in demo_script

        for mode in ("sports", "weather", "flights", "airports"):
            response = client.get(f"/api/v2/demo/frame.png?mode={mode}")
            assert response.status_code == 200
            assert response.mimetype == "image/png"
            assert Image.open(BytesIO(response.data)).size[1] == 32
    finally:
        _close(app)


def test_public_layout_explorer_has_exact_frames_without_fleet_access(tmp_path, monkeypatch) -> None:
    """Serve both board sizes and all modes without touching device records."""
    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    backend = app.extensions["sports_ticker.backend_application"]
    try:
        def reject_fleet_read():
            raise AssertionError("The sample explorer cannot read fleet state.")

        monkeypatch.setattr(backend, "list_tickers", reject_fleet_read)
        client = app.test_client()
        response = client.get("/demo/layouts")
        assert response.status_code == 200
        assert b"data-layout-explorer" in response.data
        assert b'class="layout-page"' in response.data
        assert b'class="frame explorer"' in response.data
        assert b"Back to main website" in response.data
        assert b"static/style.css" in response.data
        assert b"static/led.js" in response.data
        assert response.data.index(b"static/style.css") < response.data.index(b"static/layout-explorer.css")
        for control in ("category", "search", "device", "layout", "pixels", "brightness", "play", "share", "zoom"):
            assert f'id="{control}"'.encode() in response.data
        for asset in ("layout-explorer.css", "layout-explorer.js"):
            assert client.get(f"/dashboard/static/{asset}").status_code == 200
        response = client.get("/dashboard/static/layout-gallery.json")
        assert response.status_code == 200
        data = response.get_json()
        assert data["schema_version"] == 2
        rows = data["cases"]
        assert len(rows) >= 114
        assert len({row["name"] for row in rows}) == len(rows)
        assert {row["mode"] for row in rows} == {
            "sports", "stock", "weather", "music", "flights", "airports", "clock", "pairing", "message",
        }
        labels = {
            row["game"].get("situation", {}).get("manpower", {}).get("powerPlayLabel", "")
            for row in rows
        }
        assert {"PP", "5v3"} <= labels
        assert not {"5v4", "4v3"} & labels
        assert any(row["game"].get("status") == "OT4" and row["game"].get("sport") == "ncf_fbs" for row in rows)
        for row in rows:
            assert row["mini_source"] in {"firmware", "hardware"}
            with Image.open(BytesIO(base64.b64decode(row["mini"], validate=True))) as mini:
                assert mini.size == (64, 32), row["name"]
                mini.load()
            assert "pinned" not in row["main"]
            if row["main"]["available"]:
                response = client.get(f"/api/v2/demo/frame.png?case={row['name']}")
                assert response.status_code == 200, row["name"]
                with Image.open(BytesIO(response.data)) as main:
                    assert main.size == (384, 32), row["name"]
                    main.load()
            else:
                assert row["main"]["note"]
                assert client.get(f"/api/v2/demo/frame.png?case={row['name']}").status_code == 404
            assert not any(key.endswith("_sprite") for key in row)
            assert "ticker_id" not in row["game"]
            if row["group"] == "Other sports":
                assert "generic scoreboard" in row["note"]
        for private_value in (b"ticker2.local", b"esp32s3-E47FF1818C58", b"lehigh-guest", b"/tmp/"):
            assert private_value not in json.dumps(data).encode()
        assert client.post("/demo/layouts").status_code == 405
    finally:
        _close(app)

def test_public_demo_sports_uses_live_snapshot_independent_of_ticker_mode(tmp_path) -> None:
    from datetime import datetime, timezone
    from sports_ticker.domain import ContentItem, DisplaySettings, TickerSnapshot

    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        client = app.test_client()
        registration = client.post(
            "/api/v2/devices/register",
            json={"device_id": "test-device", "name": "Living Room", "metadata": {}},
        ).get_json()
        ticker_id = registration["ticker_id"]

        # User has their ticker set to weather mode and paired
        from sports_ticker.fleet import PairingState
        backend = app.extensions["sports_ticker.backend_application"]
        backend.repository.update_ticker(
            ticker_id,
            display_settings=DisplaySettings(mode="weather", sports_filter="my_teams"),
            pairing=PairingState(paired=True),
        )

        # Snapshot in snapshot store has real sports content
        real_game = ContentItem(
            id="mlb-real-1",
            family="sports",
            kind="scoreboard",
            data={
                "type": "scoreboard",
                "sport": "mlb",
                "away_abbr": "BOS",
                "away_score": 5,
                "away_color": "#bd3039",
                "home_abbr": "NYY",
                "home_score": 4,
                "home_color": "#003087",
                "state": "in",
                "status": "TOP 8TH",
            },
        )
        backend.snapshot_store.replace(
            TickerSnapshot(
                ticker_id=ticker_id,
                revision=1,
                observed_at=datetime.now(timezone.utc),
                content=(real_game,),
                alerts=(),
                news=(),
                effective_settings=DisplaySettings(mode="weather"),
            )
        )

        # Demo preview for sports must retrieve real sports from the snapshot
        response = client.get("/api/v2/demo/frame.png?mode=sports")
        assert response.status_code == 200
        assert response.mimetype == "image/png"
        img = Image.open(BytesIO(response.data))
        assert img.size[1] == 32
        assert img.size[0] > 0
    finally:
        _close(app)


def test_public_demo_sports_keeps_hardware_ads_off_server(tmp_path) -> None:
    from datetime import datetime, timezone
    from sports_ticker.dashboard_v2 import routes
    from sports_ticker.domain import ContentItem, DisplaySettings, TickerSnapshot
    from sports_ticker.fleet import PairingState

    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        client = app.test_client()
        registration = client.post(
            "/api/v2/devices/register",
            json={"device_id": "test-device", "name": "Living Room", "metadata": {}},
        ).get_json()
        ticker_id = registration["ticker_id"]
        backend = app.extensions["sports_ticker.backend_application"]
        settings = DisplaySettings(
            mode="sports",
            live_delay_mode=True,
            live_delay_seconds=45,
        )
        backend.repository.update_ticker(
            ticker_id,
            display_settings=settings,
            pairing=PairingState(paired=True),
        )
        games = tuple(
            ContentItem(
                id=f"mlb-real-{index}",
                family="sports",
                kind="scoreboard",
                data={
                    "type": "scoreboard",
                    "sport": "mlb",
                    "away_abbr": "BOS",
                    "away_score": index,
                    "home_abbr": "NYY",
                    "home_score": index,
                    "state": "in",
                    "status": "TOP 8TH",
                },
            )
            for index in range(6)
        )
        backend.snapshot_store.replace(
            TickerSnapshot(
                ticker_id=ticker_id,
                revision=1,
                observed_at=datetime.now(timezone.utc),
                content=games,
                alerts=(),
                news=(),
                effective_settings=settings,
            )
        )

        with app.app_context():
            content = routes._live_sports_content()
        assert all(
            item["kind"] != "fan_duel_joke_ad"
            for item in content["sports"]
        )

        response = client.get("/api/v2/demo/frame.png?mode=sports")
        assert response.status_code == 200
        assert Image.open(BytesIO(response.data)).size[1] == 32
    finally:
        _close(app)
