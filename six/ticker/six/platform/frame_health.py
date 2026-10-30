"""Record successful display presentation outside immutable releases."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from collections.abc import Mapping
from typing import Callable

from PIL import Image
from ticker.panel.content import FrameKind


class PresentedFrameHealth:
    """Write one atomic receipt after a valid frame reaches the output driver."""

    def __init__(self, path: Path, release: Path, *, clock: Callable[[], float] = time.time) -> None:
        self.path = path
        self.release = release.resolve()
        self.clock = clock
        self.recorded = False
        self.next_attempt = 0.0

    def record(self, image: Image.Image, kind: FrameKind) -> None:
        now = self.clock()
        if self.recorded or now < self.next_attempt:
            return
        if image.size != (384, 32):
            return
        pixels = image.convert("RGB")
        blank = pixels.getbbox() is None
        if blank and kind != FrameKind.SLEEP:
            return
        value = {"pid": os.getpid(), "release": str(self.release), "recorded_at": now,
                 "width": 384, "height": 32, "kind": str(kind), "blank": blank,
                 "sha256": hashlib.sha256(pixels.tobytes()).hexdigest()}
        temporary = self.path.with_name(self.path.name + ".next")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
            os.replace(temporary, self.path)
            self.recorded = True
        except OSError:
            self.next_attempt = now + 5
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def receipt_matches(value: object, release: Path, pid: int, not_before: float) -> bool:
    """Reject stale, foreign-process, wrong-release, and malformed frame receipts."""
    if not isinstance(value, Mapping):
        return False
    try:
        return (pid > 0 and value.get("pid") == pid and value.get("release") == str(release.resolve())
                and float(value.get("recorded_at", 0)) >= not_before
                and (value.get("width"), value.get("height")) == (384, 32)
                and isinstance(value.get("sha256"), str) and len(bytes.fromhex(value["sha256"])) == 32
                and (value.get("blank") is False or value.get("kind") == str(FrameKind.SLEEP)))
    except (TypeError, ValueError):
        return False
