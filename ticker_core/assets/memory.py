"""Bounded in-memory prepared image storage."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
import io
import os
from pathlib import Path
from threading import RLock
from time import monotonic
from uuid import uuid4

from PIL import Image

from .model import AssetRequest, AssetView


@dataclass(slots=True)
class _Entry:
    image: Image.Image | None
    expires_at: float


class PreparedAssetStore(AssetView):
    """Keep prepared images until LRU eviction and negative results briefly."""

    def __init__(
        self,
        *,
        capacity: int = 512,
        ttl: float | None = None,
        negative_ttl: float = 15.0,
        clock: Callable[[], float] = monotonic,
        directory: Path | str | None = None,
    ) -> None:
        if capacity <= 0:
            raise ValueError("Asset memory capacity must be positive.")
        if (ttl is not None and ttl < 0) or negative_ttl < 0:
            raise ValueError("Asset time limits cannot be negative.")
        self._capacity = capacity
        self._ttl = float("inf") if ttl is None else ttl
        self._negative_ttl = negative_ttl
        self._clock = clock
        self._directory = Path(directory) if directory is not None else None
        if self._directory is not None:
            self._directory.mkdir(parents=True, exist_ok=True)
        self._items: OrderedDict[AssetRequest, _Entry] = OrderedDict()
        self._revision = 0
        self._lock = RLock()

    @property
    def revision(self) -> int:
        """Return the current prepared-image revision."""
        with self._lock:
            return self._revision

    def image(self, url: str, processor: str, size: tuple[int, int]) -> Image.Image | None:
        """Return one prepared image without starting I/O."""
        return self.get(AssetRequest(url, processor, size))

    def get(self, request: AssetRequest) -> Image.Image | None:
        """Return a prepared image or a fresh negative result."""
        with self._lock:
            entry = self._items.get(request)
            if entry is None:
                image = self._load_disk(request)
                if image is None:
                    return None
                self._remember(request, image)
                return image
            if self._expired(request, entry):
                return None
            self._items.move_to_end(request)
            return entry.image

    def get_memory(self, request: AssetRequest) -> Image.Image | None:
        """Return a prepared image without reading durable storage."""
        with self._lock:
            entry = self._items.get(request)
            if entry is None:
                return None
            if self._expired(request, entry):
                return None
            self._items.move_to_end(request)
            return entry.image

    def contains(self, request: AssetRequest) -> bool:
        """Return if a fresh positive or negative entry exists."""
        with self._lock:
            entry = self._items.get(request)
            if entry is None:
                image = self._load_disk(request)
                if image is None:
                    return False
                self._remember(request, image)
                return True
            if self._expired(request, entry):
                return False
            self._items.move_to_end(request)
            return True

    def contains_memory(self, request: AssetRequest) -> bool:
        """Return if a fresh result is already available without disk access."""
        with self._lock:
            entry = self._items.get(request)
            if entry is None:
                return False
            if self._expired(request, entry):
                return False
            self._items.move_to_end(request)
            return True

    def put(self, request: AssetRequest, image: Image.Image | None) -> None:
        """Store a prepared image or a short-lived negative result."""
        with self._lock:
            previous = self._items.get(request)
            previous_ready = previous is not None and not self._is_expired(previous) and previous.image is not None
            lifetime = self._ttl if image is not None else self._negative_ttl
            prepared = image.convert("RGBA") if image is not None else None
            self._items[request] = _Entry(prepared, self._clock() + lifetime)
            if prepared is not None:
                self._write_disk(request, prepared)
            self._items.move_to_end(request)
            self._trim()
            if previous_ready != (prepared is not None):
                self._revision += 1

    def _remember(self, request: AssetRequest, image: Image.Image) -> None:
        """Add one persistent image to the in-memory working set."""
        with self._lock:
            previous = self._items.get(request)
            previous_ready = previous is not None and not self._is_expired(previous) and previous.image is not None
            self._items[request] = _Entry(image, self._clock() + self._ttl)
            self._items.move_to_end(request)
            self._trim()
            if not previous_ready:
                self._revision += 1

    def _expired(self, request: AssetRequest, entry: _Entry) -> bool:
        """Remove one expired entry and signal only a lost prepared image."""
        if entry.expires_at >= self._clock():
            return False
        del self._items[request]
        if entry.image is not None:
            self._revision += 1
        return True

    def _is_expired(self, entry: _Entry) -> bool:
        """Return whether one entry lifetime ended without changing state."""
        return entry.expires_at < self._clock()

    def _trim(self) -> None:
        """Keep the bounded working set bounded."""
        while len(self._items) > self._capacity:
            self._items.popitem(last=False)

    def _path(self, request: AssetRequest) -> Path | None:
        if self._directory is None:
            return None
        identity = f"{request.url}\0{request.processor}\0{request.size[0]}x{request.size[1]}".encode("utf-8")
        return self._directory / f"{sha256(identity).hexdigest()}.png"

    def _load_disk(self, request: AssetRequest) -> Image.Image | None:
        path = self._path(request)
        if path is None:
            return None
        try:
            with Image.open(path) as image:
                return image.convert("RGBA")
        except (OSError, ValueError):
            return None

    def _write_disk(self, request: AssetRequest, image: Image.Image) -> None:
        path = self._path(request)
        if path is None:
            return
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        output = io.BytesIO()
        try:
            image.save(output, format="PNG", optimize=True)
            temporary.write_bytes(output.getvalue())
            os.replace(temporary, path)
        except OSError:
            pass
        finally:
            temporary.unlink(missing_ok=True)


class MemoryAssetView(PreparedAssetStore):
    """Provide explicit test helpers over the shared memory store."""

    def put_image(self, url: str, processor: str, size: tuple[int, int], image: Image.Image) -> None:
        """Store one already-prepared test image."""
        self.put(AssetRequest(url, processor, size), image)
