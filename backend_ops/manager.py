"""Activate immutable backend components and restore verified releases after failure."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tarfile
import time
from urllib.request import urlopen

from .incidents import IncidentStore, atomic_json
from .reporting import failure as report_failure, recovered as report_recovered
from .worker_contract import MAX_MESSAGE, PROVIDERS

COMPONENTS = ("core", *PROVIDERS)
CODE_ERRORS = frozenset(("TypeError", "KeyError", "AttributeError", "AssertionError", "NameError", "UnboundLocalError", "ImportError", "SyntaxError"))


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {} if default is None else default


def switch(link, target):
    link.parent.mkdir(parents=True, exist_ok=True)
    temporary = link.with_name(link.name + ".next")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target, target_is_directory=True)
    os.replace(temporary, link)


class Host:
    """Own Linux service operations and bounded local health requests."""

    def __init__(self, home):
        self.home = home

    def command(self, args, **kwargs):
        return subprocess.run(args, check=True, timeout=kwargs.pop("timeout", 120), **kwargs)

    def unit(self, component):
        return "ticker.service" if component == "core" else f"ticker-fetcher@{component}.service"

    def restart(self, component):
        self.command(["sudo", "systemctl", "reset-failed", self.unit(component)])
        self.command(["sudo", "systemctl", "restart", self.unit(component)])

    def stack(self, component):
        self.command(["sudo", "systemctl", "kill", "--kill-whom=main", "--signal=SIGUSR2", self.unit(component)], timeout=5)

    def probe(self, component, release):
        if component == "core":
            with urlopen("http://127.0.0.1:5000/api/v2/health", timeout=3) as response:
                health = json.load(response)
        else:
            health = self.rpc(self.home / "ticker_data/backend_sockets" / (component + ".sock"),
                              {"protocol": 1, "contract": read(release / "release-manifest.json")["contract"], "op": "health"})
        if isinstance(health, dict):
            result = subprocess.run(["systemctl", "show", self.unit(component), "--property=NRestarts", "--value"],
                                    capture_output=True, text=True, timeout=3, check=False)
            if result.stdout.strip().isdigit():
                health["process_restarts"] = int(result.stdout.strip())
        return health

    def rpc(self, path, message, timeout=3):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(str(path))
            connection.sendall(json.dumps(message, separators=(",", ":")).encode() + b"\n")
            with connection.makefile("rb") as source:
                data = source.readline(MAX_MESSAGE + 1)
        if len(data) > MAX_MESSAGE or not data.endswith(b"\n"):
            raise ValueError("invalid worker response size")
        return json.loads(data)

    def replay(self, component, previous):
        """Compare one failed request with the previous isolated worker process."""
        message = read(self.home / "ticker_data/backend-control/replays" / (component + "-last-failure.json"))
        if message.get("op") != "fetch":
            return False
        active_manifest = read(self.home / "backend-components" / component / "current/release-manifest.json")
        try:
            current = self.rpc(self.home / "ticker_data/backend_sockets" / (component + ".sock"),
                               {**message, "contract": active_manifest["contract"]}, timeout=32)
            failure = current.get("result", {}).get("health", {})
            if failure.get("healthy") is not False or (failure.get("diagnostic") or {}).get("exception_type") not in CODE_ERRORS:
                return False
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return False
        message["contract"] = read(previous / "release-manifest.json")["contract"]
        path = self.home / "ticker_data/backend_sockets" / (component + "-probe.sock")
        path.unlink(missing_ok=True)
        process = subprocess.Popen([str(previous / ".venv/bin/python"), "-m", "backend_ops.worker", "--component", component,
                                    "--socket", str(path), "--env-file", str(self.home / ".env")], cwd=previous,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 15
            while not path.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.1)
            response = self.rpc(path, message, timeout=32)
            return response.get("result", {}).get("health", {}).get("healthy") is True
        except (OSError, ValueError):
            return False
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            path.unlink(missing_ok=True)


class Manager:
    def __init__(self, home, *, host=None, clock=time.time, sleep=time.sleep):
        self.home = Path(home).resolve()
        self.control = self.home / "ticker_data/backend-control"
        self.state_path = self.control / "state.json"
        self.host = host or Host(self.home)
        self.clock, self.sleep = clock, sleep
        self.incidents = IncidentStore(self.home / "ticker_data/backend-incidents", clock=clock)

    @contextmanager
    def locked(self, *, wait=True):
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

    def release(self, component, revision):
        if component not in COMPONENTS or not re.fullmatch("[0-9a-f]{40}", revision):
            raise ValueError("invalid component release identity")
        return self.home / "backend-components" / component / "releases" / revision

    def link(self, component):
        return self.home / "backend-components" / component / "current"

    def save(self, state):
        state["updated_at"] = self.clock()
        atomic_json(self.state_path, state)

    def remember_contract(self, state):
        records = state["components"]
        core = records["core"]
        current = read(self.release("core", core["active"]) / "release-manifest.json").get("contract")
        cohorts = state.setdefault("contract_baselines", {})
        cohorts[current] = {name: record["active"] for name, record in records.items()}
        previous = read(self.release("core", core["previous"]) / "release-manifest.json").get("contract") if core.get("previous") else None
        state["contract_baselines"] = {key: value for key, value in cohorts.items() if key in (current, previous)}

    def ready(self, component, revision):
        try:
            health = self.host.probe(component, self.release(component, revision))
            if not isinstance(health, dict):
                raise ValueError("component health must be an object")
            if health.get("release") != revision:
                return False, health
            if component == "core":
                runtime = health.get("runtime", {})
                return bool(runtime.get("enabled") and runtime.get("running") and runtime.get("ready") and runtime.get("cycles", 0) >= 2), health
            manifest = read(self.release(component, revision) / "release-manifest.json")
            return bool(health.get("ready") and health.get("contract") == manifest["contract"] and health.get("busy_seconds", 0) < 45), health
        except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as error:
            return False, {"probe_error": type(error).__name__}

    def trial(self, component, revision, *, seconds=90):
        deadline, successes = self.clock() + seconds, 0
        while self.clock() < deadline:
            ready, _ = self.ready(component, revision)
            successes = successes + 1 if ready else 0
            if successes >= 3:
                return True
            self.sleep(2)
        return False

    def activate(self, state, versions, revision):
        """Persist the rollback transaction before switching any component link."""
        records = state["components"]
        for name, version in versions.items():
            if version in records[name].get("quarantined", []):
                raise ValueError(f"quarantined release for {name}")
        pending = {"revision": revision, "started_at": self.clock(), "versions": versions,
                   "previous": {name: records[name]["active"] for name in versions}}
        state["pending"] = pending
        state["processed_revision"] = revision
        self.save(state)
        try:
            for name in versions:
                switch(self.link(name), self.release(name, versions[name]))
            for name in (*PROVIDERS, "core"):
                if name in versions:
                    self.host.restart(name)
            for name, version in versions.items():
                if not self.trial(name, version):
                    raise RuntimeError(f"{name} failed release readiness")
        except Exception as error:
            self.rollback_pending(state, error, category="startup_failed")
            raise
        for name, version in versions.items():
            records[name].update(previous=pending["previous"][name], active=version, failures=0,
                                 trial_at=self.clock(), restarts=0, last_good_at=self.clock(),
                                 observed_process_restarts=0, crash_count=0, crash_window_at=self.clock())
            report_recovered(state, name, self.clock())
        state["pending"] = None
        state["last_success_revision"] = revision
        self.remember_contract(state)
        self.save(state)
        self.incidents.record("deployment_accepted", component="deployment", context={"versions": versions, "revision": revision})

    def rollback_pending(self, state, error, *, category="deployment_interrupted"):
        pending = state["pending"]
        for name, version in pending["versions"].items():
            if version != pending["previous"][name]:
                report_failure(state, name, version, category, self.clock(), restored=pending["previous"][name])
        self.save(state)
        for name, old in pending["previous"].items():
            switch(self.link(name), self.release(name, old))
            record = state["components"][name]
            if record["active"] != old:
                record.update(active=old, previous=None, failures=0, restarts=0, trial_at=self.clock(),
                              crash_count=0, observed_process_restarts=0, crash_window_at=self.clock())
            record["quarantined"] = list(dict.fromkeys([*record.get("quarantined", []), pending["versions"][name]]))[-20:]
        for name in (*PROVIDERS, "core"):
            if name in pending["previous"]:
                self.host.restart(name)
                if pending["versions"][name] != pending["previous"][name]:
                    report_failure(state, name, pending["versions"][name], "rolled_back", self.clock(), restored=pending["previous"][name])
        state["pending"] = None
        state["last_rollback"] = {"at": self.clock(), "versions": pending["versions"], "restored": pending["previous"], "reason": str(error)}
        self.save(state)
        self.incidents.record("deployment_rollback", component="deployment", error=error, context=state["last_rollback"])

    def restore(self, state, name, reason):
        record = state["components"][name]
        old, failed = record.get("previous"), record["active"]
        if not old or old == failed or old in record.get("quarantined", []):
            self.incidents.record("rollback_unavailable", component=name, error=reason)
            return False
        active_contract = read(self.release(name, failed) / "release-manifest.json").get("contract")
        old_contract = read(self.release(name, old) / "release-manifest.json").get("contract")
        group = {name: old}
        if active_contract != old_contract:
            group = state.get("contract_baselines", {}).get(old_contract, {})
            if not group:
                group = {key: value["previous"] for key, value in state["components"].items() if value.get("previous")
                         and read(self.release(key, value["previous"]) / "release-manifest.json").get("contract") == old_contract}
            if set(group) != set(COMPONENTS) or any(version in state["components"][key].get("quarantined", [])
                    or read(self.release(key, version) / "release-manifest.json").get("contract") != old_contract for key, version in group.items()):
                self.incidents.record("rollback_blocked_contract", component=name, error=reason)
                return False
        state["pending"] = {"revision": state.get("processed_revision"), "started_at": self.clock(),
                            "versions": {key: state["components"][key]["active"] for key in group}, "previous": group}
        self.save(state)
        self.rollback_pending(state, RuntimeError(reason), category="rollback_started")
        for key, version in group.items():
            state["components"][key].update(active=version, previous=None, failures=0, restarts=0, trial_at=self.clock(),
                                             crash_count=0, observed_process_restarts=0, crash_window_at=self.clock())
        self.remember_contract(state)
        self.save(state)
        return True

    def guard(self, state):
        if state.get("pending"):
            self.rollback_pending(state, RuntimeError("deployment stopped before health confirmation"))
            return
        replay_used = False
        for name in COMPONENTS:
            record = state["components"][name]
            ready, health = self.ready(name, record["active"])
            if "process_restarts" in health:
                restarts = health["process_restarts"]
                if self.clock() - record.get("crash_window_at", 0) > 1800:
                    record.update(crash_count=0, crash_window_at=self.clock())
                record["crash_count"] = record.get("crash_count", 0) + max(0, restarts - record.get("observed_process_restarts", 0))
                record["observed_process_restarts"] = restarts
                if record["crash_count"] >= 3:
                    report_failure(state, name, record["active"], "crash_loop", self.clock())
                    self.save(state)
                    self.incidents.record("component_crash_loop", component=name, context={"release": record["active"], "crashes": record["crash_count"]})
                    if self.restore(state, name, "three process crashes within 30 minutes"):
                        continue
            if ready:
                record["failures"] = 0
                record["last_good_at"] = self.clock()
                if health.get("failures", 0) == 0 and record.get("crash_count", 0) < 3:
                    report_recovered(state, name, self.clock())
                if self.clock() - record.get("trial_at", 0) > 1800:
                    record["restarts"] = 0
                if not replay_used and name != "core" and health.get("failures", 0) >= 3 and health.get("error_type") in CODE_ERRORS and record.get("previous"):
                    if self.clock() - record.get("last_replay_at", 0) >= 300:
                        record["last_replay_at"] = self.clock()
                        replay_used = True
                        previous = self.release(name, record["previous"])
                        try:
                            improved = self.host.replay(name, previous)
                        except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as error:
                            self.incidents.record("replay_failed", component=name, error=error)
                            improved = False
                        if improved:
                            self.restore(state, name, "previous fetcher passes the failed request")
                        else:
                            self.incidents.record("replay_no_improvement", component=name, context={"replay_id": health.get("replay_id")})
                continue
            record["failures"] = record.get("failures", 0) + 1
            if record["failures"] < 3:
                continue
            report_failure(state, name, record["active"], "runtime_unready", self.clock())
            self.save(state)
            self.incidents.record("component_unready", component=name, context={"release": record["active"], "health": health})
            try:
                self.host.stack(name)
            except (OSError, subprocess.SubprocessError):
                pass
            if record.get("restarts", 0) == 0:
                record.update(restarts=1, failures=0, trial_at=self.clock(), observed_process_restarts=0)
                self.save(state)
                self.host.restart(name)
            elif not self.restore(state, name, "component failed after one recovery restart"):
                record["failures"] = 0
        self.save(state)

    def prepare(self, archive, component, revision):
        target = self.release(component, revision)
        if (target / ".prepared").exists():
            return target
        if target.exists():
            if target.is_symlink() or self.link(component).resolve() == target or target.resolve().parent != target.parent.resolve():
                raise RuntimeError("incomplete release is active or has an invalid path")
            shutil.rmtree(target)
        target.mkdir(parents=True)
        with tarfile.open(archive, "r:gz") as source:
            for member in source.getmembers():
                destination = (target / member.name).resolve()
                if not destination.is_relative_to(target) or not member.isfile():
                    raise ValueError("component archive contains an invalid file")
            source.extractall(target, filter="data")
        manifest = read(target / "release-manifest.json")
        if manifest.get("release") != revision or manifest.get("component") != component:
            raise ValueError("component manifest identity does not match the deployment")
        for name, digest in manifest["files"].items():
            path = (target / name).resolve()
            if not path.is_relative_to(target) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("component source checksum failed")
        environment_id = hashlib.sha256((target / "requirements.txt").read_bytes() + (target / "requirements-backend.txt").read_bytes()
                                        + sys.version.encode()).hexdigest()
        environment = self.home / "backend-environments" / environment_id
        if not (environment / ".ready").exists():
            if environment.exists():
                active = any((self.link(name) / ".venv").resolve() == environment for name in COMPONENTS)
                if active or environment.is_symlink() or environment.resolve().parent != (self.home / "backend-environments").resolve():
                    raise RuntimeError("incomplete dependency environment is active or has an invalid path")
                shutil.rmtree(environment)
            self.host.command([sys.executable, "-m", "venv", str(environment)], timeout=60)
            self.host.command([str(environment / "bin/python"), "-m", "pip", "install", "-r", str(target / "requirements-backend.txt")], timeout=600)
            (environment / ".ready").touch()
        switch(target / ".venv", environment)
        self.host.command([str(target / ".venv/bin/python"), "-m", "compileall", "-q",
                           *(name for name in ("sports_ticker", "ticker_core", "backend_ops") if (target / name).exists())], cwd=target)
        script = "from sports_ticker.asgi import create_asgi_application" if component == "core" else (
            "from sports_ticker.providers.factory import create_provider; "
            f"create_provider({component!r}, database_path={str(self.home / 'ticker_data/ticker-v2.sqlite3')!r})")
        script = f"from dotenv import load_dotenv; load_dotenv({str(self.home / '.env')!r}); " + script
        self.host.command([str(target / ".venv/bin/python"), "-c", script], cwd=target)
        (target / ".prepared").touch()
        return target

    def bootstrap(self):
        """Freeze the verified readiness release before replacing the flat service."""
        if self.state_path.exists():
            return read(self.state_path)
        revision = (self.home / "RELEASE_SHA").read_text().strip()
        health = self.host.probe("core", self.home)
        if health.get("release") != revision or not health.get("runtime", {}).get("ready"):
            raise RuntimeError("the migration baseline did not pass readiness")
        state = {"schema_version": 1, "components": {}, "pending": None, "processed_revision": revision}
        for name in COMPONENTS:
            target = self.release(name, revision)
            target.mkdir(parents=True, exist_ok=True)
            for package in ("sports_ticker", "ticker_core", "backend_ops"):
                if not (target / package).exists():
                    shutil.copytree(self.home / package, target / package, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            for filename in ("requirements.txt", "requirements-backend.txt", "VERSION", "RELEASE_SHA"):
                shutil.copy2(self.home / filename, target / filename)
            environment = self.home / "backend-environments/baseline"
            if not (environment / "bin/python").exists():
                self.host.command([sys.executable, "-m", "venv", "--system-site-packages", str(environment)])
            switch(target / ".venv", environment)
            from .worker_contract import contract_id
            manifest = {"release": revision, "component": name, "contract": contract_id(target), "files": {}}
            atomic_json(target / "release-manifest.json", manifest)
            (target / ".prepared").touch()
            switch(self.link(name), target)
            state["components"][name] = {"active": revision, "previous": None, "quarantined": [], "failures": 0, "trial_at": self.clock()}
        self.remember_contract(state)
        self.save(state)
        return state

    def install_units(self, source):
        for name in ("ticker.service", "ticker-fetcher@.service", "ticker-backend-guard.service", "ticker-backend-guard.timer"):
            self.host.command(["sudo", "cp", str(source / name), "/etc/systemd/system/" + name])
        self.host.command(["sudo", "systemctl", "daemon-reload"])
        self.host.command(["sudo", "systemctl", "enable", "ticker-backend-guard.timer"])
        for name in PROVIDERS:
            self.host.command(["sudo", "systemctl", "enable", self.host.unit(name)])

    def retain(self, state):
        """Keep active releases, rollback targets, and three recent releases per component."""
        for name, record in state["components"].items():
            directory = self.link(name).parent / "releases"
            releases = sorted((path for path in directory.iterdir() if re.fullmatch("[0-9a-f]{40}", path.name)),
                              key=lambda path: path.stat().st_mtime, reverse=True)
            retained = {record["active"], record.get("previous"), *(path.name for path in releases[:3])}
            retained.update(cohort.get(name) for cohort in state.get("contract_baselines", {}).values())
            for path in releases:
                if path.name not in retained and path.resolve().parent == directory.resolve() and not path.is_symlink():
                    shutil.rmtree(path)

    def deploy(self, staging):
        plan = read(staging / "plan.json")
        revision, selected = plan["release"], plan["components"]
        if any(name not in COMPONENTS for name in selected):
            raise ValueError("deployment plan has invalid components")
        if not selected:
            state = read(self.state_path)
            if not state:
                raise ValueError("initial migration requires component releases")
            state["processed_revision"] = revision
            self.save(state)
            return state
        state = self.bootstrap()
        if state.get("pending"):
            self.rollback_pending(state, RuntimeError("previous deployment was interrupted"))
        prepared = {name: self.prepare(staging / (name + ".tar.gz"), name, revision) for name in selected}
        contracts = {read(prepared.get(name, self.release(name, state["components"][name]["active"])) / "release-manifest.json")["contract"] for name in COMPONENTS}
        if len(contracts) != 1:
            raise ValueError("shared contract change requires all dependent components")
        if "core" in selected:
            database = self.home / "ticker_data/ticker-v2.sqlite3"
            if database.exists():
                backups = self.control / "database-backups"
                backups.mkdir(parents=True, exist_ok=True)
                backup = backups / (revision + ".sqlite3")
                with sqlite3.connect(database) as source, sqlite3.connect(backup) as destination:
                    source.backup(destination)
                backup.chmod(0o600)
                for stale in sorted(backups.glob("*.sqlite3"), key=lambda path: path.stat().st_mtime)[:-3]:
                    stale.unlink()
        toolkit = self.home / "backend-control/versions" / revision
        if not toolkit.exists():
            toolkit.mkdir(parents=True)
            source = next(iter(prepared.values()))
            shutil.copytree(source / "backend_ops", toolkit / "backend_ops", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            shutil.copy2(source / "RELEASE_SHA", toolkit / "RELEASE_SHA")
            # The guard reads release contracts from manifests. It does not import application code.
        toolkit_link = self.home / "backend-control/current"
        if not toolkit_link.exists():
            switch(toolkit_link, toolkit)
        self.install_units(staging)
        for name in PROVIDERS:
            if not (self.home / "ticker_data/backend_sockets" / (name + ".sock")).exists():
                self.host.restart(name)
        versions = {name: revision for name in selected if state["components"][name]["active"] != revision}
        try:
            if versions:
                self.activate(state, versions, revision)
        finally:
            self.host.command(["sudo", "systemctl", "start", "ticker-backend-guard.timer"])
        switch(toolkit_link, toolkit)
        self.retain(state)
        return state


def main():
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
        elif manager.state_path.exists():
            state = read(manager.state_path)
            previous_rollback = state.get("last_rollback")
            manager.guard(state)
            if previous_rollback != state.get("last_rollback"):
                from .diagnostics import bundle
                bundle(manager.home, manager.control / "latest-report.zip")


if __name__ == "__main__":
    main()
