import hashlib

import pytest

from ticker.server.offline import create_offline_application
from ticker.six.platform.device_credentials import load_device_token

pytestmark = pytest.mark.critical


def device_token(ticker_id: str) -> str:
    """Return the device token of one test device. The token alone names the ticker."""
    return hashlib.sha256(ticker_id.encode()).hexdigest()


def test_device_enrollment_requires_admin_and_rotates_without_exposing_hashes(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKER_DEPLOY_TOKEN", "admin-test")
    app = create_offline_application(tmp_path / "fleet.sqlite3", [])
    application = app.extensions["ticker.application"]
    try:
        client = app.test_client()
        client.post("/register", json={"device_id": "mini"}, headers={"X-Device-Token": device_token("mini")})
        token = load_device_token(tmp_path / "token")
        digest = hashlib.sha256(token.encode()).hexdigest()
        route = "/tickers/mini/credential"
        body = {"token_sha256": digest}
        assert client.post(route, json=body).status_code == 401
        headers = {"X-Deployment-Token": "admin-test"}
        assert client.post(route, json={"token_sha256": "bad"}, headers=headers).status_code == 400
        enrolled = client.post(route, json=body, headers=headers)
        assert enrolled.status_code == 200
        assert enrolled.get_json() == {"ticker_id": "mini", "enrolled": True}
        assert application.authorize_device("mini", token)
        assert client.post("/verify", json={}).status_code == 401
        verified = client.post("/verify", json={}, headers={"X-Device-Token": token})
        assert verified.status_code == 200 and verified.get_json() == {"ticker_id": "mini", "authenticated": True}
        assert client.post("/verify", json={}, headers={"X-Device-Token": "bad"}).status_code == 403
        assert not application.authorize_device("other", token)
        assert not application.authorize_device("mini", "bad")
        response = client.get("/data", headers={"X-Device-Token": device_token("mini")}).data
        assert token.encode() not in response and digest.encode() not in response
        replacement = device_token("mini")
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
    flask = create_offline_application(tmp_path / "fleet.sqlite3", [])
    application = flask.extensions["ticker.application"]
    try:
        client = flask.test_client()
        own, other = {"X-Device-Token": "a" * 64}, {"X-Device-Token": "b" * 64}
        registration = client.post("/register", json={"device_id": "one"}, headers=own)
        assert registration.status_code == 201
        assert client.post("/register", json={"device_id": "one"}, headers=other).status_code == 403
        # A device route finds the ticker from the token, so an unknown token is refused.
        for method, route, body in (("get", "/data", None), ("post", "/poll", {}), ("post", "/heartbeat", {"metadata": {}}),
                                    ("get", "/firmware", None), ("post", "/update-result", {}), ("post", "/verify", {})):
            operation = getattr(client, method)
            assert operation(route, json=body).status_code == 401
            assert operation(route, json=body, headers=other).status_code == 403
        # A device token does not open a controller route.
        for method, route, body in (("get", "/tickers/one", None), ("get", "/tickers/one/data", None),
                                    ("patch", "/tickers/one", {"name": "changed"})):
            assert getattr(client, method)(route, json=body, headers=own).status_code == 401
        assert client.get("/data", headers=own).status_code == 200
        assert client.post("/heartbeat", json={"metadata": {"pending_commands": []}}, headers=own).status_code == 400
        assert client.post("/register", json={"device_id": "one", "profile": {"product_family": "mini"}}, headers=own).status_code == 400
        for route in ("/news", "/alerts"):
            assert client.post(route, json={}, headers=own).status_code == 401
        assert client.post("/tickers/one/update", json={"version": "new"}, headers=own).status_code == 401
        assert client.post("/tickers/one/reboot", json={}, headers=own).status_code == 401
    finally:
        application.close()
