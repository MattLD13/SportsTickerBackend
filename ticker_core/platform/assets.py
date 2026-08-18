"""Persistent source storage and asynchronous asset coordination."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
import threading
import time
from typing import Protocol
from uuid import uuid4

from PIL import Image

from ticker_core.assets import AssetPlanner, AssetRequest, AssetView, PreparedAssetStore, prepare_car, prepare_contained, prepare_imsa_car, prepare_nascar_car


class AssetFetcher(Protocol):
    """Fetch original asset bytes for one URL."""

    def __call__(self, url: str) -> bytes | None:
        """Return response bytes or no result."""


def _asset_ttl_seconds(url: str) -> float:
    """Return cache TTL based on series livery change frequency."""
    lowered = str(url or "").lower()
    if any(k in lowered for k in ("nascar.com", "indycar.com", "indycar.blob.core.windows.net")):
        return 7 * 86400.0  # 1 week for race-by-race NASCAR and IndyCar liveries
    return 300 * 86400.0  # 300 days (season-long) for IMSA, WEC, F1, and general assets


class PersistentAssetStore:
    """Retain original downloaded bytes across process restarts with series-aware TTL."""

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)

    def load(self, url: str, *, now: float | None = None, ignore_expiry: bool = False) -> bytes | None:
        """Return the latest verified original bytes for one URL if within TTL (or if ignore_expiry is True)."""
        metadata = self._metadata_path(url)
        try:
            details = json.loads(metadata.read_text(encoding="utf-8"))
            content_hash = str(details["content_hash"])
            saved_at = float(details.get("saved_at", 0.0))
            ttl = _asset_ttl_seconds(url)
            current_time = now if now is not None else time.time()
            if not ignore_expiry and saved_at > 0 and current_time - saved_at > ttl:
                return None
            path = self.directory / "originals" / self._url_hash(url) / f"{content_hash}.bin"
            raw = path.read_bytes()
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if sha256(raw).hexdigest() != content_hash:
            return None
        return raw

    def store(self, url: str, raw: bytes, *, now: float | None = None) -> Path:
        """Atomically store original bytes and their URL index with timestamp."""
        content_hash = sha256(raw).hexdigest()
        folder = self.directory / "originals" / self._url_hash(url)
        target = folder / f"{content_hash}.bin"
        folder.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            self._atomic_write(target, raw)
        current_time = now if now is not None else time.time()
        self._atomic_write(
            self._metadata_path(url),
            json.dumps({"url": url, "content_hash": content_hash, "saved_at": current_time}, separators=(",", ":")).encode("utf-8"),
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
        self.prepared = prepared or PreparedAssetStore(directory=Path(directory) / "prepared")

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
            "imsa_car": prepare_imsa_car,
            "nascar_car": prepare_nascar_car,
        }
        self._workers = workers
        self._executor: ThreadPoolExecutor | None = None
        self._inflight: dict[AssetRequest, Future[Image.Image | None]] = {}
        self._lock = threading.Lock()

    @property
    def directory(self) -> Path:
        """Return the durable root used by isolated prepared-asset readers."""
        return self.long_term.originals.directory

    @property
    def revision(self) -> int:
        """Return the prepared-image revision for renderer caches."""
        return self.long_term.revision

    def image(self, url: str, processor: str, size: tuple[int, int]) -> Image.Image | None:
        """Return a prepared image if one exists in memory."""
        return self.long_term.prepared.get_memory(AssetRequest(url, processor, size))

    def plan(self, item: Mapping[str, object]) -> tuple[AssetRequest, ...]:
        """Extract needed asset requests from one content item."""
        return self._planner.plan(item)

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
        if self.long_term.prepared.contains_memory(request):
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
        # Persistent images are decoded in this worker. The display loop only
        # sees already prepared memory images.
        if self.long_term.prepared.contains(request):
            return self.long_term.prepared.get(request)
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
            else:
                raw = self.long_term.originals.load(request.url, ignore_expiry=True)
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

    referer = (
        "https://www.nascar.com/"
        if "nascar.com" in url
        else (
            "https://www.imsa.com/"
            if "imsa.com" in url
            else ("https://www.fiawec.com/" if "fiawec.com" in url else "https://www.google.com/")
        )
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": referer,
    }
    try:
        response = requests.get(url, headers=headers, timeout=6)
        return response.content if response.status_code == 200 else None
    except Exception:
        return None
