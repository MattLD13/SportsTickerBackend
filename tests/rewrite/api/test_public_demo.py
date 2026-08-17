"""Protect the public ticker demonstration route."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from sports_ticker.bootstrap_v2 import create_backend_application


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
            assert b"private-pi" not in response.data
        portfolio_page = client.get("/demo/portfolio").get_data(as_text=True)
        assert "demo-portfolio" in portfolio_page
        assert "demo-page-head" not in portfolio_page
        assert "demo-page-foot" not in portfolio_page
        assert b'href="#fleet"' in client.get("/").data
        assert b'data-demo-music="sample"' in client.get("/").data
        assert b'"id": "music", "kind": "canvas"' in client.get("/").data

        for asset in ("style.css", "led.js", "ticker-demo.js", "mr-blue-sky-cover.png"):
            response = client.get(f"/dashboard/static/{asset}")
            assert response.status_code == 200

        demo_script = client.get("/dashboard/static/ticker-demo.js").get_data(as_text=True)
        assert "makeMrBlueSkyCover" in demo_script
        assert "MR. BLUE SKY" in demo_script
        assert "mr-blue-sky-cover.png" in demo_script
        assert "headX" not in demo_script

        for mode in ("sports", "weather", "flights", "airports"):
            response = client.get(f"/api/preview/strip.png?mode={mode}")
            assert response.status_code == 200
            assert response.mimetype == "image/png"
            assert Image.open(BytesIO(response.data)).size == (384, 32)
    finally:
        app.extensions["sports_ticker.backend_application"].close()


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
        response = client.get("/api/preview/strip.png?mode=sports")
        assert response.status_code == 200
        assert response.mimetype == "image/png"
        img = Image.open(BytesIO(response.data))
        assert img.size[1] == 32
        assert img.size[0] >= 384
    finally:
        app.extensions["sports_ticker.backend_application"].close()

