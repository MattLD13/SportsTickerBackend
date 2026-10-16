"""Reject a release if the approved public demo assets change."""

from __future__ import annotations

import hashlib
from pathlib import Path


EXPECTED_HASHES = {
    "sports_ticker/dashboard_v2/static/layout-gallery.json": "adbb3e32ce9748d7dc062d236deee49b4939bee5aa45ea01ae3108f6b3d2fdd3",
    "sports_ticker/dashboard_v2/static/layout-explorer.js": "70efc4f9f15d27c1e6c9bde82b688f106a03dcc509290f0d9cd870f44ed9fbad",
    "sports_ticker/dashboard_v2/static/layout-explorer.css": "a63cd3957c700d2ea0321f5c354a836e89377e1d8f196290172197acd43202ca",
    "sports_ticker/dashboard_v2/templates/demo_layouts.html": "5e827749ca9cd6585368f1069705c295e6de91402c04356d70f47f0a92979a2c",
    "sports_ticker/dashboard_v2/templates/dashboard/index.html": "dbb3639955ebda3c948d2f53d579e04159b5fb149e94b207cee2bc3a6013e2f1",
    "sports_ticker/dashboard_v2/templates/demo_ticker.html": "17f31123894fa440e438568563325cd2d630e0387c26061b4e2eb2f85ada9909",
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
