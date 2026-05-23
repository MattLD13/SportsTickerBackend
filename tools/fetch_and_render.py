#!/usr/bin/env python3
"""Fetch ticker data from the backend and render it with the real controller.

Examples:
  python tools/fetch_and_render.py --mode sports --view scroll --save scroll.png
  python tools/fetch_and_render.py --mode sports --view pin --pin-id nhl:123456 --save pin.png
  python tools/fetch_and_render.py --mode sports --show

The interactive window uses:
  s       scrolling strip
  p       pinned/full-card view
  Space   grab/freeze current frame
  Left/Right or n/b  choose another item for pinned view
  r       refetch backend data
  Ctrl+S  save grabbed/current frame
  q/Esc   quit
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
import time
import traceback
from dataclasses import dataclass
from urllib.parse import urlencode, urljoin

import requests
from PIL import Image, ImageDraw, ImageEnhance

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ticker_controller.config import (  # noqa: E402
    BACKEND_URL,
    GAME_SEPARATOR_COLOR,
    GAME_SEPARATOR_W,
    PANEL_H,
    PANEL_W,
)
from ticker_controller.controller import TickerStreamer  # noqa: E402
from ticker_controller.fonts import load_display_font, load_monospace_font  # noqa: E402
from ticker_controller.stadium import StadiumRenderer  # noqa: E402


STATIC_TYPES = {
    "weather",
    "music",
    "clock",
    "flight_visitor",
    "flight_airport_hud",
}
FULLSCREEN_MODES = {"golf", "masters", "indycar", "f1", "nascar"}


@dataclass
class Snapshot:
    status: str
    mode: str
    games: list[dict]
    pinned_game: str = ""


def _make_url(base_url: str, endpoint: str, params: dict[str, str]) -> str:
    base = base_url.rstrip("/") + "/"
    path = endpoint.lstrip("/")
    url = urljoin(base, path)
    clean_params = {k: v for k, v in params.items() if v not in ("", None)}
    if clean_params:
        return f"{url}?{urlencode(clean_params)}"
    return url


def fetch_snapshot(
    base_url: str,
    mode: str,
    ticker_id: str = "",
    endpoint: str = "",
    timeout: float = 10.0,
) -> Snapshot:
    """Fetch either /data or /api/state and normalize the response shape."""
    if endpoint:
        url = _make_url(base_url, endpoint, {"id": ticker_id, "mode": mode})
    elif ticker_id:
        url = _make_url(base_url, "/data", {"id": ticker_id, "mode": mode})
    else:
        url = _make_url(base_url, "/api/state", {"mode": mode})

    resp = requests.get(url, timeout=timeout, verify=False)
    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, list):
        return Snapshot(status="ok", mode=mode, games=[g for g in data if isinstance(g, dict)])

    if not isinstance(data, dict):
        return Snapshot(status="unknown", mode=mode, games=[])

    settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    local_config = data.get("local_config") if isinstance(data.get("local_config"), dict) else {}
    content = data.get("content") if isinstance(data.get("content"), dict) else {}

    games = data.get("games")
    if not isinstance(games, list):
        games = content.get("sports")
    if not isinstance(games, list):
        games = data.get("raw_games")
    if not isinstance(games, list):
        games = []

    effective_mode = (
        local_config.get("mode")
        or settings.get("mode")
        or data.get("mode")
        or mode
    )
    pinned_game = (
        data.get("pinned_game")
        or settings.get("pinned_game")
        or local_config.get("pinned_game")
        or ""
    )

    return Snapshot(
        status=str(data.get("status", "ok")),
        mode=str(effective_mode or mode),
        games=[g for g in games if isinstance(g, dict)],
        pinned_game=str(pinned_game or ""),
    )


def make_renderer(mode: str) -> TickerStreamer:
    """Create a TickerStreamer-shaped renderer without starting hardware threads."""
    renderer = TickerStreamer.__new__(TickerStreamer)
    renderer.mode = mode
    renderer.mode_override = None
    renderer.logo_cache = {}
    renderer.stadium = StadiumRenderer(logo_cache=renderer.logo_cache)
    renderer.font = load_monospace_font(10, bold=True)
    renderer.medium_font = load_monospace_font(12, bold=True)
    renderer.big_font = load_monospace_font(14, bold=True)
    renderer.huge_font = load_display_font(20, bold=True)
    renderer.clock_giant = load_display_font(28, bold=True)
    renderer.tiny = load_monospace_font(9)
    renderer.tiny_small = load_monospace_font(8)
    renderer.micro = load_monospace_font(7)
    renderer.nano = load_monospace_font(5)
    renderer.score_default_font = load_display_font(12, bold=True)
    renderer.brightness = 1.0
    renderer.scroll_sleep = 0.05
    renderer.inverted = False
    renderer.game_render_cache = {}
    renderer.anim_tick = 0
    renderer.VINYL_SIZE = 51
    renderer.COVER_SIZE = 42
    renderer.vinyl_mask = Image.new("L", (renderer.COVER_SIZE, renderer.COVER_SIZE), 0)
    ImageDraw.Draw(renderer.vinyl_mask).ellipse((0, 0, renderer.COVER_SIZE, renderer.COVER_SIZE), fill=255)
    renderer.scratch_layer = Image.new("RGBA", (renderer.VINYL_SIZE, renderer.VINYL_SIZE), (0, 0, 0, 0))
    renderer._init_vinyl_scratch()
    renderer.vinyl_rotation = 0.0
    renderer.text_scroll_pos = 0.0
    renderer.last_frame_time = time.time()
    renderer.dominant_color = (29, 185, 84)
    renderer.spindle_color = "black"
    renderer.last_cover_url = ""
    renderer.vinyl_cache = None
    renderer.prev_vinyl_cache = None
    renderer.prev_dominant_color = (29, 185, 84)
    renderer.fade_alpha = 1.0
    renderer.transitioning_out = False
    renderer.viz_heights = [2.0] * 16
    renderer.viz_phase = [0.0] * 16
    renderer.C_BG = (5, 5, 8)
    renderer.C_AMBER = (255, 170, 0)
    renderer.C_BLUE_TXT = (80, 180, 255)
    renderer.C_WHT = (220, 220, 230)
    renderer.C_GRN = (80, 255, 80)
    renderer.C_RED = (255, 60, 60)
    renderer.C_GRY = (120, 120, 130)
    return renderer


def collapse_flight_items(games: list[dict]) -> list[dict]:
    flight_weather = None
    flight_arrivals = []
    flight_departures = []
    other_games = []

    for game in games:
        item_type = str(game.get("type", ""))
        if item_type == "flight_weather":
            flight_weather = game
        elif item_type == "flight_arrival":
            flight_arrivals.append(game)
        elif item_type == "flight_departure":
            flight_departures.append(game)
        else:
            other_games.append(game)

    if flight_weather or flight_arrivals or flight_departures:
        other_games.append({
            "type": "flight_airport_hud",
            "sport": "flight",
            "id": "airport_hud",
            "is_shown": True,
            "_weather_item": flight_weather,
            "_arrivals": flight_arrivals,
            "_departures": flight_departures,
        })
    return other_games


def visible_games(snapshot: Snapshot, include_hidden: bool = False) -> list[dict]:
    games = collapse_flight_items(snapshot.games)
    if include_hidden:
        return games
    shown = [g for g in games if g.get("is_shown", True)]
    return shown or games


def _match_pin(game: dict, pin_id: str) -> bool:
    if not pin_id:
        return False
    pin_norm = str(pin_id).strip().lower()
    game_id = str(game.get("id", "")).strip().lower()
    sport = str(game.get("sport", "")).strip().lower()
    if ":" in pin_norm:
        pin_sport, _, raw_id = pin_norm.partition(":")
        return game_id == raw_id and sport == pin_sport
    return game_id == pin_norm


def choose_pinned_game(games: list[dict], pin_id: str = "", index: int = 0) -> dict | None:
    if pin_id:
        pinned = next((g for g in games if _match_pin(g, pin_id)), None)
        if pinned:
            return pinned
    if not games:
        return None
    index = max(0, min(index, len(games) - 1))
    return games[index]


def prefetch_logos(renderer: TickerStreamer, games: list[dict]) -> None:
    logo_jobs = []
    for game in games:
        sport = str(game.get("sport", "")).lower()
        item_type = str(game.get("type", "")).lower()
        if item_type == "music" or sport == "music":
            if game.get("home_logo"):
                logo_jobs.append((game["home_logo"], (42, 42)))
            for url in game.get("next_logos", []):
                if url:
                    logo_jobs.append((url, (42, 42)))
        elif item_type == "racing" or sport in ("indycar", "f1", "nascar"):
            payload = game.get("indycar") or game.get("f1") or game.get("nascar") or {}
            for driver in payload.get("drivers", [])[:10]:
                if driver.get("team_logo"):
                    logo_jobs.append((driver["team_logo"], (18, 18)))
                    logo_jobs.append((driver["team_logo"], (10, 10)))
                    logo_jobs.append((driver["team_logo"], (7, 7)))
                if driver.get("car_illustration"):
                    logo_jobs.append((driver["car_illustration"], (36, 12)))
                    logo_jobs.append((driver["car_illustration"], (120, 16)))
        else:
            for side in ("home_logo", "away_logo"):
                if game.get(side):
                    logo_jobs.append((game[side], (22, 22)))
                    logo_jobs.append((game[side], (24, 24)))
                    logo_jobs.append((game[side], (16, 16)))

    seen = set()
    for url, size in logo_jobs:
        key = (url, size)
        if key in seen:
            continue
        seen.add(key)
        renderer.download_and_process_logo(url, size)


def render_scroll(renderer: TickerStreamer, games: list[dict]) -> Image.Image:
    renderer.mode = "sports" if renderer.mode in FULLSCREEN_MODES else renderer.mode
    cards = []
    for game in games[:60]:
        card = renderer.draw_single_game(game)
        if card:
            cards.append(card.convert("RGBA"))

    if not cards:
        return blank_frame("NO DATA")

    total_w = sum(card.width for card in cards) + len(cards) * GAME_SEPARATOR_W
    strip = Image.new("RGBA", (total_w + PANEL_W, PANEL_H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(strip)
    x = 0
    for card in cards:
        draw.line([(x, 0), (x, PANEL_H - 1)], fill=GAME_SEPARATOR_COLOR)
        x += GAME_SEPARATOR_W
        strip.paste(card, (x, 0), card)
        x += card.width

    repeat_x = x
    idx = 0
    while repeat_x < total_w + PANEL_W:
        draw.line([(repeat_x, 0), (repeat_x, PANEL_H - 1)], fill=GAME_SEPARATOR_COLOR)
        repeat_x += GAME_SEPARATOR_W
        card = cards[idx % len(cards)]
        strip.paste(card, (repeat_x, 0), card)
        repeat_x += card.width
        idx += 1

    return strip.convert("RGB")


def render_pin(renderer: TickerStreamer, game: dict | None) -> Image.Image:
    if game is None:
        return blank_frame("NO PIN DATA")
    old_mode = renderer.mode
    old_display_style = getattr(renderer, "display_style", "strip")
    sport = str(game.get("sport", "")).lower()
    item_type = str(game.get("type", "")).lower()
    if item_type in ("golf", "masters") or sport in ("golf", "masters"):
        renderer.mode = "golf"
    elif item_type == "racing" or sport in ("indycar", "f1", "nascar"):
        renderer.mode = {"f1": "f1", "nascar": "nascar"}.get(sport, "indycar")
    elif item_type not in STATIC_TYPES:
        renderer.display_style = "full"
    try:
        return renderer.draw_single_game(game).convert("RGB")
    finally:
        renderer.mode = old_mode
        renderer.display_style = old_display_style


# Width of the left info panel in draw_indycar_full (hardcoded there as INFO_W = 84)
_RACING_INFO_W  = 84
_RACING_CARD_GAP = 6


def render_pin_strip(renderer: TickerStreamer, game: dict | None) -> Image.Image:
    """Render the full scrollable content of a racing pin card as one wide image.

    For IndyCar / F1 / NASCAR pin cards, the driver leaderboard normally scrolls
    horizontally inside a 300 px viewport.  This function renders all driver cards
    side-by-side so the entire leaderboard fits in a single static PNG.

    For non-racing cards the result is identical to render_pin().
    """
    if game is None:
        return blank_frame("NO PIN DATA")

    # One render call populates _ic_driver_strip_cache on the renderer.
    pin_frame = render_pin(renderer, game)

    cache = getattr(renderer, "_ic_driver_strip_cache", None)
    if not cache or not cache.get("cards"):
        return pin_frame   # non-racing or no cache â€” return the static frame

    cards = cache["cards"]
    if len(cards) <= 1:
        return pin_frame   # single card already fits without scrolling

    gap = _RACING_CARD_GAP
    strip_content_w = sum(c.width for c in cards) + gap * len(cards)
    total_w = _RACING_INFO_W + strip_content_w
    result = Image.new("RGB", (total_w, PANEL_H), (0, 0, 0))

    # Left info panel â€” crop from the rendered pin frame
    result.paste(pin_frame.crop((0, 0, _RACING_INFO_W, PANEL_H)), (0, 0))

    # Driver cards in order, no wrapping
    x = _RACING_INFO_W
    for card in cards:
        card_rgb = card.convert("RGB") if card.mode != "RGBA" else None
        if card.mode == "RGBA":
            bg = Image.new("RGB", card.size, (0, 0, 0))
            bg.paste(card, mask=card.split()[3])
            result.paste(bg, (x, 1))
        else:
            result.paste(card_rgb, (x, 1))
        x += card.width + gap

    print(f"Full strip: {total_w}Ã—{PANEL_H}  ({len(cards)} driver cards)")
    return result


def blank_frame(label: str) -> Image.Image:
    img = Image.new("RGB", (PANEL_W, PANEL_H), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = load_monospace_font(10, bold=True)
    draw.text((4, 10), label, fill=(170, 170, 170), font=font)
    return img


def save_image(img: Image.Image, path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    img.save(path)
    print(f"Saved {path} ({img.width}x{img.height})")


def summarize_games(games: list[dict]) -> None:
    if not games:
        print("No games/items returned.")
        return
    for idx, game in enumerate(games):
        sport = game.get("sport", "")
        item_type = game.get("type", "")
        game_id = game.get("id", "")
        away = game.get("away_abbr") or game.get("away_name") or game.get("away") or ""
        home = game.get("home_abbr") or game.get("home_name") or game.get("home") or ""
        status = game.get("status") or game.get("state") or ""
        label = f"{away} @ {home}".strip(" @") or game.get("label") or game.get("title") or item_type
        print(f"{idx:02d}  {sport}:{game_id}  {item_type:14}  {label}  {status}")


def _open_preview_window(args: argparse.Namespace, snapshot: Snapshot, renderer: TickerStreamer):
    from preview_window import PreviewWindow
    PreviewWindow(args, snapshot, renderer).run()



def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch backend ticker data and render real LED frames.")
    parser.add_argument("--url", default=BACKEND_URL, help=f"Backend base URL (default: {BACKEND_URL})")
    parser.add_argument("--endpoint", default="", help="Override endpoint, e.g. /api/state or /data")
    parser.add_argument("--ticker-id", default="", help="Ticker id for /data requests")
    parser.add_argument("--mode", default="sports", help="Mode to request/render")
    parser.add_argument("--view", choices=("scroll", "pin", "strip", "both"), default="scroll",
                        help="scroll=full strip GIF, pin=384Ã—32 frame, strip=full-width pin content, both=scroll+pin")
    parser.add_argument("--pin-id", default="", help="Pinned item id, e.g. nhl:401234567")
    parser.add_argument("--index", type=int, default=0, help="Pinned item index when --pin-id is not set")
    parser.add_argument("--save", default=None, help="Output PNG path (default: previews/temp/render_<ts>.png)")
    parser.add_argument("--show", action="store_true", help="Open an interactive preview window")
    parser.add_argument("--list", action="store_true", help="Print returned items")
    parser.add_argument("--include-hidden", action="store_true", help="Render items even if is_shown is false")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--scale", type=int, default=4, help="Interactive preview scale")
    parser.add_argument("--scroll-sleep", type=float, default=0.03, help="Interactive scroll delay in seconds")
    parser.add_argument("--auto-refresh", action="store_true", help="Auto-refetch in interactive mode")
    parser.add_argument("--refresh-interval", type=float, default=30.0, help="Interactive auto-refetch interval")
    parser.add_argument("--brightness", type=float, default=1.0, help="Interactive brightness multiplier")
    parser.add_argument("--no-prefetch-logos", action="store_true", help="Skip logo downloads before rendering")
    args = parser.parse_args()

    # Resolve default save path to previews/temp/ with timestamp
    if args.save is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "previews", "temp")
        os.makedirs(temp_dir, exist_ok=True)
        args.save = os.path.join(temp_dir, f"render_{args.mode}_{ts}.png")

    try:
        snapshot = fetch_snapshot(
            args.url,
            args.mode,
            ticker_id=args.ticker_id,
            endpoint=args.endpoint,
            timeout=args.timeout,
        )
        games = visible_games(snapshot, include_hidden=args.include_hidden)
        if args.list:
            summarize_games(games)

        renderer = make_renderer(snapshot.mode or args.mode)
        renderer.scroll_sleep = args.scroll_sleep
        if not args.no_prefetch_logos:
            prefetch_logos(renderer, games)

        if args.show:
            _open_preview_window(args, snapshot, renderer)
            return 0

        pin_id = args.pin_id or snapshot.pinned_game
        pinned = choose_pinned_game(games, pin_id, args.index)

        if args.view == "scroll":
            save_image(render_scroll(renderer, games), args.save)
        elif args.view == "pin":
            save_image(render_pin(renderer, pinned), args.save)
        elif args.view == "strip":
            save_image(render_pin_strip(renderer, pinned), args.save)
        else:  # both
            root, ext = os.path.splitext(args.save)
            save_image(render_scroll(renderer, games), f"{root}_scroll{ext or '.png'}")
            save_image(render_pin(renderer, pinned),   f"{root}_pin{ext or '.png'}")
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
