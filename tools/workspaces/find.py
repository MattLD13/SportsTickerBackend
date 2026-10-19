"""Find bounded file and symbol context without a model call."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.workspaces.discovery import allowed_files, discover, excerpt
from tools.workspaces.manage import WorkspaceError, git, load, manifest_read
from tools.workspaces.start import inventory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--search", help="Literal filename words or a path prefix and symbol")
    operation.add_argument("--component", help="Manifest component name")
    operation.add_argument("--symbols", help="Safe tracked source path")
    operation.add_argument("--excerpt", help="Safe tracked source path")
    parser.add_argument("--symbol", default="", help="Definition name for --excerpt")
    args = parser.parse_args(argv)
    if args.symbol and not args.excerpt:
        parser.error("--symbol requires --excerpt")
    try:
        root = Path(git(args.repo, "rev-parse", "--show-toplevel").strip()).resolve()
        git_dir = Path(git(root, "rev-parse", "--absolute-git-dir").strip())
        manifest = load(root)[2] if (git_dir / "agent-workspace/state.json").is_file() else manifest_read(root / ".github/agent-workspaces.json")
        tracked = inventory(root, manifest, git(root, "rev-parse", "HEAD").strip())
        allowed = set(allowed_files(root, tracked))
        if args.excerpt:
            result = excerpt(root, {"path": args.excerpt, "symbol": args.symbol}, allowed)
        else:
            kind, query = next((kind, value) for kind, value in (
                ("search", args.search), ("component", args.component), ("symbols", args.symbols)) if value is not None)
            result = discover(root, {"kind": kind, "query": query}, manifest, tracked, allowed)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (WorkspaceError, OSError, ValueError, KeyError) as error:
        print("Context discovery failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
