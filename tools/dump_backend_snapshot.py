#!/usr/bin/env python3
"""Dump normalized backend ticker items for a mode as JSON.

Useful when debugging renderer inputs without opening the dashboard.
"""

from __future__ import annotations

import argparse
import json

from fetch_and_render import fetch_snapshot, visible_games
from ticker_controller.config import BACKEND_URL


def live_racing_payload(mode: str) -> dict | None:
    from sports_ticker.fetchers.sports import SportsFetcher

    fetcher = SportsFetcher("New York", 40.7128, -74.0060)
    if mode == "f1":
        return fetcher._fetch_f1(force=True)
    if mode == "indycar":
        return fetcher._fetch_indycar(force=True)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump backend snapshot content.")
    parser.add_argument("--url", default=BACKEND_URL)
    parser.add_argument("--mode", default="sports")
    parser.add_argument("--source", choices=("backend", "live"), default="backend")
    parser.add_argument("--ticker-id", default="")
    parser.add_argument("--include-hidden", action="store_true")
    args = parser.parse_args()

    if args.source == "live" and args.mode in ("indycar", "f1"):
        game = live_racing_payload(args.mode)
        payload = {"status": "ok" if game else "empty", "mode": args.mode, "pinned_game": "", "games": [game] if game else []}
    else:
        snapshot = fetch_snapshot(args.url, args.mode, ticker_id=args.ticker_id)
        payload = {
            "status": snapshot.status,
            "mode": snapshot.mode,
            "pinned_game": snapshot.pinned_game,
            "games": visible_games(snapshot, include_hidden=args.include_hidden),
        }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
