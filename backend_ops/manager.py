"""Install Ticker 3 releases, move the core and the workers to them, and restore a healthy core.

Server layout under the home folder:

| Path | Content |
|---|---|
| `ticker3/releases/<revision>/` | One immutable release: all source files, a manifest, and a `.venv` link |
| `ticker3/environments/<hash>/` | One dependency environment for each set of requirements |
| `ticker3/current` | The release of the core process |
| `ticker_data/backend-control/state.json` | The deployment record and the report queue |
| `ticker_data/ticker3-supervisor.json` | The release of each worker. The core supervisor owns this file. |

The core supervisor restarts, replaces, and rolls back workers. This manager
owns the release files, the core service, and the deployment record.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .components import COMPONENTS
from .incidents import IncidentStore, atomic_json
from .reporting import failure as report_failure, recovered as report_recovered

WORKERS = COMPONENTS[1:]
HEALTH_URL = "http://127.0.0.1:5000/health"
# The services of the deployment before Ticker 3. The first Ticker 3 deployment retires them.
LEGACY_FETCHERS = (*WORKERS, "clock")
UNITS = ("ticker.service", "ticker-backend-guard.service", "ticker-backend-guard.timer")
REPORT_KEYS = ("report_site", "report_sequence", "report_events", "report_last_ack_at")


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {} if default is None else default


def switch(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    temporary = link.with_name(link.name + ".next")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target, target_is_directory=True)
    os.replace(temporary, link)


def environment_value(path: Path, key: str) -> str | None:
    """Read one value of a dotenv file without the dotenv package. The manager runs on the system Python."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        name, separator, value = line.partition("=")
        if separator and name.strip().removeprefix("export ").strip() == key:
            return value.strip().strip("\"'")
    return None


class Host:
    """Run the service commands and the local HTTP requests of one server."""

    def __init__(self, home: Path) -> None:
        self.home = home

    def command(self, args, **kwargs):
        return subprocess.run(args, check=kwargs.pop("check", True), timeout=kwargs.pop("timeout", 120), **kwargs)

    def restart_core(self) -> None:
        self.command(["sudo", "systemctl", "reset-failed", "ticker.service"])
        self.command(["sudo", "systemctl", "restart", "ticker.service"])

    def stack_core(self) -> None:
        self.command(["sudo", "systemctl", "kill", "--kill-whom=main", "--signal=SIGUSR2", "ticker.service"], timeout=5)

    def health(self) -> dict:
        with urlopen(HEALTH_URL, timeout=3) as response:
            health = json.load(response)
        if isinstance(health, dict):
            result = subprocess.run(["systemctl", "show", "ticker.service", "--property=NRestarts", "--value"],
                                    capture_output=True, text=True, timeout=3, check=False)
            if result.stdout.strip().isdigit():
                health["process_restarts"] = int(result.stdout.strip())
        return health

    def deploy_worker(self, name: str, release: str) -> bool:
        """Ask the running core to move one worker to a release. The supervisor promotes it only after it syncs."""
        token = environment_value(self.home / ".env", "TICKER_DEPLOY_TOKEN")
        if not token:
            raise RuntimeError("TICKER_DEPLOY_TOKEN is not set")
        request = Request(f"http://127.0.0.1:5000/workers/{name}/deploy", method="POST",
                          data=json.dumps({"release": release}).encode(),
                          headers={"Content-Type": "application/json", "X-Deployment-Token": token})
        try:
            with urlopen(request, timeout=180) as response:
                return bool(json.load(response).get("deployed"))
        except HTTPError as error:
            if error.code == 409:
                return False
            raise

    def install_units(self, source: Path, backup: Path) -> None:
        """Keep a copy of the installed units, then install the units of this release."""
        backup.mkdir(parents=True, exist_ok=True)
        for name in UNITS:
            installed = Path("/etc/systemd/system") / name
            if installed.exists() and not (backup / name).exists():
                shutil.copy2(installed, backup / name)
            self.command(["sudo", "cp", str(source / name), str(installed)])
        self.command(["sudo", "systemctl", "daemon-reload"])
        self.command(["sudo", "systemctl", "enable", "ticker.service", "ticker-backend-guard.timer"])

    def restore_units(self, backup: Path) -> None:
        """Put back the units of the deployment before Ticker 3 and start its fetchers again."""
        for name in UNITS:
            if (backup / name).exists():
                self.command(["sudo", "cp", str(backup / name), str(Path("/etc/systemd/system") / name)])
        self.command(["sudo", "systemctl", "daemon-reload"])
        for name in LEGACY_FETCHERS:
            self.command(["sudo", "systemctl", "start", f"ticker-fetcher@{name}.service"], check=False)

    def retire_fetchers(self) -> None:
        """Stop the fetcher services of the deployment before Ticker 3. The core supervisor runs the workers now."""
        for name in LEGACY_FETCHERS:
            self.command(["sudo", "systemctl", "disable", "--now", f"ticker-fetcher@{name}.service"], check=False)
        self.command(["sudo", "rm", "-f", "/etc/systemd/system/ticker-fetcher@.service"])
        self.command(["sudo", "systemctl", "daemon-reload"])


