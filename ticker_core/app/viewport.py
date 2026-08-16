"""Render a scrolling viewport from independent card surfaces."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Mapping
from concurrent.futures import Executor, Future, ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from multiprocessing import get_context
import os
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from PIL import Image, ImageDraw

from ticker_core.context import RenderContext
from ticker_core.rendering import ContentRendererCatalog, ContentScene
from ticker_core.runtime import Content, StripLayout, StripSegment


@dataclass(frozen=True, slots=True)
class _CardRequest:
    """Describe one card image that a worker must render."""

    item: Content
    mode: str
    context: RenderContext
    asset_generation: int
    generation: int


@dataclass(frozen=True, slots=True)
class _CardSurface:
    """Hold one completed card image and its render revision."""

    item_id: str
    image: Image.Image
    scene: Mapping[str, Any]
    mode: str
    asset_generation: int


@dataclass(frozen=True, slots=True)
class _CardJob:
    """Carry one serializable renderer scene to a card worker."""

    item_id: str
    scene: dict[str, Any]
    mode: str
    context: RenderContext


@dataclass(frozen=True, slots=True)
class _CardPixels:
    """Carry one rendered RGBA card across a worker boundary."""

    width: int
    height: int
    rgba: bytes


class CardViewport:
    """Own scrolling card surfaces without building one long strip image."""

    def __init__(
        self,
        catalog: ContentRendererCatalog,
        *,
        use_process: bool = False,
        asset_directory: Path | str | None = None,
        worker_cpu: int | None = None,
        issue_handler: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self._catalog = catalog
        self._use_process = use_process and asset_directory is not None
        self._asset_directory = Path(asset_directory) if asset_directory is not None else None
        self._worker_cpu = worker_cpu
        self._issue_handler = issue_handler
        self._lock = Lock()
        self._worker: Executor
        self._render_job: Callable[[_CardJob], _CardPixels]
        if self._use_process:
            self._worker = ProcessPoolExecutor(
                max_workers=1,
                mp_context=get_context("spawn"),
                initializer=_initialize_process_catalog,
                initargs=(str(asset_directory), worker_cpu),
            )
            self._render_job = _render_process_job
        else:
            self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ticker-card")
            self._render_job = self._render_local_job
        self._future: Future[_CardPixels] | None = None
        self._active_request: _CardRequest | None = None
        self._pending: OrderedDict[str, _CardRequest] = OrderedDict()
        self._desired: dict[str, _CardRequest] = {}
        self._order: tuple[str, ...] = ()
        self._surfaces: dict[str, _CardSurface] = {}
        self._staging_surfaces: dict[str, _CardSurface] = {}
        self._generation = 0
        self._staging_generation = 0
        self._staging_successes: set[str] = set()
        self._failed = 0
        self._worker_retries: set[tuple[int, str]] = set()
        self._layout: StripLayout | None = None
        self._asset_generation = 0

    @property
    def layout(self) -> StripLayout | None:
        """Return current card geometry without image composition."""
        with self._lock:
            return self._layout

    @property
    def status(self) -> Mapping[str, int]:
        """Return readiness facts for the current viewport generation."""
        with self._lock:
            pending = len(self._pending) + int(self._future is not None)
            return {
                "desired": len(self._desired),
                "pending": pending,
                "ready": len(self._staging_surfaces),
                "failed": self._failed,
                "committed_generation": self._generation,
                "staging_generation": self._staging_generation,
            }

    def set_issue_handler(self, handler: Callable[[Mapping[str, Any]], None] | None) -> None:
        """Install the application-owned issue sink after composition."""
        with self._lock:
            self._issue_handler = handler

    def update(self, items: Iterable[Content], context: RenderContext, mode: str) -> StripLayout | None:
        """Queue only cards whose full renderer scene changed."""
        content = tuple(items)[:60]
        requests = tuple(
            _CardRequest(item, mode, context, self._asset_generation, self._staging_generation + 1)
            for item in content
        )
        with self._lock:
            self._staging_generation += 1
            generation = self._staging_generation
            requests = tuple(
                _CardRequest(request.item, request.mode, request.context, request.asset_generation, generation)
                for request in requests
            )
            self._order = tuple(request.item.id for request in requests)
            self._desired = {request.item.id: request for request in requests}
            self._staging_surfaces = {
                item_id: surface for item_id, surface in self._surfaces.items()
                if item_id in self._desired
            }
            self._staging_successes = set()
            self._failed = 0
            self._worker_retries.clear()
            self._pending.clear()
            for request in requests:
                current = self._staging_surfaces.get(request.item.id)
                active = self._active_request
                if current is not None and _matches(request, current):
                    continue
                if active is not None and _same_work_request(active, request):
                    continue
                self._pending[request.item.id] = request
            self._start_next()
            self._maybe_commit()
            return self._layout

    def install_completed(self) -> StripLayout | None:
        """Commit one completed card at a frame boundary."""
        with self._lock:
            future = self._future
            request = self._active_request
            if future is None or request is None or not future.done():
                return None
            self._future = None
            self._active_request = None
        try:
            surface = future.result()
        except Exception as error:
            surface = None
            with self._lock:
                if request.generation == self._staging_generation:
                    self._failed += 1
                self._report_failure(request, error)
                if isinstance(error, BrokenProcessPool):
                    self._restart_worker_locked()
                    self._queue_worker_retry_locked(request)
        with self._lock:
            desired = self._desired.get(request.item.id)
            if surface is not None and desired is not None and request.generation == self._staging_generation:
                card = _CardSurface(
                    request.item.id,
                    Image.frombytes("RGBA", (surface.width, surface.height), surface.rgba),
                    request.item.data,
                    request.mode,
                    request.asset_generation,
                )
                if _matches(desired, card):
                    self._staging_surfaces[card.item_id] = card
                    self._staging_successes.add(card.item_id)
            self._start_next()
            before = self._layout
            self._maybe_commit()
            return self._layout if self._layout != before else None

    def invalidate(self) -> None:
        """Queue new card surfaces after prepared assets change."""
        with self._lock:
            self._asset_generation += 1
            self._staging_generation += 1
            generation = self._staging_generation
            current = tuple(self._desired.values())
            refreshed = tuple(
                _CardRequest(
                    request.item,
                    request.mode,
                    request.context,
                    self._asset_generation,
                    generation,
                )
                for request in current
            )
            self._desired = {request.item.id: request for request in refreshed}
            self._staging_surfaces = {
                item_id: surface for item_id, surface in self._surfaces.items()
                if item_id in self._desired
            }
            self._staging_successes = set()
            self._failed = 0
            self._worker_retries.clear()
            self._pending = OrderedDict((request.item.id, request) for request in refreshed)
            self._start_next()
            self._maybe_commit()

    def frame(self, offset: int, width: int = 384, height: int = 32) -> Image.Image:
        """Build one viewport from only cards visible at this offset."""
        with self._lock:
            layout = self._layout
            surfaces = dict(self._surfaces)
            order = self._order
        image = Image.new("RGB", (width, height), "black")
        if layout is None or not order:
            return image
        position = offset % layout.width
        start = 0
        index = 0
        for index, segment in enumerate(layout.segments):
            if start + segment.width > position:
                break
            start += segment.width
        x = start - position
        draw = ImageDraw.Draw(image)
        while x < width:
            segment = layout.segments[index % len(layout.segments)]
            surface = surfaces.get(segment.item_id)
            draw.line((x, 0, x, height - 1), fill=(45, 45, 45))
            if surface is not None:
                image.paste(surface.image, (x + 1, 0), surface.image)
            x += segment.width
            index += 1
        return image

    def close(self) -> None:
        """Stop the owned card renderer."""
        self._worker.shutdown(wait=True, cancel_futures=True)

    def _start_next(self) -> None:
        if self._future is not None:
            return
        while self._pending:
            _, request = self._pending.popitem(last=False)
            desired = self._desired.get(request.item.id)
            if desired is None or not _same_work_request(desired, request):
                continue
            self._active_request = request
            job = _CardJob(request.item.id, _content_mapping(request.item), request.mode, request.context)
            try:
                self._future = self._worker.submit(self._render_job, job)
                return
            except BrokenProcessPool as error:
                self._active_request = None
                self._report_failure(request, error)
                self._restart_worker_locked()
                if self._queue_worker_retry_locked(request):
                    continue
                if request.generation == self._staging_generation:
                    self._failed += 1
                self._maybe_commit()
                return

    def _queue_worker_retry_locked(self, request: _CardRequest) -> bool:
        """Requeue one current request once after a broken worker."""
        if request.generation != self._staging_generation:
            return False
        desired = self._desired.get(request.item.id)
        if desired is None or not _same_work_request(desired, request):
            return False
        retry_key = (request.generation, request.item.id)
        if retry_key in self._worker_retries:
            return False
        self._worker_retries.add(retry_key)
        pending = OrderedDict([(request.item.id, request)])
        pending.update(self._pending)
        self._pending = pending
        return True

    def _layout_now(self, surfaces: Mapping[str, _CardSurface] | None = None) -> StripLayout | None:
        active_surfaces = self._surfaces if surfaces is None else surfaces
        item_ids = tuple(item_id for item_id in self._order if item_id in active_surfaces)
        if not item_ids:
            return None
        segments = tuple(
            StripSegment(item_id, active_surfaces[item_id].image.width + 1)
            for item_id in item_ids
        )
        return StripLayout(sum(segment.width for segment in segments), segments)

    def _maybe_commit(self) -> None:
        if self._future is not None or self._pending:
            return
        if not self._desired:
            self._surfaces = {}
            self._layout = None
            self._generation = self._staging_generation
            return
        all_ready = all(
            item_id in self._staging_surfaces
            and _matches(self._desired[item_id], self._staging_surfaces[item_id])
            for item_id in self._desired
        )
        if not self._staging_surfaces and not all_ready:
            return
        committed = {
            item_id: surface for item_id, surface in self._staging_surfaces.items()
            if item_id in self._desired
            and (_matches(self._desired[item_id], surface) or item_id not in self._staging_successes)
        }
        layout = self._layout_now(committed)
        if layout is None:
            return
        self._surfaces = committed
        self._layout = layout
        self._generation = self._staging_generation

    def _restart_worker_locked(self) -> None:
        old_worker = self._worker
        old_worker.shutdown(wait=False, cancel_futures=True)
        if self._use_process:
            assert self._asset_directory is not None
            self._worker = ProcessPoolExecutor(
                max_workers=1,
                mp_context=get_context("spawn"),
                initializer=_initialize_process_catalog,
                initargs=(str(self._asset_directory), self._worker_cpu),
            )
            self._render_job = _render_process_job
        else:
            self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ticker-card")
            self._render_job = self._render_local_job

    def _report_failure(self, request: _CardRequest, error: BaseException) -> None:
        handler = self._issue_handler
        if handler is None:
            return
        details = {
            "source": "card_renderer",
            "item_id": request.item.id,
            "family": str(request.item.data.get("family", request.item.sport)),
            "kind": str(request.item.data.get("kind", request.item.type)),
            "mode": request.mode,
            "generation": request.generation,
            "error_type": type(error).__name__,
            "error": str(error)[:500],
        }
        try:
            handler(details)
        except Exception:
            pass

    def _render_local_job(self, job: _CardJob) -> _CardPixels:
        """Render through the injected catalog in test and desktop processes."""
        return _render_catalog_job(self._catalog, job)


def _same_work_request(left: _CardRequest, right: _CardRequest) -> bool:
    """Return if two worker requests use the same immutable scene."""
    return (
        left.item.id == right.item.id
        and left.item.data is right.item.data
        and left.mode == right.mode
        and left.asset_generation == right.asset_generation
        and left.generation == right.generation
    )


def _matches(request: _CardRequest, surface: _CardSurface) -> bool:
    """Return if one card surface matches a renderer scene exactly."""
    return (
        request.item.id == surface.item_id
        and request.item.data is surface.scene
        and request.mode == surface.mode
        and request.asset_generation == surface.asset_generation
    )


_PROCESS_CATALOG: ContentRendererCatalog | None = None


def _initialize_process_catalog(asset_directory: str, worker_cpu: int | None) -> None:
    """Start a clean worker with read-only prepared assets and no inherited locks."""
    from ticker_core.bootstrap import create_default_content_catalog
    from ticker_core.platform.assets import LongTermAssetCache

    global _PROCESS_CATALOG
    _pin_worker_cpu(worker_cpu)
    _PROCESS_CATALOG = create_default_content_catalog(LongTermAssetCache(asset_directory))


def _pin_worker_cpu(cpu: int | None) -> None:
    """Move the separate card worker away from the display CPU when configured."""
    if cpu is None or not hasattr(os, "sched_setaffinity"):
        return
    try:
        os.sched_setaffinity(0, {cpu})
    except OSError:
        return


def _render_process_job(job: _CardJob) -> _CardPixels:
    """Render one card in the isolated process catalog."""
    if _PROCESS_CATALOG is None:
        raise RuntimeError("The card renderer process has no catalog.")
    return _render_catalog_job(_PROCESS_CATALOG, job)


def _render_catalog_job(catalog: ContentRendererCatalog, job: _CardJob) -> _CardPixels:
    """Render one serializable scene and return only pixel data."""
    rendered = catalog.render(job.context, ContentScene(job.scene, job.mode))
    image = rendered.image.convert("RGBA")
    return _CardPixels(image.width, image.height, image.tobytes())


def _plain_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Copy immutable protocol mappings for the renderer worker."""
    return {str(key): _plain(item) for key, item in value.items()}


def _content_mapping(content: Content) -> dict[str, Any]:
    """Expose explicit content identity and family facts to the card worker."""
    data = _plain_mapping(content.data)
    data.setdefault("id", content.id)
    data.setdefault("type", content.type)
    data.setdefault("sport", content.sport)
    return data


def _plain(value: Any) -> Any:
    """Convert immutable protocol values into JSON-compatible objects."""
    if isinstance(value, Mapping):
        return _plain_mapping(value)
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value
