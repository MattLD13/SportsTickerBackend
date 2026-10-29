"""Prove process selection, release packaging, core activation, rollback, and the first Ticker 3 migration."""
import hashlib
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from backend_ops.components import COMPONENTS, WORKERS, owners, package
from backend_ops.incidents import atomic_json
from backend_ops.manager import Manager, read, switch

pytestmark = pytest.mark.critical
OLD, NEW, THIRD = "1" * 40, "2" * 40, "3" * 40
SPORTS = {"espn", "fotmob", "golf", "racing"}


class Host:
    """Play the server: the core service, its health, and the worker deploy route."""

    def __init__(self):
        self.manager = None
        self.calls = []
        self.broken = set()
        self.refused = set()
        self.process_restarts = 0
        self.running = "legacy"

    def command(self, args, **kwargs):
        self.calls.append(("command", Path(args[0]).name, *args[1:3]))
        if list(args[1:3]) == ["-m", "venv"]:
            Path(args[3]).mkdir(parents=True)

    def restart_core(self):
        self.calls.append("restart")
        current = self.manager.current
        self.running = current.resolve().name if current.exists() else "legacy"
        if self.running != "legacy" and not self.manager.supervisor_path.exists():
            # A new supervisor starts each worker on the release of the core.
            atomic_json(self.manager.supervisor_path, {"features": {name: {"active": self.running, "previous": None, "bad": []}
                                                                    for name in WORKERS}})

    def stack_core(self):
        self.calls.append("stack")

    def health(self):
        return {"release": self.running, "process_restarts": self.process_restarts, "scheduler": {"providers": {}},
                "runtime": {"enabled": True, "running": True, "ready": self.running not in self.broken, "cycles": 5}}

    def deploy_worker(self, name, release):
        self.calls.append(("deploy", name, release))
        return name not in self.refused

    def install_units(self, source, backup):
        self.calls.append("install_units")

    def restore_units(self, backup):
        self.calls.append("restore_units")

    def retire_fetchers(self):
        self.calls.append("retire_fetchers")


