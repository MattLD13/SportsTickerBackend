"""Compare physical Mini frame captures with the backend's validated logo bytes."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import struct
import sys
import time

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sports_ticker.assets.mini_sprite import validate_sprite
from tools.device_auth import device_headers


def verify(frames: Path, backend: str, ticker: str, token_file: Path | None = None) -> dict:
    headers = {"User-Agent": "SportsTicker-Hardware-Check/1.0", **device_headers(token_file)}
    response = requests.get(
        f"{backend}/api/v2/tickers/{ticker}/data", params={"_t": time.time()}, headers=headers, timeout=20,
    )
    response.raise_for_status()
    games = {str(item["id"]): item["data"] for item in response.json()["content"]["sports"]}
    captures = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(frames.glob("*.json"))]
    assets = {}
    for game in games.values():
        for side in ("away", "home"):
            asset = game.get(f"{side}_logo_asset", {})
            if asset.get("state") == "ready":
                assets[asset["asset_id"]] = asset

    def fetch(entry: tuple[str, dict]) -> tuple[str, bytes]:
        identity, asset = entry
        result = requests.get(f"{backend}/api/v2/assets/mini-sports/{identity}.mts", headers=headers, timeout=20)
        result.raise_for_status()
        if not validate_sprite(result.content, asset["sha256"]):
            raise ValueError(f"Backend sprite fails its checksum: {identity}")
        return identity, result.content

    with ThreadPoolExecutor(max_workers=4) as pool:
        sprites = dict(pool.map(fetch, assets.items()))
    checked = 0
    pixels = 0
    failures = []
    unavailable = 0
    identities = set()
    for capture in captures:
        pane = capture["pane"]
        if pane["kind"] != "sports":
            continue
        identity = str(pane["item_id"])
        if identity not in games:
            failures.append({"item_id": identity, "reason": "game absent from current backend snapshot"})
            continue
        identities.add(identity)
        for side, left in (("away", 1), ("home", 47)):
            asset = games[identity].get(f"{side}_logo_asset", {})
            if asset.get("state") != "ready":
                unavailable += 1
                continue
            body = sprites[asset["asset_id"]]
            tested = different = 0
            # The rank shadow overlaps the tenth logo row.
            rows = 9 if games[identity].get(f"{side}_rank") else 10
            for y in range(rows):
                for x in range(16):
                    source = ((2 * y + 1) * 18 // 32) * 18 + (2 * x + 1) * 18 // 32
                    if not (body[16 + 18 * 18 * 2 + source // 8] >> (source % 8)) & 1:
                        continue
                    ink = struct.unpack_from("<H", body, 16 + source * 2)[0]
                    red, green, blue = (ink >> 8) & 248, (ink >> 3) & 252, (ink << 3) & 255
                    red |= red >> 5
                    green |= green >> 6
                    blue |= blue >> 5
                    expected = f"{red:02x}{green:02x}{blue:02x}"
                    different += capture["matrix"][12 + y][left + x] != expected
                    tested += 1
            if different or not tested:
                failures.append({"item_id": identity, "side": side, "frame": capture["id"], "different_pixels": different})
            checked += 1
            pixels += tested
    if not checked:
        raise ValueError("No ready backend logos match the captured sports frames")
    return {
        "frames": len(captures), "games": len(identities), "logos_checked": checked,
        "pixels_checked": pixels, "backend_unavailable": unavailable, "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--backend", default="https://ticker.mattdicks.org")
    parser.add_argument("--device-token-file", type=Path)
    parser.add_argument("--ticker", required=True)
    args = parser.parse_args()
    result = verify(args.frames, args.backend.rstrip("/"), args.ticker, args.device_token_file)
    print(json.dumps(result, indent=2))
    if result["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
