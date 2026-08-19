"""Verify browser controller surfaces use the scoped token boundary."""

from __future__ import annotations
import pytest

from sports_ticker.bootstrap_v2 import create_backend_application

pytestmark = pytest.mark.critical


def test_dashboard_shell_does_not_render_fleet_before_controller_token(tmp_path) -> None:
    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        client = app.test_client()
        client.post(
            "/api/v2/devices/register",
            json={"device_id": "private-pi", "name": "Private", "metadata": {}},
        )

        response = client.get("/dashboard")
        assert response.status_code == 200
        assert b"controller-token" in response.data
        assert b"private-pi" not in response.data

        script = client.get("/dashboard/static/dashboard_v2/app.js")
        assert script.status_code == 200
        source = script.get_data(as_text=True)
        assert "Authorization" in source
        assert "sessionStorage" in source
        assert 'api("/api/v2/tickers", {\n        method: "POST"' not in source
    finally:
        app.extensions["sports_ticker.backend_application"].close()


def test_display_alert_surface_sends_the_controller_token(tmp_path) -> None:
    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None)
    try:
        client = app.test_client()
        page = client.get("/display-alerts")
        assert page.status_code == 200
        source = page.get_data(as_text=True)
        assert 'id="controller-token"' in source
        assert "Authorization" in source
        assert "sessionStorage" in source
    finally:
        app.extensions["sports_ticker.backend_application"].close()
