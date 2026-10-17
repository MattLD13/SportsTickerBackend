"""Compare deployed backend source with the configured deployment scope."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess


def backend_revision(repository: Path, ref: str) -> str:
    patterns = json.loads((repository / ".github/deployment-paths.json").read_text(encoding="utf-8"))["backend"]
    return subprocess.check_output(
        ["git", "log", "-1", "--format=%H", ref, "--", *(f":(top,glob){pattern}" for pattern in patterns)],
        cwd=repository, text=True,
    ).strip()


def recovery_needed(repository: Path, deployed: str) -> bool:
    if not re.fullmatch(r"[0-9a-f]{7,40}", deployed):
        return True
    try:
        resolved = subprocess.check_output(
            ["git", "rev-parse", "--verify", f"{deployed}^{{commit}}"], cwd=repository, text=True, stderr=subprocess.DEVNULL,
        ).strip()
        if subprocess.run(["git", "merge-base", "--is-ancestor", resolved, "HEAD"], cwd=repository, check=False).returncode:
            return True
        return backend_revision(repository, resolved) != backend_revision(repository, "HEAD")
    except subprocess.CalledProcessError:
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--deployed", required=True)
    args = parser.parse_args()
    needed = recovery_needed(args.repository, args.deployed)
    print(f"needed={'true' if needed else 'false'}")


if __name__ == "__main__":
    main()
