"""Prove durable delivery, safe public facts, and GitHub check deduplication."""
from contextlib import contextmanager
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

import pytest

from backend_ops.github_reports import GitHub, deliver
from backend_ops.reporting import RuntimeReport, acknowledge, export, failure, recovered

pytestmark = pytest.mark.critical
OLD, NEW = "1" * 40, "2" * 40
RUN = "https://github.com/owner/repo/actions/runs/1"


def state():
    return {"components": {"core": {"active": NEW}}}


@contextmanager
def github():
    checks, writes = [], []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            self.reply({"check_runs": checks})
        def mutate(self):
            assert self.headers["Authorization"] == "Bearer test-token"
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            writes.append((self.command, body))
            if self.command == "POST":
                value = {**body, "id": len(checks) + 1}
                checks.append(value)
            else:
                value = next(item for item in checks if item["id"] == int(self.path.rsplit("/", 1)[-1]))
                value.update(body)
            self.reply(value)
        do_POST = mutate
        do_PATCH = mutate
        def reply(self, value):
            data = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield GitHub("owner/repo", "test-token", api=f"http://127.0.0.1:{server.server_port}"), checks, writes
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def test_reports_survive_restart_acknowledge_only_confirmed_ids_and_exclude_details():
    value = state()
    failure(value, "core", NEW, "runtime_unready", 100)
    failure(value, "core", NEW, "runtime_unready", 101)
    assert len(value["report_events"]) == 1
    value = json.loads(json.dumps(value))
    first = export(value)["reports"][0]
    failure(value, "core", NEW, "rolled_back", 102, restored=OLD)
    assert acknowledge(value, {"schema_version": 1, "report_ids": [first["id"]]}) == 1
    assert len(export(value)["reports"]) == 1
    failure(value, "core", NEW, "runtime_unready", 103)
    assert len(value["report_events"]) == 1
    assert set(first) == {"id", "site", "sequence", "component", "release", "state", "category", "restored_release", "scope", "observed_at"}
    with pytest.raises(ValueError):
        RuntimeReport.parse({**first, "traceback": "private source data"})


def test_rollback_recovery_marks_the_restored_revision_without_clearing_the_failed_revision(tmp_path):
    value = state()
    failure(value, "core", NEW, "rolled_back", 100, restored=OLD)
    value["components"]["core"]["active"] = OLD
    recovered(value, "core", 101)
    with github() as (api, checks, writes):
        deliver(api, export(value), run_url=RUN, acknowledgement=tmp_path / "ack.json", evidence=True)
        assert len(checks) == 2
        assert {item["head_sha"]: item["conclusion"] for item in checks} == {NEW: "failure", OLD: "success"}
        assert "Encrypted diagnostic" in checks[0]["output"]["summary"]
        assert all("test-token" not in json.dumps(body) for method, body in writes)


def test_lost_acknowledgement_cannot_create_duplicate_checks_or_regress_recovery(tmp_path):
    value = state()
    failure(value, "core", NEW, "runtime_unready", 100)
    initial = deepcopy(export(value))
    recovered(value, "core", 101)
    with github() as (api, checks, writes):
        deliver(api, initial, run_url=RUN, acknowledgement=tmp_path / "ack.json")
        deliver(api, export(value), run_url=RUN, acknowledgement=tmp_path / "ack.json")
        assert len(checks) == 1 and checks[0]["conclusion"] == "success"
        assert [method for method, body in writes] == ["POST", "PATCH"]
        deliver(api, initial, run_url=RUN, acknowledgement=tmp_path / "retry.json")
        assert [method for method, body in writes] == ["POST", "PATCH"]
        assert checks[0]["conclusion"] == "success"


def test_failed_delivery_keeps_reports_queued_and_retries_after_confirmation(tmp_path):
    value = state()
    failure(value, "core", NEW, "runtime_unready", 100)
    class Offline:
        def request(self, *args):
            raise OSError("offline")
    path = tmp_path / "ack.json"
    with pytest.raises(RuntimeError):
        deliver(Offline(), export(value), run_url=RUN, acknowledgement=path)
    acknowledge(value, json.loads(path.read_text()))
    assert len(value["report_events"]) == 1
    with github() as (api, checks, writes):
        deliver(api, export(value), run_url=RUN, acknowledgement=path)
    acknowledge(value, json.loads(path.read_text()))
    assert not value["report_events"]


@pytest.mark.parametrize("field,item", [("component", "unknown"), ("sequence", True), ("observed_at", float("nan")), ("release", "invalid")])
def test_invalid_reports_never_reach_github(tmp_path, field, item):
    value = state()
    failure(value, "core", NEW, "runtime_unready", 100)
    envelope = export(value)
    envelope["reports"][0][field] = item
    with github() as (api, checks, writes):
        with pytest.raises(ValueError):
            deliver(api, envelope, run_url=RUN, acknowledgement=tmp_path / "ack.json")
        assert not checks and not writes