def manager_for(tmp_path, *, releases=(OLD, NEW)):
    now = [1000.0]
    host = Host()
    manager = Manager(tmp_path, host=host, clock=lambda: now[0], sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
    host.manager = manager
    for revision in releases:
        manager.release(revision).mkdir(parents=True)
    return manager, host, now


def running(tmp_path):
    """Return a manager whose core and workers run OLD."""
    manager, host, now = manager_for(tmp_path)
    state = manager.load()
    for name in COMPONENTS:
        state["components"][name].update(active=OLD, trial_at=now[0])
    switch(manager.current, manager.release(OLD))
    host.restart_core()
    host.calls.clear()
    manager.save(state)
    return manager, state, host, now


def test_deployment_selects_the_processes_that_load_a_file():
    workers = set(WORKERS)
    assert owners("sports_ticker/providers/music.py") == {"music"}
    assert owners("ticker3/api/control.py") == {"core"}
    assert owners("ticker3/core/engine.py") == {"core"}
    assert owners("ticker3/worker/runner.py") == workers
    assert owners("sports_ticker/integrations/spotify.py") == {"core", "music"}
    assert owners("sports_ticker/providers/clock.py") == {"core"}
    assert owners("sports_ticker/domain/models.py") == set(COMPONENTS)
    assert owners("sports_ticker/__init__.py") == set(COMPONENTS)
    assert owners("ticker3/contract/wire.py") == set(COMPONENTS)
    assert owners("backend_ops/incidents.py") == set(COMPONENTS)
    assert owners("requirements-backend.txt") == set(COMPONENTS)
    assert owners("tests/python/test_modes.py") == set()
    assert owners("sports_ticker/providers/score_alerts.py") == {"espn", "fotmob"}
    assert owners("sports_ticker/providers/racing_session.py") == {"core", "racing"}
    assert owners("sports_ticker/providers/sports_display.py") == {"core"} | SPORTS
    assert owners("sports_ticker/providers/stock_catalog.py") == {"core"}
    assert owners("sports_ticker/providers/weather.py") == {"weather"}
    assert owners("sports_ticker/providers/weather_location.py") == {"core"}
    assert owners("sports_ticker/projections/data_api.py") == {"core"}


def test_deployment_selects_every_process_for_files_without_import_edges():
    assert owners("sports_ticker/providers/removed_source.py") == set(COMPONENTS)
    assert owners("sports_ticker/providers/team_overrides.json") == set(COMPONENTS)
    assert owners("sports_ticker/removed_view.py") == {"core"}
    assert owners("ticker3/web/static/style.css") == {"core"}


@pytest.mark.parametrize("module,component", [
    ("golf_source", "golf"), ("stock_source", "stock"), ("flight_source", "flights"), ("news_source", "news"),
])
def test_source_file_changes_select_only_their_worker(module, component):
    assert owners(f"sports_ticker/providers/{module}.py") == {component}


def repository(tmp_path):
    root = tmp_path / "repository"
    for name in ("sports_ticker/__init__.py", "ticker_core/__init__.py", "ticker3/__init__.py", "ticker3/contract/__init__.py",
                 "backend_ops/__init__.py", "backend_ops/manager.py"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(f"# {name}\n", encoding="utf-8")
    for name in ("requirements.txt", "requirements-backend.txt", "VERSION"):
        (root / name).write_text("test\n", encoding="utf-8")
    for command in (["init"], ["config", "user.name", "Deployment Test"], ["config", "user.email", "deployment@example.invalid"],
                    ["add", "."], ["commit", "-m", "Create package fixture"]):
        subprocess.run(["git", *command], cwd=root, check=True, capture_output=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    (root / "RELEASE_SHA").write_text(revision, encoding="utf-8")
    return root, revision


def test_one_release_package_carries_every_file_with_its_checksum(tmp_path):
    root, revision = repository(tmp_path)
    plan = package(root, tmp_path / "out", ["music", "core"])
    assert plan == {"schema_version": 2, "release": revision, "components": ["core", "music"]}
    with tarfile.open(tmp_path / "out/release.tar.gz", "r:gz") as archive:
        names = set(archive.getnames())
        manifest = json.load(archive.extractfile("release-manifest.json"))
    assert {"ticker3/contract/__init__.py", "backend_ops/manager.py", "RELEASE_SHA", "release-manifest.json"} <= names
    assert manifest["release"] == revision and set(manifest["files"]) == names - {"release-manifest.json"}
    assert manifest["files"]["VERSION"] == hashlib.sha256(b"test\n").hexdigest()


def test_prepare_checks_every_file_and_reuses_a_prepared_release(tmp_path):
    root, revision = repository(tmp_path)
    package(root, tmp_path / "out", ["core"])
    manager, host, _ = manager_for(tmp_path / "home", releases=())
    release = manager.prepare(tmp_path / "out/release.tar.gz", revision)
    assert (release / ".prepared").exists() and (release / ".venv").is_symlink()
    assert host.calls[-1][:3] == ("command", "python", "-c")
    calls = len(host.calls)
    assert manager.prepare(tmp_path / "out/release.tar.gz", revision) == release
    assert len(host.calls) == calls

    with tarfile.open(tmp_path / "out/release.tar.gz", "r:gz") as source:
        members = [(member, source.extractfile(member).read()) for member in source.getmembers()]
    with tarfile.open(tmp_path / "bad.tar.gz", "w:gz") as archive:
        for member, content in members:
            if member.name == "VERSION":
                content = b"changed\n"
                member.size = len(content)
            import io
            archive.addfile(member, io.BytesIO(content))
    other = Manager(tmp_path / "other", host=Host())
    with pytest.raises(ValueError, match="checksum"):
        other.prepare(tmp_path / "bad.tar.gz", revision)


def test_core_activation_moves_only_the_core(tmp_path):
    manager, state, host, _ = running(tmp_path)
    manager.activate_core(state, NEW)
    assert host.calls == ["restart"]
    assert manager.current.resolve() == manager.release(NEW)
    assert state["components"]["core"]["active"] == NEW and state["components"]["core"]["previous"] == OLD
    assert all(state["components"][name]["active"] == OLD for name in WORKERS)
    assert read(manager.state_path)["pending"] is None


def test_failed_core_startup_restores_the_old_release_and_quarantines_the_candidate(tmp_path):
    manager, state, host, _ = running(tmp_path)
    host.broken.add(NEW)
    database = tmp_path / "ticker_data/user-state"
    database.write_text("pairing and settings remain")
    with pytest.raises(RuntimeError, match="failed release readiness"):
        manager.activate_core(state, NEW)
    assert manager.current.resolve() == manager.release(OLD)
    assert host.running == OLD and host.calls == ["restart", "restart"]
    assert state["components"]["core"]["quarantined"] == [NEW]
    assert {event["category"] for event in state["report_events"]} == {"startup_failed", "rolled_back"}
    assert all(event["release"] == NEW and event["state"] == "failure" for event in state["report_events"])
    assert database.read_text() == "pairing and settings remain"
    with pytest.raises(ValueError, match="quarantined"):
        manager.activate_core(state, NEW)


def test_a_refused_worker_release_keeps_the_old_worker_and_is_reported(tmp_path):
    manager, state, host, _ = running(tmp_path)
    host.refused.add("news")
    assert manager.deploy_workers(state, ["music", "news"], NEW) == ["news"]
    assert host.calls == [("deploy", "music", NEW), ("deploy", "news", NEW)]
    assert state["components"]["music"]["active"] == NEW and state["components"]["music"]["previous"] == OLD
    assert state["components"]["news"]["active"] == OLD and state["components"]["news"]["quarantined"] == [NEW]
    assert [(event["component"], event["category"]) for event in state["report_events"]] == [("news", "startup_failed")]


def test_guard_reports_a_supervisor_rollback_and_copies_the_worker_releases(tmp_path):
    manager, state, host, _ = running(tmp_path)
    atomic_json(manager.supervisor_path, {"features": {"music": {"active": OLD, "previous": None, "bad": [NEW]}}})
    manager.guard(state)
    assert state["components"]["music"]["quarantined"] == [NEW]
    assert [(event["component"], event["release"], event["category"], event["restored_release"])
            for event in state["report_events"]] == [("music", NEW, "rolled_back", OLD)]
    manager.guard(state)
    assert len(state["report_events"]) == 1


def test_guard_restarts_once_then_restores_the_previous_core(tmp_path):
    manager, state, host, _ = running(tmp_path)
    manager.activate_core(state, NEW)
    host.calls.clear()
    host.broken.add(NEW)
    for _ in range(6):
        manager.guard(state)
    assert host.calls == ["stack", "restart", "stack", "restart"]
    assert state["components"]["core"]["active"] == OLD
    assert manager.current.resolve() == manager.release(OLD)
    manager.guard(state)
    assert state["report_events"][-1]["release"] == OLD
    assert state["report_events"][-1]["state"] == "success"


def test_guard_resolves_an_interrupted_activation_from_the_saved_record(tmp_path):
    manager, state, host, now = running(tmp_path)
    state["pending"] = {"revision": NEW, "started_at": now[0], "previous": OLD}
    manager.save(state)
    switch(manager.current, manager.release(NEW))
    manager.guard(read(manager.state_path))
    recovered = read(manager.state_path)
    assert manager.current.resolve() == manager.release(OLD)
    assert recovered["components"]["core"]["quarantined"] == [NEW]
    assert recovered["pending"] is None
    kinds = {json.loads(path.read_text())["kind"] for path in (tmp_path / "ticker_data/backend-incidents").glob("*.json")}
    assert "deployment_rollback" in kinds


def test_guard_detects_core_crashes_between_good_health_samples(tmp_path):
    manager, state, host, _ = running(tmp_path)
    manager.activate_core(state, NEW)
    host.process_restarts = 3
    manager.guard(state)
    assert state["components"]["core"]["active"] == OLD
    assert state["components"]["core"]["crash_count"] == 0


@pytest.mark.parametrize("health", [[], {"release": OLD, "runtime": None},
                                    {"release": OLD, "runtime": {"enabled": True, "running": True, "ready": True, "cycles": "bad"}},
                                    {"release": THIRD, "runtime": {"enabled": True, "running": True, "ready": True, "cycles": 5}}])
def test_bad_or_foreign_health_counts_as_unready(tmp_path, health):
    manager, host, _ = manager_for(tmp_path)
    host.health = lambda: health
    assert not manager.ready(OLD)[0]


def staged(tmp_path, root, components):
    staging = tmp_path / "staging"
    package(root, staging, components)
    return staging


def test_first_deployment_moves_every_process_and_retires_the_fetcher_services(tmp_path):
    root, revision = repository(tmp_path)
    manager, host, _ = manager_for(tmp_path / "home", releases=())
    legacy = {"schema_version": 1, "processed_revision": OLD, "report_site": "a" * 32, "report_sequence": 4, "report_events": [],
              "components": {"clock": {"active": OLD}}}
    atomic_json(manager.state_path, legacy)
    switch(manager.home / "backend-control/current", manager.home / "backend-control/versions/legacy")
    state = manager.deploy(staged(tmp_path, root, ["music"]))
    assert host.calls.count("install_units") == 1 and "retire_fetchers" in host.calls
    assert not [call for call in host.calls if call[0] == "deploy"]
    assert all(state["components"][name]["active"] == revision for name in COMPONENTS)
    assert state["report_sequence"] == 4 and "legacy_toolkit" not in state
    assert read(manager.control / "state-before-ticker3.json") == legacy
    assert (manager.home / "backend-control/current").resolve() == manager.home / "backend-control/versions" / revision


def test_failed_first_deployment_gives_control_back_to_the_old_deployment(tmp_path):
    root, revision = repository(tmp_path)
    manager, host, _ = manager_for(tmp_path / "home", releases=())
    host.broken.add(revision)
    legacy = {"schema_version": 1, "processed_revision": OLD, "components": {"core": {"active": OLD}}}
    atomic_json(manager.state_path, legacy)
    toolkit = manager.home / "backend-control/versions/legacy"
    toolkit.mkdir(parents=True)
    switch(manager.home / "backend-control/current", toolkit)
    with pytest.raises(RuntimeError, match="failed release readiness"):
        manager.deploy(staged(tmp_path, root, ["core"]))
    assert host.calls[-2:] == ["restore_units", "restart"] and host.running == "legacy"
    assert not manager.current.exists()
    assert (manager.home / "backend-control/current").resolve() == toolkit
    restored = read(manager.state_path)
    assert restored["components"] == legacy["components"] and restored["schema_version"] == 1
    assert {event["category"] for event in restored["report_events"]} == {"startup_failed", "rolled_back"}


def test_a_worker_only_deployment_asks_the_supervisor_and_keeps_the_core(tmp_path):
    manager, state, host, _ = running(tmp_path)
    root, revision = repository(tmp_path)
    state = manager.deploy(staged(tmp_path, root, ["music"]))
    assert [call for call in host.calls if call == "restart" or call[0] == "deploy"] == [("deploy", "music", revision)]
    assert state["components"]["core"]["active"] == OLD
    assert state["components"]["music"]["active"] == revision
    assert manager.current.resolve() == manager.release(OLD)
