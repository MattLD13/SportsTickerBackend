"""Separate firmware code changes from comment changes during validation."""
import argparse
from pathlib import Path
import shlex
import subprocess


def mini_code_changed(repository: Path, base: str, head: str = "HEAD") -> bool:
    changes = subprocess.check_output(
        ["git", "diff", "--no-ext-diff", "--unified=0", base, head, "--", "esp32_hub75"],
        cwd=repository, text=True,
    )
    suffix = ""
    for line in changes.splitlines():
        if line.startswith("diff --git "):
            suffix = Path(shlex.split(line)[-1]).suffix.lower()
        if suffix == ".md":
            continue
        if line.startswith(("rename from ", "rename to ", "Binary files ", "new file mode ", "deleted file mode ")):
            return True
        if line.startswith(("+++", "---")) or not line.startswith(("+", "-")):
            continue
        content = line[1:].strip()
        comment = suffix in (".h", ".hpp", ".c", ".cpp", ".ino") and content.startswith("//")
        if content and not comment:
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print("mini_publish=" + str(mini_code_changed(args.repository, args.base)).lower())


if __name__ == "__main__":
    main()