class Manager:
    def __init__(self, home, *, host=None, clock=time.time, sleep=time.sleep) -> None:
        self.home = Path(home).resolve()
        self.root = self.home / "ticker3"
        self.current = self.root / "current"
        self.control = self.home / "ticker_data/backend-control"
        self.state_path = self.control / "state.json"
        self.supervisor_path = self.home / "ticker_data/ticker3-supervisor.json"
        self.host = host or Host(self.home)
        self.clock, self.sleep = clock, sleep
        self.incidents = IncidentStore(self.home / "ticker_data/backend-incidents", clock=clock)

    @contextmanager
    def locked(self, *, wait: bool = True):
        import fcntl
        self.control.mkdir(parents=True, exist_ok=True)
        with (self.control / "lock").open("a") as descriptor:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)

    # Records

    def release(self, revision: str) -> Path:
        if not isinstance(revision, str) or not re.fullmatch("[0-9a-f]{40}", revision):
            raise ValueError("invalid release identity")
        return self.root / "releases" / revision

    def save(self, state: dict) -> None:
        state["updated_at"] = self.clock()
        atomic_json(self.state_path, state)

    def load(self) -> dict:
        """Return the deployment record. A record from before Ticker 3 keeps only its report queue."""
        state = read(self.state_path)
        if state.get("schema_version") == 2:
            return state
        fresh = {"schema_version": 2, "pending": None, "processed_revision": state.get("processed_revision"),
                 "components": {name: {"active": None, "previous": None, "quarantined": []} for name in COMPONENTS}}
        fresh.update({key: state[key] for key in REPORT_KEYS if key in state})
        # Reports of a process that no longer exists cannot pass the report contract.
        fresh["report_events"] = [event for event in fresh.get("report_events", []) if event.get("component") in COMPONENTS]
        return fresh

    # Core readiness

    def ready(self, revision: str) -> tuple[bool, dict]:
        try:
            health = self.host.health()
            if not isinstance(health, dict):
                raise ValueError("health must be an object")
            runtime = health.get("runtime", {})
            ready = (health.get("release") == revision and runtime.get("enabled") is True and runtime.get("running") is True
                     and runtime.get("ready") is True and int(runtime.get("cycles", 0)) >= 2)
            return ready, health
        except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as error:
            return False, {"probe_error": type(error).__name__}

    def trial(self, revision: str, *, seconds: float = 90) -> bool:
        deadline, successes = self.clock() + seconds, 0
        while self.clock() < deadline:
            ready, _ = self.ready(revision)
            successes = successes + 1 if ready else 0
            if successes >= 3:
                return True
            self.sleep(2)
        return False

    # Core activation

    def activate_core(self, state: dict, revision: str) -> None:
        """Save the rollback record, move the core to `revision`, and require three ready checks."""
        record = state["components"]["core"]
        if revision in record.get("quarantined", []):
            raise ValueError(f"quarantined release for core: {revision}")
        state["pending"] = {"revision": revision, "started_at": self.clock(), "previous": record.get("active")}
        self.save(state)
        try:
            switch(self.current, self.release(revision))
            self.host.restart_core()
            if not self.trial(revision):
                raise RuntimeError("core failed release readiness")
        except Exception as error:
            self.rollback_pending(state, error, category="startup_failed")
            raise
        if record.get("active") is None:
            self.host.retire_fetchers()
            state.pop("legacy_toolkit", None)
        record.update(previous=record.get("active"), active=revision, failures=0, restarts=0, trial_at=self.clock(),
                      last_good_at=self.clock(), crash_count=0, observed_process_restarts=0, crash_window_at=self.clock())
        report_recovered(state, "core", self.clock())
        state["pending"] = None
        state["last_success_revision"] = revision
        self.save(state)
        self.incidents.record("deployment_accepted", component="core", context={"revision": revision})

    def rollback_pending(self, state: dict, error: BaseException, *, category: str = "deployment_interrupted") -> None:
        """Return the core to the release before the saved activation, and quarantine the candidate."""
        pending = state["pending"]
        record = state["components"]["core"]
        candidate, previous = pending["revision"], pending["previous"]
        report_failure(state, "core", candidate, category, self.clock(), restored=previous)
        self.save(state)
        if previous is None:
            self.restore_legacy(state, candidate, error)
            return
        switch(self.current, self.release(previous))
        self.host.restart_core()
        record.update(active=previous, failures=0, restarts=0, trial_at=self.clock(), crash_count=0,
                      observed_process_restarts=0, crash_window_at=self.clock())
        record["quarantined"] = list(dict.fromkeys([*record.get("quarantined", []), candidate]))[-20:]
        report_failure(state, "core", candidate, "rolled_back", self.clock(), restored=previous)
        state["pending"] = None
        state["last_rollback"] = {"at": self.clock(), "component": "core", "release": candidate, "restored": previous,
                                  "reason": str(error)}
        self.save(state)
        self.incidents.record("deployment_rollback", component="core", error=error, context=state["last_rollback"])

    def restore_legacy(self, state: dict, candidate: str, error: BaseException) -> None:
        """Give control back to the deployment before Ticker 3 after its first Ticker 3 activation fails.

        The units, the guard manager, and the old deployment record return. The report queue keeps the failure.
        """
        self.current.unlink(missing_ok=True)
        self.host.restore_units(self.control / "units-before-ticker3")
        if state.get("legacy_toolkit"):
            switch(self.home / "backend-control/current", Path(state["legacy_toolkit"]))
        self.host.restart_core()
        report_failure(state, "core", candidate, "rolled_back", self.clock())
        legacy = read(self.control / "state-before-ticker3.json")
        legacy.update({key: state[key] for key in REPORT_KEYS if key in state})
        legacy["updated_at"] = self.clock()
        atomic_json(self.state_path, legacy)
        state["pending"] = None
        self.incidents.record("deployment_rollback", component="core", error=error,
                              context={"release": candidate, "restored": "the deployment before Ticker 3"})

    def restore_core(self, state: dict, reason: str) -> bool:
        record = state["components"]["core"]
        previous, failed = record.get("previous"), record.get("active")
        if not previous or previous == failed or previous in record.get("quarantined", []):
            self.incidents.record("rollback_unavailable", component="core", error=reason)
            return False
        state["pending"] = {"revision": failed, "started_at": self.clock(), "previous": previous}
        self.save(state)
        self.rollback_pending(state, RuntimeError(reason), category="rollback_started")
        record["previous"] = None
        self.save(state)
        return True

    # Workers

    def deploy_workers(self, state: dict, names, revision: str) -> list[str]:
        """Move each named worker to `revision` through the core supervisor. Return the workers that refused it."""
        refused = []
        for name in names:
            record = state["components"][name]
            try:
                deployed = self.host.deploy_worker(name, revision)
            except (OSError, ValueError, RuntimeError) as error:
                self.incidents.record("worker_deploy_failed", component=name, error=error, context={"revision": revision})
                deployed = False
            if deployed:
                record.update(previous=record.get("active"), active=revision)
                report_recovered(state, name, self.clock())
            else:
                report_failure(state, name, revision, "startup_failed", self.clock(), restored=record.get("active"))
                record["quarantined"] = list(dict.fromkeys([*record.get("quarantined", []), revision]))[-20:]
                refused.append(name)
            self.save(state)
        return refused

    def sync_workers(self, state: dict) -> None:
        """Copy the worker releases of the supervisor into the record, and report each supervisor rollback."""
        features = read(self.supervisor_path).get("features", {})
        for name in WORKERS:
            feature = features.get(name)
            if not feature:
                continue
            record = state["components"][name]
            active, bad = feature.get("active"), list(feature.get("bad", []))
            for release in bad:
                if release not in record.get("quarantined", []) and re.fullmatch("[0-9a-f]{40}", str(release)):
                    restored = active if re.fullmatch("[0-9a-f]{40}", str(active)) else None
                    report_failure(state, name, release, "rolled_back", self.clock(), restored=restored)
            record.update(active=active, previous=feature.get("previous"),
                          quarantined=list(dict.fromkeys([*record.get("quarantined", []), *bad]))[-20:])

    # Guard

    def guard(self, state: dict) -> None:
        """Check the core every 30 seconds. Restart it once after three failed checks, then restore the previous release."""
        if state.get("pending"):
            self.rollback_pending(state, RuntimeError("deployment stopped before health confirmation"))
            return
        record = state["components"]["core"]
        if record.get("active") is None:
            return
        ready, health = self.ready(record["active"])
        if "process_restarts" in health:
            restarts = health["process_restarts"]
            if self.clock() - record.get("crash_window_at", 0) > 1800:
                record.update(crash_count=0, crash_window_at=self.clock())
            record["crash_count"] = record.get("crash_count", 0) + max(0, restarts - record.get("observed_process_restarts", 0))
            record["observed_process_restarts"] = restarts
            if record["crash_count"] >= 3:
                report_failure(state, "core", record["active"], "crash_loop", self.clock())
                self.save(state)
                self.incidents.record("component_crash_loop", component="core",
                                      context={"release": record["active"], "crashes": record["crash_count"]})
                if self.restore_core(state, "three process crashes within 30 minutes"):
                    self.save(state)
                    return
        self.sync_workers(state)
        if ready:
            record["failures"] = 0
            record["last_good_at"] = self.clock()
            if record.get("crash_count", 0) < 3:
                report_recovered(state, "core", self.clock())
            workers = health.get("scheduler", {}).get("providers", {})
            for name in WORKERS:
                if workers.get(name, {}).get("healthy") is True:
                    report_recovered(state, name, self.clock())
            if self.clock() - record.get("trial_at", 0) > 1800:
                record["restarts"] = 0
            self.save(state)
            return
        record["failures"] = record.get("failures", 0) + 1
        if record["failures"] >= 3:
            report_failure(state, "core", record["active"], "runtime_unready", self.clock())
            self.save(state)
            self.incidents.record("component_unready", component="core", context={"release": record["active"], "health": health})
            try:
                self.host.stack_core()
            except (OSError, subprocess.SubprocessError):
                pass
            if record.get("restarts", 0) == 0:
                record.update(restarts=1, failures=0, trial_at=self.clock(), observed_process_restarts=0)
                self.save(state)
                self.host.restart_core()
            elif not self.restore_core(state, "core failed after one recovery restart"):
                record["failures"] = 0
        self.save(state)

    # Release files

    def prepare(self, archive: Path, revision: str) -> Path:
        """Unpack and check one release, and give it a dependency environment. Running processes do not change."""
        target = self.release(revision)
        if (target / ".prepared").exists():
            return target
        if target.exists():
            if target.is_symlink() or (self.current.exists() and self.current.resolve() == target):
                raise RuntimeError("an incomplete release is active or has an invalid path")
            shutil.rmtree(target)
        target.mkdir(parents=True)
        with tarfile.open(archive, "r:gz") as source:
            for member in source.getmembers():
                destination = (target / member.name).resolve()
                if not destination.is_relative_to(target) or not member.isfile():
                    raise ValueError("the release archive contains an invalid file")
            source.extractall(target, filter="data")
        manifest = read(target / "release-manifest.json")
        if manifest.get("release") != revision or manifest.get("schema_version") != 2:
            raise ValueError("the release manifest does not match the deployment")
        for name, digest in manifest["files"].items():
            path = (target / name).resolve()
            if not path.is_relative_to(target) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("a release file checksum failed")
        environments = self.root / "environments"
        identity = hashlib.sha256((target / "requirements.txt").read_bytes() + (target / "requirements-backend.txt").read_bytes()
                                  + sys.version.encode()).hexdigest()
        environment = environments / identity
        if not (environment / ".ready").exists():
            if environment.exists():
                if environment.is_symlink() or environment.resolve().parent != environments.resolve():
                    raise RuntimeError("an incomplete dependency environment has an invalid path")
                shutil.rmtree(environment)
            self.host.command([sys.executable, "-m", "venv", str(environment)], timeout=60)
            self.host.command([str(environment / "bin/python"), "-m", "pip", "install", "-r",
                               str(target / "requirements-backend.txt")], timeout=600)
            (environment / ".ready").touch()
        switch(target / ".venv", environment)
        python = str(target / ".venv/bin/python")
        self.host.command([python, "-m", "compileall", "-q", "sports_ticker", "ticker_core", "ticker3", "backend_ops"], cwd=target)
        script = (f"from dotenv import load_dotenv; load_dotenv({str(self.home / '.env')!r}); "
                  "import ticker3.server, ticker3.worker.__main__, sports_ticker.providers.factory")
        self.host.command([python, "-c", script], cwd=target)
        (target / ".prepared").touch()
        return target

    def backup_database(self, revision: str) -> None:
        database = self.home / "ticker_data/ticker-v2.sqlite3"
        if not database.exists():
            return
        backups = self.control / "database-backups"
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / (revision + ".sqlite3")
        with sqlite3.connect(database) as source, sqlite3.connect(backup) as destination:
            source.backup(destination)
        backup.chmod(0o600)
        for stale in sorted(backups.glob("*.sqlite3"), key=lambda path: path.stat().st_mtime)[:-3]:
            stale.unlink()

    def install_toolkit(self, release: Path, revision: str) -> None:
        """Give the guard timer the manager of this release. The guard reads records and imports no server code."""
        toolkit = self.home / "backend-control/versions" / revision
        if not toolkit.exists():
            toolkit.mkdir(parents=True)
            for package in ("backend_ops", "ticker3/contract"):
                shutil.copytree(release / package, toolkit / package, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            shutil.copy2(release / "ticker3/__init__.py", toolkit / "ticker3/__init__.py")
            shutil.copy2(release / "RELEASE_SHA", toolkit / "RELEASE_SHA")
        switch(self.home / "backend-control/current", toolkit)

    def retain(self, state: dict) -> None:
        """Keep each release that a process runs or can roll back to, and the three newest releases."""
        directory = self.root / "releases"
        if not directory.exists():
            return
        releases = sorted((path for path in directory.iterdir() if re.fullmatch("[0-9a-f]{40}", path.name)),
                          key=lambda path: path.stat().st_mtime, reverse=True)
        kept = {path.name for path in releases[:3]}
        for record in state["components"].values():
            kept.update((record.get("active"), record.get("previous")))
        for feature in read(self.supervisor_path).get("features", {}).values():
            kept.update((feature.get("active"), feature.get("previous")))
        for path in releases:
            if path.name not in kept and path.resolve().parent == directory.resolve() and not path.is_symlink():
                shutil.rmtree(path)

    def deploy(self, staging: Path) -> dict:
        plan = read(staging / "plan.json")
        revision, selected = plan["release"], list(plan["components"])
        if plan.get("schema_version") != 2 or any(name not in COMPONENTS for name in selected):
            raise ValueError("the deployment plan is invalid")
        state = self.load()
        if state.get("pending"):
            self.rollback_pending(state, RuntimeError("the previous deployment was interrupted"))
        first = state["components"]["core"].get("active") is None
        if first:
            # The first Ticker 3 deployment moves every process. Keep what the deployment before Ticker 3 needs to return.
            selected = list(COMPONENTS)
            previous = read(self.state_path)
            if previous and previous.get("schema_version") != 2 and not (self.control / "state-before-ticker3.json").exists():
                atomic_json(self.control / "state-before-ticker3.json", previous)
            toolkit = self.home / "backend-control/current"
            if toolkit.exists() and "legacy_toolkit" not in state:
                state["legacy_toolkit"] = str(toolkit.resolve())
        state["processed_revision"] = revision
        if not selected:
            self.save(state)
            return state
        release = self.prepare(staging / "release.tar.gz", revision)
        self.install_toolkit(release, revision)
        self.host.install_units(staging, self.control / "units-before-ticker3")
        if "core" in selected and state["components"]["core"].get("active") != revision:
            self.backup_database(revision)
            self.activate_core(state, revision)
        workers = [name for name in WORKERS if name in selected and state["components"][name].get("active") != revision]
        if first:
            # A new supervisor starts each worker on the release of the core.
            self.sync_workers(state)
            workers = [name for name in workers if state["components"][name].get("active") != revision]
        refused = self.deploy_workers(state, workers, revision)
        self.retain(state)
        self.save(state)
        if refused:
            raise RuntimeError(f"workers kept their previous release: {', '.join(refused)}")
        return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("deploy", "guard", "status"))
    parser.add_argument("--home", type=Path, default=Path("/home/ubuntu"))
    parser.add_argument("--staging", type=Path)
    args = parser.parse_args()
    manager = Manager(args.home)
    if args.operation == "status":
        print(json.dumps(read(manager.state_path), indent=2))
        return
    with manager.locked(wait=args.operation == "deploy") as acquired:
        if not acquired:
            return
        if args.operation == "deploy":
            manager.deploy(args.staging)
        elif read(manager.state_path).get("schema_version") == 2:
            state = manager.load()
            previous_rollback = state.get("last_rollback")
            manager.guard(state)
            if previous_rollback != state.get("last_rollback"):
                from .diagnostics import bundle
                bundle(manager.home, manager.control / "latest-report.zip")


if __name__ == "__main__":
    main()
