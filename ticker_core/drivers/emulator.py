"""Optional Tk desktop display output."""

from __future__ import annotations

import queue
import threading
from typing import Any

from PIL import Image

from .memory import MemoryFrameSink, _brightness, _prepare_frame


class TkFrameSink(MemoryFrameSink):
    """Mirror frames in a Tk window when Tk is installed."""

    def __init__(self, width: int = 384, height: int = 32, scale: int = 3) -> None:
        super().__init__(width, height)
        if scale <= 0:
            raise ValueError("Emulator scale must be positive.")
        self._scale = scale
        self._frames: queue.Queue[Image.Image] = queue.Queue(maxsize=1)
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._failed = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the emulator worker after the application owns it."""
        if self._thread is not None or self._failed:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="ticker-emulator")
        self._thread.start()
        self._ready.wait(timeout=1.0)

    def close(self) -> None:
        """Stop the emulator worker during application shutdown."""
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        self._thread = None

    def present(
        self,
        image: Image.Image,
        *,
        brightness: int = 100,
        inverted: bool = False,
    ) -> None:
        self.start()
        frame = _prepare_frame(image, self.width, self.height, inverted)
        self.brightness = _brightness(brightness)
        self.inverted = inverted
        self.last_image = frame
        if self._failed:
            return
        try:
            self._frames.get_nowait()
        except queue.Empty:
            pass
        try:
            self._frames.put_nowait(frame)
        except queue.Full:
            pass

    def _run(self) -> None:
        try:
            import tkinter as tk
            from PIL import ImageTk
            root = tk.Tk()
            root.title("Ticker Emulator")
            canvas = tk.Canvas(root, width=self.width * self._scale, height=self.height * self._scale)
            canvas.pack()
        except Exception:
            self._failed = True
            self._ready.set()
            return
        photo: Any = None

        def draw() -> None:
            if self._stop.is_set():
                root.destroy()
                return
            nonlocal photo
            try:
                frame = self._frames.get_nowait()
            except queue.Empty:
                pass
            else:
                enlarged = frame.resize((self.width * self._scale, self.height * self._scale), Image.Resampling.NEAREST)
                photo = ImageTk.PhotoImage(enlarged)
                canvas.create_image(0, 0, anchor="nw", image=photo)
            root.after(16, draw)

        self._ready.set()
        root.after(0, draw)
        root.mainloop()
