#!/usr/bin/env python3
"""Render live racing previews for IndyCar and F1 using backend data.

Examples:
  python tools/render_racing_previews.py
  python tools/render_racing_previews.py --mode f1 --out-dir previews
"""

from __future__ import annotations

import argparse
import os

from fetch_and_render import (
    fetch_snapshot,
    make_renderer,
    prefetch_logos,
    render_pin,
    render_scroll,
    save_image,
    visible_games,
)
from ticker_controller.config import BACKEND_URL


def live_racing_game(mode: str) -> dict | None:
    from sports_ticker.fetchers.sports import SportsFetcher

    fetcher = SportsFetcher("New York", 40.7128, -74.0060)
    if mode == "f1":
        return fetcher._fetch_f1(force=True)
    if mode == "indycar":
        return fetcher._fetch_indycar(force=True)
    if mode == "nascar":
        return fetcher._fetch_nascar(force=True)
    return None


def backend_racing_games(url: str, mode: str) -> tuple[list[dict], str]:
    snapshot = fetch_snapshot(url, mode)
    games = [
        game for game in visible_games(snapshot, include_hidden=True)
        if str(game.get("sport", "")).lower() == mode
    ]
    return games, snapshot.mode or mode


def main() -> int:
    parser = argparse.ArgumentParser(description="Render live IndyCar/F1 preview PNGs.")
    parser.add_argument("--url", default=BACKEND_URL)
    parser.add_argument("--mode", choices=("indycar", "f1", "nascar", "both"), default="both")
    parser.add_argument("--source", choices=("auto", "backend", "live"), default="auto")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--no-prefetch-logos", action="store_true")
    args = parser.parse_args()

    modes = ["indycar", "f1", "nascar"] if args.mode == "both" else [args.mode]

    for mode in modes:
        out_dir = args.out_dir or os.path.join("previews", mode)
        os.makedirs(out_dir, exist_ok=True)
        games = []
        render_mode = mode
        if args.source in ("auto", "backend"):
            games, render_mode = backend_racing_games(args.url, mode)
        if not games and args.source in ("auto", "live"):
            live_game = live_racing_game(mode)
            games = [live_game] if live_game else []
            render_mode = mode
        renderer = make_renderer(render_mode)
        renderer.mode = mode
        if not args.no_prefetch_logos:
            prefetch_logos(renderer, games)
        scroll_path = os.path.join(out_dir, f"{mode}_scroll.png")
        pin_path = os.path.join(out_dir, f"{mode}_pin.png")
        save_image(render_scroll(renderer, games), scroll_path)
        save_image(render_pin(renderer, games[0] if games else None), pin_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
