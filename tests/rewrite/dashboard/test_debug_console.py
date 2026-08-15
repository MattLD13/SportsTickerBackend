import pytest
from flask import Flask

from sports_ticker.dashboard_v2 import dashboard_v2


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TICKER_DEBUG_PASSWORD", "test-secret")
    app = Flask("test-debug-console")
    app.secret_key = "session-secret"
    app.register_blueprint(dashboard_v2)
    return app.test_client()


def test_debug_console_requires_password(client):
    response = client.get("/debug/test")
    assert response.status_code == 200
    assert b"Unlock console" in response.data
    assert b"Feature test console" in response.data

    rejected = client.post("/debug/test", data={"password": "wrong"})
    assert rejected.status_code == 401

    accepted = client.post("/debug/test", data={"password": "test-secret"})
    assert accepted.status_code == 302
    page = client.get("/debug/test")
    assert page.status_code == 200
    assert b"Backend and catalogs" in page.data


def test_debug_console_logout_clears_session(client):
    client.post("/debug/test", data={"password": "test-secret"})
    assert client.post("/debug/test/logout").status_code == 302
    assert b"Unlock console" in client.get("/debug/test").data


def test_legacy_overlay_pages_redirect_to_the_unified_console(client):
    assert client.get("/debug/alerts").status_code == 302
    assert client.get("/debug/news").status_code == 302


def test_v2_dashboard_template_is_served_from_the_v2_blueprint(client):
    class EmptyApplication:
        def list_tickers(self):
            return ()

    client.application.extensions["sports_ticker.backend_application"] = EmptyApplication()
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert b"Fleet control" in response.data
