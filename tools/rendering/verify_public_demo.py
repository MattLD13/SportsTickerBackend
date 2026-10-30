"""Verify the public page style and generated Mini renderer provenance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


EXPECTED_HASHES = {
    "server/ticker/server/web/static/hardware-catalog.js": "729c32630a300bb6ae1ce4284401e2650e2f052e5e06d2b340d4b7f0ecc749ce",
    "server/ticker/server/web/static/layout-explorer.js": "000f60aa73c5bb0c2b9e996847e691ad6df11f7166f5bc02287965f8de1e5bc4",
    "server/ticker/server/web/static/layout-explorer.css": "3c40636efc755308866aac02327e0c9bb9c5198b4c0290fce69ce2b8b9bb6dbf",
    "server/ticker/server/web/templates/demo_layouts.html": "d22d8e4527e74bfd2a66ac69c5c97390774700437fa82e30f6b36702b2df8606",
    "server/ticker/server/web/templates/dashboard/index.html": "4edd610c42230214850302f73bb5e9c7a8eb3f1afb312a27d344af024c9671e5",
    "server/ticker/server/web/templates/demo_ticker.html": "ea2d260f1cbbc36f23874f2edd404b4202296bd97f914e4ad5ca4e638547e140",
    "server/ticker/server/web/templates/demo_portfolio.html": "dcf3976d96e9451e72afb17815bf3807c047c1c925d8bd782938474a325a357f",
    "server/ticker/server/web/static/led.js": "f2bdef1b209887868e6333c886bbf9cecc14b0362c1d4490d038f4f475dc92b7",
    "server/ticker/server/web/static/style.css": "ebe3e16e99f9dd44396e6e113d2fa836c351ce615fccdbd7b4a1c6e1d3e1cef7",
    "server/ticker/server/web/static/ticker-demo.js": "1d809e72123d4a509185b31cbb8bb4409a8393da3c7dfb36e50b5f172fbd8d95",
}


def main() -> None:
    """Verify the approved page and renderer assets are exact."""

    root = Path(__file__).resolve().parents[2]
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
    from tools.rendering.build_demo_layouts import DESTINATION, SOURCE, provenance
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
