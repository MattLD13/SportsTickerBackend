"""Select immutable deployment components from their owned source changes."""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

from .worker_contract import PROVIDERS, contract_id

ALL = ("core", *PROVIDERS)
OWNERS = {
    "golf_source.py": ("golf",), "stock_source.py": ("stock",),
    "flight_source.py": ("flights",), "news_source.py": ("news",), "clock.py": ("clock",),
    "source_values.py": ("golf", "stock", "flights", "news"),
    "racing_session.py": ("core", "racing"),
    "espn_events.py": ("espn", "golf"),
    "espn*": ("espn",), "nhl_live.py": ("espn",), "score_alerts.py": ("espn", "fotmob"),
    "fotmob.py": ("fotmob",), "golf.py": ("golf",), "stocks.py": ("stock",),
    "market_sessions.py": ("stock",), "flights.py": ("flights",), "music.py": ("music",),
    "news*": ("news",), "racing*": ("racing",), "weather.py": ("core", "weather"),
    "catalog.py": ("core", "news"),
}


def owners(path):
    if path in ("sports_ticker/tls.py", "sports_ticker/immutable.py"):
        return set(ALL)
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


def changed_components(root, base, head="HEAD"):
    paths = subprocess.check_output(["git", "diff", "--name-only", base, head], cwd=root, text=True).splitlines()
    selected = set()
    for path in paths:
        selected.update(owners(path))
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
                                                    "sports_ticker/tls.py", "sports_ticker/immutable.py", "requirements.txt", "requirements-backend.txt",
                                                    "VERSION", "RELEASE_SHA")]
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
