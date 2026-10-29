"""Exercise fetcher recovery, loop readiness, and redacted agent evidence."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import zipfile

import pytest

from backend_ops.incidents import IncidentStore, redact
from backend_ops.diagnostics import bundle
from sports_ticker.domain import DisplaySettings
from sports_ticker.providers.music import MusicProvider

pytestmark = pytest.mark.critical


def test_provider_preserves_exception_location_for_private_diagnostics(monkeypatch, tmp_path):
    secret = "private-provider-secret"
    monkeypatch.setenv("TEST_API_KEY", secret)
    class Source:
        def fetch(self, settings):
            raise ValueError("invalid source https://example.org/feed?api_key=" + secret)
    result = MusicProvider(Source()).fetch(DisplaySettings())
    assert not result.health.healthy
    assert result.health.diagnostic["exception_type"] == "ValueError"
    store = IncidentStore(tmp_path)
    store.record("provider_failure", component="music", context=dict(result.health.diagnostic))
    body = next(tmp_path.glob("*.json")).read_text()
    assert "test_backend_recovery.py" in body and "in fetch" in body
    assert secret not in body and "api_key=" not in body


def test_incidents_and_agent_bundle_are_bounded_and_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_CLIENT_SECRET", "secret-value-123")
    now = [1.0]
    directory = tmp_path / "ticker_data/backend-incidents"
    store = IncidentStore(directory, clock=lambda: now[0], limit=2)
    for number in range(3):
        now[0] += 61
        store.record("provider_failure", component="espn", error=ValueError("secret-value-123"),
                     context={"access_token": "other-secret", "url": "https://user:pass@example.org/feed?key=hello"})
    assert len(list(directory.glob("*.json"))) == 2
    output = bundle(tmp_path, tmp_path / "report.zip", probe=lambda: {"status": "ok"})
    with zipfile.ZipFile(output) as archive:
        body = archive.read("report.json").decode()
        assert len(json.loads(body)["incidents"]) == 2
        assert all(value not in body for value in ("secret-value-123", "other-secret", "user:pass", "key=hello"))
        assert set(archive.namelist()) == {"report.json", "TRIAGE.md"}
    assert redact("Authorization: Bearer abc.def.ghi") == "Authorization: Bearer [REDACTED]"
