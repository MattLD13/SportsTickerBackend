import hashlib

import pytest

from sports_ticker.bootstrap_v2 import create_backend_application
from ticker_core.platform.device_credentials import load_device_token

pytestmark = pytest.mark.critical


def test_device_enrollment_requires_admin_and_rotates_without_exposing_hashes(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKER_DEPLOY_TOKEN", "admin-test")
    app = create_backend_application(tmp_path / "fleet.sqlite3", [])
    application = app.extensions["sports_ticker.backend_application"]
    try:
        client = app.test_client()
        client.post("/api/v2/devices/register", json={"device_id": "mini"}, headers={"X-Device-Token": "a" * 64})
        token = load_device_token(tmp_path / "token")
        digest = hashlib.sha256(token.encode()).hexdigest()
        route = "/api/v2/tickers/mini/device-credential"
        body = {"token_sha256": digest}
        assert client.post(route, json=body).status_code == 401
        headers = {"X-Deployment-Token": "admin-test"}
        assert client.post(route, json={"token_sha256": "bad"}, headers=headers).status_code == 400
        enrolled = client.post(route, json=body, headers=headers)
        assert enrolled.status_code == 200
        assert enrolled.get_json() == {"ticker_id": "mini", "enrolled": True}
        assert application.authorize_device("mini", token)
        assert client.post(route + "/verify", json={}).status_code == 401
        assert client.post(route + "/verify", json={}, headers={"X-Device-Token": token}).status_code == 200
        assert client.post(route + "/verify", json={}, headers={"X-Device-Token": "bad"}).status_code == 403
        assert not application.authorize_device("other", token)
        assert not application.authorize_device("mini", "bad")
        response = client.get("/api/v2/tickers/mini/data", headers={"X-Device-Token": "a" * 64}).data
        assert token.encode() not in response and digest.encode() not in response
        replacement = "a" * 64
        client.post(route, json={"token_sha256": hashlib.sha256(replacement.encode()).hexdigest()}, headers=headers)
        assert not application.authorize_device("mini", token)
        assert application.authorize_device("mini", replacement)
        application.delete_ticker("mini")
        assert not application.authorize_device("mini", replacement)
    finally:
        application.close()


def test_device_secret_survives_restart_and_rejects_corruption(tmp_path):
    path = tmp_path / "device_token"
    first = load_device_token(path)
    assert len(first) == 64
    assert load_device_token(path) == first
    path.write_text("corrupt")
    with pytest.raises(ValueError, match="invalid"):
        load_device_token(path)


def test_device_authorization_rejects_other_devices_and_registration_claims(tmp_path):
    flask = create_backend_application(tmp_path / "fleet.sqlite3", [])
    application = flask.extensions["sports_ticker.backend_application"]
    try:
        client = flask.test_client()
        own, other = {"X-Device-Token": "a" * 64}, {"X-Device-Token": "b" * 64}
        registration = client.post("/api/v2/devices/register", json={"device_id": "one"}, headers=own)
        assert registration.status_code == 201
        assert client.post("/api/v2/devices/register", json={"device_id": "one"}, headers=other).status_code == 403
        for method, suffix, body in (("get", "", None), ("get", "/data", None), ("post", "/data", {}),
                                     ("post", "/heartbeat", {"metadata": {}}), ("get", "/firmware", None),
                                     ("post", "/updates/result", {}), ("patch", "", {"name": "changed"})):
            route = "/api/v2/tickers/one" + suffix
            operation = getattr(client, method)
            assert operation(route, json=body).status_code == 401
            assert operation(route, json=body, headers=other).status_code == 403
        assert client.get("/api/v2/tickers/one/data", headers=own).status_code == 200
        assert client.post("/api/v2/tickers/one/heartbeat", json={"metadata": {"pending_commands": []}}, headers=own).status_code == 400
        assert client.post("/api/v2/devices/register", json={"device_id": "one", "profile": {"product_family": "mini"}}, headers=own).status_code == 400
        for route in ("/api/v2/events/news", "/api/v2/events/alerts"):
            assert client.post(route, json={}, headers=own).status_code == 401
        assert client.post("/api/v2/tickers/one/updates", json={"version": "new"}, headers=own).status_code == 401
        assert client.post("/api/v2/tickers/one/commands/reboot", json={}, headers=own).status_code == 401
    finally:
        application.close()
