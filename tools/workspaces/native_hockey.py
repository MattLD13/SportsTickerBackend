"""Compile the production Mini hockey path against its recorded ArduinoJson revision."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ARDUINOJSON_SHA = "77771d3c07668e01d8f52acb03910c1110bb373f"
ARDUINOJSON_REMOTE = "https://github.com/bblanchon/ArduinoJson.git"


def run(root: Path, compiler: str, include: Path | None = None) -> int:
    if shutil.which(compiler) is None:
        raise RuntimeError(f"Install a C++17 compiler or pass --compiler. Missing: {compiler}")
    git_dir = Path(subprocess.check_output(["git", "rev-parse", "--absolute-git-dir"], cwd=root, text=True).strip())
    output = git_dir / "agent-workspace" / "native"
    output.mkdir(parents=True, exist_ok=True)
    if include is None:
        dependency = output / "ArduinoJson"
        if not dependency.exists():
            dependency.mkdir()
            subprocess.run(["git", "init", "--quiet"], cwd=dependency, check=True)
            subprocess.run(["git", "fetch", "--quiet", "--depth=1", ARDUINOJSON_REMOTE, ARDUINOJSON_SHA],
                           cwd=dependency, check=True)
            subprocess.run(["git", "checkout", "--quiet", "--detach", ARDUINOJSON_SHA], cwd=dependency, check=True)
        actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=dependency, text=True).strip()
        if actual != ARDUINOJSON_SHA or subprocess.check_output(["git", "status", "--porcelain"], cwd=dependency):
            raise RuntimeError("The native ArduinoJson dependency differs from its recorded revision")
        include = dependency / "src"
    executable = output / ("hockey.exe" if sys.platform == "win32" else "hockey")
    if Path(compiler).stem.lower() == "cl":
        arguments = ["/nologo", "/std:c++17", "/EHsc", "/O1", "/Iesp32_hub75/src/mini/protocol",
                     f"/I{include.resolve()}", "tests/native/mini_hockey_panes.cpp",
                     f"/Fe:{executable}", f"/Fo:{output / 'hockey.obj'}"]
    else:
        arguments = ["-std=c++17", "-O1", "-Iesp32_hub75/src/mini/protocol",
                     f"-I{include.resolve()}", "tests/native/mini_hockey_panes.cpp", "-o", str(executable)]
    subprocess.run([compiler, *arguments], cwd=root, check=True)
    return subprocess.call([str(executable), "tests/fixtures/display/mini_hockey_panes.json"], cwd=root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--arduinojson", type=Path)
    args = parser.parse_args()
    try:
        return run(Path.cwd(), args.compiler, args.arduinojson)
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
