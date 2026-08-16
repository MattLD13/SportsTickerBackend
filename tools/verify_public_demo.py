"""Reject a release if the approved public demo assets change."""

from __future__ import annotations

import hashlib
from pathlib import Path


EXPECTED_HASHES = {
    "sports_ticker/dashboard_v2/templates/dashboard/index.html": "3e1539445b347018e771c9418c63c28a5079570b801729d57c9dc34c5aa6cc97",
    "sports_ticker/dashboard_v2/templates/demo_ticker.html": "1e21d0cdab72fd7d7a7e18d7b053667d3d163533c7646671233315f2dfee8de1",
    "sports_ticker/dashboard_v2/static/led.js": "f2bdef1b209887868e6333c886bbf9cecc14b0362c1d4490d038f4f475dc92b7",
    "sports_ticker/dashboard_v2/static/style.css": "09823dc316afb81a7b73320d21985536ae2e2386d80c288fabfecac5e36b13b0",
    "sports_ticker/dashboard_v2/static/ticker-demo.js": "8d9fd17db0bdbb4086150fcba4909add3f6ef4b2031c549e022bdb4fb949f192",
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
