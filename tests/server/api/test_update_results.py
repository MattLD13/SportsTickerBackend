"""Verify durable boot failure reports and family isolation."""
import hashlib

import pytest

from ticker.server.offline import create_offline_application

pytestmark = pytest.mark.critical


def test_boot_failure_quarantines_only_assigned_family_and_preserves_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKER_DEPLOY_TOKEN", "admin")
    path = tmp_path / "fleet.sqlite3"
    flask = create_offline_application(path, [])
    app = flask.extensions["ticker.application"]
    tokens = {"mini-a": "a" * 64, "mini-b": "b" * 64, "six": "c" * 64}
    try:
        for identity, token in tokens.items():
            app.register_device(identity, profile={"product_family": "full" if identity == "six" else "mini"}, credential_hash=hashlib.sha256(token.encode()).hexdigest())
            app.request_update(identity, "release-1")
            app.request_reboot(identity)
        client = flask.test_client()
        target = app.get_ticker("mini-a")
        attempt = next(item["id"] for item in target.device.metadata["pending_commands"] if item["type"] == "update")
        report = {"id": attempt, "version": "release-1", "running_version": "release-0", "status": "rolled_back", "reason": "boot_reset"}
        route = "/update-result"
        assert client.post(route, json=report).status_code == 401
        assert client.post(route, json=report, headers={"X-Device-Token": "d" * 64}).status_code == 403
        # The token names mini-b, and the attempt of mini-a is not assigned to mini-b.
        assert client.post(route, json=report, headers={"X-Device-Token": tokens["mini-b"]}).status_code == 400
        assert client.post(route, json={**report, "id": "not-assigned"}, headers={"X-Device-Token": tokens["mini-a"]}).status_code == 400
        before = {item.ticker_id: item for item in app.repository.list_tickers()}
        result = client.post(route, json=report, headers={"X-Device-Token": tokens["mini-a"]})
        assert result.status_code == 200
        assert result.get_json() == {"accepted": True, "quarantined": True, "cancelled": 2}
        assert client.post(route, json=report, headers={"X-Device-Token": tokens["mini-a"]}).get_json()["accepted"]
        for identity in tokens:
            ticker = app.get_ticker(identity)
            assert ticker.device.last_seen_at == before[identity].device.last_seen_at
            assert ticker.display_settings == before[identity].display_settings
            assert ticker.pairing == before[identity].pairing
            kinds = {item["type"] for item in ticker.device.metadata["pending_commands"]}
            assert kinds == ({"reboot", "update"} if identity == "six" else {"reboot"})
        other_attempt = next(item["id"] for item in before["mini-b"].device.metadata["pending_commands"] if item["type"] == "update")
        blocked = app.repository.updates.report("mini-b", {"id": other_attempt, "version": "release-1", "running_version": "release-0", "status": "started", "reason": ""}, 100)
        assert blocked["accepted"] and blocked["quarantined"]
        with pytest.raises(ValueError, match="quarantined"):
            app.request_update("mini-b", "release-1")
        app.request_update("six", "release-1")
        assert client.get("/fleet/updates").status_code == 401
        history = client.get("/fleet/updates", headers={"X-Deployment-Token": "admin"}).get_json()
        assert sum(item["status"] == "rolled_back" for item in history["events"]) == 1
    finally:
        app.close()
    restarted = create_offline_application(path, [])
    try:
        ledger = restarted.extensions["ticker.application"].repository.updates
        assert ledger.quarantined("mini", "release-1")
        assert not ledger.quarantined("full", "release-1")
    finally:
        restarted.extensions["ticker.application"].close()


def test_download_failure_remains_retryable_and_cannot_claim_another_release(tmp_path):
    flask = create_offline_application(tmp_path / "fleet.sqlite3", [])
    app = flask.extensions["ticker.application"]
    try:
        app.register_device("mini", profile={"product_family": "mini"})
        ticker = app.request_update("mini", "new")
        attempt = next(item["id"] for item in ticker.device.metadata["pending_commands"] if item["type"] == "update")
        report = {"id": attempt, "version": "new", "running_version": "old", "status": "download_failed", "reason": "download"}
        ledger = app.repository.updates
        assert not ledger.report("mini", report, 100)["quarantined"]
        assert not app.get_ticker("mini").device.metadata["pending_commands"]
        with pytest.raises(ValueError, match="assigned"):
            ledger.report("mini", {**report, "version": "other"}, 101)
        retry = app.request_update("mini", "new")
        retry_id = next(item["id"] for item in retry.device.metadata["pending_commands"] if item["type"] == "update")
        assert retry_id != attempt
        assert ledger.report("mini", {**report, "id": retry_id, "status": "installed", "running_version": "new", "reason": ""}, 102)["accepted"]
        assert not app.get_ticker("mini").device.metadata["pending_commands"]
    finally:
        app.close()
