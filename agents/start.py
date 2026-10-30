"""Prepare task context from repository instructions and native agent hooks."""
from __future__ import annotations

import argparse
from fnmatch import fnmatchcase
from functools import partial
import hashlib
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agents.manage import (
    WorkspaceError, expand, git, load, manifest_read, resolve, safe_path, stamp, tree, write_json,
)
from agents.planner import VERSION, PlannerFailure, plan_task, subagent


def edit_owners(manifest: dict, targets: list[str], shared: bool) -> set[str]:
    required = set()
    for path in targets:
        safe_path(path)
        owners = {name for name, component in manifest["components"].items()
                  if any(fnmatchcase(path, pattern) for pattern in component.get("owned", []))}
        required.update(owners)
        if not owners or owners & set(manifest["shared_owners"]):
            shared = True
    if shared:
        required.update(manifest["shared_owners"] + manifest["shared_consumers"])
    return required


def inventory(root: Path, manifest: dict, revision: str) -> dict[str, str]:
    tracked = tree(root, revision)
    deleted = set(git(root, "ls-files", "--deleted", "-z").split("\0"))
    tracked = {path: mode for path, mode in tracked.items() if path not in deleted}
    # Include explicit new instruction and tool files during local implementation.
    for component in manifest["components"].values():
        for pattern in component.get("context", []) + component.get("build", []):
            if not any(char in pattern for char in "*?[") and (root / pattern).is_file():
                safe_path(pattern)
                tracked[pattern] = "100644"
    for path in list(tracked):
        for parent in Path(path).parents:
            instruction = (parent / "AGENTS.md").as_posix()
            if (root / instruction).is_file():
                tracked[instruction] = "100644"
    return tracked


