"""Select immutable deployment components from their owned source changes."""
from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

from .worker_contract import PROVIDERS, contract_id

ALL = ("core", *PROVIDERS)
SOURCE_ENTRIES = {"golf": "EspnGolfSource", "stock": "FinnhubStockSource", "flights": "FlightRadarSource",
                  "news": "EspnNewsSource", "clock": "ClockProvider"}
OWNERS = {
    "espn.py": ("espn", "golf", "news"),
    "espn*": ("espn",), "nhl_live.py": ("espn",), "score_alerts.py": ("espn",),
    "fotmob.py": ("fotmob",), "golf.py": ("golf",), "stocks.py": ("stock",),
    "market_sessions.py": ("stock",), "flights.py": ("flights",), "music.py": ("music",),
    "news*": ("news",), "racing*": ("racing",), "weather.py": ("core", "weather"),
    "catalog.py": ("core", "news"),
}


def definitions(source):
    tree = ast.parse(source)
    nodes = {}
    other = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nodes[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [part.id for target in targets for part in ast.walk(target) if isinstance(part, ast.Name)]
            for name in names:
                nodes[name] = node
        elif not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            other.append(ast.dump(node, include_attributes=False))
    return nodes, other


def source_owners(before, after):
    """Follow local symbol dependencies in the shared provider source module."""
    try:
        old, old_other = definitions(before)
        new, new_other = definitions(after)
    except SyntaxError:
        return set(SOURCE_ENTRIES)
    if old_other != new_other or any(token in after for token in ("globals(", "eval(", "exec(")):
        return set(SOURCE_ENTRIES)
    changed = {name for name in old.keys() | new.keys()
               if ast.dump(old.get(name, ast.Pass()), include_attributes=False) != ast.dump(new.get(name, ast.Pass()), include_attributes=False)}
    affected = set()
    for owner, entry in SOURCE_ENTRIES.items():
        used, pending = set(), [entry]
        while pending:
            name = pending.pop()
            if name in used:
                continue
            used.add(name)
            for graph in (old, new):
                if name in graph:
                    pending.extend(part.id for part in ast.walk(graph[name]) if isinstance(part, ast.Name) and part.id not in used)
        if changed & used:
            affected.add(owner)
    if changed and not affected:
        return set(SOURCE_ENTRIES)
    return affected


def owners(path, *, before=None, after=None):
    if path == "sports_ticker/providers/live_sources.py":
        return source_owners(before or "", after or "")
    if path.startswith(("sports_ticker/integrations/", "sports_ticker/fleet/")):
        return {"core", "music"}
    if path.startswith("sports_ticker/providers/"):
        name = path.rsplit("/", 1)[-1]
        for pattern, components in OWNERS.items():
            if fnmatch.fnmatchcase(name, pattern):
                return set(components)
        return set(ALL)
    if path.startswith(("sports_ticker/domain/", "sports_ticker/leagues", "sports_ticker/markets", "backend_ops/")):
        return set(ALL)
    if path in ("requirements.txt", "requirements-backend.txt") or path.startswith(".github/") or path.endswith((".service", ".timer")):
        return set(ALL)
    if path.startswith(("sports_ticker/", "ticker_core/", "docs/contracts/demo-", "esp32_hub75/")):
        return {"core"}
    if path in ("tools/rendering/build_demo_layouts.py", "tools/rendering/render_mini_ui.cpp", "tools/rendering/verify_public_demo.py"):
        return {"core"}
    return set()


def git_text(root, ref, path):
    result = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=root, capture_output=True)
    return result.stdout.decode("utf-8") if result.returncode == 0 else ""


def changed_components(root, base, head="HEAD"):
    paths = subprocess.check_output(["git", "diff", "--name-only", base, head], cwd=root, text=True).splitlines()
    selected = set()
    for path in paths:
        if path == "sports_ticker/providers/live_sources.py":
            before = git_text(root, base, path)
            after = git_text(root, head, path)
        else:
            before = after = None
        selected.update(owners(path, before=before, after=after))
    return [name for name in ALL if name in selected]


def package(root, output, components):
    """Carry a complete dependency closure inside each selected process release."""
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    files = []
    for directory in ("sports_ticker", "ticker_core", "backend_ops"):
        files.extend(path for path in (root / directory).rglob("*") if path.is_file()
                     and "__pycache__" not in path.parts and path.suffix != ".pyc")
    files.extend(root / name for name in ("requirements.txt", "requirements-backend.txt", "VERSION", "RELEASE_SHA"))
    manifest = {"schema_version": 1, "release": revision, "contract": contract_id(root),
                "files": {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}}
    output.mkdir(parents=True, exist_ok=True)
    for component in components:
        included = files if component == "core" else [path for path in files if
            path.relative_to(root).as_posix().startswith(("backend_ops/", "sports_ticker/providers/", "sports_ticker/domain/",
                                                         "sports_ticker/fleet/", "sports_ticker/integrations/"))
            or path.relative_to(root).as_posix() in ("sports_ticker/__init__.py", "sports_ticker/leagues.py", "sports_ticker/markets.py",
                                                    "requirements.txt", "requirements-backend.txt", "VERSION", "RELEASE_SHA")]
        with tarfile.open(output / (component + ".tar.gz"), "w:gz") as archive:
            for path in included:
                archive.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
            import io
            content = json.dumps({**manifest, "component": component,
                                  "files": {path.relative_to(root).as_posix(): manifest["files"][path.relative_to(root).as_posix()] for path in included}}, sort_keys=True).encode()
            info = tarfile.TarInfo("release-manifest.json")
            info.size, info.mode = len(content), 0o600
            archive.addfile(info, io.BytesIO(content))
    plan = {"schema_version": 1, "release": revision, "components": list(components)}
    (output / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    root = Path.cwd()
    selected = list(ALL) if args.all else changed_components(root, args.base)
    print(json.dumps(package(root, args.output, selected)))


if __name__ == "__main__":
    main()
