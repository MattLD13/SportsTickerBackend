"""Verify browser controller surfaces use the scoped token boundary."""

from __future__ import annotations

import hashlib

import pytest

from ticker3.offline import create_offline_application

pytestmark = pytest.mark.critical


def device_token(ticker_id: str) -> str:
    """Return the device token of one test device. The token alone names the ticker."""
    return hashlib.sha256(ticker_id.encode()).hexdigest()


def test_dashboard_shell_does_not_render_fleet_before_controller_token(tmp_path) -> None:
    app = create_offline_application(tmp_path / "ticker.sqlite3", [])
    try:
        client = app.test_client()
        client.post(
            "/register",
            json={"device_id": "private-pi", "name": "Private", "metadata": {}},
            headers={"X-Device-Token": device_token("private-pi")},
        )

        response = client.get("/dashboard")
        assert response.status_code == 200
        assert b"controller-token" in response.data
        assert b"private-pi" not in response.data

        script = client.get("/static/control/app.js")
        assert script.status_code == 200
        source = script.get_data(as_text=True)
        assert "Authorization" in source
        assert "sessionStorage" in source
        assert 'api("/tickers", {\n        method: "POST"' not in source
    finally:
        app.extensions["ticker.application"].close()


def test_display_alert_surface_sends_the_controller_token(tmp_path) -> None:
    app = create_offline_application(tmp_path / "ticker.sqlite3", [])
    try:
        client = app.test_client()
        page = client.get("/display-alerts")
        assert page.status_code == 200
        source = page.get_data(as_text=True)
        assert 'id="controller-token"' in source
        assert "Authorization" in source
        assert "sessionStorage" in source
    finally:
        app.extensions["ticker.application"].close()
