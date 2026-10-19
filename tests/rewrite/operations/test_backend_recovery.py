"""Exercise fetcher recovery, loop readiness, and redacted agent evidence."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import zipfile

import pytest

from backend_ops.incidents import IncidentStore, redact
from backend_ops.diagnostics import bundle
from sports_ticker.application.scheduler import RefreshScheduler
from sports_ticker.application.runtime import BackendRuntime
from sports_ticker.domain import DisplaySettings
from sports_ticker.providers.music import MusicProvider

pytestmark = pytest.mark.critical


def test_fetcher_circuit_preserves_good_data_and_other_tickers(tmp_path):
    now = [0.0]
    failing = [False]
    calls = []
    published = {}
    def fetch(ticker, settings):
        calls.append((ticker, now[0]))
        if ticker == "a" and failing[0]:
            raise RuntimeError("remote service unavailable")
        return {"content": str(now[0])}
    scheduler = RefreshScheduler(
        lambda ticker, settings, data: published.update({ticker: dict(data)}) or True,
        monotonic=lambda: now[0], wall_clock=lambda: datetime(2026, 10, 18, tzinfo=timezone.utc),
        incidents=IncidentStore(tmp_path, clock=lambda: now[0]),
    )
    scheduler.register_provider("music", 1, fetch)
    for ticker in ("a", "b"):
        scheduler.register_ticker(ticker, lambda identity: {})
    scheduler.run_due()
    failing[0] = True
    for tick in range(1, 5):
        now[0] = tick
        scheduler.run_due()
    assert published["a"]["music"]["content"] == "0.0"
    assert published["b"]["music"]["content"] == "4"
    assert sum(ticker == "a" for ticker, _ in calls) == 4
    assert scheduler.recovery_health()["music"]["open_circuits"] == 1
    now[0] = 33
    failing[0] = False
    scheduler.run_due()
    assert published["a"]["music"]["content"] == "33"
    assert scheduler.recovery_health()["music"]["open_circuits"] == 0
    assert {json.loads(path.read_text())["kind"] for path in tmp_path.glob("*.json")} == {"provider_failure", "provider_recovered"}


def test_runtime_readiness_detects_stalls_without_treating_provider_errors_as_a_crash():
    now = [0.0]
    runtime = BackendRuntime(SimpleNamespace(run_due=lambda tick: ()), SimpleNamespace(remove_expired=lambda: None),
                             0.2, monotonic=lambda: now[0])
    runtime._running = True
    assert not runtime.status()["ready"]
    runtime.run_once()
    assert runtime.status()["ready"] and runtime.status()["cycles"] == 1
    now[0] = 91
    assert not runtime.status()["ready"]
    runtime.run_once()
    assert runtime.status()["ready"]
    runtime._running = False
    assert not runtime.status()["ready"]


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
    output = bundle(tmp_path, tmp_path / "report.zip", probe=lambda: {"api_version": "v2"})
    with zipfile.ZipFile(output) as archive:
        body = archive.read("report.json").decode()
        assert len(json.loads(body)["incidents"]) == 2
        assert all(value not in body for value in ("secret-value-123", "other-secret", "user:pass", "key=hello"))
        assert set(archive.namelist()) == {"report.json", "TRIAGE.md"}
    assert redact("Authorization: Bearer abc.def.ghi") == "Authorization: Bearer [REDACTED]"
