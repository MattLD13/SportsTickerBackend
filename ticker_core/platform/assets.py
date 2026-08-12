"""Persistent source storage and asynchronous asset coordination."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
import threading
from typing import Protocol
from uuid import uuid4

from PIL import Image

from ticker_core.assets import AssetPlanner, AssetRequest, AssetView, PreparedAssetStore, prepare_car, prepare_contained


class AssetFetcher(Protocol):
    """Fetch original asset bytes for one URL."""

    def __call__(self, url: str) -> bytes | None:
        """Return response bytes or no result."""


class PersistentAssetStore:
    """Retain original downloaded bytes across process restarts."""

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)

    def load(self, url: str) -> bytes | None:
        """Return the latest verified original bytes for one URL."""
        metadata = self._metadata_path(url)
        try:
            details = json.loads(metadata.read_text(encoding="utf-8"))
            content_hash = str(details["content_hash"])
            path = self.directory / "originals" / self._url_hash(url) / f"{content_hash}.bin"
            raw = path.read_bytes()
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if sha256(raw).hexdigest() != content_hash:
            return None
        return raw

    def store(self, url: str, raw: bytes) -> Path:
        """Atomically store original bytes and their URL index."""
        content_hash = sha256(raw).hexdigest()
        folder = self.directory / "originals" / self._url_hash(url)
        target = folder / f"{content_hash}.bin"
        folder.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            self._atomic_write(target, raw)
        self._atomic_write(
            self._metadata_path(url),
            json.dumps({"url": url, "content_hash": content_hash}, separators=(",", ":")).encode("utf-8"),
        )
        return target

    def _metadata_path(self, url: str) -> Path:
        return self.directory / "indexes" / f"{self._url_hash(url)}.json"

    @staticmethod
    def _url_hash(url: str) -> str:
        return sha256(url.encode("utf-8")).hexdigest()

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)


class LongTermAssetCache(AssetView):
    """Own reusable source bytes and decoded image variants."""

    def __init__(self, directory: Path | str, *, prepared: PreparedAssetStore | None = None) -> None:
        self.originals = PersistentAssetStore(directory)
        self.prepared = prepared or PreparedAssetStore()

    @property
    def revision(self) -> int:
        """Return the decoded image revision."""
        return self.prepared.revision

    def image(self, url: str, processor: str, size: tuple[int, int]) -> Image.Image | None:
        """Return a decoded image through the bounded working cache."""
        return self.prepared.get(AssetRequest(url, processor, size))


class AssetCoordinator(AssetView):
    """Plan, fetch, persist, and prepare every payload asset once."""

    def __init__(
        self,
        directory: Path | str,
        *,
        fetch: AssetFetcher | None = None,
        planner: AssetPlanner | None = None,
        prepared: PreparedAssetStore | None = None,
        workers: int = 4,
    ) -> None:
        if workers <= 0:
            raise ValueError("Asset worker count must be positive.")
        self.long_term = LongTermAssetCache(directory, prepared=prepared)
        self._fetch = fetch or _fetch_with_requests
        self._planner = planner or AssetPlanner()
        self._processors: Mapping[str, Callable[[bytes, tuple[int, int]], Image.Image]] = {
            "logo": prepare_contained,
            "artwork": prepare_contained,
            "image": prepare_contained,
            "car": prepare_car,
        }
        self._workers = workers
        self._executor: ThreadPoolExecutor | None = None
        self._inflight: dict[AssetRequest, Future[Image.Image | None]] = {}
        self._lock = threading.Lock()

    @property
    def revision(self) -> int:
        """Return the prepared-image revision for renderer caches."""
        return self.long_term.revision

    def image(self, url: str, processor: str, size: tuple[int, int]) -> Image.Image | None:
        """Return a prepared memory image without doing any I/O."""
        return self.long_term.image(url, processor, size)

    def prefetch_payload(self, payload_or_content: object) -> tuple[Future[Image.Image | None], ...]:
        """Plan and prefetch all assets before a mode chooses content."""
        return self.prefetch(self._planner.plan(payload_or_content).requests)

    def start(self) -> None:
        """Start asset workers after the application owns their lifetime."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self._workers, thread_name_prefix="ticker-assets")

    def prefetch(self, requests: Iterable[AssetRequest]) -> tuple[Future[Image.Image | None], ...]:
        """Schedule unique asset preparation work without waiting for it."""
        self.start()
        return tuple(self._schedule(request) for request in dict.fromkeys(requests))

    def close(self) -> None:
        """Finish queued work and stop coordinator workers."""
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=False)
            self._executor = None

    def _schedule(self, request: AssetRequest) -> Future[Image.Image | None]:
        if self.long_term.prepared.contains(request):
            done: Future[Image.Image | None] = Future()
            done.set_result(self.long_term.prepared.get(request))
            return done
        with self._lock:
            existing = self._inflight.get(request)
            if existing is not None:
                return existing
            executor = self._executor
            if executor is None:
                raise RuntimeError("Asset workers are not running.")
            future = executor.submit(self._prepare, request)
            self._inflight[request] = future
            future.add_done_callback(lambda complete: self._complete(request, complete))
            return future

    def _complete(self, request: AssetRequest, complete: Future[Image.Image | None]) -> None:
        with self._lock:
            if self._inflight.get(request) is complete:
                del self._inflight[request]

    def _prepare(self, request: AssetRequest) -> Image.Image | None:
        raw = self.long_term.originals.load(request.url)
        if raw is None:
            try:
                raw = self._fetch(request.url)
            except Exception:
                raw = None
            if raw:
                try:
                    self.long_term.originals.store(request.url, raw)
                except OSError:
                    pass
        processor = self._processors.get(request.processor)
        if not raw or processor is None:
            self.long_term.prepared.put(request, None)
            return None
        try:
            image = processor(raw, request.size)
        except (OSError, ValueError):
            image = None
        self.long_term.prepared.put(request, image)
        return image


def _fetch_with_requests(url: str) -> bytes | None:
    """Fetch bytes with requests only when the coordinator needs them."""
    import requests

    response = requests.get(url, headers={"User-Agent": "SportsTicker/2"}, timeout=5)
    return response.content if response.status_code == 200 else None
