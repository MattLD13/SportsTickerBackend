import json
import pytest
from sports_ticker.core import tickers, state, create_ticker_record
import sports_ticker.routes.state as route_state

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


def test_unknown_hardware_enters_pairing_mode(client):
    client_id = "new_hardware_client"
    headers = {"X-Client-ID": client_id}

    response = client.get(f"/data?id={client_id}", headers=headers)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "pairing"
    assert payload["code"].isdigit()
    assert len(payload["code"]) == 6
    assert tickers[client_id]["paired"] is False
    assert tickers[client_id]["clients"] == []

    pair_response = client.post(
        "/pair/id",
        json={"id": client_id, "name": "New Hardware"},
        headers=headers,
    )

    assert pair_response.status_code == 200
    assert pair_response.get_json()["success"] is True
    assert tickers[client_id]["paired"] is True
    assert tickers[client_id]["clients"] == [client_id]


def test_get_data_empty_sports_returns_no_games_placeholder(client, monkeypatch):
    tid = "ticker_empty_games_test"
    tickers[tid] = create_ticker_record("Empty Games Ticker", client_id="empty_client")
    tickers[tid]["settings"]["mode"] = "sports"

    def _empty_snapshot(mode, delay_seconds=0):
        return []

    monkeypatch.setattr(route_state.fetcher, "get_mode_snapshot", _empty_snapshot)

    response = client.get(f"/data?id={tid}")
    assert response.status_code == 200
    payload = response.get_json()

    sports = payload["content"]["sports"]
    assert len(sports) == 1
    assert sports[0]["no_games"] is True
    assert sports[0]["type"] == "no_games"
    assert sports[0]["status"] == "NO GAMES AVAILABLE"


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


def _seed_score_alert(sport="mlb", scorer="NYY"):
    """Drive a scoring play through the detector the way a buffer build does."""
    from sports_ticker.services.score_alerts import score_alerts

    base = {
        "type": "scoreboard", "id": "alert_game", "sport": sport, "state": "in",
        "status": "BOT 7", "home_abbr": scorer, "away_abbr": "BOS",
        "home_score": 3, "away_score": 1,
        "home_logo": "h.png", "away_logo": "a.png",
        "last_play": {"text": "homered to right", "team": scorer},
    }
    score_alerts.ingest([base])
    score_alerts.ingest([dict(base, home_score=7)])


def test_data_serves_score_alerts_only_in_a_sports_mode(client):
    tid = "ticker_alert_test"
    tickers[tid] = create_ticker_record("Alert Ticker", client_id="alert_client")
    tickers[tid]["my_teams"] = ["mlb:NYY"]
    tickers[tid]["settings"]["mode"] = "my_teams"

    _seed_score_alert()
    alerts = client.get(f"/data?id={tid}").get_json()["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["headline"] == "GRAND SLAM"

    # A board set to the weather is not asking about scores.
    tickers[tid]["settings"]["mode"] = "weather"
    assert client.get(f"/data?id={tid}").get_json()["alerts"] == []


def test_live_delay_holds_the_alert_back(client):
    """The takeover must not outrun the delayed content it sits on top of."""
    from sports_ticker.services.score_alerts import score_alerts

    tid = "ticker_alert_delay"
    tickers[tid] = create_ticker_record("Delayed Ticker", client_id="delay_client")
    tickers[tid]["my_teams"] = ["mlb:NYY"]
    tickers[tid]["settings"]["mode"] = "sports"
    tickers[tid]["settings"]["live_delay_mode"] = True
    tickers[tid]["settings"]["live_delay_seconds"] = 45

    _seed_score_alert()
    assert client.get(f"/data?id={tid}").get_json()["alerts"] == []

    for entry in score_alerts._alerts:
        entry["ts"] -= 50
    assert client.get(f"/data?id={tid}").get_json()["alerts"]


def test_debug_route_fires_an_alert_and_reports_the_gates(client):
    tid = "ticker_debug_alert"
    tickers[tid] = create_ticker_record("Debug Ticker", client_id="debug_client")
    tickers[tid]["my_teams"] = ["nhl:NYR"]
    tickers[tid]["settings"]["mode"] = "sports"

    res = client.get(f"/api/debug/score_alert?id={tid}").get_json()
    assert res["will_display"] is True
    assert res["alert"]["team_abbr"] == "NYR"        # picked a followed team
    assert any(a["id"] == res["alert"]["id"]
               for a in client.get(f"/data?id={tid}").get_json()["alerts"])

    # A blocked board says which gate stopped it instead of staying silent.
    tickers[tid]["settings"]["mode"] = "weather"
    blocked = client.get(f"/api/debug/score_alert?id={tid}").get_json()
    assert blocked["will_display"] is False
    assert any("weather" in r for r in blocked["blocked_by"])
