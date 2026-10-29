"""Select the processes that a change reaches, and package one release for the server.

The server runs one core process and one worker process for each provider in
`ticker3.contract.WORKERS`. Each release folder holds the complete source, so
the core and every worker can run any release. The selection only decides
which processes the deployment moves to the new release.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import subprocess
import tarfile
from functools import lru_cache
from pathlib import Path

from ticker3.contract import WORKERS

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ("core", *WORKERS)
PACKAGES = ("sports_ticker", "ticker_core", "ticker3", "backend_ops")
RELEASE_FILES = ("requirements.txt", "requirements-backend.txt", "VERSION", "RELEASE_SHA")
FACTORY = "sports_ticker.providers.factory"
CORE_ENTRY = "ticker3.server"
WORKER_ENTRY = "ticker3.worker.__main__"
# A change here can change how the core and the workers talk, or how a release runs.
SHARED = ("ticker3/contract/", "backend_ops/", "deploy/backend/", ".github/")
# Workers load data files from these folders. A data file has no import edge, so it can change any worker.
WORKER_DATA = ("sports_ticker/providers/", "sports_ticker/domain/", "sports_ticker/fleet/", "sports_ticker/integrations/")


def _module_files(root: Path) -> dict[str, Path]:
    found = {}
    for package in PACKAGES:
        for path in sorted((root / package).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            parts = path.relative_to(root).with_suffix("").parts
            found[".".join(parts[:-1] if parts[-1] == "__init__" else parts)] = path
    return found


def _parents(name: str, known) -> set[str]:
    """Return a module and each parent package. Python loads each parent package before the module."""
    parts = name.split(".")
    return {".".join(parts[:index]) for index in range(1, len(parts) + 1)} & set(known)


def _imports(nodes, module: str, is_package: bool, known) -> set[str]:
    """Return the first-party modules that the import statements in `nodes` load."""
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
        loaded |= _parents(target, known)
    return loaded - {module}


@lru_cache(maxsize=4)
def import_closures(root: Path = REPOSITORY_ROOT) -> dict[str, frozenset[str]]:
    """Return the source files that each process can load.

    A worker makes its provider through one branch of `create_provider`. Each
    branch belongs only to the worker that it names. The core loads no branch.
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
                    branches[test.comparators[0].value] = _imports(branch, module, False, known)
                    nodes -= branch
        graph[module] = _imports(nodes, module, path.name == "__init__.py", known)
    if set(branches) != set(WORKERS):
        raise ValueError("provider factory branches do not match the worker list")

    def closure(roots: set[str]) -> frozenset[str]:
        seen, pending = set(), [name for root_name in roots for name in _parents(root_name, known)]
        while pending:
            module = pending.pop()
            if module not in seen:
                seen.add(module)
                pending.extend(graph.get(module, ()))
        return frozenset(known[module].relative_to(root).as_posix() for module in seen)

    # The worker loads the factory by name at run time, so the factory is a root of each worker.
    closures = {"core": closure({CORE_ENTRY})}
    closures.update((name, closure({WORKER_ENTRY, FACTORY, *branches[name]})) for name in WORKERS)
    return closures


def owners(path: str, root: Path = REPOSITORY_ROOT) -> set[str]:
    """Return the processes that a change of `path` reaches."""
    if path.startswith(SHARED) or path in RELEASE_FILES:
        return set(COMPONENTS)
    if path.startswith(("sports_ticker/", "ticker_core/", "ticker3/")):
        selected = {name for name, files in import_closures(Path(root)).items() if path in files}
        if selected:
            return selected
        # A deleted module or a data file has no import edge.
        if path.startswith(WORKER_DATA) and not (path.endswith(".py") and (Path(root) / path).exists()):
            return set(COMPONENTS)
        return {"core"}
    if path.startswith(("docs/contracts/demo-", "esp32_hub75/")):
        return {"core"}
    if path in ("tools/rendering/build_demo_layouts.py", "tools/rendering/render_mini_ui.cpp", "tools/rendering/verify_public_demo.py"):
        return {"core"}
    return set()


def changed_components(root: Path, base: str, head: str = "HEAD") -> list[str]:
    paths = subprocess.check_output(["git", "diff", "--name-only", base, head], cwd=root, text=True).splitlines()
    selected = set()
    for path in paths:
        selected |= owners(path, Path(root))
    return [name for name in COMPONENTS if name in selected]


def release_files(root: Path) -> list[Path]:
    files = []
    for directory in PACKAGES:
        files.extend(path for path in sorted((root / directory).rglob("*")) if path.is_file()
                     and "__pycache__" not in path.parts and path.suffix != ".pyc")
    files.extend(root / name for name in RELEASE_FILES)
    return files


def package(root: Path, output: Path, components) -> dict:
    """Write `release.tar.gz` with every release file and its checksum, and `plan.json` with the selected processes."""
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    files = release_files(root)
    manifest = {"schema_version": 2, "release": revision,
                "files": {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}}
    output.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output / "release.tar.gz", "w:gz") as archive:
        for path in files:
            archive.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
        content = json.dumps(manifest, sort_keys=True).encode()
        info = tarfile.TarInfo("release-manifest.json")
        info.size, info.mode = len(content), 0o600
        archive.addfile(info, io.BytesIO(content))
    plan = {"schema_version": 2, "release": revision, "components": [name for name in COMPONENTS if name in components]}
    (output / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    root = Path.cwd()
    selected = list(COMPONENTS) if args.all else changed_components(root, args.base)
    print(json.dumps(package(root, args.output, selected)))


if __name__ == "__main__":
    main()
