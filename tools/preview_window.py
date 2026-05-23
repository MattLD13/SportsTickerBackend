"""Tkinter live preview for fetch_and_render."""

from __future__ import annotations

import argparse
import datetime
import os
import time

from PIL import Image, ImageEnhance

from fetch_and_render import (
    BACKEND_URL,
    PANEL_H,
    PANEL_W,
    Snapshot,
    TickerStreamer,
    blank_frame,
    choose_pinned_game,
    fetch_snapshot,
    prefetch_logos,
    render_pin,
    render_pin_strip,
    render_scroll,
    visible_games,
)
from sports_ticker.catalog.modes import MODE_OPTIONS

_PREVIEW_MODES = [item['id'] for item in MODE_OPTIONS]
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
        self.view = args.view if args.view in ("scroll", "pin", "strip") else "scroll"
        self.pin_index = max(0, args.index)
        self.offset = 0
        self.strip_offset = 0  # horizontal scroll offset for strip view
        self.photo = None
        self.current_frame = None
        self.grabbed_frame = None
        self.grabbed = False
        self._full_strip: Image.Image | None = None  # cached full-width strip image
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
            values=_PREVIEW_MODES,
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
        self._button(row2, "Strip", lambda: self._set_view("strip")).pack(side="left", padx=(0, 4))
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
        # In strip view, save the full-width image instead of the current viewport
        if self.view == "strip" and not self.grabbed and self._full_strip is not None:
            frame = self._full_strip
        else:
            frame = self.grabbed_frame if self.grabbed and self.grabbed_frame is not None else self.current_frame
        if frame is None:
            self.message_var.set("No frame to save yet.")
            return
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        initial = f"ticker_frame_{self.view}_{ts}.png"
        temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "previews", "temp")
        os.makedirs(temp_dir, exist_ok=True)
        path = self.filedialog.asksaveasfilename(
            title="Save current ticker frame",
            defaultextension=".png",
            initialdir=temp_dir,
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
        game = choose_pinned_game(self.games, pin_id, self.pin_index)
        self.pin = render_pin(self.renderer, game)
        self._full_strip = render_pin_strip(self.renderer, game)
        self.strip_offset = 0
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
        elif self.view == "strip" and self._full_strip and not self.grabbed:
            max_x = max(1, self._full_strip.width - PANEL_W)
            self.strip_offset = (self.strip_offset + 1) % max_x
            self._draw_current()
        self.root.after(max(1, int(self.args.scroll_sleep * 1000)), self._tick)

    def _draw_current(self) -> None:
        if self.grabbed and self.grabbed_frame is not None:
            frame = self.grabbed_frame.copy()
        elif self.view == "scroll" and self.strip:
            max_x = max(1, self.strip.width - PANEL_W)
            x = self.offset % max_x
            frame = self.strip.crop((x, 0, x + PANEL_W, PANEL_H))
        elif self.view == "strip" and self._full_strip:
            # Show a scrolling 384px window into the full-width strip
            max_x = max(1, self._full_strip.width - PANEL_W)
            x = self.strip_offset % max_x
            frame = self._full_strip.crop((x, 0, x + PANEL_W, PANEL_H))
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

