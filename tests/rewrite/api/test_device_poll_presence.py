import pytest

from sports_ticker.bootstrap_v2 import create_backend_application

pytestmark = pytest.mark.critical


def test_device_poll_refreshes_presence_and_get_reads_preserve_it(tmp_path):
    now = [10000.0]
    app = create_backend_application(tmp_path / "fleet.sqlite3", [], scheduler=None, clock=lambda: now[0])
    application = app.extensions["sports_ticker.backend_application"]
    client = app.test_client()
    try:
        client.post("/api/v2/devices/register", json={"device_id": "mini", "name": "Mini"})
        original = application.get_ticker("mini").device.last_seen_at
        now[0] += 100
        reference = client.get("/api/v2/tickers/mini/data").get_json()
        assert application.get_ticker("mini").device.last_seen_at == original
        response = client.post("/api/v2/tickers/mini/data", json={"metadata": {"build": "test", "wifi_available": True}})
        assert response.status_code == 200
        assert response.get_json() == reference
        device = application.get_ticker("mini").device
        assert device.last_seen_at == now[0]
        assert device.metadata["build"] == "test"
        assert device.metadata["wifi_available"] is True
        now[0] += 6
        assert client.post("/api/v2/tickers/mini/data", json={}).status_code == 200
        assert application.get_ticker("mini").device.last_seen_at == now[0]
        assert client.post("/api/v2/tickers/missing/data", json={}).status_code == 404
        assert client.post("/api/v2/tickers/mini/data", json={"mode": "clock"}).status_code == 400
        assert application.get_ticker("mini").display_settings.mode == "sports"
    finally:
        application.close()
