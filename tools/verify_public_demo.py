"""Reject a release if the approved public demo assets change."""

from __future__ import annotations

import hashlib
from pathlib import Path


EXPECTED_HASHES = {
    "sports_ticker/dashboard_v2/templates/dashboard/index.html": "5998bae7cf4cd180f4ec201aea8d436c48975b5872931156de19d60e1d441a93",
    "sports_ticker/dashboard_v2/templates/demo_ticker.html": "3ab679b53ea42b80e9787840a6bb84c158edc0a6f2344ece94f8e356d4732029",
    "sports_ticker/dashboard_v2/static/led.js": "f2bdef1b209887868e6333c886bbf9cecc14b0362c1d4490d038f4f475dc92b7",
    "sports_ticker/dashboard_v2/static/style.css": "09823dc316afb81a7b73320d21985536ae2e2386d80c288fabfecac5e36b13b0",
    "sports_ticker/dashboard_v2/static/ticker-demo.js": "578879c83c9174658c642824f1e3081022766a878b2f7805fa659a9ab07aa4c9",
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