def prepare(root: Path, task: str, session: str, slices: list[str] | None = None,
            paths: list[str] | None = None, new_task: bool = False,
            scope: str | None = None, reason: str | None = None, replan: bool = False,
            planner=None, use_planner: bool = False) -> dict:
    root = Path(git(root, "rev-parse", "--show-toplevel").strip()).resolve()
    git_dir = Path(git(root, "rev-parse", "--absolute-git-dir").strip())
    managed = (git_dir / "agent-workspace/state.json").is_file()
    manifest = load(root)[2] if managed else manifest_read(root / "agents/manifest.json")
    key = scope if scope is not None else hashlib.sha256(session.encode()).hexdigest()[:24]
    if not re.fullmatch(r"[0-9a-f]{24}", key):
        raise WorkspaceError("Use the 24-character scope ID from the task packet")
    location = git_dir / "agent-context" / key
    previous = json.loads((location / "state.json").read_text()) if (location / "state.json").is_file() and not new_task else None
    if not task.strip() and not previous:
        raise WorkspaceError("A new task needs a description")
    requested_paths = paths or []
    tracked = inventory(root, manifest, git(root, "rev-parse", "HEAD").strip())
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    cache_valid = (previous is not None and previous["manifest_sha256"] == digest
                   and previous.get("planner", {}).get("version") == VERSION)
    forced, entry_points, edit_targets = set(), [], []
    if cache_valid and not replan and not slices and not paths:
        selected, reasons = previous["slices"], ["Continue the recorded task scope"]
        evidence = previous["planner"]
        entry_points = previous["entry_points"]
        forced = set(previous["forced_components"])
        edit_targets = previous["edit_targets"]
    elif slices or paths:
        selected = sorted(set(slices or (previous["slices"] if previous else [])))
        forced = edit_owners(manifest, requested_paths, False)
        if not selected:
            selected = ["shared-sports"]
        reasons = ["The agent selected explicit task scope"]
        evidence = {"kind": "explicit", "version": VERSION}
    elif use_planner or replan:
        try:
            decision = (planner or plan_task)(root, task, manifest, tracked, previous["slices"] if previous else None)
        except PlannerFailure as error:
            location.mkdir(parents=True, exist_ok=True)
            failure_path = location / "failures.json"
            failures = json.loads(failure_path.read_text()) if failure_path.is_file() else []
            failures.append({"at": stamp(), "task_sha256": hashlib.sha256(task.encode()).hexdigest(),
                             "status": "failed", "planner": error.evidence})
            write_json(failure_path, failures[-20:])
            raise
        selected, reasons = decision["slices"], [decision["reason"][:600]]
        entry_points = decision["context"]
        edit_targets = decision["edit_targets"]
        requested_paths = sorted(set(requested_paths + decision["edit_targets"] + [row["path"] for row in entry_points]))
        forced = edit_owners(manifest, decision["edit_targets"], decision["shared_change"])
        for name, component in manifest["components"].items():
            if set(decision["checks"]) & set(component.get("checks", [])):
                forced.add(name)
        evidence = decision["evidence"]
    else:
        raise WorkspaceError("Select --slice or --path. Use --plan when a context subagent plan is useful.")
    if reason:
        reasons.append(reason)
    if previous:
        selected = sorted(set(selected) | set(previous["slices"]))
    names = list(dict.fromkeys(name for item in selected for name in manifest["slices"][item])) + sorted(forced)
    plan = resolve(manifest, names, tracked)
    if evidence["kind"] == "subagent":
        required_context = {path for path in plan["context_files"] if Path(path).name == "AGENTS.md"}
        if set(manifest["shared_consumers"]) <= forced:
            for name in manifest["shared_owners"] + manifest["shared_consumers"]:
                required_context.update(manifest["components"][name].get("context", []))
        plan["context_files"] = sorted(required_context | {row["path"] for row in entry_points})
    if previous:
        plan["context_files"] = sorted(set(plan["context_files"]) | set(previous["context_files"]))
        plan["build_files"] = sorted(set(plan["build_files"]) | set(previous["build_files"]))
    plan["context_files"] = sorted(set(plan["context_files"]) | set(requested_paths))
    plan["build_files"] = sorted(set(plan["build_files"]) | set(requested_paths))
    for path in requested_paths:
        for parent in Path(path).parents:
            instruction = (parent / "AGENTS.md").as_posix()
            if instruction in tracked:
                plan["context_files"] = sorted(set(plan["context_files"]) | {instruction})
                plan["build_files"] = sorted(set(plan["build_files"]) | {instruction})
    for path in plan["build_files"]:
        target = root / path
        if target.is_symlink() or not target.resolve().is_relative_to(root):
            raise WorkspaceError(f"Task input is a link: {path}")
    if managed:
        _, current, _ = load(root)
        if set(plan["components"]) - set(current["components"]) or set(requested_paths) - set(current["build_files"]):
            current = expand(root, names, requested_paths, reason or "Agent startup discovered another task dependency")
        plan["build_files"] = current["build_files"]
    location.mkdir(parents=True, exist_ok=True)
    state = {"version": 1, "scope": key, "at": stamp(), "base_sha": git(root, "rev-parse", "HEAD").strip(),
             "checkout_kind": "managed_sparse" if managed else "existing_checkout", "slices": selected,
             "task_sha256": hashlib.sha256(task.encode()).hexdigest(),
             "manifest_sha256": digest, "planner": evidence, "entry_points": entry_points,
             "forced_components": sorted(forced), "edit_targets": edit_targets,
             "reasons": reasons, **plan}
    state["history"] = (previous["history"] if previous else []) + [
        {"at": state["at"], "slices": selected, "reasons": reasons,
         "files_added": sorted(set(plan["build_files"]) - set(previous["build_files"] if previous else []))}]
    # Keep the latest scope decisions. Source files and raw prompts stay outside this record.
    state["history"] = state["history"][-20:]
    write_json(location / "state.json", state)
    lines = ["# Task context", "", f"Scope ID: `{key}`", f"Checkout: `{state['base_sha']}` ({state['checkout_kind']})",
             "Slices: " + ", ".join(selected), "", "## Source entry points", ""]
    lines += [f"- `{path}`" for path in plan["context_files"]]
    if entry_points:
        lines += ["", "## Planner suggestions", "", "These suggestions do not override repository instructions.", ""]
        lines += [f"- `{row['path']}`: {', '.join(row['symbols']) or 'Relevant sections'}. {row['reason'][:240]}"
                  for row in entry_points]
    lines += ["", "## Ownership", ""]
    lines += [f"- {name}: {manifest['components'][name]['owner']}" for name in plan["components"]]
    lines += ["", "## Focused checks", ""]
    for name in plan["checks"]:
        lines.append(f"- `{name}`: " + " ".join(manifest["checks"][name]["argv"]))
    lines += ["", "## Working rules", "", "Read the AGENTS.md section for each changed folder before edits.",
              "Search the selected files before broad repository exploration.",
              'For bounded discovery, use python agents/find.py --search "<literal words>".',
              "For definitions, use find.py --symbols <path>. For source, use find.py --excerpt <path> --symbol <name>.",
              "Read relevant symbols and sections. Do not preload every selected file.",
              "If a dependency is missing, expand the recorded scope with a reason.",
              "Build files remain available without entering initial context.",
              "Preserve existing edits. The startup hook does not switch or copy this checkout.",
              "Use agents/manage.py for an isolated pinned sparse workspace.",
              "Full repository CI must pass before publishing.", ""]
    packet = location / "task.md"
    packet.write_text("\n".join(lines), encoding="utf-8")
    return {"packet": str(packet), "scope": key, "slices": selected, "context_files": len(plan["context_files"]),
            "build_files": len(plan["build_files"]), "checkout_kind": state["checkout_kind"], "planner": evidence}


