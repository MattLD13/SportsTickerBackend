"""Queue safe runtime facts until GitHub confirms their receipt."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, fields
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import tempfile
from uuid import uuid4

from .components import COMPONENTS
CATEGORIES = frozenset(("startup_failed", "deployment_interrupted", "runtime_unready", "crash_loop",
                        "rollback_started", "rolled_back", "recovered"))
SCOPES = frozenset(("production", "verification"))


@dataclass(frozen=True)
class RuntimeReport:
    id: str
    site: str
    sequence: int
    component: str
    release: str
    state: str
    category: str
    restored_release: str | None
    scope: str
    observed_at: float

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict) or set(value) != {item.name for item in fields(cls)}:
            raise ValueError("runtime report fields do not match the contract")
        report = cls(**value)
        if report.component not in COMPONENTS or report.state not in ("failure", "success") or report.category not in CATEGORIES or report.scope not in SCOPES:
            raise ValueError("runtime report contains an unknown lifecycle value")
        for name, length in (("id", 64), ("site", 32), ("release", 40)):
            if not isinstance(value[name], str) or not re.fullmatch(f"[0-9a-f]{{{length}}}", value[name]):
                raise ValueError("runtime report identity is invalid")
        if report.restored_release is not None and (not isinstance(report.restored_release, str) or not re.fullmatch("[0-9a-f]{40}", report.restored_release)):
            raise ValueError("runtime recovery identity is invalid")
        if type(report.sequence) is not int or report.sequence < 1:
            raise ValueError("runtime report sequence is invalid")
        if type(report.observed_at) not in (int, float) or not math.isfinite(report.observed_at) or report.observed_at < 0:
            raise ValueError("runtime report time is invalid")
        if (report.category == "recovered") != (report.state == "success"):
            raise ValueError("runtime report outcome does not match its lifecycle")
        return report


def _append(state, problem, component, release, outcome, category, restored, now, scope):
    phase = ":".join((outcome, category, release, restored or ""))
    if phase in problem.setdefault("emitted", []):
        return
    site = state.setdefault("report_site", uuid4().hex)
    sequence = state.get("report_sequence", 0) + 1
    identifier = hashlib.sha256(f"{site}:{problem['episode']}:{phase}".encode()).hexdigest()
    report = RuntimeReport(identifier, site, sequence, component, release, outcome, category, restored, scope, float(now))
    RuntimeReport.parse(asdict(report))
    state.setdefault("report_events", []).append(asdict(report))
    state["report_sequence"] = sequence
    problem["emitted"].append(phase)


def failure(state, component, release, category, now, *, restored=None, scope="production"):
    """Retain one failure episode and each distinct recovery decision."""
    record = state["components"][component]
    problem = record.get("report_problem")
    if problem is None or problem["release"] != release:
        problem = {"release": release, "episode": uuid4().hex, "emitted": []}
        record["report_problem"] = problem
    _append(state, problem, component, release, "failure", category, restored, now, scope)


def recovered(state, component, now, *, scope="production"):
    """Clear a failure only after the active version passes local readiness."""
    record = state["components"][component]
    problem = record.get("report_problem")
    if problem is None:
        return
    _append(state, problem, component, record["active"], "success", "recovered", None, now, scope)
    del record["report_problem"]


def export(state, *, limit=100):
    events = [asdict(RuntimeReport.parse(value)) for value in state.get("report_events", [])[:limit]]
    return {"schema_version": 1, "busy": False, "reports": events}


def acknowledge(state, value):
    if not isinstance(value, dict) or set(value) != {"schema_version", "report_ids"} or value["schema_version"] != 1:
        raise ValueError("runtime acknowledgement does not match the contract")
    identities = value["report_ids"]
    if not isinstance(identities, list) or len(identities) > 100 or any(not isinstance(item, str) or not re.fullmatch("[0-9a-f]{64}", item) for item in identities):
        raise ValueError("runtime acknowledgement identities are invalid")
    confirmed = set(identities)
    old = state.get("report_events", [])
    state["report_events"] = [event for event in old if event["id"] not in confirmed]
    return len(old) - len(state["report_events"])


def main():
    from .manager import Manager, read
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("export", "ack", "seed-test"))
    parser.add_argument("--home", type=Path, default=Path("/home/ubuntu"))
    parser.add_argument("--release")
    args = parser.parse_args()
    manager = Manager(args.home)
    with manager.locked(wait=False) as acquired:
        if not acquired:
            if args.operation == "export":
                print(json.dumps({"schema_version": 1, "busy": True, "reports": []}))
                return
            raise RuntimeError("deployment is active. Reports remain queued")
        state = read(manager.state_path)
        if args.operation == "seed-test":
            if manager.home.parent != Path(tempfile.gettempdir()).resolve() or not re.fullmatch("ticker-reporting-test-[0-9]+", manager.home.name):
                raise ValueError("verification requires an isolated temporary home")
            if state:
                raise ValueError("verification home already contains state")
            state = {"components": {"core": {"active": args.release}}}
            failure(state, "core", args.release, "runtime_unready", 1, scope="verification")
            recovered(state, "core", 2, scope="verification")
            manager.save(state)
        elif args.operation == "export":
            print(json.dumps(export(state), separators=(",", ":")))
        else:
            body = sys.stdin.buffer.read(65537)
            if len(body) > 65536:
                raise ValueError("runtime acknowledgement is too large")
            removed = acknowledge(state, json.loads(body))
            state["report_last_ack_at"] = manager.clock()
            manager.save(state)
            print(f"Acknowledged {removed} runtime reports")


if __name__ == "__main__":
    main()
