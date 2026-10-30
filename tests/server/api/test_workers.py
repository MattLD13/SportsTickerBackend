"""Check the operator routes that report and deploy provider workers."""
import pytest

from ticker.server.offline import create_offline_application

pytestmark = pytest.mark.critical
OPERATOR = {"X-Deployment-Token": "deploy-secret"}


class Engine:
    """Stand in for the engine: one worker that accepts one release."""

    providers = ("music",)

    def __init__(self):
        self.status = {"active": "1" * 40, "bad": [], "connected": True}
        self.deploys = []

    def workers(self):
        return {"music": dict(self.status)}

    def deploy(self, name, release):
        self.deploys.append((name, release))
        if release == "bad":
            raise RuntimeError("release bad of music is marked bad")
        if release == "2" * 40:
            self.status["active"] = release
            return True
        self.status["bad"] = [release]
        return False


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKER_DEPLOY_TOKEN", "deploy-secret")
    flask = create_offline_application(tmp_path / "ticker.sqlite3")
    yield flask
    flask.extensions["ticker.application"].close()


def test_worker_routes_need_the_operator_secret_and_an_engine(app):
    client = app.test_client()
    assert client.get("/workers").status_code == 401
    missing = client.get("/workers", headers=OPERATOR)
    assert missing.status_code == 503 and missing.get_json()["error"]["code"] == "workers_unavailable"


def test_a_worker_deploy_reports_the_release_that_the_supervisor_keeps(app):
    engine = Engine()
    app.extensions["ticker3.engine"] = engine
    client = app.test_client()
    assert client.get("/workers", headers=OPERATOR).get_json() == {"workers": {"music": engine.status}}
    accepted = client.post("/workers/music/deploy", json={"release": "2" * 40}, headers=OPERATOR)
    assert accepted.status_code == 200
    assert accepted.get_json() == {"worker": "music", "release": "2" * 40, "deployed": True, "active": "2" * 40, "bad": []}
    kept = client.post("/workers/music/deploy", json={"release": "3" * 40}, headers=OPERATOR)
    assert kept.status_code == 409 and kept.get_json()["deployed"] is False and kept.get_json()["bad"] == ["3" * 40]
    refused = client.post("/workers/music/deploy", json={"release": "bad"}, headers=OPERATOR)
    assert refused.status_code == 409 and refused.get_json()["error"]["code"] == "deploy_refused"
    assert client.post("/workers/espn/deploy", json={"release": "2" * 40}, headers=OPERATOR).status_code == 404
    assert client.post("/workers/music/deploy", json={"version": "x"}, headers=OPERATOR).status_code == 400
    assert engine.deploys == [("music", "2" * 40), ("music", "3" * 40), ("music", "bad")]
