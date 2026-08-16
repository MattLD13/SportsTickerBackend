"""Reject a release if the approved public demo assets change."""

from __future__ import annotations

import hashlib
from pathlib import Path


EXPECTED_HASHES = {
    "sports_ticker/dashboard_v2/templates/demo_ticker.html": "846ee6a79565aa7b6334f4dd6b7f83d7e2ca9dc3126e06946714f4db5654f5d4",
    "sports_ticker/dashboard_v2/static/led.js": "99f0815f8266874cf0bd9ba61f15c6bd70fb1e3b242d92386ab5bdf44c9f788e",
    "sports_ticker/dashboard_v2/static/style.css": "090dd6c2e51b83d4e67cf2759e9362fbf6c7b951665d290d522fdaa551909f82",
    "sports_ticker/dashboard_v2/static/ticker-demo.js": "744eafd1852239825bb16f47b8df15240b5862a182546e5dccb5ce0b9f553b57",
}


def main() -> None:
    """Verify the approved page and renderer assets are exact."""

    root = Path(__file__).resolve().parents[1]
    failures = []
    for relative_path, expected_hash in EXPECTED_HASHES.items():
        path = root / relative_path
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"
        if actual_hash != expected_hash:
            failures.append(relative_path)
    if failures:
        raise SystemExit(f"Public demo changed or missing: {', '.join(failures)}")


if __name__ == "__main__":
    main()
