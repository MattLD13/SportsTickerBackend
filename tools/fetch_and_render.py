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
FULLSCREEN_MODES = {"sports_full", "soccer_full", "golf", "masters", "indycar", "indycar_full"}


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
        elif item_type == "racing" or sport == "indycar":
            for driver in (game.get("indycar") or {}).get("drivers", [])[:10]:
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
    sport = str(game.get("sport", "")).lower()
    item_type = str(game.get("type", "")).lower()
    if item_type in ("golf", "masters") or sport in ("golf", "masters"):
        renderer.mode = "golf"
    elif item_type == "racing" or sport == "indycar":
        renderer.mode = "indycar"
    elif item_type not in STATIC_TYPES:
        renderer.mode = "sports_full"
    try:
        return renderer.draw_single_game(game).convert("RGB")
    finally:
        renderer.mode = old_mode


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


class PreviewWindow:
    def __init__(self, args: argparse.Namespace, snapshot: Snapshot, renderer: TickerStreamer):
        try:
            import tkinter.filedialog as filedialog
            import tkinter.ttk as ttk
            import tkinter as tk
            from PIL import ImageTk
        except Exception as exc:
            raise SystemExit(f"Tkinter preview is unavailable: {exc}") from exc

        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.ImageTk = ImageTk
        self.args = args
        self.snapshot = snapshot
        self.renderer = renderer
        self.games = visible_games(snapshot, include_hidden=args.include_hidden)
        self.view = args.view if args.view in ("scroll", "pin") else "scroll"
        self.pin_index = max(0, args.index)
        self.offset = 0
        self.photo = None
        self.current_frame = None
        self.grabbed_frame = None
        self.grabbed = False
        self.auto_refresh = bool(args.auto_refresh)
        self.next_refresh_at = time.monotonic() + max(1.0, args.refresh_interval)
        self.root = tk.Tk()
        self.root.title("Fetch and Render")
        self.root.configure(bg="#111")
        self.root.resizable(False, False)
        self.url_var = tk.StringVar(value=args.url)
        self.mode_var = tk.StringVar(value=args.mode)
        self.ticker_var = tk.StringVar(value=args.ticker_id)
        self.pin_var = tk.StringVar(value=args.pin_id or snapshot.pinned_game)
        self.pin_choice_var = tk.StringVar(value="")
        self.view_var = tk.StringVar(value=self.view)
        self.auto_var = tk.BooleanVar(value=self.auto_refresh)
        self.item_var = tk.StringVar(value="")
        self.message_var = tk.StringVar(value="")
        self.pin_choices: list[tuple[str, str, int]] = []

        self._build_controls()
        self.canvas = tk.Canvas(
            self.root,
            width=PANEL_W * args.scale,
            height=PANEL_H * args.scale,
            bg="black",
            highlightthickness=0,
        )
        self.canvas.pack(padx=8, pady=(8, 4))
        self.status = tk.Label(self.root, bg="#111", fg="#888", font=("Courier New", 9), anchor="w")
        self.status.pack(fill="x", padx=8, pady=(0, 8))
        self.message = tk.Label(self.root, bg="#111", fg="#666", font=("Courier New", 8), anchor="w")
        self.message.pack(fill="x", padx=8, pady=(0, 8))
        self.strip = None
        self.pin = None
        self._bind()
        self._rebuild()
        self.root.after(33, self._tick)

    def _build_controls(self) -> None:
        tk = self.tk
        ttk = self.ttk
        outer = tk.Frame(self.root, bg="#111")
        outer.pack(fill="x", padx=8, pady=(8, 0))

        row1 = tk.Frame(outer, bg="#111")
        row1.pack(fill="x")
        self._label(row1, "URL").pack(side="left")
        tk.Entry(row1, textvariable=self.url_var, width=34, bg="#202020", fg="#eee", insertbackground="#eee",
                 relief="flat").pack(side="left", padx=(4, 8))
        self._label(row1, "Mode").pack(side="left")
        mode_box = ttk.Combobox(
            row1,
            textvariable=self.mode_var,
            width=14,
            values=[
                "sports", "live", "my_teams", "sports_full", "soccer_full",
                "golf", "masters", "indycar", "stocks", "weather", "music",
                "clock", "flights", "flight_tracker",
            ],
        )
        mode_box.pack(side="left", padx=(4, 8))
        self._button(row1, "Fetch", self._refetch_from_ui).pack(side="left", padx=(0, 4))
        tk.Checkbutton(
            row1,
            text="Auto",
            variable=self.auto_var,
            command=self._toggle_auto,
            bg="#111",
            fg="#bbb",
            activebackground="#111",
            activeforeground="#fff",
            selectcolor="#202020",
            font=("Courier New", 9),
        ).pack(side="left")

        row2 = tk.Frame(outer, bg="#111")
        row2.pack(fill="x", pady=(6, 0))
        self._label(row2, "Ticker").pack(side="left")
        tk.Entry(row2, textvariable=self.ticker_var, width=18, bg="#202020", fg="#eee", insertbackground="#eee",
                 relief="flat").pack(side="left", padx=(4, 8))
        self._label(row2, "Pinned Game").pack(side="left")
        self.pin_choice_box = ttk.Combobox(row2, textvariable=self.pin_choice_var, width=42, state="readonly")
        self.pin_choice_box.pack(side="left", padx=(4, 8))
        self.pin_choice_box.bind("<<ComboboxSelected>>", lambda _e: self._select_pin_choice())
        self._button(row2, "Scroll", lambda: self._set_view("scroll")).pack(side="left", padx=(0, 4))
        self._button(row2, "Pin", lambda: self._set_view("pin")).pack(side="left", padx=(0, 4))
        self._button(row2, "Grab", self._grab_frame).pack(side="left", padx=(0, 4))
        self._button(row2, "Live", self._release_grab).pack(side="left", padx=(0, 4))
        self._button(row2, "Save", self._save_frame_dialog).pack(side="left")

        row3 = tk.Frame(outer, bg="#111")
        row3.pack(fill="x", pady=(6, 0))
        self._label(row3, "Manual Pin").pack(side="left")
        tk.Entry(row3, textvariable=self.pin_var, width=24, bg="#202020", fg="#eee", insertbackground="#eee",
                 relief="flat").pack(side="left", padx=(4, 8))
        self._button(row3, "Use", self._use_manual_pin).pack(side="left", padx=(0, 8))
        self._label(row3, "Item").pack(side="left")
        self.item_box = ttk.Combobox(row3, textvariable=self.item_var, width=56, state="readonly")
        self.item_box.pack(side="left", padx=(4, 0), fill="x", expand=True)
        self.item_box.bind("<<ComboboxSelected>>", lambda _e: self._select_item_from_ui())

    def _label(self, parent, text: str):
        return self.tk.Label(parent, text=text, bg="#111", fg="#888", font=("Courier New", 9))

    def _button(self, parent, text: str, command):
        return self.tk.Button(
            parent,
            text=text,
            command=command,
            bg="#252525",
            fg="#eee",
            activebackground="#333",
            activeforeground="#fff",
            relief="flat",
            padx=8,
            pady=2,
            font=("Courier New", 9),
        )

    def _bind(self) -> None:
        self.root.bind("s", lambda _e: self._set_view("scroll"))
        self.root.bind("p", lambda _e: self._set_view("pin"))
        self.root.bind("r", lambda _e: self._refetch())
        self.root.bind("<space>", lambda _e: self._toggle_grab())
        self.root.bind("<Control-s>", lambda _e: self._save_frame_dialog())
        self.root.bind("n", lambda _e: self._step_pin(1))
        self.root.bind("b", lambda _e: self._step_pin(-1))
        self.root.bind("<Right>", lambda _e: self._step_pin(1))
        self.root.bind("<Left>", lambda _e: self._step_pin(-1))
        self.root.bind("q", lambda _e: self.root.destroy())
        self.root.bind("<Escape>", lambda _e: self.root.destroy())

    def _set_view(self, view: str) -> None:
        self.view = view
        self.view_var.set(view)
        self.grabbed = False
        self._draw_current()

    def _step_pin(self, delta: int) -> None:
        if not self.games:
            return
        self.pin_index = (self.pin_index + delta) % len(self.games)
        game = choose_pinned_game(self.games, "", self.pin_index)
        self._set_pin_from_game(game, update_choice=True)
        self.pin = render_pin(self.renderer, game)
        self.view = "pin"
        self._sync_item_box()
        self._draw_current()

    def _toggle_auto(self) -> None:
        self.auto_refresh = bool(self.auto_var.get())
        self.next_refresh_at = time.monotonic() + max(1.0, self.args.refresh_interval)

    def _toggle_grab(self) -> None:
        if self.grabbed:
            self._release_grab()
        else:
            self._grab_frame()

    def _grab_frame(self) -> None:
        if self.current_frame is None:
            self._draw_current()
        if self.current_frame is not None:
            self.grabbed_frame = self.current_frame.copy()
            self.grabbed = True
            self.message_var.set("Grabbed current frame. Press Live/Space to resume or Save to write PNG.")
            self._draw_current()

    def _release_grab(self) -> None:
        self.grabbed = False
        self.message_var.set("Live preview resumed.")
        self._draw_current()

    def _save_frame_dialog(self) -> None:
        frame = self.grabbed_frame if self.grabbed and self.grabbed_frame is not None else self.current_frame
        if frame is None:
            self.message_var.set("No frame to save yet.")
            return
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        initial = f"ticker_frame_{self.view}_{ts}.png"
        path = self.filedialog.asksaveasfilename(
            title="Save current ticker frame",
            defaultextension=".png",
            initialfile=initial,
            filetypes=[("PNG image", "*.png"), ("All files", "*.*")],
        )
        if not path:
            return
        frame.save(path)
        self.message_var.set(f"Saved {path}")

    def _pin_value_for_game(self, game: dict) -> str:
        sport = str(game.get("sport", "")).strip()
        game_id = str(game.get("id", "")).strip()
        return f"{sport}:{game_id}" if sport and game_id else game_id

    def _label_for_game(self, idx: int, game: dict) -> str:
        sport = game.get("sport", "")
        game_id = game.get("id", "")
        item_type = game.get("type", "")
        away = game.get("away_abbr") or game.get("away_name") or game.get("away") or ""
        home = game.get("home_abbr") or game.get("home_name") or game.get("home") or ""
        status = game.get("status") or game.get("state") or ""
        label = f"{away} @ {home}".strip(" @") or game.get("label") or game.get("title") or item_type
        return f"{idx:02d}  {sport}:{game_id}  {label}  {status}"

    def _set_pin_from_game(self, game: dict | None, update_choice: bool = False) -> None:
        if not game:
            return
        pin_value = self._pin_value_for_game(game)
        self.pin_var.set(pin_value)
        if update_choice:
            label = self._label_for_game(self.pin_index, game)
            if label in [choice[0] for choice in self.pin_choices]:
                self.pin_choice_var.set(label)

    def _select_pin_choice(self) -> None:
        selected_label = self.pin_choice_var.get()
        for label, pin_value, idx in self.pin_choices:
            if label == selected_label:
                self.pin_index = idx
                self.pin_var.set(pin_value)
                self.pin = render_pin(self.renderer, self.games[idx])
                self.view = "pin"
                self._sync_item_box()
                self.message_var.set(f"Pinned {pin_value}")
                self._draw_current()
                return

    def _use_manual_pin(self) -> None:
        pin_id = self.pin_var.get().strip()
        game = choose_pinned_game(self.games, pin_id, self.pin_index)
        if game:
            self.pin_index = self.games.index(game)
            self.pin = render_pin(self.renderer, game)
            self.view = "pin"
            self._sync_item_box()
            self.message_var.set(f"Pinned {self.pin_var.get().strip() or self._pin_value_for_game(game)}")
            self._draw_current()
        else:
            self.message_var.set("Manual pin did not match a fetched item.")

    def _select_item_from_ui(self) -> None:
        if not self.games:
            return
        try:
            selected = self.item_box.current()
        except Exception:
            selected = -1
        if selected < 0:
            return
        self.pin_index = selected
        game = self.games[self.pin_index]
        self._set_pin_from_game(game, update_choice=True)
        self.pin = render_pin(self.renderer, game)
        self.view = "pin"
        self._draw_current()

    def _refetch_from_ui(self) -> None:
        self.args.url = self.url_var.get().strip() or BACKEND_URL
        self.args.mode = self.mode_var.get().strip() or "sports"
        self.args.ticker_id = self.ticker_var.get().strip()
        self.args.pin_id = self.pin_var.get().strip()
        self._refetch()

    def _refetch(self) -> None:
        self.snapshot = fetch_snapshot(
            self.args.url,
            self.args.mode,
            ticker_id=self.args.ticker_id,
            endpoint=self.args.endpoint,
            timeout=self.args.timeout,
        )
        self.games = visible_games(self.snapshot, include_hidden=self.args.include_hidden)
        self.renderer.mode = self.snapshot.mode or self.args.mode
        if not self.pin_var.get().strip() and self.snapshot.pinned_game:
            self.pin_var.set(self.snapshot.pinned_game)
        self.next_refresh_at = time.monotonic() + max(1.0, self.args.refresh_interval)
        self.message_var.set("Fetched latest data.")
        self._rebuild()

    def _rebuild(self) -> None:
        if not self.args.no_prefetch_logos:
            prefetch_logos(self.renderer, self.games)
        self.strip = render_scroll(self.renderer, self.games)
        pin_id = self.pin_var.get().strip() or self.args.pin_id or self.snapshot.pinned_game
        self.pin = render_pin(self.renderer, choose_pinned_game(self.games, pin_id, self.pin_index))
        self._sync_item_box()
        self._draw_current()

    def _sync_item_box(self) -> None:
        values = []
        pin_values = []
        self.pin_choices = []
        for idx, game in enumerate(self.games):
            label = self._label_for_game(idx, game)
            pin_value = self._pin_value_for_game(game)
            values.append(label)
            if pin_value:
                pin_values.append(label)
                self.pin_choices.append((label, pin_value, idx))
        self.item_box["values"] = values
        self.pin_choice_box["values"] = pin_values
        if values:
            self.pin_index = max(0, min(self.pin_index, len(values) - 1))
            self.item_box.current(self.pin_index)
            current_pin = self.pin_var.get().strip()
            selected = None
            for label, pin_value, idx in self.pin_choices:
                if pin_value == current_pin:
                    selected = (label, idx)
                    break
            if selected is None and self.pin_choices:
                choice_idx = max(0, min(self.pin_index, len(self.pin_choices) - 1))
                selected = (self.pin_choices[choice_idx][0], self.pin_choices[choice_idx][2])
            if selected:
                self.pin_choice_var.set(selected[0])
        else:
            self.item_var.set("")
            self.pin_choice_var.set("")

    def _tick(self) -> None:
        now = time.monotonic()
        if self.auto_refresh and not self.grabbed and now >= self.next_refresh_at:
            try:
                self._refetch()
            except Exception as exc:
                self.message_var.set(f"Fetch failed: {exc}")
                self.next_refresh_at = now + max(1.0, self.args.refresh_interval)

        if self.view == "scroll" and self.strip and not self.grabbed:
            max_x = max(1, self.strip.width - PANEL_W)
            self.offset = (self.offset + 1) % max_x
            self._draw_current()
        self.root.after(max(1, int(self.args.scroll_sleep * 1000)), self._tick)

    def _draw_current(self) -> None:
        if self.grabbed and self.grabbed_frame is not None:
            frame = self.grabbed_frame.copy()
        elif self.view == "scroll" and self.strip:
            max_x = max(1, self.strip.width - PANEL_W)
            x = self.offset % max_x
            frame = self.strip.crop((x, 0, x + PANEL_W, PANEL_H))
        else:
            frame = self.pin or blank_frame("NO PIN DATA")

        if self.args.brightness < 1.0:
            frame = ImageEnhance.Brightness(frame).enhance(max(0.0, self.args.brightness))
        self.current_frame = frame.copy()
        scaled = frame.resize((PANEL_W * self.args.scale, PANEL_H * self.args.scale), Image.Resampling.NEAREST)
        self.photo = self.ImageTk.PhotoImage(scaled)
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        auto_text = "auto" if self.auto_refresh else "manual"
        grab_text = "  GRABBED" if self.grabbed else ""
        self.status.config(
            text=(
                f"{self.view.upper()}{grab_text}  mode={self.snapshot.mode}  items={len(self.games)}  "
                f"{auto_text}  space=grab Ctrl+S=save s/p=view arrows=pick r=fetch q=quit"
            )
        )
        self.message.config(text=self.message_var.get())

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch backend ticker data and render real LED frames.")
    parser.add_argument("--url", default=BACKEND_URL, help=f"Backend base URL (default: {BACKEND_URL})")
    parser.add_argument("--endpoint", default="", help="Override endpoint, e.g. /api/state or /data")
    parser.add_argument("--ticker-id", default="", help="Ticker id for /data requests")
    parser.add_argument("--mode", default="sports", help="Mode to request/render")
    parser.add_argument("--view", choices=("scroll", "pin", "both"), default="scroll")
    parser.add_argument("--pin-id", default="", help="Pinned item id, e.g. nhl:401234567")
    parser.add_argument("--index", type=int, default=0, help="Pinned item index when --pin-id is not set")
    parser.add_argument("--save", default="live_render.png", help="Output PNG path")
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
            PreviewWindow(args, snapshot, renderer).run()
            return 0

        if args.view == "scroll":
            save_image(render_scroll(renderer, games), args.save)
        elif args.view == "pin":
            pin_id = args.pin_id or snapshot.pinned_game
            save_image(render_pin(renderer, choose_pinned_game(games, pin_id, args.index)), args.save)
        else:
            root, ext = os.path.splitext(args.save)
            scroll_path = f"{root}_scroll{ext or '.png'}"
            pin_path = f"{root}_pin{ext or '.png'}"
            save_image(render_scroll(renderer, games), scroll_path)
            pin_id = args.pin_id or snapshot.pinned_game
            save_image(render_pin(renderer, choose_pinned_game(games, pin_id, args.index)), pin_path)
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
