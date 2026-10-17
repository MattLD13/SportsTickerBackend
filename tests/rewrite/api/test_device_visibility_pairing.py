"""Check inactive fleet rows and current app pairing codes through V2 routes."""
from datetime import datetime, timezone

import pytest

from sports_ticker.bootstrap_v2 import create_backend_application
from sports_ticker.domain import ContentItem, DisplaySettings, TickerSnapshot
from sports_ticker.fleet import TickerRecord
from sports_ticker.projections import project_data_v2

pytestmark = pytest.mark.critical


def test_month_old_rows_hide_without_revoking_controller_or_device_state(tmp_path):
    now = [10_000_000.0]
    app = create_backend_application(tmp_path / "fleet.sqlite3", [], clock=lambda: now[0])
    application = app.extensions["sports_ticker.backend_application"]
    client = app.test_client()
    try:
        registration = client.post("/api/v2/devices/register", json={"device_id":"mini", "name":"My Mini"}, headers={"X-Device-Token": "a" * 64}).get_json()
        paired = client.post("/api/v2/pairings/exchange", json={"pairing_code":registration["pairing_code"]}).get_json()
        headers = {"Authorization":f'Bearer {paired["controller_token"]}'}
        endpoint = "/api/v2/tickers"
        assert len(client.get(endpoint, headers=headers).get_json()["tickers"]) == 1
        now[0] += 30 * 86400 - 1
        assert len(client.get(endpoint, headers=headers).get_json()["tickers"]) == 1
        now[0] += 1
        response = client.get(endpoint, headers=headers)
        assert response.status_code == 200 and response.get_json()["tickers"] == []
        assert application.list_tickers() == ()
        assert application.get_ticker("mini").name == "My Mini"
        assert application.authorize_controller("mini", paired["controller_token"])
        assert client.get(endpoint, headers={"Authorization":"Bearer bad"}).status_code == 403
        application.heartbeat("mini", {"last_seen_at":-1, "metadata":{"last_seen_at":-1}})
        assert application.get_ticker("mini").device.last_seen_at == now[0]
        assert [row["ticker_id"] for row in client.get(endpoint, headers=headers).get_json()["tickers"]] == ["mini"]
        never_seen = [TickerRecord("new", created_at=now[0]), TickerRecord("old", created_at=now[0]-30*86400)]
        assert [row.ticker_id for row in application.visible_tickers(never_seen)] == ["new"]
    finally:
        application.close()


def test_snapshot_refreshes_expired_code_without_rebooting_mini(tmp_path):
    now = [1000.0]
    app = create_backend_application(tmp_path / "pairing.sqlite3", [], clock=lambda: now[0])
    client = app.test_client()
    try:
        first = client.post("/api/v2/devices/register", json={"device_id":"mini"}, headers={"X-Device-Token": "a" * 64}).get_json()["pairing_code"]
        now[0] += 601
        second = client.get("/api/v2/tickers/mini/data", headers={"X-Device-Token": "a" * 64}).get_json()["meta"]["pairing"]["code"]
        assert second and second != first
        assert client.get("/api/v2/tickers/mini/data", headers={"X-Device-Token": "a" * 64}).get_json()["meta"]["pairing"]["code"] == second
        assert client.post("/api/v2/pairings/exchange", json={"pairing_code":first}).status_code == 400
        assert client.post("/api/v2/pairings/exchange", json={"pairing_code":second}).status_code == 201
        assert client.get("/api/v2/tickers/mini/data", headers={"X-Device-Token": "a" * 64}).get_json()["meta"]["pairing"] == {"paired":True,"code":None}
    finally:
        app.extensions["sports_ticker.backend_application"].close()


@pytest.mark.parametrize("state,status,expected", [
    ("in", "Top of 7th", {"number":7,"half":"top","phase":"playing"}),
    ("in", "Top 7th", {"number":7,"half":"top","phase":"playing"}),
    ("in", "Bot 12th", {"number":12,"half":"bottom","phase":"playing"}),
    ("in", "Bottom 17th", {"number":17,"half":"bottom","phase":"playing"}),
    ("in", "Mid 7th", {"number":7,"half":"break","phase":"break"}),
    ("in", "End 12th", {"number":12,"half":"break","phase":"break"}),
    ("in", "Rain Delay", {"number":0,"half":"none","phase":"paused"}),
    ("pre", "7:00 PM", {"number":0,"half":"none","phase":"inactive"}),
    ("post", "Final/12", {"number":0,"half":"none","phase":"inactive"}),
])
def test_v2_owns_baseball_inning_facts_for_both_renderers(state, status, expected):
    item = ContentItem("game", "sports", "scoreboard", True, {"sport":"mlb", "state":state, "status":status})
    snapshot = TickerSnapshot("mini", 1, datetime.now(timezone.utc), (item,), (), (), DisplaySettings())
    output = project_data_v2(snapshot, {"healthy":True}, {})
    assert output["content"]["sports"][0]["data"]["baseball_inning"] == expected
