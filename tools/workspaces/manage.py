"""Prepare pinned sparse Git workspaces and record task evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from fnmatch import fnmatchcase
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / ".github/agent-workspaces.json"
SHA = re.compile(r"[0-9a-f]{40}")
# These exclusions also apply to later expansions.
DENIED = (".git/*", ".env*", "*/.env*", "*.key", "*.pem", "*.ppk", "*.secret",
          ".ssh/*", ".claude/*", ".codex/*", ".gemini/*", ".oci/*", ".tmp/*", "ticker_data/*", "hardware/*",
          "previews/*", "caches/*", "*.log", ".spotify_token", "*credentials*.json",
          "stock_cache.json", "game_cache.json", "global_config.json", "*.sqlite*", "*.db",
          "mini/src/mini/platform/config.h")
PUBLIC_AGENT_CONFIGS = frozenset((".claude/settings.json", ".codex/hooks.json", ".gemini/settings.json"))


class WorkspaceError(RuntimeError):
    pass


def git(root: Path, *args: str, data: str | None = None) -> str:
    result = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=root,
                            input=data, text=True, capture_output=True, encoding="utf-8")
    if result.returncode:
        raise WorkspaceError(f"Git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def safe_path(path: str) -> str:
    parts = PurePosixPath(path).parts
    if (not parts or path != str(PurePosixPath(path)) or path.startswith(("/", "-")) or "\\" in path or ":" in path
            or any(part.lower() in ("..", ".git") or part.rstrip(". ") != part for part in parts)
            or any(ord(char) < 32 for char in path)
            or any(char in path for char in "*?[]!")):
        raise WorkspaceError(f"Unsafe path: {path}")
    if path not in PUBLIC_AGENT_CONFIGS and any(fnmatchcase(path.lower(), pattern.lower()) for pattern in DENIED):
        raise WorkspaceError(f"Excluded private or runtime path: {path}")
    return path


def supports_filter(remote: str) -> bool:
    environment = dict(os.environ, GIT_TRACE_PACKET="1", GIT_PROTOCOL="version=2")
    result = subprocess.run(["git", "-c", "protocol.version=2", "ls-remote", "--refs", remote],
                            env=environment, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise WorkspaceError("Cannot read the remote Git capabilities")
    return any("fetch=" in line and re.search(r"\bfilter\b", line) for line in result.stderr.splitlines())


def tree(root: Path, revision: str) -> dict[str, str]:
    result = {}
    for row in git(root, "ls-tree", "-r", "-z", revision).split("\0"):
        if row:
            metadata, path = row.split("\t", 1)
            result[path] = metadata.split()[0]
    return result


def matching(patterns: list[str], tracked: dict[str, str]) -> set[str]:
    result = set()
    for pattern in patterns:
        found = {path for path in tracked if fnmatchcase(path, pattern)}
        if not found:
            raise WorkspaceError(f"Manifest pattern has no files: {pattern}")
        result.update(found)
    return result


def resolve(manifest: dict, names: list[str], tracked: dict[str, str]) -> dict:
    components = manifest["components"]
    ordered, visiting = [], set()

    def visit(name: str) -> None:
        if name in visiting:
            raise WorkspaceError(f"Component dependency cycle: {name}")
        if name in ordered:
            return
        if name not in components:
            raise WorkspaceError(f"Unknown component: {name}")
        visiting.add(name)
        for dependency in components[name].get("dependencies", []):
            visit(dependency)
        visiting.remove(name)
        ordered.append(name)

    for name in names:
        visit(name)
    context, build, checks = set(), set(), set()
    for name in ordered:
        component = components[name]
        context.update(matching(component.get("context", []), tracked))
        build.update(matching(component.get("build", []), tracked))
        checks.update(component.get("checks", []))
    build.update(context)
    for path in list(build):
        for parent in PurePosixPath(path).parents:
            instruction = str(parent / "AGENTS.md")
            if instruction in tracked:
                context.add(instruction)
                build.add(instruction)
    for path in build:
        safe_path(path)
        if tracked[path] not in ("100644", "100755"):
            raise WorkspaceError(f"Workspace selection contains a link or submodule: {path}")
    for name in checks:
        if name not in manifest["checks"]:
            raise WorkspaceError(f"Unknown check: {name}")
        if not matching(manifest["checks"][name].get("files", []), tracked) <= build:
            raise WorkspaceError(f"Check files are absent from the build set: {name}")
    return {"components": ordered, "context_files": sorted(context),
            "build_files": sorted(build), "checks": sorted(checks)}


def manifest_read(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1:
        raise WorkspaceError("Unsupported workspace manifest version")
    return manifest


def select(manifest: dict, slice_name: str, shared: bool) -> list[str]:
    if slice_name not in manifest["slices"]:
        raise WorkspaceError(f"Unknown slice: {slice_name}")
    names = list(manifest["slices"][slice_name])
    if shared:
        names.extend(manifest["shared_consumers"])
    return names


def sparse(root: Path, paths: list[str]) -> None:
    git(root, "sparse-checkout", "set", "--no-cone", "--stdin",
        data="".join(f"/{path}\n" for path in paths))


def metadata(root: Path) -> Path:
    path = Path(git(root, "rev-parse", "--absolute-git-dir").strip()) / "agent-workspace"
    if not path.is_dir():
        raise WorkspaceError("This checkout is not a managed agent workspace")
    return path


def load(root: Path) -> tuple[Path, dict, dict]:
    location = metadata(root)
    state = json.loads((location / "state.json").read_text(encoding="utf-8"))
    manifest = manifest_read(location / "manifest.json")
    digest = hashlib.sha256((location / "manifest.json").read_bytes()).hexdigest()
    if digest != state["manifest_sha256"]:
        raise WorkspaceError("The recorded manifest changed")
    git(root, "merge-base", "--is-ancestor", state["base_sha"], "HEAD")
    return location, state, manifest


def save(root: Path, location: Path, state: dict, manifest: dict) -> None:
    write_json(location / "state.json", state)
    lines = ["# Agent task packet", "", state["task"], "",
             f"Base commit: `{state['base_sha']}`", f"Slice: `{state['slice']}`", "",
             "## Ownership", ""]
    for name in state["components"]:
        lines.append(f"- **{name}**: {manifest['components'][name]['owner']}")
    lines += ["", "## Initial context files", ""]
    lines += [f"- `{path}`" for path in state["context_files"]]
    lines += ["", "## Checks", ""]
    for name in state["checks"]:
        lines.append(f"- `{name}`: " + " ".join(manifest["checks"][name]["argv"]))
    lines += ["", "## Build files", "", "`state.json` records every workspace file and expansion.",
              "Build files are available for compilation. Search initial context paths first.", "",
              "## Rules", "", "Keep changes as ordinary Git commits.",
              "If a shared contract changes, expand every consumer before validation.",
              "Run audit before returning changes. Full repository CI must pass before publishing.",
              "Workspace selection does not select deployments.",
              "Sparse Git controls checkout size. It does not restrict repository access.",
              "The credential header stays excluded. Use the native build for Mini renderer checks.", ""]
    (location / "task.md").write_text("\n".join(lines), encoding="utf-8")


def create(destination: Path, remote: str, revision: str, manifest_path: Path,
           slice_name: str, task: str, shared: bool = False) -> dict:
    if not SHA.fullmatch(revision):
        raise WorkspaceError("Use a full lowercase 40-character commit SHA")
    if destination.exists():
        raise WorkspaceError("The workspace destination already exists")
    manifest = manifest_read(manifest_path)
    names = select(manifest, slice_name, shared)
    if not supports_filter(remote):
        raise WorkspaceError("The remote has no blob filter. A full fetch can copy excluded credentials.")
    destination.mkdir(parents=True)
    git(destination, "init", "--quiet")
    git(destination, "remote", "add", "origin", remote)
    git(destination, "config", "remote.origin.promisor", "true")
    git(destination, "config", "remote.origin.partialclonefilter", "blob:none")
    # Fetch only the pinned history. Git reports servers that ignore filtering.
    fetch = subprocess.run(["git", "-c", "protocol.version=2", "fetch", "--no-tags", "--depth=1",
                            "--filter=blob:none", "origin", revision], cwd=destination,
                           text=True, capture_output=True, encoding="utf-8")
    if fetch.returncode:
        raise WorkspaceError(f"Pinned fetch failed: {fetch.stderr.strip()}")
    if "filtering not recognized" in fetch.stderr.lower():
        raise WorkspaceError("The remote ignores blob filtering. Use a filter-capable remote.")
    if git(destination, "rev-parse", "FETCH_HEAD^{commit}").strip() != revision:
        raise WorkspaceError("The fetched commit does not match the task pin")
    tracked = tree(destination, revision)
    plan = resolve(manifest, names, tracked)
    sparse(destination, plan["build_files"])
    git(destination, "checkout", "--quiet", "--detach", revision)
    if git(destination, "status", "--porcelain"):
        raise WorkspaceError("The new workspace has unexpected Git changes")
    location = Path(git(destination, "rev-parse", "--absolute-git-dir").strip()) / "agent-workspace"
    location.mkdir()
    raw = manifest_path.read_bytes()
    (location / "manifest.json").write_bytes(raw)
    state = {"version": 1, "base_sha": revision, "remote": remote, "slice": slice_name,
             "task": task, "created_at": stamp(), "manifest_sha256": hashlib.sha256(raw).hexdigest(),
             "manifest_source": str(manifest_path.resolve()), "filter_requested": "blob:none",
             "filter_supported": "filtering not recognized" not in fetch.stderr.lower(),
             "requested_components": names, **plan, "initial_context_files": plan["context_files"],
             "initial_build_files": plan["build_files"], "expansions": [], "runs": []}
    save(destination, location, state, manifest)
    return state


def expand(root: Path, components: list[str], paths: list[str], reason: str) -> dict:
    if not reason.strip():
        raise WorkspaceError("An expansion requires a reason")
    location, state, manifest = load(root)
    tracked = tree(root, state["base_sha"])
    for path in paths:
        safe_path(path)
        if not (root / path).resolve().is_relative_to(root.resolve()) or (root / path).is_symlink():
            raise WorkspaceError(f"Expansion path is a link: {path}")
        if path in tracked and tracked[path] not in ("100644", "100755"):
            raise WorkspaceError(f"Expansion requires a regular file: {path}")
    if set(components) & set(manifest["shared_owners"]):
        components = list(dict.fromkeys(components + manifest["shared_consumers"]))
    names = list(dict.fromkeys(state["requested_components"] + components))
    plan = resolve(manifest, names, tracked)
    build = set(plan["build_files"]) | set(state["build_files"]) | set(paths)
    context = set(plan["context_files"]) | set(state["context_files"]) | set(paths)
    for path in paths:
        for parent in PurePosixPath(path).parents:
            instruction = str(parent / "AGENTS.md")
            if instruction in tracked:
                build.add(instruction)
                context.add(instruction)
    # Unknown ownership requires the shared components and all consumers.
    if paths:
        owners = [name for name, component in manifest["components"].items()
                  if any(fnmatchcase(path, pattern) for path in paths for pattern in component.get("owned", []))]
        uncertain = any(not any(fnmatchcase(path, pattern) for component in manifest["components"].values()
                               for pattern in component.get("owned", [])) for path in paths)
        required = owners + (manifest["shared_consumers"] + manifest["shared_owners"] if uncertain else [])
        if any(name in manifest["shared_owners"] for name in owners):
            required += manifest["shared_consumers"]
        if set(required) - set(plan["components"]):
            return expand(root, list(dict.fromkeys(components + required)), paths, reason)
    for path in build:
        safe_path(path)
    added = sorted(build - set(state["build_files"]))
    context_added = sorted(context - set(state["context_files"]))
    sparse(root, sorted(build))
    state.update(plan, requested_components=names, build_files=sorted(build), context_files=sorted(context))
    state["expansions"].append({"at": stamp(), "reason": reason, "components": components, "files": added,
                                "context_added": context_added})
    save(root, location, state, manifest)
    return state


def audit(root: Path) -> dict:
    location, state, manifest = load(root)
    changed = set()
    for args in (("diff", "--name-only", "-z", "--no-renames", state["base_sha"], "HEAD"),
                 ("diff", "--name-only", "-z", "--no-renames", "HEAD"),
                 ("diff", "--cached", "--name-only", "-z", "--no-renames"),
                 ("ls-files", "--others", "--exclude-standard", "-z")):
        changed.update(filter(None, git(root, *args).split("\0")))
    problems, owners = [], set()
    for path in sorted(changed):
        safe_path(path)
        resolved = (root / path).resolve()
        if not resolved.is_relative_to(root.resolve()) or (root / path).is_symlink():
            raise WorkspaceError(f"Changed path is a link: {path}")
        if path not in state["build_files"]:
            problems.append(f"Unrecorded path: {path}. Expand before editing new files.")
        found = {name for name, component in manifest["components"].items()
                 if any(fnmatchcase(path, pattern) for pattern in component.get("owned", []))}
        owners.update(found)
        if not found:
            owners.update(manifest["shared_owners"])
    missing_owners = owners - set(state["components"])
    if missing_owners:
        problems.append("Changed files require owner expansion: " + ", ".join(sorted(missing_owners)))
    if owners & set(manifest["shared_owners"]):
        missing = set(manifest["shared_consumers"]) - set(state["components"])
        if missing:
            problems.append("Shared changes require consumer expansion: " + ", ".join(sorted(missing)))
    result = {"at": stamp(), "base_sha": state["base_sha"], "changed_files": sorted(changed),
              "problems": problems, "ok": not problems, "full_repository_ci_required": True}
    state["last_audit"] = result
    save(root, location, state, manifest)
    return result


def run_check(root: Path, name: str) -> int:
    location, state, manifest = load(root)
    if name not in state["checks"]:
        raise WorkspaceError(f"Check is outside the selected components: {name}")
    if not audit(root)["ok"]:
        raise WorkspaceError("Resolve the workspace audit before running checks")
    command = [part.replace("{python}", sys.executable).replace("{tools}", str(ROOT / "tools"))
               for part in manifest["checks"][name]["argv"]]
    input_sha256 = input_digest(root, state)
    index = len(state["runs"]) + 1
    log = location / f"check-{index}.log"
    start = time.monotonic()
    code = 127
    try:
        with log.open("w", encoding="utf-8") as output:
            code = subprocess.call(command, cwd=root, stdout=output, stderr=subprocess.STDOUT)
    except OSError as error:
        log.write_text(str(error), encoding="utf-8")
    _, state, manifest = load(root)
    state["runs"].append({"at": stamp(), "check": name, "argv": command, "exit_code": code,
                          "seconds": round(time.monotonic() - start, 3), "log": log.name,
                          "head_sha": git(root, "rev-parse", "HEAD").strip(),
                          "manager_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                          "input_sha256": input_sha256,
                          "inputs_changed_during_check": input_sha256 != input_digest(root, state),
                          "control_tools": {part: hashlib.sha256(Path(part).read_bytes()).hexdigest()
                                            for part in command if Path(part).is_file()
                                            and Path(part).is_relative_to(ROOT / "tools")},
                          "diff_sha256": hashlib.sha256(git(root, "diff", "HEAD").encode()).hexdigest()})
    save(root, location, state, manifest)
    print(log.read_text(encoding="utf-8"), end="")
    return code


def input_digest(root: Path, state: dict) -> str:
    digest = hashlib.sha256()
    digest.update(git(root, "rev-parse", "HEAD").encode())
    digest.update(git(root, "diff", "--cached", "--binary").encode())
    for path in state["build_files"]:
        target = root / path
        if not target.resolve().is_relative_to(root.resolve()) or target.is_symlink():
            raise WorkspaceError(f"Build input is a link: {path}")
        digest.update(path.encode() + b"\0")
        digest.update(b"present\0" + target.read_bytes() if target.is_file() else b"absent\0")
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "create"):
        command = sub.add_parser(name)
        command.add_argument("--slice", required=True)
        command.add_argument("--sha", required=True)
        command.add_argument("--manifest", type=Path, default=MANIFEST)
        command.add_argument("--shared-change", action="store_true")
        if name == "plan":
            command.add_argument("--source", type=Path, default=ROOT)
        else:
            command.add_argument("--dest", type=Path, required=True)
            command.add_argument("--remote", default="https://github.com/MattLD13/SportsTickerBackend.git")
            command.add_argument("--task", required=True)
    for name in ("expand", "audit", "run"):
        command = sub.add_parser(name)
        command.add_argument("--workspace", type=Path, required=True)
        if name == "expand":
            command.add_argument("--component", action="append", default=[])
            command.add_argument("--path", action="append", default=[])
            command.add_argument("--reason", required=True)
        if name == "run":
            command.add_argument("--check", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            if not SHA.fullmatch(args.sha):
                raise WorkspaceError("Use a full lowercase 40-character commit SHA")
            manifest = manifest_read(args.manifest)
            result = resolve(manifest, select(manifest, args.slice, args.shared_change), tree(args.source, args.sha))
        elif args.command == "create":
            if not re.fullmatch(r"(?:https://github\.com/|git@github\.com:)[\w.-]+/[\w.-]+(?:\.git)?", args.remote):
                raise WorkspaceError("Use a GitHub HTTPS or SSH repository URL without credentials")
            result = create(args.dest.resolve(), args.remote, args.sha, args.manifest,
                            args.slice, args.task, args.shared_change)
        elif args.command == "expand":
            result = expand(args.workspace.resolve(), args.component, args.path, args.reason)
        elif args.command == "run":
            return run_check(args.workspace.resolve(), args.check)
        else:
            result = audit(args.workspace.resolve())
        print(json.dumps(result, indent=2))
        return 1 if result.get("ok") is False else 0
    except (WorkspaceError, KeyError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
