"""Server-side NASCAR carbadge proxy — fetches, resizes, and caches badge PNGs.

The Pi fetches /api/nascar/badge/<num>.png from its own backend server
instead of hitting cf.nascar.com directly.  The server caches each badge
in memory after the first request so subsequent Pi renders are instant.
"""

import io
import threading

import requests
from flask import Response

from ..routes_runtime import app

_CF_BADGE_BASE = "https://cf.nascar.com/data/images/carbadges/1"
_BADGE_TARGET  = (32, 32)       # pre-resized to fit the LED card height
_BADGE_CACHE: dict[int, bytes] = {}
_BADGE_LOCK = threading.Lock()


def _fetch_and_resize(num: int) -> bytes | None:
    with _BADGE_LOCK:
        if num in _BADGE_CACHE:
            return _BADGE_CACHE[num]
    try:
        from PIL import Image
        r = requests.get(f"{_CF_BADGE_BASE}/{num}.png", timeout=8)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        img.thumbnail(_BADGE_TARGET, Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        data = buf.getvalue()
        with _BADGE_LOCK:
            _BADGE_CACHE[num] = data
        print(f"[nascar_badge] cached #{num} ({len(data)} bytes)")
        return data
    except Exception as exc:
        print(f"[nascar_badge] fetch failed #{num}: {exc}")
        return None


@app.route("/api/nascar/badge/<int:num>.png")
@app.route("/api/nascar/badge/<int:num>")
def nascar_carbadge(num: int):
    data = _fetch_and_resize(num)
    if data is None:
        return Response(status=404)
    resp = Response(data, mimetype="image/png")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp
