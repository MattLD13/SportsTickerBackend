import json
import pytest
from sports_ticker.core import tickers, state, create_ticker_record

def test_status_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"ticker" in response.data.lower()


def test_register_ticker(client):
    headers = {"X-Client-ID": "client_abc"}
    
    # 1. Successful registration
    response = client.post("/register", json={"name": "Office Ticker"}, headers=headers)
    assert response.status_code == 200
    res_data = response.get_json()
    assert res_data["success"] is True
    assert "ticker_id" in res_data
    
    tid = res_data["ticker_id"]
    assert tid in tickers
    assert tickers[tid]["name"] == "Office Ticker"
    assert "client_abc" in tickers[tid]["clients"]

    # 2. Duplicate registration should return the same ticker ID
    response_dup = client.post("/register", json={"name": "Different Name"}, headers=headers)
    assert response_dup.status_code == 200
    res_dup_data = response_dup.get_json()
    assert res_dup_data["ticker_id"] == tid

    # 3. Missing X-Client-ID header
    response_err = client.post("/register", json={"name": "Error Ticker"})
    assert response_err.status_code == 400


def test_pair_by_code(client):
    # Register an unpaired ticker (or just seed one)
    tid = "ticker_unpaired"
    tickers[tid] = create_ticker_record("Unpaired Ticker", paired=False)
    code = tickers[tid]["pairing_code"]

    headers = {"X-Client-ID": "new_client"}
    
    # 1. Pair with correct code
    response = client.post("/pair", json={"code": code, "name": "Cozy Living Room"}, headers=headers)
    assert response.status_code == 200
    res_data = response.get_json()
    assert res_data["success"] is True
    assert res_data["ticker_id"] == tid
    assert "new_client" in tickers[tid]["clients"]
    assert tickers[tid]["name"] == "Cozy Living Room"
    assert tickers[tid]["paired"] is True

    # 2. Pair with invalid code
    response_fail = client.post("/pair", json={"code": "999999"}, headers=headers)
    assert response_fail.status_code == 200
    assert response_fail.get_json()["success"] is False


def test_pair_by_id(client):
    tid = "ticker_id_test"
    tickers[tid] = create_ticker_record("ID Ticker", paired=True)
    
    headers = {"X-Client-ID": "another_client"}
    
    # 1. Success path
    response = client.post("/pair/id", json={"id": tid, "name": "Direct Named"}, headers=headers)
    assert response.status_code == 200
    assert response.get_json()["success"] is True
    assert "another_client" in tickers[tid]["clients"]

    # 2. Not found path
    response_404 = client.post("/pair/id", json={"id": "does_not_exist"}, headers=headers)
    assert response_404.status_code == 404


def test_unpair_and_list(client):
    tid = "ticker_unpair_test"
    tickers[tid] = create_ticker_record("Unpair Me", client_id="unpair_client")
    
    headers = {"X-Client-ID": "unpair_client"}
    
    # 1. List tickers
    response_list = client.get("/tickers", headers=headers)
    assert response_list.status_code == 200
    tickers_list = response_list.get_json()
    assert len(tickers_list) == 1
    assert tickers_list[0]["id"] == tid

    # 2. Unpair
    response_unpair = client.post(f"/ticker/{tid}/unpair", headers=headers)
    assert response_unpair.status_code == 200
    assert "unpair_client" not in tickers[tid]["clients"]
    assert tickers[tid]["paired"] is False


def test_get_data_and_state(client):
    tid = "ticker_data_test"
    tickers[tid] = create_ticker_record("Data Ticker", client_id="data_client")
    
    # 1. GET /data
    response_data = client.get(f"/data?id={tid}")
    assert response_data.status_code == 200
    payload = response_data.get_json()
    assert "global_config" in payload
    assert "local_config" in payload
    assert "status" in payload

    # 2. GET /api/state
    response_state = client.get(f"/api/state?id={tid}")
    assert response_state.status_code == 200
    state_payload = response_state.get_json()
    assert "settings" in state_payload
    assert "active_sports" in state_payload["settings"]


def test_api_config_global_and_ticker(client):
    tid = "ticker_config_test"
    tickers[tid] = create_ticker_record("Config Ticker", client_id="config_client")
    
    headers = {"X-Client-ID": "config_client"}

    # 1. Global config change (e.g., weather city)
    response_global = client.post(
        "/api/config", 
        json={"weather_city": "Los Angeles", "weather_lat": 34.05, "weather_lon": -118.24},
        headers=headers
    )
    assert response_global.status_code == 200
    assert state["weather_city"] == "Los Angeles"
    assert state["weather_lat"] == 34.05

    # 2. Per-ticker isolated config change (e.g., mode, active_modes)
    response_ticker = client.post(
        "/api/config",
        json={"ticker_id": tid, "mode": "clock", "active_modes": {"clock": True}},
        headers=headers
    )
    assert response_ticker.status_code == 200
    # Mode of specific ticker should change, NOT global state mode
    assert tickers[tid]["settings"]["mode"] == "clock"
    assert state["mode"] != "clock"  # Global mode is still sports (or default)


def test_api_config_unauthorized(client):
    tid = "ticker_auth_test"
    tickers[tid] = create_ticker_record("Protected Ticker", client_id="authorized_owner")
    
    # Client 'hacker' is NOT in clients list
    headers = {"X-Client-ID": "hacker"}

    response = client.post(
        "/api/config",
        json={"ticker_id": tid, "mode": "weather"},
        headers=headers
    )
    # Should get 403 Forbidden
    assert response.status_code == 403
    assert tickers[tid]["settings"]["mode"] != "weather"


def test_update_settings_and_unauthorized(client):
    tid = "ticker_settings_test"
    tickers[tid] = create_ticker_record("Settings Ticker", client_id="settings_owner")
    
    # 1. Authorized update
    headers = {"X-Client-ID": "settings_owner"}
    response = client.post(f"/ticker/{tid}", json={"brightness": 80}, headers=headers)
    assert response.status_code == 200
    assert tickers[tid]["settings"]["brightness"] == 80

    # 2. Unauthorized update
    headers_bad = {"X-Client-ID": "intruder"}
    response_bad = client.post(f"/ticker/{tid}", json={"brightness": 10}, headers=headers_bad)
    assert response_bad.status_code == 403
    assert tickers[tid]["settings"]["brightness"] == 80


def test_get_metadata_leagues(client):
    response = client.get("/leagues")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert "id" in data[0]
