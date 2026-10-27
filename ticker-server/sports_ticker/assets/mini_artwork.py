"""Prepare bounded, memory-only album artwork for the Mini display."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import struct
from threading import RLock
import time
from urllib.parse import urlparse

from PIL import Image, ImageOps
import requests

from .mini_service import fetch_source
from .music_palette import artwork_colors

SIZE = 32
HEADER = struct.Struct("<4sBBBBHHHH")
WIRE_BYTES = HEADER.size + SIZE * SIZE * 2


def encode_artwork(source: bytes) -> tuple[str, bytes]:
    """Encode a complete square cover without logo transparency or outlines."""
    with Image.open(io.BytesIO(source)) as original:
        if original.width > 2048 or original.height > 2048:
            raise ValueError("artwork dimensions exceed the preparation limit")
        cover = ImageOps.fit(original.convert("RGB"), (SIZE, SIZE), method=Image.Resampling.LANCZOS)
    pixels = bytearray()
    for red, green, blue in cover.getdata():
        pixels.extend(struct.pack("<H", ((red & 248) << 8) | ((green & 252) << 3) | (blue >> 3)))
    body = HEADER.pack(b"MTA1", 1, 1, SIZE, SIZE, len(pixels), 0, 0, 0) + pixels
    return hashlib.sha256(body).hexdigest(), body


class MiniArtworkService:
    """Prepare each requested cover outside API calls and retain bounded RAM data."""

    def __init__(self, *, fetcher=fetch_source, clock=time.monotonic, max_entries=12):
        if max_entries < 1:
            raise ValueError("artwork capacity must be positive")
        self._fetch, self._clock, self._limit = fetcher, clock, max_entries
        self._lock = RLock()
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mini-artwork")
        self._urls = OrderedDict()
        self._bodies = OrderedDict()
        self._pending, self._retry = {}, {}
        self._closed = False

    def reference(self, url: str) -> dict:
        try:
            parsed = urlparse(str(url or ""))
            allowed = parsed.scheme == "https" and parsed.hostname == "i.scdn.co" and not parsed.username and parsed.port in {None, 443}
        except ValueError:
            allowed = False
        if not allowed:
            return {"state": "unavailable"}
        with self._lock:
            identity = self._urls.get(url)
            if identity in self._bodies:
                self._urls.move_to_end(url)
                self._bodies.move_to_end(identity)
                return {"state": "ready", "asset_id": identity, "sha256": identity,
                        "width": SIZE, "height": SIZE, "length": WIRE_BYTES,
                        "format": "rgb565-le", "pipeline_version": 1,
                        "accent_rgb": list(self._bodies[identity][1]),
                        "url": f"/api/v2/assets/mini-artwork/{identity}.mta"}
            if not self._closed and url not in self._pending and len(self._pending) < self._limit and self._clock() >= self._retry.get(url, 0):
                self._pending[url] = self._worker.submit(self._prepare, url)
            return {"state": "pending" if url in self._pending else "unavailable"}

    def music_references(self, music: dict) -> dict:
        """Prepare the current cover, three queued covers, and one previous cover."""
        current = self.reference(str(music.get("cover") or ""))
        queued = music.get("next_covers")
        upcoming = [self.reference(str(url or "")) for url in queued[:3]] if isinstance(queued, list) else []
        previous = self.reference(str(music.get("last_cover") or ""))
        return {"cover_asset": current, "next_cover_assets": upcoming, "last_cover_asset": previous}

    def _prepare(self, url):
        try:
            reply = self._fetch(url, "", "")
            if not reply.body or len(reply.body) > 256 * 1024:
                raise ValueError("invalid artwork source size")
            identity, body = encode_artwork(reply.body)
            with Image.open(io.BytesIO(reply.body)) as original:
                accent, _ = artwork_colors(ImageOps.fit(original.convert("RGB"), (42, 42)))
            with self._lock:
                self._urls[url] = identity
                self._bodies[identity] = (body, accent)
                self._retry.pop(url, None)
                while len(self._urls) > self._limit:
                    self._urls.popitem(last=False)
                while len(self._bodies) > self._limit:
                    self._bodies.popitem(last=False)
        except (OSError, ValueError, requests.RequestException):
            with self._lock:
                self._retry[url] = self._clock() + 30
                while len(self._retry) > self._limit:
                    self._retry.pop(next(iter(self._retry)))
        finally:
            with self._lock:
                self._pending.pop(url, None)

    def read(self, identity):
        if not isinstance(identity, str) or len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
            return None
        with self._lock:
            entry = self._bodies.get(identity)
            return (entry[0], identity) if entry else None

    def wait(self):
        with self._lock:
            futures = tuple(self._pending.values())
        for future in futures:
            future.result()

    def close(self):
        with self._lock:
            self._closed = True
        self._worker.shutdown(wait=True)
