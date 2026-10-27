"""Measure context discovery with held-out cases and explicit live execution."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ai.workspaces.manage import WorkspaceError, git, manifest_read, resolve, safe_path
from ai.workspaces.start import edit_owners, inventory

CASES = ROOT / "ai/fixtures/context-cases.json"
TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
EVALUATION_PATHS = frozenset(("ai/fixtures/context-cases.json", "ai/benchmarks/context_discovery.py",
                              "ai/tests/test_context_benchmark.py",
                              "ai/research/2026-10-19-progressive-agent-context.md",
                              "ai/research/agent-context-v5-evidence.json"))


class AttemptFailure(WorkspaceError):
    """Retain usage when a model attempt fails."""

    def __init__(self, message: str, usage: dict | None = None):
        super().__init__(message)
        self.usage = usage


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def load_cases(path: Path, manifest: dict, tracked: dict[str, str]) -> list[dict]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("version") != 1 or not isinstance(document.get("cases"), list):
        raise WorkspaceError("Unsupported context evaluation cases")
    cases = document["cases"]
    seen = set()
    for case in cases:
        if case["id"] in seen or not case["task"].strip():
            raise WorkspaceError("Context cases need unique IDs and task text")
        seen.add(case["id"])
        expected = case["expected"]
        for path_value in expected["paths"]:
            safe_path(path_value)
            if path_value not in tracked:
                raise WorkspaceError("Expected context path is absent: " + path_value)
        if set(expected["components"]) - set(manifest["components"]):
            raise WorkspaceError("Expected context component is absent")
        if set(expected["checks"]) - set(manifest["checks"]):
            raise WorkspaceError("Expected context check is absent")
        if expected["shared_change"] is not None and type(expected["shared_change"]) is not bool:
            raise WorkspaceError("Expected shared_change must be boolean or null")
    if not {"narrow-known", "unfamiliar-component", "shared-contract"} <= {case["task_class"] for case in cases}:
        raise WorkspaceError("Context cases must cover all three task classes")
    return cases


def usage_counts(usage: dict | None) -> dict:
    """Input includes cache. Output includes reasoning. Subsets do not add to totals."""
    usage = usage or {}
    result = {key: value if type(value := usage.get(key)) is int and value >= 0 else None for key in TOKEN_FIELDS}
    details = usage.get("output_tokens_details") or usage.get("completion_tokens_details") or {}
    if result["reasoning_output_tokens"] is None:
        value = details.get("reasoning_tokens", usage.get("reasoning_tokens"))
        result["reasoning_output_tokens"] = value if type(value) is int and value >= 0 else None
    if result["cached_input_tokens"] is None:
        value = (usage.get("input_tokens_details") or {}).get("cached_tokens")
        result["cached_input_tokens"] = value if type(value) is int and value >= 0 else None
    complete = result["input_tokens"] is not None and result["output_tokens"] is not None
    result["total_tokens"] = result["input_tokens"] + result["output_tokens"] if complete else None
    result["uncached_input_plus_output_tokens"] = (
        result["total_tokens"] - result["cached_input_tokens"]
        if complete and result["cached_input_tokens"] is not None else None
    )
    result["complete"] = complete
    return result


def observed_runner(runner, instructions: str, attempts: list[dict], clock=time.perf_counter, request_text=None,
                    on_attempt=None):
    """Record every attempt without adding evaluation expectations to its prompt."""
    def call(prompt, specification, timeout):
        serialized = json.dumps(prompt)
        request = request_text(prompt) if request_text else instructions + "\n" + serialized
        inspections = prompt.get("inspection_results", [])
        sources = [row for row in inspections if isinstance(row, dict) and isinstance(row.get("source"), str)]
        attempt = {
            "request_bytes": len(request.encode()),
            "prompt_bytes": len(request.encode()) - len((instructions + "\n").encode()),
            "schema_bytes": len(json.dumps(specification).encode()),
            "request_sha256": hashlib.sha256(request.encode()).hexdigest(),
            "source_excerpt_bytes": sum(len(row["source"].encode()) for row in sources),
            "source_excerpt_paths": sorted({row["path"] for row in sources}),
            "source_excerpts": [{"path": row["path"], "symbol": row.get("symbol"),
                                 "start_line": row.get("start_line"), "bytes": len(row["source"].encode()),
                                 "sha256": hashlib.sha256(row["source"].encode()).hexdigest()} for row in sources],
            "discovery_result_bytes": len(json.dumps(prompt.get("discovery_results", [])).encode()),
            "indexed_paths": len(prompt.get("files", [])),
            "status": "running",
            "usage": usage_counts(None),
        }
        started = clock()
        attempts.append(attempt)
        if on_attempt is not None:
            on_attempt()
        try:
            result, usage = runner(prompt, specification, timeout)
            attempt["status"] = "succeeded"
            attempt["usage"] = usage_counts(usage)
            return result, usage
        except Exception as error:
            attempt["status"] = "failed"
            evidence = getattr(error, "evidence", {}) or {}
            attempt["usage"] = usage_counts(getattr(error, "usage", None) or evidence.get("usage"))
            if evidence.get("usage_complete") is False:
                attempt["usage"]["complete"] = False
            attempt["error"] = str(error)
            raise
        finally:
            attempt["seconds"] = round(clock() - started, 6)
            if on_attempt is not None:
                on_attempt()
    return call


def total_usage(attempts: list[dict]) -> dict:
    result = {}
    for field in (*TOKEN_FIELDS, "total_tokens", "uncached_input_plus_output_tokens"):
        measured = [row["usage"][field] for row in attempts if row["usage"][field] is not None]
        result[field] = sum(measured) if measured else None
    result["complete"] = bool(attempts) and all(row["usage"]["complete"] for row in attempts)
    result["unknown_usage_attempts"] = sum(not row["usage"]["complete"] for row in attempts)
    result["is_lower_bound"] = not result["complete"]
    return result


def coverage(expected: list[str], actual: set[str]) -> dict:
    found = sorted(set(expected) & actual)
    return {"required": sorted(expected), "found": found, "missing": sorted(set(expected) - actual),
            "fraction": len(found) / len(expected) if expected else 1.0}


def score_result(result: dict, expected: dict, manifest: dict, tracked: dict) -> dict:
    """Score explicit entry points separately from broad materialized build scope."""
    paths = {row["path"] for row in result["context"]} | set(result["edit_targets"])
    forced = edit_owners(manifest, result["edit_targets"], result["shared_change"])
    for name, component in manifest["components"].items():
        if set(component.get("checks", [])) & set(result["checks"]):
            forced.add(name)
    components = set(forced)
    for name in result["slices"]:
        components.update(manifest["slices"][name])
    scope = resolve(manifest, sorted(components), tracked)
    context_paths = {path for path in scope["context_files"] if Path(path).name == "AGENTS.md"}
    if set(manifest["shared_consumers"]) <= forced:
        for name in manifest["shared_owners"] + manifest["shared_consumers"]:
            context_paths.update(manifest["components"][name].get("context", []))
    context_paths.update(paths)
    for path in paths:
        for parent in Path(path).parents:
            instruction = (parent / "AGENTS.md").as_posix()
            if instruction in tracked:
                context_paths.add(instruction)
    shared = expected["shared_change"] is None or result["shared_change"] == expected["shared_change"]
    scores = {"entry_points": coverage(expected["paths"], paths),
              "effective_entry_points": coverage(expected["paths"], context_paths),
              "components": coverage(expected["components"], set(scope["components"])),
              "checks": coverage(expected["checks"], set(scope["checks"])),
              "shared_change_matches": shared,
              "selected_entry_point_count": len(paths),
              "scope_context_file_count": len(context_paths),
              "scope_build_file_count": len(set(scope["build_files"]) | paths),
              "scope_components": scope["components"]}
    scores["complete"] = shared and all(scores[key]["fraction"] == 1 for key in ("entry_points", "components", "checks"))
    return scores


def paired_summary(runs: list[dict], arms: list[str]) -> dict:
    pairs = {}
    for run in runs:
        pairs.setdefault((run["case_id"], run["repeat"]), {})[run["arm"]] = run
    comparable = [pair for pair in pairs.values() if all(
        arm in pair and pair[arm]["status"] == "succeeded" and pair[arm]["usage"]["complete"] for arm in arms)]
    totals = {}
    for arm in arms:
        selected = [pair[arm] for pair in comparable]
        totals[arm] = {"seconds": round(sum(row["seconds"] for row in selected), 6),
                       "request_bytes": sum(row["request_bytes"] for row in selected),
                       "total_tokens": sum(row["usage"]["total_tokens"] for row in selected),
                       "complete_context_cases": sum(row["coverage"]["complete"] for row in selected),
                       "mean_entry_point_coverage": (sum(row["coverage"]["entry_points"]["fraction"] for row in selected)
                                                     / len(selected) if selected else None)}
    return {"comparable_pairs": len(comparable), "excluded_pairs": len(pairs) - len(comparable), "arms": totals}


def evaluate(root: Path, manifest: dict, tracked: dict, cases: list[dict], *, planners: dict,
             runners: dict, instructions: dict | None = None, request_texts: dict | None = None,
             repeats: int = 1, clock=time.perf_counter, excluded_paths=EVALUATION_PATHS, checkpoint=None) -> dict:
    """Run injected planners and runners. This function never selects a live runner."""
    if set(planners) != set(runners) or len(planners) != 2 or repeats < 1:
        raise WorkspaceError("Supply two planner and runner arms and a positive repeat count")
    arms = list(planners)
    planner_tracked = {path: mode for path, mode in tracked.items() if path not in excluded_paths}
    runs = []
    for repeat in range(repeats):
        for case_index, case in enumerate(cases):
            order = arms if (repeat + case_index) % 2 == 0 else list(reversed(arms))
            for arm in order:
                attempts = []
                started = clock()
                row = {"case_id": case["id"], "task_class": case["task_class"], "repeat": repeat, "arm": arm,
                       "status": "failed", "attempts": attempts}
                def save_progress():
                    if checkpoint is not None:
                        current = {**row, "status": "running", "usage": total_usage(attempts)}
                        checkpoint({"version": 1, "measurement": "planning-only", "status": "running",
                                    "runs": deepcopy(runs + [current])})
                observed = observed_runner(runners[arm], (instructions or {}).get(arm, ""), attempts, clock,
                                           (request_texts or {}).get(arm), on_attempt=save_progress)
                try:
                    result = planners[arm](root, case["task"], deepcopy(manifest), dict(planner_tracked), runner=observed)
                    row["coverage"] = score_result(result, case["expected"], manifest, tracked)
                    row["result"] = result
                    row["status"] = "succeeded"
                except Exception as error:
                    row["error"] = str(error)
                row["seconds"] = round(clock() - started, 6)
                row["usage"] = total_usage(attempts)
                row["request_bytes"] = sum(attempt["request_bytes"] for attempt in attempts)
                row["initial_request_bytes"] = attempts[0]["request_bytes"] if attempts else None
                row["max_request_bytes"] = max((attempt["request_bytes"] for attempt in attempts), default=None)
                row["source_excerpt_bytes"] = sum(attempt["source_excerpt_bytes"] for attempt in attempts)
                row["source_excerpt_paths"] = sorted({path for attempt in attempts for path in attempt["source_excerpt_paths"]})
                runs.append(row)
                if checkpoint is not None:
                    checkpoint({"version": 1, "measurement": "planning-only", "status": "running", "runs": deepcopy(runs)})
    all_runs = {arm: {"successful_runs": sum(row["status"] == "succeeded" for row in runs if row["arm"] == arm),
                      "failed_runs": sum(row["status"] == "failed" for row in runs if row["arm"] == arm),
                      "usage": total_usage([attempt for row in runs if row["arm"] == arm for attempt in row["attempts"]])}
                for arm in arms}
    return {"version": 1, "measurement": "planning-only", "cases_sha256": digest(cases),
            "manifest_sha256": digest(manifest), "excluded_evaluation_paths": sorted(excluded_paths),
            "runs": runs, "paired": paired_summary(runs, arms),
            "all_runs": all_runs,
            "limits": ["Planning coverage does not measure coding correctness or coding token cost.",
                       "Input includes cached input. Output includes reasoning. Subsets do not add to totals.",
                       "Unknown attempt usage makes measured usage a lower bound.",
                       "Source excerpt bytes count repeated text in each request.",
                       "Request bytes measure CLI stdin. Schema bytes are separate."]}


def load_planner(path: Path):
    specification = importlib.util.spec_from_file_location("context_evaluation_baseline", path)
    if specification is None or specification.loader is None:
        raise WorkspaceError("Cannot load the frozen baseline planner")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def write_report(path: Path, report: dict) -> None:
    """Keep attempt evidence across interrupted evaluations."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--live", action="store_true", help="Explicitly enable model calls")
    parser.add_argument("--baseline-planner", type=Path, help="Frozen baseline Python file in ignored local evidence")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    if args.baseline_planner and not args.live:
        parser.error("--baseline-planner requires --live")
    if args.live and not args.baseline_planner:
        parser.error("--live requires a frozen --baseline-planner")
    if args.live and not args.output:
        parser.error("--live requires --output to retain attempt evidence")
    manifest = manifest_read(ROOT / "ai/workspaces.json")
    revision = git(ROOT, "rev-parse", "HEAD").strip()
    tracked = inventory(ROOT, manifest, revision)
    cases = load_cases(args.cases, manifest, tracked)
    if args.live:
        from ai.workspaces import planner
        baseline = load_planner(args.baseline_planner)
        implementation_paths = ("ai/workspaces/planner.py", "ai/workspaces/discovery.py", "ai/workspaces/start.py",
                                "ai/benchmarks/context_discovery.py", "ai/workspaces.json")
        hashes = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in implementation_paths}
        def checkpoint(report):
            report.update(revision=revision, implementation_sha256=hashes)
            write_report(args.output.with_suffix(".partial.json"), report)
        excluded_paths = set(EVALUATION_PATHS)
        if args.cases.resolve().is_relative_to(ROOT.resolve()):
            excluded_paths.add(args.cases.resolve().relative_to(ROOT.resolve()).as_posix())
        report = evaluate(ROOT, manifest, tracked, cases,
                          planners={"baseline": baseline.plan_task, "progressive": planner.plan_task},
                          runners={"baseline": baseline.run_codex, "progressive": planner.run_codex},
                          instructions={"baseline": baseline.INSTRUCTIONS, "progressive": planner.INSTRUCTIONS},
                          request_texts={"progressive": planner.request_text},
                          repeats=args.repeat, excluded_paths=excluded_paths, checkpoint=checkpoint)
        report.update(revision=revision, baseline_sha256=hashlib.sha256(args.baseline_planner.read_bytes()).hexdigest(),
                      progressive_sha256=hashlib.sha256(Path(planner.__file__).read_bytes()).hexdigest(),
                      implementation_sha256=hashes, model=planner.MODEL, mode="live")
    else:
        report = {"version": 1, "mode": "offline-validation", "model_calls": 0, "revision": revision,
                  "cases_sha256": digest(cases), "manifest_sha256": digest(manifest),
                  "cases": [{"id": case["id"], "task_class": case["task_class"]} for case in cases],
                  "limits": ["Offline validation checks evaluation inputs. It does not measure model performance."]}
    if args.output:
        write_report(args.output, report)
    print(json.dumps(report if not args.live else {"mode": "live", "paired": report["paired"],
                                                "output": str(args.output) if args.output else None}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
