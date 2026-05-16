#!/usr/bin/env python3
"""
emulator.py - Sports Ticker desktop emulator
Renders the same 384x32 LED display in a Tkinter window so you can test
without physical hardware.

Requirements:
    pip install pillow requests python-dotenv

Usage:
    python emulator.py                              # targets http://localhost:5000
    python emulator.py --url http://localhost:5000
    python emulator.py --url https://ticker.mattdicks.org
    python emulator.py --scale 5                    # zoom 1-8 (default 4)

Keyboard shortcuts:
    +  /  =     zoom in
    -           zoom out
    p           pause / resume scrolling
    g           toggle pixel grid (visible at scale >= 4)
    s           save screenshot to current directory
    q / Esc     quit
"""

import argparse
import datetime
import queue
import sys
import threading

try:
    import tkinter as tk
except ImportError:
    sys.exit("tkinter is required. Install it with your Python distribution.")

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageTk
except ImportError:
    sys.exit("Pillow is required: pip install pillow")

# ── Patch BACKEND_URL before importing ticker_controller ─────────────────────
# poll_backend() reads BACKEND_URL from module globals at call time, so setting
# it here (before TickerStreamer.__init__ starts the poll thread) is sufficient.
import ticker_controller as _tc

DEFAULT_URL = "http://localhost:5000"
SCALE_OPTIONS = [2, 3, 4, 5, 6, 8]
MODE_OPTIONS = [
    "sports",
    "live",
    "my_teams",
    "sports_full",
    "soccer_full",
    "golf",
    "stocks",
    "weather",
    "music",
    "clock",
    "flights",
    "flight_tracker",
]


# ── Emulated ticker ───────────────────────────────────────────────────────────

from ticker_controller import TickerStreamer, PANEL_W, PANEL_H


class EmulatedTicker(TickerStreamer):
    """
    TickerStreamer subclass that redirects update_display() to a frame queue
    instead of writing to an LED matrix.
    """

    def __init__(self, frame_queue: queue.Queue):
        self._frame_queue = frame_queue
        super().__init__()  # starts poll_backend daemon thread

    def update_display(self, pil_image):
        img = pil_image.convert("RGB")

        # Apply brightness attenuation to simulate LED dimming.
        b = max(0.0, min(1.0, float(self.brightness)))
        if b < 0.99:
            img = ImageEnhance.Brightness(img).enhance(b)

        if self.inverted:
            img = img.rotate(180)

        # Keep the queue shallow (at most 2 frames) so Tkinter is never stale.
        try:
            self._frame_queue.put_nowait(img)
        except queue.Full:
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._frame_queue.put_nowait(img)
            except queue.Full:
                pass


# ── Tkinter display ────────────────────────────────────────────────────────────

_HELP_TEXT = (
    "+/=  zoom in    -  zoom out    p  pause    g  grid    m/M  mode    s  screenshot    q  quit"
)

# Refresh interval for the Tkinter poll (ms).  30 ms ≈ 33 fps.
_POLL_MS = 30


