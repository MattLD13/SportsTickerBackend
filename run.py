"""Launch a product with the Python paths declared by its immutable release."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import runpy
import sys


def release_paths(root: Path, key: str) -> list[Path]:
    """Read bounded relative paths from the selected release layout."""
    root = root.resolve()
    layout = json.loads((root / "release-layout.json").read_text())
    if layout.get("schema_version") != 1:
        raise ValueError("unsupported release layout")
    values = layout.get(key)
    if not isinstance(values, list) or not values or not all(isinstance(v, str) for v in values):
        raise ValueError("invalid release paths")
    paths = [(root / value).resolve() for value in values]
    if any(Path(value).is_absolute() or not path.is_relative_to(root) for value, path in zip(values, paths)):
        raise ValueError("release path escapes the selected release")
    if any(not path.is_dir() for path in paths):
        raise FileNotFoundError("release package directory is missing")
    return paths


def configure_paths(root: Path) -> None:
    """Configure this process and its children before product imports."""
    roots = [str(path) for path in release_paths(root, "python_roots")]
    sys.path[:0] = roots
    inherited = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = os.pathsep.join(roots + ([inherited] if inherited else []))
    os.environ["TICKER_REPOSITORY_DIR"] = str(root.resolve())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("product", choices=("server", "six"))
    args, remaining = parser.parse_known_args()
    configure_paths(Path(__file__).resolve().parent)
    module = {"server": "sports_ticker.server", "six": "ticker_core"}[args.product]
    sys.argv = [module, *remaining]
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
