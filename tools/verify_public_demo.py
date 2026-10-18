"""Verify the public page style and generated Mini renderer provenance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


EXPECTED_HASHES = {
    "sports_ticker/dashboard_v2/static/layout-explorer.js": "000f60aa73c5bb0c2b9e996847e691ad6df11f7166f5bc02287965f8de1e5bc4",
    "sports_ticker/dashboard_v2/static/layout-explorer.css": "3c40636efc755308866aac02327e0c9bb9c5198b4c0290fce69ce2b8b9bb6dbf",
    "sports_ticker/dashboard_v2/templates/demo_layouts.html": "7e9526fbb773bfd766509645629ca0841a8f829db4908cb837ab7f26ffe8a709",
    "sports_ticker/dashboard_v2/templates/dashboard/index.html": "e86498b951eb91f6d841253ea446746d56bb7f5239edb2d9cc297b4e1de159f9",
    "sports_ticker/dashboard_v2/templates/demo_ticker.html": "36aa4ad71c01f98aa80f54ffceb3f743bee46ddceecb2bee2598c64ac7bb863b",
    "sports_ticker/dashboard_v2/templates/demo_portfolio.html": "7d7fe0bf667e9ae06512f58350da8495890138919ce8b136366d2b77b50937e7",
    "sports_ticker/dashboard_v2/static/led.js": "f2bdef1b209887868e6333c886bbf9cecc14b0362c1d4490d038f4f475dc92b7",
    "sports_ticker/dashboard_v2/static/style.css": "4fa8d200c025a6bd6fcb6933b15ab26d7ddd65021892c050ea579ac4ef549c8f",
    "sports_ticker/dashboard_v2/static/ticker-demo.js": "8fa8918cf2a419e9a29cb63ea2ccd266e55d687bb4f52efc876dbcb543a9dac0",
}


def main() -> None:
    """Verify the approved page and renderer assets are exact."""

    root = Path(__file__).resolve().parents[1]
    failures = []
    for relative_path, expected_hash in EXPECTED_HASHES.items():
        path = root / relative_path
        source = path.read_bytes().replace(b"\r\n", b"\n") if path.is_file() else None
        actual_hash = hashlib.sha256(source).hexdigest() if source is not None else "missing"
        if actual_hash != expected_hash:
            failures.append(relative_path)
    if failures:
        raise SystemExit(f"Public demo changed or missing: {', '.join(failures)}")
    sys.path.insert(0, str(root))
    from tools.build_demo_layouts import DESTINATION, SOURCE, provenance
    gallery = json.loads(DESTINATION.read_text(encoding="utf-8"))
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    if gallery.get("schema_version") != 3 or gallery.get("mini_firmware") != provenance()["mini_firmware"]:
        raise SystemExit("Public Mini layouts require a renderer rebuild.")
    if gallery.get("mini_source_hashes") != provenance()["mini_source_hashes"]:
        raise SystemExit("Public Mini layouts do not match the current renderer sources.")
    expected = {row["name"]: row for row in source["cases"]}
    if set(expected) != {row["name"] for row in gallery["cases"]}:
        raise SystemExit("Public Mini layouts do not match the approved example inputs.")
    for row in gallery["cases"]:
        if row["game"] != expected[row["name"]]["game"] or row.get("mini_source") != "firmware":
            raise SystemExit(f"Public example requires a renderer rebuild: {row['name']}")


if __name__ == "__main__":
    main()
