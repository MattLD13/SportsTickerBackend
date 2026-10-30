import hashlib

import pytest

from ticker.server.offline import create_offline_application

pytestmark = pytest.mark.critical


def device_token(ticker_id: str) -> str:
    """Return the device token of one test device. The token alone names the ticker."""
    return hashlib.sha256(ticker_id.encode()).hexdigest()


def test_device_poll_refreshes_presence_and_get_reads_preserve_it(tmp_path):
    now = [10000.0]
    app = create_offline_application(tmp_path / "fleet.sqlite3", [], clock=lambda: now[0])
    application = app.extensions["ticker.application"]
    client = app.test_client()
    try:
        client.post("/register", json={"device_id": "mini", "name": "Mini"}, headers={"X-Device-Token": device_token("mini")})
        original = application.get_ticker("mini").device.last_seen_at
        now[0] += 100
        reference = client.get("/data", headers={"X-Device-Token": device_token("mini")}).get_json()
        assert application.get_ticker("mini").device.last_seen_at == original
        response = client.post("/poll", json={"metadata": {"build": "test", "wifi_available": True}}, headers={"X-Device-Token": device_token("mini")})
        assert response.status_code == 200
        assert response.get_json() == reference
        device = application.get_ticker("mini").device
        assert device.last_seen_at == now[0]
        assert device.metadata["build"] == "test"
        assert device.metadata["wifi_available"] is True
        now[0] += 6
        assert client.post("/poll", json={}, headers={"X-Device-Token": device_token("mini")}).status_code == 200
        assert application.get_ticker("mini").device.last_seen_at == now[0]
        assert client.post("/poll", json={}, headers={"X-Device-Token": device_token("missing")}).status_code == 403
        assert client.post("/poll", json={"mode": "clock"}, headers={"X-Device-Token": device_token("mini")}).status_code == 400
        assert application.get_ticker("mini").display_settings.mode == "sports"
    finally:
        application.close()


def test_device_poll_omits_hidden_games_and_controller_read_retains_them(tmp_path):
    from datetime import datetime, timezone

    from ticker.shared.domain import ContentItem, TickerSnapshot
    flask = create_offline_application(tmp_path / "fleet.sqlite3", [])
    application = flask.extensions["ticker.application"]
    client = flask.test_client()
    headers = {"X-Device-Token": "a" * 64}
    try:
        client.post("/register", json={"device_id": "mini"}, headers=headers)
        application.update_ticker("mini", pairing={"paired": True}, display_settings={"sports_filter": "live"})
        settings = application.get_ticker("mini").display_settings
        items = tuple(ContentItem(id=state, family="sports", kind="nfl", data={"sport": "nfl", "state": state, "status": "Q1 10:00" if state == "in" else "7:00 PM", "away_abbr": "DAL", "home_abbr": "NYG"}) for state in ("in", "pre"))
        application.snapshot_store.replace(TickerSnapshot(ticker_id="mini", revision=1, observed_at=datetime.now(timezone.utc), content=items, alerts=(), news=(), effective_settings=settings))
        original = client.get("/data", headers=headers).get_json()
        selected = client.post("/poll", json={}, headers=headers).get_json()
        assert len(original["content"]["sports"]) == 2
        assert selected["content"]["sports"] == [item for item in original["content"]["sports"] if item["is_shown"]]
        assert len(selected["content"]["sports"]) == 1
        assert selected["meta"] == original["meta"]
        assert selected["settings"] == original["settings"]
    finally:
        application.close()