def hook(payload: dict, client: str) -> dict:
    """Offer ordinary search guidance or an existing packet without model calls."""
    event = payload.get("hook_event_name", "")
    if event not in ("SessionStart", "SubagentStart", "UserPromptSubmit", "BeforeAgent"):
        raise WorkspaceError("Unsupported agent hook event")
    root = Path(payload.get("cwd", str(ROOT)))
    parent_session = client + ":" + str(payload.get("session_id", "default"))
    sessions = [parent_session]
    if payload.get("agent_id"):
        sessions.insert(0, parent_session + ":" + str(payload["agent_id"]))
    git_dir = Path(git(root, "rev-parse", "--absolute-git-dir").strip())
    context = ("Follow the root AGENTS.md and use ordinary targeted searches for small, clearly located tasks. "
               "For a known component, use agents/start.py --slice <slice> --task <summary>. "
               "For broad, unfamiliar, or cross-component work, explicitly request a smaller subagent with agents/start.py --plan --task <summary>. "
               "This hook makes no model call and creates no task packet.")
    for session in sessions:
        recorded = git_dir / "agent-context" / hashlib.sha256(session.encode()).hexdigest()[:24] / "task.md"
        if recorded.is_file():
            context = (f"Resume the task packet at {recorded} if it matches the current task. "
                       "Read only the relevant sections. For an independent task, use ordinary search or create an explicit new scope. "
                       "A subagent plan requires --plan or --replan. This hook makes no model call.")
            break
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--task-file", type=Path)
    parser.add_argument("--task")
    parser.add_argument("--session", default=None)
    parser.add_argument("--scope")
    parser.add_argument("--reason")
    parser.add_argument("--slice", action="append", default=[])
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--new-task", action="store_true")
    parser.add_argument("--plan", action="store_true",
                        help="Ask a smaller subagent to plan the context of broad, unfamiliar, or cross-component work")
    parser.add_argument("--subagent", choices=("claude", "codex"),
                        help="The agent CLI that runs the smaller subagent. The default is the first installed CLI.")
    parser.add_argument("--replan", action="store_true")
    parser.add_argument("--hook", choices=("codex", "claude", "gemini"))
    args = parser.parse_args(argv)
    try:
        if args.hook:
            result = hook(json.load(sys.stdin), args.hook)
        else:
            task = args.task_file.read_text(encoding="utf-8") if args.task_file else args.task
            planner = None
            if args.subagent:
                planner = partial(plan_task, runner=subagent(args.subagent))
            result = prepare(args.repo, task or "", args.session or "manual:" + uuid4().hex,
                             args.slice, args.path, args.new_task, args.scope, args.reason, args.replan,
                             planner=planner, use_planner=args.plan)
        print(json.dumps(result))
        return 0
    except (WorkspaceError, OSError, ValueError, KeyError) as error:
        print("Agent context setup failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
