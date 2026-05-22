#!/usr/bin/env python3
"""Render the full ticker scroll loop as an animated GIF.

Captures one complete pass through all scroll cards at 384×32,
scaled up for readability, and saves a looping GIF.

Examples:
  python tools/render_ticker_gif.py --mode sports
  python tools/render_ticker_gif.py --mode golf --fps 20 --speed 3
  python tools/render_ticker_gif.py --source live --mode indycar
  python tools/render_ticker_gif.py --source live --mode f1 --scale 6
  python tools/render_ticker_gif.py --out previews/f1/f1_loop.gif --source live --mode f1
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch_and_render import (
    fetch_snapshot,
    make_renderer,
    prefetch_logos,
    render_scroll,
    save_image,
    visible_games,
)
from ticker_controller.config import BACKEND_URL, PANEL_H, PANEL_W


def live_games(mode: str) -> tuple[list[dict], str]:
    """Fetch games directly from the SportsFetcher without a running backend."""
    from sports_ticker.fetchers.sports import SportsFetcher

    fetcher = SportsFetcher("New York", 40.7128, -74.0060)

    single_sport_map = {
        "f1":      "_fetch_f1",
        "nascar":  "_fetch_nascar",
        "indycar": "_fetch_indycar",
        "golf":    "_fetch_golf_game",
        "masters": "_fetch_golf_game",
    }

    if mode in single_sport_map:
        fn = getattr(fetcher, single_sport_map[mode], None)
        if fn:
            game = fn(force=True)
            return ([game] if game else []), mode
        return [], mode

    # General sports: try every individual fetcher and collect results
    games = []
    for fn_name in ("_fetch_f1", "_fetch_indycar", "_fetch_nascar", "_fetch_golf_game"):
        fn = getattr(fetcher, fn_name, None)
        if fn:
            try:
                g = fn(force=True)
                if g:
                    games.append(g)
            except Exception as exc:
                print(f"  [live] {fn_name} failed: {exc}")
    return games, mode


def backend_games(url: str, mode: str) -> tuple[list[dict], str]:
    snapshot = fetch_snapshot(url, mode)
    return visible_games(snapshot, include_hidden=False), snapshot.mode or mode


def make_gif(
    strip: Image.Image,
    fps: int,
    speed: int,
    scale: int,
    loops: int,
) -> list[Image.Image]:
    """Slice the scroll strip into animation frames."""
    content_w = strip.width - PANEL_W
    if content_w <= 0:
        # Strip is narrower than one panel — just return a static frame
        frame = strip.crop((0, 0, PANEL_W, PANEL_H))
        if scale > 1:
            frame = frame.resize((PANEL_W * scale, PANEL_H * scale), Image.Resampling.NEAREST)
        return [frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)]

    out_w = PANEL_W * scale
    out_h = PANEL_H * scale

    offsets = range(0, content_w * loops, speed)
    frames: list[Image.Image] = []
    for raw_offset in offsets:
        x = raw_offset % content_w
        frame = strip.crop((x, 0, x + PANEL_W, PANEL_H))
        if scale > 1:
            frame = frame.resize((out_w, out_h), Image.Resampling.NEAREST)
        frames.append(frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=256))

    return frames


def save_gif(frames: list[Image.Image], path: str, fps: int) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    delay_ms = max(20, int(1000 / fps))
    frames[0].save(
        path,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        loop=0,
        duration=delay_ms,
        optimize=False,
    )
    print(f"Saved {path} ({frames[0].width}x{frames[0].height}, {len(frames)} frames, {delay_ms}ms/frame)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Render ticker scroll as a looping GIF.")
    parser.add_argument("--url", default=BACKEND_URL, help="Backend base URL")
    parser.add_argument("--mode", default="sports", help="Mode/sport to render")
    parser.add_argument("--source", choices=("auto", "backend", "live"), default="auto")
    parser.add_argument("--fps", type=int, default=20, help="Frames per second (default 20)")
    parser.add_argument("--speed", type=int, default=2, help="Pixels advanced per frame (default 2)")
    parser.add_argument("--scale", type=int, default=4, help="Display scale factor (default 4, so 1536×128)")
    parser.add_argument("--loops", type=int, default=1, help="How many full content loops to capture (default 1)")
    parser.add_argument("--out", default=None, help="Output GIF path (default: previews/temp/ticker_<mode>_<ts>.gif)")
    parser.add_argument("--sport-dir", default=None, help="Also save a fixed-name copy here, e.g. previews/sports")
    parser.add_argument("--no-prefetch-logos", action="store_true")
    args = parser.parse_args()

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    temp_dir = os.path.join(repo_root, "previews", "temp")
    os.makedirs(temp_dir, exist_ok=True)

    if args.out is None:
        args.out = os.path.join(temp_dir, f"ticker_{args.mode}_{ts}.gif")

    # Fetch game data
    games: list[dict] = []
    render_mode = args.mode

    if args.source in ("auto", "backend"):
        try:
            games, render_mode = backend_games(args.url, args.mode)
            print(f"Backend: {len(games)} items")
        except Exception as exc:
            print(f"Backend unavailable ({exc})")

    if not games and args.source in ("auto", "live"):
        print("Fetching live data directly...")
        games, render_mode = live_games(args.mode)
        print(f"Live: {len(games)} items")

    if not games:
        print("No data — nothing to render.")
        return 1

    # Build renderer and strip
    renderer = make_renderer(render_mode)
    renderer.mode = args.mode
    if not args.no_prefetch_logos:
        prefetch_logos(renderer, games)

    strip = render_scroll(renderer, games)
    print(f"Strip: {strip.width}x{strip.height}  content_width={strip.width - PANEL_W}px  {len(games)} cards")

    # Build GIF frames
    frames = make_gif(strip, fps=args.fps, speed=args.speed, scale=args.scale, loops=args.loops)
    if not frames:
        print("No frames generated.")
        return 1

    # Save primary output
    save_gif(frames, args.out, args.fps)

    # Save fixed-name copy in sport dir if requested
    if args.sport_dir:
        os.makedirs(args.sport_dir, exist_ok=True)
        fixed_path = os.path.join(args.sport_dir, f"{args.mode}_scroll.gif")
        save_gif(frames, fixed_path, args.fps)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
