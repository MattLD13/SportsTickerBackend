"""Reject a release if the approved public demo assets change."""

from __future__ import annotations

import hashlib
from pathlib import Path


EXPECTED_HASHES = {
    "sports_ticker/dashboard_v2/templates/dashboard/index.html": "3e1539445b347018e771c9418c63c28a5079570b801729d57c9dc34c5aa6cc97",
    "sports_ticker/dashboard_v2/templates/demo_ticker.html": "1e21d0cdab72fd7d7a7e18d7b053667d3d163533c7646671233315f2dfee8de1",
    "sports_ticker/dashboard_v2/templates/demo_portfolio.html": "919b486cf670c5f4aa4cb76878e7045c16c8f6ae3f606df9500bafa1464127ab",
    "sports_ticker/dashboard_v2/static/led.js": "f2bdef1b209887868e6333c886bbf9cecc14b0362c1d4490d038f4f475dc92b7",
    "sports_ticker/dashboard_v2/static/style.css": "4fa8d200c025a6bd6fcb6933b15ab26d7ddd65021892c050ea579ac4ef549c8f",
    "sports_ticker/dashboard_v2/static/ticker-demo.js": "b23710a3d355afc0b762d8ab4b6251d4b8dad60611994ddf5b4148e42b45efce",
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


if __name__ == "__main__":
    main()
