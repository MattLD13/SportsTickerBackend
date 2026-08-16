"""Reject a release if the approved public demo assets change."""

from __future__ import annotations

import hashlib
from pathlib import Path


EXPECTED_HASHES = {
    "sports_ticker/dashboard_v2/templates/dashboard/index.html": "e109f293366a7b17e5330ec7f2119b440edc290abc11ae30c23932a0f7efb8de",
    "sports_ticker/dashboard_v2/templates/demo_ticker.html": "37ef9d16301eb9d2c27936812f09d4b48a16820b7926918feef67e038bdf800c",
    "sports_ticker/dashboard_v2/static/led.js": "f2bdef1b209887868e6333c886bbf9cecc14b0362c1d4490d038f4f475dc92b7",
    "sports_ticker/dashboard_v2/static/style.css": "09823dc316afb81a7b73320d21985536ae2e2386d80c288fabfecac5e36b13b0",
    "sports_ticker/dashboard_v2/static/ticker-demo.js": "4053c39ca48a08d4eceb6c8383019ee48db1067791700b0113a1824b18b49d82",
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
