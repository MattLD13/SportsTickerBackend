#!/usr/bin/env python3
"""GUI for generating ticker scroll GIFs.

Run from the repo root:
  python tools/gif_maker_ui.py
"""

from __future__ import annotations

import datetime
import io
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.filedialog as filedialog
import tkinter.ttk as ttk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image, ImageTk

from ticker_controller.config import BACKEND_URL, PANEL_H, PANEL_W

# ── Colour palette ──────────────────────────────────────────────────────────
BG       = "#111111"
BG2      = "#1a1a1a"
BG3      = "#222222"
FG       = "#dddddd"
FG_DIM   = "#777777"
ACCENT   = "#4a9eff"
SUCCESS  = "#4caf50"
ERROR    = "#ef5350"
FONT     = ("Courier New", 9)
FONT_B   = ("Courier New", 9, "bold")
FONT_LG  = ("Courier New", 11, "bold")

MODES = [
    "sports", "my_teams", "live",
    "soccer",
    "golf", "masters",
    "indycar", "f1", "nascar",
    "stocks", "weather", "music", "clock", "flights",
]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMP_DIR  = os.path.join(REPO_ROOT, "previews", "temp")


# ── Stdout capture ───────────────────────────────────────────────────────────

class _QueueWriter(io.TextIOBase):
    """Redirect writes into a thread-safe queue."""
    def __init__(self, q: queue.Queue) -> None:
        self._q = q

    def write(self, s: str) -> int:
        if s:
            self._q.put(s)
        return len(s)

    def flush(self) -> None:
        pass


# ── Main application ─────────────────────────────────────────────────────────

class GifMakerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Ticker GIF Maker")
        self.root.configure(bg=BG)
        self.root.resizable(True, True)

        self._log_queue: queue.Queue[str] = queue.Queue()
        self._running = False
        self._last_gif_path: str | None = None
        self._gif_frames: list[ImageTk.PhotoImage] = []
        self._gif_pil_frames: list[Image.Image] = []
        self._gif_frame_idx = 0
        self._gif_delay_ms = 50
        self._gif_after_id: str | None = None

        self._build_ui()
        self._poll_log()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── Top: title bar
        title_bar = tk.Frame(self.root, bg=BG, pady=6)
        title_bar.pack(fill="x", padx=12)
        tk.Label(title_bar, text="Ticker GIF Maker", font=("Courier New", 13, "bold"),
                 bg=BG, fg=ACCENT).pack(side="left")
        tk.Label(title_bar, text="384×32 scroll loop → animated GIF", font=FONT,
                 bg=BG, fg=FG_DIM).pack(side="left", padx=(12, 0))

        sep = tk.Frame(self.root, bg=BG3, height=1)
        sep.pack(fill="x")

        # ── Main content: left controls + right preview/log
        content = tk.Frame(self.root, bg=BG)
        content.pack(fill="both", expand=True, padx=12, pady=10)

        left  = tk.Frame(content, bg=BG, width=260)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        right = tk.Frame(content, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        self._build_controls(left)
        self._build_preview_and_log(right)

    def _build_controls(self, parent: tk.Frame) -> None:
        def section(text: str) -> None:
            tk.Label(parent, text=text, font=FONT_B, bg=BG, fg=ACCENT,
                     anchor="w").pack(fill="x", pady=(10, 2))
            tk.Frame(parent, bg=BG3, height=1).pack(fill="x", pady=(0, 6))

        def row(label: str) -> tk.Frame:
            f = tk.Frame(parent, bg=BG)
            f.pack(fill="x", pady=2)
            tk.Label(f, text=f"{label}:", width=12, anchor="w",
                     font=FONT, bg=BG, fg=FG_DIM).pack(side="left")
            return f

        # ── Source
        section("Data Source")

        self._source_var = tk.StringVar(value="auto")
        for val, label in (("auto", "Auto (backend → live)"),
                           ("live", "Live API (no backend)"),
                           ("backend", "Backend only")):
            tk.Radiobutton(
                parent, text=label, variable=self._source_var, value=val,
                command=self._on_source_change,
                font=FONT, bg=BG, fg=FG, selectcolor=BG3,
                activebackground=BG, activeforeground=FG,
            ).pack(anchor="w", padx=4)

        f = row("URL")
        self._url_var = tk.StringVar(value=BACKEND_URL)
        self._url_entry = tk.Entry(f, textvariable=self._url_var, width=22,
                                   bg=BG3, fg=FG, insertbackground=FG, relief="flat",
                                   font=FONT)
        self._url_entry.pack(side="left", fill="x", expand=True)

        # ── Mode
        section("Render Settings")

        f = row("Mode")
        self._mode_var = tk.StringVar(value="golf")
        mode_box = ttk.Combobox(f, textvariable=self._mode_var, values=MODES,
                                 width=16, font=FONT)
        mode_box.pack(side="left")
        self._style_combobox(mode_box)

        f = row("FPS")
        self._fps_var = tk.IntVar(value=20)
        self._fps_spin = tk.Spinbox(f, from_=5, to=60, textvariable=self._fps_var,
                                     width=6, bg=BG3, fg=FG, insertbackground=FG,
                                     buttonbackground=BG2, relief="flat", font=FONT)
        self._fps_spin.pack(side="left")
        tk.Label(f, text="fps", font=FONT, bg=BG, fg=FG_DIM).pack(side="left", padx=4)

        f = row("Speed")
        self._speed_var = tk.IntVar(value=2)
        self._speed_spin = tk.Spinbox(f, from_=1, to=16, textvariable=self._speed_var,
                                       width=6, bg=BG3, fg=FG, insertbackground=FG,
                                       buttonbackground=BG2, relief="flat", font=FONT)
        self._speed_spin.pack(side="left")
        tk.Label(f, text="px/frame", font=FONT, bg=BG, fg=FG_DIM).pack(side="left", padx=4)

        f = row("Scale")
        self._scale_var = tk.IntVar(value=4)
        self._scale_spin = tk.Spinbox(f, from_=1, to=8, textvariable=self._scale_var,
                                       width=6, bg=BG3, fg=FG, insertbackground=FG,
                                       buttonbackground=BG2, relief="flat", font=FONT)
        self._scale_spin.pack(side="left")
        tk.Label(f, text="× (output size)", font=FONT, bg=BG, fg=FG_DIM).pack(side="left", padx=4)

        f = row("Loops")
        self._loops_var = tk.IntVar(value=1)
        self._loops_spin = tk.Spinbox(f, from_=1, to=10, textvariable=self._loops_var,
                                       width=6, bg=BG3, fg=FG, insertbackground=FG,
                                       buttonbackground=BG2, relief="flat", font=FONT)
        self._loops_spin.pack(side="left")
        tk.Label(f, text="content pass(es)", font=FONT, bg=BG, fg=FG_DIM).pack(side="left", padx=4)

        self._skip_logos_var = tk.BooleanVar(value=False)
        tk.Checkbutton(parent, text="Skip logo downloads", variable=self._skip_logos_var,
                       font=FONT, bg=BG, fg=FG_DIM, selectcolor=BG3,
                       activebackground=BG, activeforeground=FG).pack(anchor="w", pady=(6, 0))

        # ── View mode
        section("View")

        self._view_var = tk.StringVar(value="scroll")
        view_frame = tk.Frame(parent, bg=BG)
        view_frame.pack(fill="x")
        for val, label in (("scroll", "Scroll"), ("pin", "Pin"), ("both", "Both")):
            tk.Radiobutton(
                view_frame, text=label, variable=self._view_var, value=val,
                command=self._on_view_change,
                font=FONT, bg=BG, fg=FG, selectcolor=BG3,
                activebackground=BG, activeforeground=FG,
            ).pack(side="left", padx=(0, 8))

        # Pin-specific controls (shown/hidden based on view)
        self._pin_controls_frame = tk.Frame(parent, bg=BG)
        self._pin_controls_frame.pack(fill="x", pady=(4, 0))

        f = tk.Frame(self._pin_controls_frame, bg=BG)
        f.pack(fill="x", pady=2)
        tk.Label(f, text="Pin game:", width=12, anchor="w",
                 font=FONT, bg=BG, fg=FG_DIM).pack(side="left")
        self._pin_idx_var = tk.IntVar(value=0)
        self._pin_idx_spin = tk.Spinbox(f, from_=0, to=99, textvariable=self._pin_idx_var,
                                         width=6, bg=BG3, fg=FG, insertbackground=FG,
                                         buttonbackground=BG2, relief="flat", font=FONT)
        self._pin_idx_spin.pack(side="left")
        tk.Label(f, text="index", font=FONT, bg=BG, fg=FG_DIM).pack(side="left", padx=4)

        f2 = tk.Frame(self._pin_controls_frame, bg=BG)
        f2.pack(fill="x", pady=2)
        tk.Label(f2, text="Duration:", width=12, anchor="w",
                 font=FONT, bg=BG, fg=FG_DIM).pack(side="left")
        self._pin_dur_var = tk.IntVar(value=3)
        self._pin_dur_spin = tk.Spinbox(f2, from_=1, to=30, textvariable=self._pin_dur_var,
                                         width=6, bg=BG3, fg=FG, insertbackground=FG,
                                         buttonbackground=BG2, relief="flat", font=FONT)
        self._pin_dur_spin.pack(side="left")
        tk.Label(f2, text="sec", font=FONT, bg=BG, fg=FG_DIM).pack(side="left", padx=4)

        self._on_view_change()  # set initial visibility

        # ── Output paths
        section("Output")

        f = row("Save to")
        self._out_var = tk.StringVar(value="")
        self._out_entry = tk.Entry(f, textvariable=self._out_var, width=16,
                                    bg=BG3, fg=FG, insertbackground=FG, relief="flat",
                                    font=FONT)
        self._out_entry.pack(side="left", fill="x", expand=True)
        self._btn(f, "…", self._browse_out).pack(side="left", padx=(4, 0))

        f = row("Also save")
        self._sportdir_var = tk.StringVar(value="")
        self._sportdir_entry = tk.Entry(f, textvariable=self._sportdir_var, width=16,
                                         bg=BG3, fg=FG, insertbackground=FG, relief="flat",
                                         font=FONT)
        self._sportdir_entry.pack(side="left", fill="x", expand=True)
        self._btn(f, "…", self._browse_sportdir).pack(side="left", padx=(4, 0))
        tk.Label(parent, text="(fixed-name copy in this folder)", font=("Courier New", 8),
                 bg=BG, fg=FG_DIM).pack(anchor="w")

        # ── Action buttons
        tk.Frame(parent, bg=BG3, height=1).pack(fill="x", pady=(14, 8))

        self._gen_btn = self._btn(parent, "Generate GIF", self._on_generate,
                                   accent=True, pady=6)
        self._gen_btn.pack(fill="x", pady=(0, 4))

        self._open_btn = self._btn(parent, "Open Output Folder", self._on_open_folder)
        self._open_btn.pack(fill="x", pady=(0, 4))

        self._clear_btn = self._btn(parent, "Clear Log", self._clear_log)
        self._clear_btn.pack(fill="x")

        # ── Progress
        self._progress = ttk.Progressbar(parent, mode="indeterminate", length=220)
        self._progress.pack(fill="x", pady=(10, 0))

        self._status_var = tk.StringVar(value="Ready")
        tk.Label(parent, textvariable=self._status_var, font=FONT,
                 bg=BG, fg=FG_DIM, anchor="w", wraplength=240,
                 justify="left").pack(fill="x", pady=(4, 0))

    def _build_preview_and_log(self, parent: tk.Frame) -> None:
        # Preview canvas
        preview_label = tk.Label(parent, text="Preview", font=FONT_B, bg=BG, fg=ACCENT, anchor="w")
        preview_label.pack(anchor="w")

        preview_frame = tk.Frame(parent, bg=BG3, bd=1, relief="flat")
        preview_frame.pack(fill="x", pady=(2, 8))

        # Reserve space for scale=4 → 1536×128
        self._canvas = tk.Canvas(preview_frame, bg="black", highlightthickness=0,
                                  width=PANEL_W * 4, height=PANEL_H * 4)
        self._canvas.pack()

        self._preview_info = tk.Label(parent, text="No GIF generated yet.",
                                       font=FONT, bg=BG, fg=FG_DIM, anchor="w")
        self._preview_info.pack(anchor="w", pady=(0, 8))

        # Log
        log_label = tk.Label(parent, text="Log", font=FONT_B, bg=BG, fg=ACCENT, anchor="w")
        log_label.pack(anchor="w")

        log_frame = tk.Frame(parent, bg=BG3)
        log_frame.pack(fill="both", expand=True, pady=(2, 0))

        self._log = tk.Text(log_frame, font=("Courier New", 8), bg=BG2, fg="#aaaaaa",
                             insertbackground=FG, relief="flat", wrap="word",
                             state="disabled")
        scrollbar = tk.Scrollbar(log_frame, orient="vertical", command=self._log.yview)
        self._log.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._log.pack(side="left", fill="both", expand=True)

        self._log.tag_config("ok",  foreground=SUCCESS)
        self._log.tag_config("err", foreground=ERROR)
        self._log.tag_config("dim", foreground=FG_DIM)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _btn(self, parent, text: str, command, accent: bool = False, pady: int = 2) -> tk.Button:
        return tk.Button(
            parent, text=text, command=command,
            font=FONT_B if accent else FONT,
            bg=ACCENT if accent else "#252525",
            fg="black" if accent else FG,
            activebackground="#6ab5ff" if accent else "#333333",
            activeforeground="black" if accent else FG,
            relief="flat", padx=8, pady=pady, cursor="hand2",
        )

    def _style_combobox(self, cb: ttk.Combobox) -> None:
        style = ttk.Style()
        style.theme_use("default")
        style.configure("TCombobox",
                         fieldbackground=BG3, background=BG2,
                         foreground=FG, selectbackground=BG3,
                         selectforeground=FG)

    def _on_source_change(self) -> None:
        is_live = self._source_var.get() == "live"
        state = "disabled" if is_live else "normal"
        self._url_entry.config(state=state)

    def _on_view_change(self) -> None:
        view = self._view_var.get()
        if view in ("pin", "both"):
            self._pin_controls_frame.pack(fill="x", pady=(4, 0))
        else:
            self._pin_controls_frame.pack_forget()

    def _browse_out(self) -> None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        mode = self._mode_var.get() or "ticker"
        initial = f"ticker_{mode}_{ts}.gif"
        os.makedirs(TEMP_DIR, exist_ok=True)
        path = filedialog.asksaveasfilename(
            title="Save GIF",
            defaultextension=".gif",
            initialdir=TEMP_DIR,
            initialfile=initial,
            filetypes=[("GIF animation", "*.gif"), ("All files", "*.*")],
        )
        if path:
            self._out_var.set(path)

    def _browse_sportdir(self) -> None:
        path = filedialog.askdirectory(
            title="Choose fixed-name output folder",
            initialdir=os.path.join(REPO_ROOT, "previews"),
        )
        if path:
            self._sportdir_var.set(path)

    def _clear_log(self) -> None:
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")

    def _append_log(self, text: str, tag: str = "") -> None:
        self._log.config(state="normal")
        self._log.insert("end", text, tag)
        self._log.see("end")
        self._log.config(state="disabled")

    def _poll_log(self) -> None:
        """Drain the log queue into the text widget (called on the main thread)."""
        try:
            while True:
                chunk = self._log_queue.get_nowait()
                tag = "err" if any(w in chunk.lower() for w in ("error", "fail", "traceback")) else ""
                self._append_log(chunk, tag)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_log)

    def _set_status(self, text: str, colour: str = FG_DIM) -> None:
        self._status_var.set(text)

    # ── Generate ──────────────────────────────────────────────────────────

    def _on_generate(self) -> None:
        if self._running:
            return
        self._running = True
        self._gen_btn.config(state="disabled", bg="#2a5a8a")
        self._progress.start(12)
        self._set_status("Working…")
        self._clear_log()
        self._append_log(f"{'─'*60}\n", "dim")

        thread = threading.Thread(target=self._render_thread, daemon=True)
        thread.start()

    def _render_thread(self) -> None:
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        writer = _QueueWriter(self._log_queue)
        sys.stdout = writer
        sys.stderr = writer
        gif_path: str | None = None
        try:
            gif_path = self._run_render()
        except Exception as exc:
            import traceback
            print(f"\nERROR: {exc}")
            traceback.print_exc()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        self.root.after(0, self._on_render_done, gif_path)

    def _run_render(self) -> str | None:
        """Called in a background thread. Returns saved GIF path or None."""
        import time as _time
        from render_ticker_gif import (
            backend_games,
            live_games,
            make_gif,
            save_gif,
        )
        from fetch_and_render import (
            choose_pinned_game,
            make_renderer,
            prefetch_logos,
            render_pin,
            render_scroll,
        )

        mode   = self._mode_var.get().strip() or "sports"
        source = self._source_var.get()
        url    = self._url_var.get().strip() or BACKEND_URL
        fps    = max(1, self._fps_var.get())
        speed  = max(1, self._speed_var.get())
        scale  = max(1, self._scale_var.get())
        loops  = max(1, self._loops_var.get())
        skip   = self._skip_logos_var.get()
        view   = self._view_var.get()          # "scroll" | "pin" | "both"
        pin_idx = max(0, self._pin_idx_var.get())
        pin_dur = max(1, self._pin_dur_var.get())

        out_path  = self._out_var.get().strip() or None
        sport_dir = self._sportdir_var.get().strip() or None

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(TEMP_DIR, exist_ok=True)

        # Resolve output paths per view
        def _out(suffix: str) -> str:
            if out_path:
                if view == "both":
                    root, ext = os.path.splitext(out_path)
                    return f"{root}_{suffix}{ext or '.gif'}"
                return out_path
            return os.path.join(TEMP_DIR, f"ticker_{mode}_{ts}_{suffix}.gif")

        scroll_out = _out("scroll")
        pin_out    = _out("pin")

        # Fetch data
        games: list[dict] = []
        render_mode = mode

        if source in ("auto", "backend"):
            try:
                games, render_mode = backend_games(url, mode)
                print(f"Backend: {len(games)} items")
            except Exception as exc:
                print(f"Backend unavailable: {exc}")

        if not games and source in ("auto", "live"):
            print("Fetching live data directly…")
            games, render_mode = live_games(mode)
            print(f"Live: {len(games)} items")

        if not games:
            print("No data returned — nothing to render.")
            return None

        renderer = make_renderer(render_mode)
        renderer.mode = mode
        if not skip:
            prefetch_logos(renderer, games)

        last_path: str | None = None

        # ── Scroll GIF
        if view in ("scroll", "both"):
            strip = render_scroll(renderer, games)
            content_w = strip.width - PANEL_W
            print(f"Strip: {strip.width}×{strip.height}  content={content_w}px  cards={len(games)}")
            frames = make_gif(strip, fps=fps, speed=speed, scale=scale, loops=loops)
            print(f"Scroll frames: {len(frames)}  size: {frames[0].width}×{frames[0].height}")
            save_gif(frames, scroll_out, fps)
            if sport_dir:
                os.makedirs(sport_dir, exist_ok=True)
                save_gif(frames, os.path.join(sport_dir, f"{mode}_scroll.gif"), fps)
            # Keep for preview
            self._gif_pil_frames = [f.convert("RGB") for f in frames]
            self._gif_delay_ms = max(20, int(1000 / fps))
            last_path = scroll_out

        # ── Pin GIF
        if view in ("pin", "both"):
            game = choose_pinned_game(games, "", pin_idx)
            if game is None:
                print("No game at that index.")
            else:
                sport = game.get("sport", "")
                gname = game.get("away_abbr") or game.get("home_abbr") or game.get("id") or sport
                n_frames = fps * pin_dur
                print(f"Pin [{pin_idx}]: {sport} {gname}  →  {n_frames} frames @ {fps}fps")
                delay = 1.0 / fps
                out_w  = PANEL_W * scale
                out_h  = PANEL_H * scale
                pin_frames: list[Image.Image] = []
                for _ in range(n_frames):
                    frame = render_pin(renderer, game)
                    if scale > 1:
                        frame = frame.resize((out_w, out_h), Image.Resampling.NEAREST)
                    pin_frames.append(
                        frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
                    )
                    _time.sleep(delay)
                print(f"Pin frames: {len(pin_frames)}  size: {pin_frames[0].width}×{pin_frames[0].height}")
                save_gif(pin_frames, pin_out, fps)
                if sport_dir:
                    os.makedirs(sport_dir, exist_ok=True)
                    save_gif(pin_frames, os.path.join(sport_dir, f"{mode}_pin.gif"), fps)
                # Pin preview takes priority when view == "pin"
                if view == "pin" or not self._gif_pil_frames:
                    self._gif_pil_frames = [f.convert("RGB") for f in pin_frames]
                    self._gif_delay_ms = max(20, int(1000 / fps))
                last_path = pin_out

        return last_path

    def _on_render_done(self, gif_path: str | None) -> None:
        self._running = False
        self._progress.stop()
        self._gen_btn.config(state="normal", bg=ACCENT)

        if gif_path and os.path.exists(gif_path):
            self._last_gif_path = gif_path
            size_kb = os.path.getsize(gif_path) / 1024
            frames  = len(self._gif_pil_frames)
            self._preview_info.config(
                text=f"{os.path.basename(gif_path)}  •  {frames} frames  •  {size_kb:.1f} KB",
                fg=SUCCESS,
            )
            self._set_status(f"Done — {os.path.basename(gif_path)}")
            self._start_gif_preview()
        else:
            self._set_status("Failed — check log for details")
            self._preview_info.config(text="Render failed.", fg=ERROR)

    # ── GIF preview animation ─────────────────────────────────────────────

    def _start_gif_preview(self) -> None:
        if self._gif_after_id is not None:
            self.root.after_cancel(self._gif_after_id)
            self._gif_after_id = None

        if not self._gif_pil_frames:
            return

        scale = self._scale_var.get()
        out_w = PANEL_W * scale
        out_h = PANEL_H * scale
        self._canvas.config(width=out_w, height=out_h)

        self._gif_frames = []
        for pil in self._gif_pil_frames:
            # Frames are already scaled in make_gif; just convert for tkinter
            self._gif_frames.append(ImageTk.PhotoImage(pil))

        self._gif_frame_idx = 0
        self._animate_gif()

    def _animate_gif(self) -> None:
        if not self._gif_frames:
            return
        idx = self._gif_frame_idx % len(self._gif_frames)
        photo = self._gif_frames[idx]
        self._canvas.create_image(0, 0, anchor="nw", image=photo)
        self._canvas.image = photo  # prevent GC
        self._gif_frame_idx = (idx + 1) % len(self._gif_frames)
        self._gif_after_id = self.root.after(self._gif_delay_ms, self._animate_gif)

    # ── Open folder ───────────────────────────────────────────────────────

    def _on_open_folder(self) -> None:
        target = None
        if self._last_gif_path and os.path.exists(self._last_gif_path):
            target = os.path.dirname(self._last_gif_path)
        elif self._sportdir_var.get().strip():
            target = self._sportdir_var.get().strip()
        else:
            target = TEMP_DIR

        if target and os.path.isdir(target):
            if sys.platform == "win32":
                os.startfile(target)
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", target])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", target])


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    root = tk.Tk()
    app = GifMakerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
