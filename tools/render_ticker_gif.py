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
import time
from dataclasses import dataclass, field

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch_and_render import (
    choose_pinned_game,
    fetch_snapshot,
    make_renderer,
    prefetch_logos,
    render_pin,
    render_scroll,
    save_image,
    visible_games,
)
from ticker_controller.config import BACKEND_URL, PANEL_H, PANEL_W


@dataclass
class GifRenderResult:
    games: list[dict] = field(default_factory=list)
    render_mode: str = ''
    scroll_path: str | None = None
    pin_path: str | None = None
    scroll_frames: list[Image.Image] = field(default_factory=list)
    pin_frames: list[Image.Image] = field(default_factory=list)


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


def fetch_games_for_render(
    mode: str,
    *,
    source: str = 'auto',
    url: str = BACKEND_URL,
) -> tuple[list[dict], str]:
    """Resolve game list from backend and/or live fetchers."""
    games: list[dict] = []
    render_mode = mode

    if source in ('auto', 'backend'):
        try:
            games, render_mode = backend_games(url, mode)
            print(f"Backend: {len(games)} items")
        except Exception as exc:
            print(f"Backend unavailable ({exc})")

    if not games and source in ('auto', 'live'):
        print("Fetching live data directly...")
        games, render_mode = live_games(mode)
        print(f"Live: {len(games)} items")

    return games, render_mode


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


def render_scroll_gif(
    renderer,
    games: list[dict],
    *,
    fps: int = 20,
    speed: int = 2,
    scale: int = 4,
    loops: int = 1,
    out_path: str,
    sport_dir: str | None = None,
) -> tuple[list[Image.Image], str]:
    strip = render_scroll(renderer, games)
    content_w = strip.width - PANEL_W
    print(f"Strip: {strip.width}x{strip.height}  content_width={content_w}px  {len(games)} cards")
    frames = make_gif(strip, fps=fps, speed=speed, scale=scale, loops=loops)
    if not frames:
        return [], out_path
    save_gif(frames, out_path, fps)
    if sport_dir:
        os.makedirs(sport_dir, exist_ok=True)
        fixed = os.path.join(sport_dir, f"{renderer.mode}_scroll.gif")
        save_gif(frames, fixed, fps)
    return frames, out_path


def render_pin_gif(
    renderer,
    games: list[dict],
    *,
    pin_idx: int = 0,
    pin_id: str = '',
    fps: int = 20,
    pin_dur: int = 3,
    scale: int = 4,
    out_path: str,
    sport_dir: str | None = None,
) -> tuple[list[Image.Image], str | None]:
    game = choose_pinned_game(games, pin_id, pin_idx)
    if game is None:
        print("No game at that index.")
        return [], None

    sport = game.get("sport", "")
    gname = game.get("away_abbr") or game.get("home_abbr") or game.get("id") or sport
    n_frames = fps * pin_dur
    print(f"Pin [{pin_idx}]: {sport} {gname}  ->  {n_frames} frames @ {fps}fps")
    delay = 1.0 / fps
    out_w = PANEL_W * scale
    out_h = PANEL_H * scale
    pin_frames: list[Image.Image] = []
    for _ in range(n_frames):
        frame = render_pin(renderer, game)
        if scale > 1:
            frame = frame.resize((out_w, out_h), Image.Resampling.NEAREST)
        pin_frames.append(frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=256))
        time.sleep(delay)

    print(f"Pin frames: {len(pin_frames)}  size: {pin_frames[0].width}x{pin_frames[0].height}")
    save_gif(pin_frames, out_path, fps)
    if sport_dir:
        os.makedirs(sport_dir, exist_ok=True)
        save_gif(pin_frames, os.path.join(sport_dir, f"{renderer.mode}_pin.gif"), fps)
    return pin_frames, out_path