class EmulatorWindow:
    def __init__(self, root: tk.Tk, ticker: EmulatedTicker,
                 frame_queue: queue.Queue, scale: int):
        self.root = root
        self.ticker = ticker
        self.queue = frame_queue
        self.scale = scale
        self.mode_var = tk.StringVar(value=self._current_mode())

        self.paused = False
        self.show_grid = False
        self.last_frame: Image.Image | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self._last_seen_ts = 0.0

        self._build_ui()
        self._bind_keys()
        self._start_render_thread()
        self.root.after(_POLL_MS, self._poll)

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        self.root.configure(bg="#111")
        self.root.resizable(False, False)

        # LED canvas
        self.canvas = tk.Canvas(
            self.root,
            width=PANEL_W * self.scale,
            height=PANEL_H * self.scale,
            bg="black",
            highlightthickness=0,
        )
        self.canvas.pack(padx=8, pady=(8, 4))

        # Status bar
        bar = tk.Frame(self.root, bg="#1a1a1a", pady=2)
        bar.pack(fill="x", padx=8)

        self.lbl_left = tk.Label(
            bar, text="Connecting…", font=("Courier New", 9),
            bg="#1a1a1a", fg="#888", anchor="w"
        )
        self.lbl_left.pack(side="left", fill="x", expand=True)

        self.lbl_right = tk.Label(
            bar, text="", font=("Courier New", 9),
            bg="#1a1a1a", fg="#555", anchor="e"
        )
        self.lbl_right.pack(side="right")

        mode_bar = tk.Frame(self.root, bg="#111")
        mode_bar.pack(fill="x", padx=8, pady=(4, 0))

        tk.Label(
            mode_bar, text="Mode", font=("Courier New", 9),
            bg="#111", fg="#888", anchor="w"
        ).pack(side="left")

        mode_menu = tk.OptionMenu(
            mode_bar,
            self.mode_var,
            *MODE_OPTIONS,
            command=self._apply_mode_from_ui,
        )
        mode_menu.config(
            bg="#222",
            fg="#eee",
            activebackground="#333",
            activeforeground="#fff",
            highlightthickness=0,
            bd=0,
            relief="flat",
            font=("Courier New", 9),
        )
        mode_menu["menu"].config(
            bg="#222",
            fg="#eee",
            activebackground="#444",
            activeforeground="#fff",
            relief="flat",
        )
        mode_menu.pack(side="left", padx=(8, 0))

        # Help footer
        tk.Label(
            self.root, text=_HELP_TEXT,
            font=("Courier New", 8), bg="#111", fg="#3a3a3a"
        ).pack(padx=8, pady=(4, 8))

    # ── Key bindings ───────────────────────────────────────────────────────────

    def _bind_keys(self):
        for key in ("<plus>", "<equal>", "<KP_Add>"):
            self.root.bind(key, lambda _e: self._zoom(+1))
        for key in ("<minus>", "<KP_Subtract>"):
            self.root.bind(key, lambda _e: self._zoom(-1))
        self.root.bind("p",        lambda _e: self._toggle_pause())
        self.root.bind("g",        lambda _e: self._toggle_grid())
        self.root.bind("m",        lambda _e: self._cycle_mode(+1))
        self.root.bind("M",        lambda _e: self._cycle_mode(-1))
        self.root.bind("s",        lambda _e: self._screenshot())
        self.root.bind("q",        lambda _e: self.root.destroy())
        self.root.bind("<Escape>", lambda _e: self.root.destroy())

    # ── Render thread ──────────────────────────────────────────────────────────

    def _start_render_thread(self):
        threading.Thread(
            target=self.ticker.render_loop,
            name="render_loop",
            daemon=True,
        ).start()

    # ── Frame polling ──────────────────────────────────────────────────────────

    def _poll(self):
        """Called by Tkinter every _POLL_MS ms to drain the frame queue."""
        got_new = False
        try:
            while True:
                frame = self.queue.get_nowait()
                if not self.paused:
                    self.last_frame = frame
                    got_new = True
        except queue.Empty:
            pass

        if got_new and self.last_frame:
            self._render(self.last_frame)
            self._last_seen_ts = __import__("time").monotonic()

        self._update_status()
        self.root.after(_POLL_MS, self._poll)

    def _render(self, frame: Image.Image):
        W = PANEL_W * self.scale
        H = PANEL_H * self.scale
        scaled = frame.resize((W, H), Image.NEAREST)

        if self.show_grid and self.scale >= 4:
            d = ImageDraw.Draw(scaled)
            grid_col = (25, 25, 25)
            for x in range(0, W, self.scale):
                d.line([(x, 0), (x, H - 1)], fill=grid_col)
            for y in range(0, H, self.scale):
                d.line([(0, y), (W - 1, y)], fill=grid_col)

        self.photo = ImageTk.PhotoImage(scaled)
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)

    # ── Status bar ─────────────────────────────────────────────────────────────

    def _update_status(self):
        import time as _time
        mode = getattr(self.ticker, "mode", "?")
        if self.mode_var.get() != mode and mode in MODE_OPTIONS:
            self.mode_var.set(mode)
        n_scroll = len(getattr(self.ticker, "games", []))
        n_static = len(getattr(self.ticker, "static_items", []))
        device = str(getattr(self.ticker, "device_id", "?"))[:12]
        paired = not getattr(self.ticker, "is_pairing", False)

        age = _time.monotonic() - self._last_seen_ts
        if self._last_seen_ts == 0.0:
            conn_txt = "connecting…"
        elif age > 3.0:
            conn_txt = f"no data ({age:.0f}s ago)"
        else:
            conn_txt = "live"

        flags = []
        if self.paused:
            flags.append("PAUSED")
        if not paired:
            flags.append("unparied")
        flag_txt = "  [" + "  ".join(flags) + "]" if flags else ""

        self.lbl_left.config(
            text=f"mode={mode}  scroll={n_scroll}  static={n_static}"
                 f"  dev={device}  {conn_txt}{flag_txt}"
        )
        self.lbl_right.config(
            text=f"{self.scale}x" + ("  grid" if self.show_grid else "")
        )
        self.root.title(
            f"Ticker Emulator - {mode} - {_tc.BACKEND_URL}"
        )

    def _current_mode(self) -> str:
        mode = str(getattr(self.ticker, "mode", "sports") or "sports")
        return mode if mode in MODE_OPTIONS else "sports"

    # ── Actions ────────────────────────────────────────────────────────────────

    def _apply_mode_from_ui(self, mode: str):
        if mode not in MODE_OPTIONS:
            return
        self.mode_var.set(mode)
        self.ticker.set_mode(mode)

    def _cycle_mode(self, delta: int):
        current = self.mode_var.get()
        if current not in MODE_OPTIONS:
            current = self._current_mode()
        idx = MODE_OPTIONS.index(current)
        idx = (idx + delta) % len(MODE_OPTIONS)
        self._apply_mode_from_ui(MODE_OPTIONS[idx])

    def _zoom(self, delta: int):
        if self.scale not in SCALE_OPTIONS:
            self.scale = 4
        idx = SCALE_OPTIONS.index(self.scale)
        idx = max(0, min(len(SCALE_OPTIONS) - 1, idx + delta))
        self.scale = SCALE_OPTIONS[idx]
        self.canvas.config(
            width=PANEL_W * self.scale,
            height=PANEL_H * self.scale,
        )
        # Re-render immediately so the canvas resize feels instant.
        if self.last_frame:
            self._render(self.last_frame)
        self.root.update_idletasks()

    def _toggle_pause(self):
        self.paused = not self.paused

    def _toggle_grid(self):
        self.show_grid = not self.show_grid
        if self.last_frame:
            self._render(self.last_frame)

    def _screenshot(self):
        if not self.last_frame:
            print("No frame to save yet.")
            return
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"ticker_screenshot_{ts}.png"
        # Save the raw 384x32 image (not scaled).
        self.last_frame.save(fname)
        print(f"Screenshot saved: {fname}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sports Ticker desktop emulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--url", default=DEFAULT_URL,
        help=f"Backend URL (default: {DEFAULT_URL})"
    )
    parser.add_argument(
        "--scale", type=int, default=4, choices=SCALE_OPTIONS,
        metavar="{" + ",".join(str(s) for s in SCALE_OPTIONS) + "}",
        help="Zoom factor (default: 4 -> 1536x128 px window)"
    )
    args = parser.parse_args()

    # Patch URL before TickerStreamer.poll_backend thread starts.
    _tc.BACKEND_URL = args.url
    scale = args.scale if args.scale in SCALE_OPTIONS else 4

    print(f"Backend:  {_tc.BACKEND_URL}")
    print(f"Display:  {PANEL_W * scale}x{PANEL_H * scale} px  (scale={scale}x)")
    print(f"Source:   {PANEL_W}x{PANEL_H} LED panel")

    frame_queue: queue.Queue = queue.Queue(maxsize=2)
    ticker = EmulatedTicker(frame_queue=frame_queue)

    root = tk.Tk()
    EmulatorWindow(root, ticker, frame_queue, scale)
    try:
        root.mainloop()
    finally:
        ticker.running = False


if __name__ == "__main__":
    main()
