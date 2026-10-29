"""Select immutable deployment components from their owned source changes."""
from __future__ import annotations

import argparse
import ast
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

from .worker_contract import PROVIDERS, REPOSITORY_ROOT, contract_files, contract_id

ALL = ("core", *PROVIDERS)
PACKAGES = ("sports_ticker", "ticker_core", "backend_ops")
FACTORY = "sports_ticker.providers.factory"
CORE_ENTRY = "sports_ticker.server"
WORKER_ENTRY = "backend_ops.worker"
# Workers carry these paths. A data file in them can change any worker.
WORKER_PATHS = ("sports_ticker/providers/", "sports_ticker/domain/", "sports_ticker/fleet/", "sports_ticker/integrations/")


def _module_files(root):
    found = {}
    for package in PACKAGES:
        for path in sorted((root / package).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            parts = path.relative_to(root).with_suffix("").parts
            found[".".join(parts[:-1] if parts[-1] == "__init__" else parts)] = path
    return found


def _imports(nodes, module, is_package, known):
    """Return the first-party modules that the import statements in ``nodes`` load."""
    package = module if is_package else module.rpartition(".")[0]
    targets = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                anchor = package.split(".")[:len(package.split(".")) - node.level + 1]
                base = ".".join(anchor + ([node.module] if node.module else []))
            else:
                base = node.module
            targets.add(base)
            targets.update(f"{base}.{alias.name}" for alias in node.names)
    loaded = set()
    for target in targets:
        parts = target.split(".")
        # Python loads each parent package before the module.
        loaded.update(name for name in (".".join(parts[:index]) for index in range(1, len(parts) + 1)) if name in known)
    return loaded - {module}


@lru_cache(maxsize=4)
def import_closures(root=REPOSITORY_ROOT):
    """Return the first-party modules that each deployed process can load.

    The provider factory constructs one provider per worker. Each branch of
    ``create_provider`` belongs only to the worker that it names, and core runs
    with worker processes, so core loads none of those branches.
    """
    root = Path(root)
    known = _module_files(root)
    graph, branches = {}, {}
    for module, path in known.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        nodes = set(ast.walk(tree))
        if module == FACTORY:
            for node in list(nodes):
                test = getattr(node, "test", None)
                if (isinstance(node, ast.If) and isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
                        and test.left.id == "name" and isinstance(test.ops[0], ast.Eq)
                        and isinstance(test.comparators[0], ast.Constant)):
                    branch = {child for statement in node.body for child in ast.walk(statement)}
                    branches[node.test.comparators[0].value] = _imports(branch, module, False, known)
                    nodes -= branch
        graph[module] = _imports(nodes, module, path.name == "__init__.py", known)
    if set(branches) != set(PROVIDERS):
        raise ValueError("provider factory branches do not match the worker list")

    def closure(roots):
        seen, pending = set(), list(roots)
        while pending:
            module = pending.pop()
            if module not in seen:
                seen.add(module)
                pending.extend(graph.get(module, ()))
        return frozenset(known[module].relative_to(root).as_posix() for module in seen)

    closures = {"core": closure({CORE_ENTRY})}
    closures.update((name, closure({WORKER_ENTRY, FACTORY, *branches[name]})) for name in PROVIDERS)
    return closures


def owners(path, root=REPOSITORY_ROOT):
    """Return the components whose deployed process can load ``path``."""
    if path in contract_files(root) or path.startswith("backend_ops/"):
        return set(ALL)
    if path in ("requirements.txt", "requirements-backend.txt") or path.startswith(".github/") or path.endswith((".service", ".timer")):
        return set(ALL)
    if path.startswith(("sports_ticker/", "ticker_core/")):
        closures = import_closures(root)
        selected = {name for name, files in closures.items() if path in files}
        if selected:
            return selected
        # A deleted module or a data file has no import edge.
        if path.startswith(WORKER_PATHS) and not (path.endswith(".py") and (Path(root) / path).exists()):
            return set(ALL)
        return {"core"}
    if path.startswith(("docs/contracts/demo-", "esp32_hub75/")):
        return {"core"}
    if path in ("tools/rendering/build_demo_layouts.py", "tools/rendering/render_mini_ui.cpp", "tools/rendering/verify_public_demo.py"):
        return {"core"}
    return set()


def packaged(component, path):
    """Return whether the release package of ``component`` carries ``path``."""
    if component == "core":
        return True
    return path.startswith(("backend_ops/", *WORKER_PATHS)) or path in (
        "sports_ticker/__init__.py", "sports_ticker/leagues.py", "sports_ticker/markets.py", "sports_ticker/tls.py",
        "sports_ticker/immutable.py", "requirements.txt", "requirements-backend.txt", "VERSION", "RELEASE_SHA")


def changed_components(root, base, head="HEAD"):
    paths = subprocess.check_output(["git", "diff", "--name-only", base, head], cwd=root, text=True).splitlines()
    selected = set()
    for path in paths:
        selected.update(owners(path, Path(root)))
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
        included = [path for path in files if packaged(component, path.relative_to(root).as_posix())]
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
