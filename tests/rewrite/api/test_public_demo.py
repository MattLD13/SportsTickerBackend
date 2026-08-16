"""Protect the public ticker demonstration route."""

from __future__ import annotations

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

        for asset in ("style.css", "led.js", "ticker-demo.js"):
            response = client.get(f"/dashboard/static/{asset}")
            assert response.status_code == 200
    finally:
        app.extensions["sports_ticker.backend_application"].close()
