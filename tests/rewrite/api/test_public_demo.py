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

        for route in ("/", "/demo"):
            response = client.get(route)
            assert response.status_code == 200
            assert b"data-ticker-demo" in response.data
            assert b"private-pi" not in response.data
        assert b'href="#fleet"' in client.get("/").data
        assert b'data-demo-music="sample"' in client.get("/").data

        for asset in ("style.css", "led.js", "ticker-demo.js"):
            response = client.get(f"/dashboard/static/{asset}")
            assert response.status_code == 200

        for mode in ("sports", "weather", "flights", "airports"):
            response = client.get(f"/api/preview/strip.png?mode={mode}")
            assert response.status_code == 200
            assert response.mimetype == "image/png"
            assert Image.open(BytesIO(response.data)).size == (384, 32)
    finally:
        app.extensions["sports_ticker.backend_application"].close()