def render_gif_jobs(
    mode: str,
    *,
    source: str = 'auto',
    url: str = BACKEND_URL,
    view: str = 'scroll',
    scroll_out: str | None = None,
    pin_out: str | None = None,
    fps: int = 20,
    speed: int = 2,
    scale: int = 4,
    loops: int = 1,
    pin_idx: int = 0,
    pin_id: str = '',
    pin_dur: int = 3,
    sport_dir: str | None = None,
    do_prefetch_logos: bool = True,
) -> GifRenderResult:
    """Fetch data and render scroll and/or pin GIFs (used by CLI and gif_maker_ui)."""
    games, render_mode = fetch_games_for_render(mode, source=source, url=url)
    result = GifRenderResult(games=games, render_mode=render_mode)
    if not games:
        return result

    renderer = make_renderer(render_mode)
    renderer.mode = mode
    if do_prefetch_logos:
        prefetch_logos(renderer, games)

    if view in ('scroll', 'both') and scroll_out:
        frames, path = render_scroll_gif(
            renderer, games,
            fps=fps, speed=speed, scale=scale, loops=loops,
            out_path=scroll_out, sport_dir=sport_dir,
        )
        result.scroll_frames = [f.convert('RGB') for f in frames]
        result.scroll_path = path

    if view in ('pin', 'both') and pin_out:
        frames, path = render_pin_gif(
            renderer, games,
            pin_idx=pin_idx, pin_id=pin_id,
            fps=fps, pin_dur=pin_dur, scale=scale,
            out_path=pin_out, sport_dir=sport_dir,
        )
        if frames:
            result.pin_frames = [f.convert('RGB') for f in frames]
            result.pin_path = path

    return result


def render_gif_job(
    mode: str,
    *,
    source: str = 'auto',
    url: str = BACKEND_URL,
    fps: int = 20,
    speed: int = 2,
    scale: int = 4,
    loops: int = 1,
    out_path: str | None = None,
    sport_dir: str | None = None,
    do_prefetch_logos: bool = True,
) -> tuple[list[dict], str | None]:
    """Backward-compatible scroll-only helper."""
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    temp_dir = os.path.join(repo_root, 'previews', 'temp')
    os.makedirs(temp_dir, exist_ok=True)
    if out_path is None:
        out_path = os.path.join(temp_dir, f'ticker_{mode}_{ts}.gif')

    bundle = render_gif_jobs(
        mode,
        source=source,
        url=url,
        view='scroll',
        scroll_out=out_path,
        fps=fps,
        speed=speed,
        scale=scale,
        loops=loops,
        sport_dir=sport_dir,
        do_prefetch_logos=do_prefetch_logos,
    )
    return bundle.games, bundle.scroll_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Render ticker scroll as a looping GIF.")
    parser.add_argument("--url", default=BACKEND_URL, help="Backend base URL")
    parser.add_argument("--mode", default="sports", help="Mode/sport to render")
    parser.add_argument("--source", choices=("auto", "backend", "live"), default="auto")
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument("--speed", type=int, default=2)
    parser.add_argument("--scale", type=int, default=4)
    parser.add_argument("--loops", type=int, default=1)
    parser.add_argument("--out", default=None)
    parser.add_argument("--sport-dir", default=None)
    parser.add_argument("--no-prefetch-logos", action="store_true")
    args = parser.parse_args()

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    temp_dir = os.path.join(repo_root, "previews", "temp")
    os.makedirs(temp_dir, exist_ok=True)

    if args.out is None:
        args.out = os.path.join(temp_dir, f"ticker_{args.mode}_{ts}.gif")

    bundle = render_gif_jobs(
        args.mode,
        source=args.source,
        url=args.url,
        view='scroll',
        scroll_out=args.out,
        fps=args.fps,
        speed=args.speed,
        scale=args.scale,
        loops=args.loops,
        sport_dir=args.sport_dir,
        do_prefetch_logos=not args.no_prefetch_logos,
    )
    if not bundle.games:
        print("No data — nothing to render.")
        return 1
    if not bundle.scroll_path:
        print("No frames generated.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
