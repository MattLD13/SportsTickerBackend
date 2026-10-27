"""Prove component selection, atomic activation, rollback, and quarantine."""
import copy
import json
from pathlib import Path
import shutil
import tarfile
import subprocess

import pytest

from backend_ops.components import ALL, owners, package
from backend_ops.incidents import atomic_json
from backend_ops.manager import Host as LinuxHost, Manager, read, switch
from backend_ops.worker_contract import contract_id

pytestmark = pytest.mark.critical
OLD, NEW = "1" * 40, "2" * 40


class Host:
    def __init__(self):
        self.restarts = []
        self.broken = set()
        self.code_failure = False
        self.replay_passes = True

    def restart(self, name):
        self.restarts.append(name)

    def probe(self, name, release):
        version = release.name
        ready = (name, version) not in self.broken
        return {"release": version, "ready": ready, "contract": read(release / "release-manifest.json")["contract"], "busy_seconds": 0,
                "runtime": {"enabled": True, "running": True, "ready": ready, "cycles": 10},
                "failures": 3 if name == "music" and self.code_failure else 0,
                "error_type": "KeyError" if self.code_failure else None}

    def stack(self, name):
        pass

    def replay(self, name, previous):
        return self.replay_passes


def setup(tmp_path):
    now = [1000.0]
    host = Host()
    manager = Manager(tmp_path, host=host, clock=lambda: now[0], sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
    state = {"schema_version": 1, "pending": None, "processed_revision": OLD, "components": {}}
    for name in ALL:
        for version in (OLD, NEW):
            release = manager.release(name, version)
            release.mkdir(parents=True)
            atomic_json(release / "release-manifest.json", {"release": version, "contract": "contract"})
        state["components"][name] = {"active": OLD, "previous": None, "quarantined": [], "failures": 0, "trial_at": 1000}
        try:
            switch(manager.link(name), manager.release(name, OLD))
        except OSError as error:
            if getattr(error, "winerror", None) == 1314:
                pytest.skip("Linux CI validates atomic symlinks. Windows has no symlink privilege")
            raise
    manager.save(state)
    return manager, state, host, now


def test_deployment_selects_the_fact_owner_and_shared_dependencies():
    assert owners("sports_ticker/providers/music.py") == {"music"}
    assert owners("sports_ticker/api/routes.py") == {"core"}
    assert owners("sports_ticker/integrations/spotify.py") == {"core", "music"}
    assert owners("sports_ticker/tls.py") == set(ALL)
    assert owners("sports_ticker/immutable.py") == set(ALL)
    assert owners("sports_ticker/domain/models.py") == set(ALL)
    assert owners("tests/python/test_modes.py") == set()
    assert owners("sports_ticker/providers/source_values.py") == {"golf", "stock", "flights", "news"}
    assert owners("sports_ticker/providers/score_alerts.py") == {"espn", "fotmob"}
    assert owners("sports_ticker/domain/settings.py") == set(ALL)
    assert owners("sports_ticker/providers/racing_session.py") == {"core", "racing"}


@pytest.mark.parametrize("module,component", [
    ("golf_source", "golf"), ("stock_source", "stock"),
    ("flight_source", "flights"), ("news_source", "news"), ("clock", "clock"),
])
def test_source_file_changes_select_only_their_worker(module, component):
    assert owners(f"sports_ticker/providers/{module}.py") == {component}


def test_deployment_packages_shared_tls_helper_for_each_process(tmp_path):
    source = Path.cwd()
    root = tmp_path / "repository"
    required = (
        "backend_ops/worker_contract.py",
        "sports_ticker/domain/models.py",
        "sports_ticker/providers/contracts.py",
        "sports_ticker/immutable.py",
        "sports_ticker/tls.py",
    )
    for relative in required:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
    for directory in ("ticker_core", "backend_ops", "sports_ticker"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    for filename in ("requirements.txt", "requirements-backend.txt", "VERSION", "RELEASE_SHA"):
        (root / filename).write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Deployment Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "deployment@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "Create package fixture"], cwd=root, check=True, capture_output=True)
    output = tmp_path / "packages"
    package(root, output, ALL)
    for component in ALL:
        with tarfile.open(output / f"{component}.tar.gz", "r:gz") as archive:
            assert "sports_ticker/tls.py" in archive.getnames()
            assert "sports_ticker/immutable.py" in archive.getnames()


def test_bootstrap_copies_actual_legacy_contract_without_new_helper(tmp_path, monkeypatch):
    for name in ("backend_ops/worker_contract.py", "sports_ticker/domain/models.py",
                 "sports_ticker/providers/contracts.py"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((Path("tests/fixtures/backend_legacy") / name).read_bytes())
    (tmp_path / "ticker_core").mkdir()
    for name in ("requirements.txt", "requirements-backend.txt", "VERSION"):
        (tmp_path / name).write_text("test\n", encoding="utf-8")
    (tmp_path / "RELEASE_SHA").write_text(OLD, encoding="utf-8")

    class BaselineHost:
        def probe(self, component, release):
            return {"release": OLD, "runtime": {"ready": True}}
        def command(self, args):
            pass

    monkeypatch.setattr("backend_ops.manager.switch", lambda link, target: None)
    manager = Manager(tmp_path, host=BaselineHost(), clock=lambda: 1000)
    legacy_contract = contract_id(tmp_path)
    state = manager.bootstrap()
    for name in ALL:
        release = manager.release(name, OLD)
        assert not (release / "sports_ticker/immutable.py").exists()
        assert read(release / "release-manifest.json")["contract"] == legacy_contract
        assert state["components"][name]["active"] == OLD


def test_activation_restarts_only_the_changed_component(tmp_path):
    manager, state, host, _ = setup(tmp_path)
    manager.activate(state, {"music": NEW}, NEW)
    assert host.restarts == ["music"]
    assert state["components"]["music"]["active"] == NEW
    assert state["components"]["core"]["active"] == OLD
    assert manager.link("music").resolve() == manager.release("music", NEW)
    assert read(manager.state_path)["pending"] is None


def test_failed_startup_restores_old_release_and_quarantines_candidate(tmp_path):
    manager, state, host, _ = setup(tmp_path)
    host.broken.add(("core", NEW))
    database = tmp_path / "ticker_data/user-state"
    database.write_text("pairing and settings remain")
    with pytest.raises(RuntimeError, match="failed release readiness"):
        manager.activate(state, {"core": NEW}, NEW)
    assert manager.link("core").resolve() == manager.release("core", OLD)
    assert state["components"]["core"]["quarantined"] == [NEW]
    assert {event["category"] for event in state["report_events"]} == {"startup_failed", "rolled_back"}
    assert all(event["release"] == NEW and event["state"] == "failure" for event in state["report_events"])
    assert host.restarts == ["core", "core"]
    assert database.read_text() == "pairing and settings remain"
    with pytest.raises(ValueError, match="quarantined"):
        manager.activate(state, {"core": NEW}, NEW)


@pytest.mark.parametrize("replay_passes", [False, True])
def test_fetcher_code_rollback_requires_a_healthy_previous_replay(tmp_path, replay_passes):
    manager, state, host, _ = setup(tmp_path)
    manager.activate(state, {"music": NEW}, NEW)
    host.restarts.clear()
    host.code_failure, host.replay_passes = True, replay_passes
    manager.guard(state)
    assert state["components"]["music"]["active"] == (OLD if replay_passes else NEW)
    assert host.restarts == (["music"] if replay_passes else [])
    assert bool(state.get("report_events")) == replay_passes


def test_guard_restarts_once_then_restores_only_the_failed_worker(tmp_path):
    manager, state, host, _ = setup(tmp_path)
    manager.activate(state, {"music": NEW}, NEW)
    host.restarts.clear()
    host.broken.add(("music", NEW))
    for _ in range(6):
        manager.guard(state)
    assert host.restarts == ["music", "music"]
    assert state["components"]["music"]["active"] == OLD
    assert all(record["active"] == OLD for record in state["components"].values())
    manager.guard(state)
    assert state["report_events"][-1]["release"] == OLD
    assert state["report_events"][-1]["state"] == "success"


def test_guard_resolves_an_interrupted_activation_from_durable_state(tmp_path):
    manager, state, host, now = setup(tmp_path)
    state["pending"] = {"revision": NEW, "started_at": now[0], "versions": {"music": NEW}, "previous": {"music": OLD}}
    manager.save(state)
    switch(manager.link("music"), manager.release("music", NEW))
    manager.guard(read(manager.state_path))
    recovered = read(manager.state_path)
    assert manager.link("music").resolve() == manager.release("music", OLD)
    assert recovered["components"]["music"]["quarantined"] == [NEW]
    assert recovered["pending"] is None
    assert "deployment_rollback" in {json.loads(path.read_text())["kind"] for path in (tmp_path / "ticker_data/backend-incidents").glob("*.json")}


def test_failed_health_does_not_promote_a_process_with_another_release(tmp_path):
    manager, state, host, _ = setup(tmp_path)
    original = copy.copy(host.probe)
    host.probe = lambda name, path: {**original(name, path), "release": "3" * 40}
    assert not manager.ready("core", OLD)[0]


def test_contract_rollback_keeps_a_compatible_cohort_after_later_worker_updates(tmp_path):
    manager, state, host, _ = setup(tmp_path)
    manager.remember_contract(state)
    for name in ALL:
        atomic_json(manager.release(name, NEW) / "release-manifest.json", {"release": NEW, "contract": "next-contract"})
    manager.activate(state, {name: NEW for name in ALL}, NEW)
    third = "3" * 40
    release = manager.release("music", third)
    release.mkdir(parents=True)
    atomic_json(release / "release-manifest.json", {"release": third, "contract": "next-contract"})
    manager.activate(state, {"music": third}, third)
    assert manager.restore(state, "core", "core regression after a contract change")
    assert all(record["active"] == OLD for record in state["components"].values())


@pytest.mark.parametrize("malformed", [[], {"release": OLD, "runtime": None},
    {"release": OLD, "runtime": {"enabled": True, "running": True, "ready": True, "cycles": "bad"}}])
def test_malformed_process_health_counts_as_failure_instead_of_stopping_the_guard(tmp_path, malformed):
    manager = Manager(tmp_path, host=Host())
    manager.host.probe = lambda name, release: malformed
    assert not manager.ready("core", OLD)[0]


def test_replay_does_not_roll_back_a_fetcher_that_has_already_recovered(tmp_path):
    atomic_json(tmp_path / "ticker_data/backend-control/replays/music-last-failure.json", {"op": "fetch", "settings": {}, "ticker_id": "test"})
    atomic_json(tmp_path / "backend-components/music/current/release-manifest.json", {"contract": "contract"})
    host = LinuxHost(tmp_path)
    calls = []
    host.rpc = lambda path, message, **kwargs: calls.append(message) or {"result": {"health": {"healthy": True}}}
    assert not host.replay("music", tmp_path / "previous")
    assert len(calls) == 1


def test_guard_detects_crashes_between_successful_health_samples(tmp_path):
    manager, state, host, _ = setup(tmp_path)
    manager.activate(state, {"core": NEW}, NEW)
    original = host.probe
    host.probe = lambda name, release: {**original(name, release), "process_restarts": 3 if name == "core" and release.name == NEW else 0}
    manager.guard(state)
    assert state["components"]["core"]["active"] == OLD
    assert state["components"]["core"]["crash_count"] == 0
    manager.guard(state)
    assert state["components"]["core"]["active"] == OLD
