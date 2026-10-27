"""Render a scrolling window from cached panes and an incrementally updated strip."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Mapping
from concurrent.futures import Executor, Future, ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from multiprocessing import get_context
from pathlib import Path
from threading import Lock
from time import monotonic
from types import MappingProxyType
from typing import Any, Callable

from PIL import Image, ImageChops

from ticker_core.context import RenderContext
from ticker_core.rendering import ContentRendererCatalog, ContentScene
from ticker_core.rendering.catalog import content_family
from ticker_core.rendering.strip import compose_pane_strip
from ticker_core.rendering.style import pane_divider_colors
from ticker_core.rendering.values import plain_mapping as _plain_mapping
from ticker_core.platform.affinity import pin_to_cpu
from ticker_core.runtime import Content, StripLayout, StripSegment
from ticker_core.platform.panes import asset_signatures


@dataclass(frozen=True, slots=True)
class _CardRequest:
    """Describe one card image that a worker must render."""

    item: Content
    mode: str
    context: RenderContext
    asset_generation: int
    generation: int
    scene: Mapping[str, Any] = field(init=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "scene", _scene_mapping(self.item))


@dataclass(frozen=True, slots=True)
class _CardSurface:
    """Hold one completed card image and its render revision."""

    item_id: str
    image: Image.Image
    scene: Mapping[str, Any]
    mode: str
    asset_generation: int
    changed_pixels: Image.Image | None = None
    installed_mono: float = 0.0


@dataclass(frozen=True, slots=True)
class _CardJob:
    """Carry one serializable renderer scene to a card worker."""

    item_id: str
    scene: dict[str, Any]
    mode: str
    context: RenderContext
    asset_generation: int


@dataclass(frozen=True, slots=True)
class _CardPixels:
    """Carry one rendered RGBA card across a worker boundary."""

    width: int
    height: int
    rgba: bytes
    asset_signatures: tuple[tuple[str, str | None], ...] = ()


class CardViewport:
    """Own cached cards and publish ready changes in scrolling order."""

    def __init__(
        self,
        catalog: ContentRendererCatalog,
        *,
        use_process: bool = False,
        asset_directory: Path | str | None = None,
        worker_cpu: int | None = None,
        issue_handler: Callable[[Mapping[str, Any]], None] | None = None,
        pane_cache=None,
    ) -> None:
        self._catalog = catalog
        self._use_process = use_process and asset_directory is not None
        self._asset_directory = Path(asset_directory) if asset_directory is not None else None
        self._worker_cpu = worker_cpu
        self._issue_handler = issue_handler
        self._pane_cache = pane_cache
        self._cache_futures: dict[str, tuple[_CardRequest, Future]] = {}
        self._cache_attempted: dict[str, _CardRequest] = {}
        self._cache_hits = 0
        self._cache_misses = 0
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
        self._failed = 0
        self._worker_retries: set[tuple[int, str]] = set()
        self._layout: StripLayout | None = None
        self._tiled_strip: Image.Image | None = None
        self._asset_generation = 0
        self._scroll_offset = 0
        self._priority_anchor: str | None = None
        self._strip_revision = 0
        self._full_compositions = 0
        self._region_patches = 0
        self._patched_pixels = 0
        self._cold_build = True

    @property
    def revision(self) -> int:
        """Identify the installed strip pixels independently of backend payload changes."""
        with self._lock:
            return self._strip_revision

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
                "strip_revision": self._strip_revision,
                "full_compositions": self._full_compositions,
                "region_patches": self._region_patches,
                "patched_pixels": self._patched_pixels,
                "cache_hits": self._cache_hits,
                "cache_misses": self._cache_misses,
            }

    def set_issue_handler(self, handler: Callable[[Mapping[str, Any]], None] | None) -> None:
        """Install the application-owned issue sink after composition."""
        with self._lock:
            self._issue_handler = handler

    def update(self, items: Iterable[Content], context: RenderContext, mode: str, *,
               changed_ids: frozenset[str] | None = None) -> StripLayout | None:
        """Queue only cards whose full renderer scene changed."""
        content = tuple(items)
        with self._lock:
            self._cold_build = self._cold_build or self._layout is None
            self._staging_generation += 1
            generation = self._staging_generation
            order = tuple(item.id for item in content)
            if (changed_ids is not None and order == self._order
                    and all(request.mode == mode for request in self._desired.values())):
                for item in content:
                    previous = self._desired[item.id].item
                    if item.id not in changed_ids and (previous is item or previous == item):
                        continue
                    request = _CardRequest(item, mode, context, self._asset_generation, generation)
                    self._desired[item.id] = request
                    self._pending.pop(item.id, None)
                    current = self._staging_surfaces.get(item.id)
                    if current is not None and _matches(request, current):
                        continue
                    if self._active_request is not None and _same_work_request(self._active_request, request):
                        continue
                    self._pending[item.id] = request
                self._priority_anchor = None
                self._start_next()
                self._maybe_commit()
                return self._layout
            requests = tuple(
                _CardRequest(item, mode, context, self._asset_generation, generation)
                for item in content
            )
            self._order = tuple(request.item.id for request in requests)
            self._desired = {request.item.id: request for request in requests}
            self._queue_cached_panes(requests)
            self._staging_surfaces = {
                item_id: surface for item_id, surface in (self._surfaces | self._staging_surfaces).items()
                if item_id in self._desired
            }
            self._failed = 0
            self._worker_retries.clear()
            self._pending.clear()
            self._priority_anchor = None
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
            before = self._layout
            cached = self._install_cached_panes()
            future = self._future
            request = self._active_request
            if future is None or request is None or not future.done():
                if cached:
                    self._start_next()
                    self._maybe_commit()
                return self._layout if self._layout != before else None
            self._future = None
            self._active_request = None
        try:
            surface = future.result()
        except Exception as error:
            surface = None
            with self._lock:
                desired = self._desired.get(request.item.id)
                if desired is not None and _same_work_request(request, desired):
                    self._failed += 1
                self._report_failure(request, error)
                if isinstance(error, BrokenProcessPool):
                    self._restart_worker_locked()
                    self._queue_worker_retry_locked(request)
        with self._lock:
            desired = self._desired.get(request.item.id)
            if surface is not None and desired is not None and _same_work_request(request, desired):
                image = Image.frombytes("RGBA", (surface.width, surface.height), surface.rgba)
                previous = self._surfaces.get(request.item.id)
                current_rgb = _surface_rgb(image)
                previous_rgb = _surface_rgb(previous.image).crop((0, 0, image.width, image.height)) if previous else Image.new("RGB", image.size)
                card = _CardSurface(
                    request.item.id,
                    image,
                    desired.scene,
                    desired.mode,
                    desired.asset_generation,
                    ImageChops.difference(current_rgb, previous_rgb),
                    monotonic(),
                )
                if _matches(desired, card):
                    self._staging_surfaces[card.item_id] = card
                    if self._pane_cache is not None and card.item_id in self._order[:16] and _cacheable(desired):
                        self._pane_cache.save(card.item_id, desired.scene, desired.mode, surface.width, surface.height,
                                              surface.rgba, surface.asset_signatures)
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
            self._queue_cached_panes(refreshed)
            self._staging_surfaces = {
                item_id: surface for item_id, surface in (self._surfaces | self._staging_surfaces).items()
                if item_id in self._desired
            }
            self._failed = 0
            self._worker_retries.clear()
            self._pending = OrderedDict((request.item.id, request) for request in refreshed)
            self._priority_anchor = None
            self._start_next()
            self._maybe_commit()

    def visible_updates(self, offset: int, item_ids: Iterable[str], width: int = 384) -> dict[str, dict[str, Any]]:
        """Find current pane versions with changed pixels inside the presented viewport."""
        wanted = set(item_ids)
        result = {}
        with self._lock:
            layout = self._layout
            if layout is None:
                return result
            position, remaining = offset % layout.width, width
            while remaining > 0:
                end = min(layout.width, position + remaining)
                start = 0
                for segment in layout.segments:
                    left, right = max(position, start + 1), min(end, start + segment.width)
                    surface = self._surfaces.get(segment.item_id)
                    desired = self._desired.get(segment.item_id)
                    if left < right and segment.item_id in wanted and surface is not None and desired is not None and _matches(desired, surface):
                        changed = surface.changed_pixels
                        if changed is None:
                            changed = _surface_rgb(surface.image)
                        if changed.getbbox() is None:
                            result[segment.item_id] = {"changed_visible": False, "installed_mono": surface.installed_mono}
                        elif changed.crop((left - start - 1, 0, right - start - 1, min(32, changed.height))).getbbox() is not None:
                            result[segment.item_id] = {"changed_visible": True, "installed_mono": surface.installed_mono}
                    start += segment.width
                remaining -= end - position
                position = 0
        return result

    def frame(self, offset: int, width: int = 384, height: int = 32) -> Image.Image:
        """Crop one panel from the cached tiled pane strip."""
        with self._lock:
            self._scroll_offset = offset
            self._prioritize_pending()
            layout, strip = self._layout, self._tiled_strip
            if layout is None or strip is None:
                return Image.new("RGB", (width, height), "black")
            position = offset % layout.width
            source_height = min(height, strip.height)
            if position + width <= strip.width:
                crop = strip.crop((position, 0, position + width, source_height))
                if source_height == height:
                    return crop
                image = Image.new("RGB", (width, height), "black")
                image.paste(crop, (0, 0))
                return image
            image = Image.new("RGB", (width, height), "black")
            destination_x = 0
            remaining = width
            while remaining > 0:
                span = min(remaining, layout.width - position)
                image.paste(strip.crop((position, 0, position + span, source_height)), (destination_x, 0))
                destination_x += span
                remaining -= span
                position = 0
            return image

    def close(self) -> None:
        """Stop the owned card renderer."""
        self._worker.shutdown(wait=True, cancel_futures=True)
        if self._pane_cache is not None:
            self._pane_cache.close()

    def _start_next(self) -> None:
        if self._future is not None:
            return
        self._prioritize_pending()
        while self._pending:
            _, request = self._pending.popitem(last=False)
            desired = self._desired.get(request.item.id)
            if desired is None or not _same_work_request(desired, request):
                continue
            self._active_request = request
            job = _CardJob(request.item.id, _plain_mapping(request.scene), request.mode, request.context, request.asset_generation)
            try:
                self._future = self._worker.submit(self._render_job, job)
                return
            except BrokenProcessPool as error:
                self._active_request = None
                self._report_failure(request, error)
                self._restart_worker_locked()
                if self._queue_worker_retry_locked(request):
                    continue
                desired = self._desired.get(request.item.id)
                if desired is not None and _same_work_request(request, desired):
                    self._failed += 1
                self._maybe_commit()
                return

    def _queue_cached_panes(self, requests: Iterable[_CardRequest]) -> None:
        if self._pane_cache is None or not self._cold_build:
            return
        selected = tuple(requests)[:16]
        identifiers = {request.item.id for request in selected}
        for identifier in tuple(self._cache_futures):
            if identifier not in identifiers:
                self._cache_futures.pop(identifier)[1].cancel()
        self._cache_attempted = {identifier: request for identifier, request in self._cache_attempted.items() if identifier in identifiers}
        for request in selected:
            if not _cacheable(request):
                continue
            previous = self._cache_attempted.get(request.item.id)
            if previous is not None and _same_work_request(previous, request):
                continue
            if request.item.id in self._cache_futures:
                self._cache_futures[request.item.id][1].cancel()
            self._cache_attempted[request.item.id] = request
            future = self._pane_cache.load(request.item.id, request.scene, request.mode)
            self._cache_futures[request.item.id] = (request, future)

    def _install_cached_panes(self) -> bool:
        installed = False
        if self._pane_cache is not None:
            for error in self._pane_cache.errors():
                if self._issue_handler is not None:
                    self._issue_handler({"source": "pane_cache", "error_type": type(error).__name__, "error": str(error)[:500]})
        for identifier, (request, future) in tuple(self._cache_futures.items()):
            if not future.done():
                continue
            del self._cache_futures[identifier]
            try:
                pixels = future.result()
            except Exception as error:
                self._report_failure(request, error)
                continue
            desired = self._desired.get(identifier)
            current = self._staging_surfaces.get(identifier)
            if (pixels is None or desired is None or not _same_work_request(request, desired)
                    or current is not None and _matches(desired, current)):
                if pixels is None:
                    self._cache_misses += 1
                continue
            width, height, rgba = pixels
            image = Image.frombytes("RGBA", (width, height), rgba)
            previous = self._surfaces.get(identifier)
            previous_rgb = _surface_rgb(previous.image).crop((0, 0, width, height)) if previous else Image.new("RGB", image.size)
            self._staging_surfaces[identifier] = _CardSurface(identifier, image, desired.scene, desired.mode,
                desired.asset_generation, ImageChops.difference(_surface_rgb(image), previous_rgb), monotonic())
            self._pending.pop(identifier, None)
            self._cache_hits += 1
            installed = True
        return installed

    def _queue_worker_retry_locked(self, request: _CardRequest) -> bool:
        """Requeue one current request once after a broken worker."""
        desired = self._desired.get(request.item.id)
        if desired is None or not _same_work_request(desired, request):
            return False
        retry_key = (desired.generation, desired.item.id)
        if retry_key in self._worker_retries:
            return False
        self._worker_retries.add(retry_key)
        pending = OrderedDict([(desired.item.id, desired)])
        pending.update(self._pending)
        self._pending = pending
        self._priority_anchor = None
        return True

    def _prioritize_pending(self) -> None:
        """Draw visible cards first, then continue forward through the scrolling rotation."""
        if not self._pending or self._layout is None:
            return
        position = self._scroll_offset % self._layout.width
        start = 0
        for index, segment in enumerate(self._layout.segments):
            if start + segment.width > position:
                break
            start += segment.width
        anchor = segment.item_id
        if anchor == self._priority_anchor:
            return
        self._priority_anchor = anchor
        segments = self._layout.segments
        order = tuple(segment.item_id for segment in segments[index:] + segments[:index])
        pending = OrderedDict((identifier, self._pending[identifier]) for identifier in order if identifier in self._pending)
        pending.update((identifier, request) for identifier, request in self._pending.items() if identifier not in pending)
        self._pending = pending

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
        complete = self._future is None and not self._pending
        if not self._desired:
            self._surfaces = {}
            self._layout = None
            self._tiled_strip = None
            self._generation = self._staging_generation
            self._strip_revision += 1
            return
        if self._cold_build and not complete:
            committed = {}
            for identifier in self._order:
                if identifier not in self._staging_surfaces:
                    break
                committed[identifier] = self._staging_surfaces[identifier]
            ready_width = sum(surface.image.width + 1 for surface in committed.values())
            if ready_width < 384:
                return
            if self._layout is not None and ready_width - self._layout.width < 384:
                return
        else:
            if not complete and not all(identifier in self._staging_surfaces for identifier in self._desired):
                return
            committed = {item_id: surface for item_id, surface in self._staging_surfaces.items() if item_id in self._desired}
        layout = self._layout_now(committed)
        if layout is None:
            return
        previous_surfaces = self._surfaces
        changed = {item_id for item_id, surface in committed.items() if previous_surfaces.get(item_id) is not surface}
        geometry_changed = (layout != self._layout or self._tiled_strip is None
                            or self._tiled_strip.height != max(surface.image.height for surface in committed.values()))
        if geometry_changed:
            self._tiled_strip = _compose_tiled_strip(layout, committed)
            self._full_compositions += 1
        elif changed:
            self._patched_pixels += _patch_tiled_strip(self._tiled_strip, layout, committed, changed)
            self._region_patches += len(changed)
        self._surfaces = committed
        self._layout = layout
        if geometry_changed or changed:
            self._strip_revision += 1
        if complete:
            self._generation = self._staging_generation
            self._cold_build = False

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
        signatures = self._pane_cache.signatures(job.scene) if self._pane_cache is not None else ()
        return _render_catalog_job(self._catalog, job, signatures)


def _surface_rgb(image: Image.Image) -> Image.Image:
    rgb = Image.new("RGB", image.size)
    rgb.paste(image, (0, 0), image if image.mode == "RGBA" else None)
    return rgb


def _same_work_request(left: _CardRequest, right: _CardRequest) -> bool:
    """Return if two worker requests render the same immutable scene."""
    return (
        left.item.id == right.item.id
        and left.scene == right.scene
        and left.mode == right.mode
        and left.asset_generation == right.asset_generation
    )


def _matches(request: _CardRequest, surface: _CardSurface) -> bool:
    """Return if one card surface matches a renderer scene exactly."""
    return (
        request.item.id == surface.item_id
        and request.scene == surface.scene
        and request.mode == surface.mode
        and request.asset_generation == surface.asset_generation
    )


def _patch_tiled_strip(
    strip: Image.Image,
    layout: StripLayout,
    surfaces: Mapping[str, _CardSurface],
    changed: set[str],
) -> int:
    """Replace changed card rectangles and adjacent dividers in every tiled copy."""
    colors = pane_divider_colors(surfaces[segment.item_id].scene.get("competition_stage") for segment in layout.segments)
    offsets, start = [], 0
    for segment in layout.segments:
        offsets.append(start)
        start += segment.width
    writes = 0
    for index, segment in enumerate(layout.segments):
        if segment.item_id not in changed:
            continue
        surface = surfaces[segment.item_id]
        patch = Image.new("RGB", (segment.width, strip.height), "black")
        patch.paste(colors[index], (0, 0, 1, strip.height))
        patch.paste(surface.image, (1, 0), surface.image if surface.image.mode == "RGBA" else None)
        adjacent = (index + 1) % len(layout.segments)
        for repeat in range(strip.width // layout.width):
            origin = repeat * layout.width
            strip.paste(patch, (origin + offsets[index], 0))
            boundary = origin + offsets[adjacent]
            strip.paste(colors[adjacent], (boundary, 0, boundary + 1, strip.height))
            writes += (segment.width + 1) * strip.height
    return writes


def _compose_tiled_strip(
    layout: StripLayout,
    surfaces: Mapping[str, _CardSurface],
) -> Image.Image:
    """Compose complete strip pixels when layout geometry changes."""
    height = max((surface.image.height for surface in surfaces.values()), default=32)
    pane_strip = compose_pane_strip(
        ((surfaces[segment.item_id].image if segment.item_id in surfaces else None, segment.width) for segment in layout.segments),
        height,
        divider_colors=pane_divider_colors(
            surfaces[segment.item_id].scene.get("competition_stage") if segment.item_id in surfaces else None
            for segment in layout.segments
        ),
    )
    repeat_count = (384 + layout.width - 1) // layout.width + 1
    tiled = Image.new("RGB", (layout.width * repeat_count, height), "black")
    for index in range(repeat_count):
        tiled.paste(pane_strip, (index * layout.width, 0))
    return tiled


_PROCESS_CATALOG: ContentRendererCatalog | None = None
_PROCESS_ASSETS = None
_PROCESS_ASSET_GENERATION = None


def _initialize_process_catalog(asset_directory: str, worker_cpu: int | None) -> None:
    """Start a clean worker with read-only prepared assets and no inherited locks."""
    from ticker_core.bootstrap import create_default_content_catalog
    from ticker_core.platform.assets import AssetCoordinator

    global _PROCESS_CATALOG, _PROCESS_ASSETS, _PROCESS_ASSET_GENERATION
    pin_to_cpu(worker_cpu)
    _PROCESS_ASSETS = AssetCoordinator(asset_directory)
    _PROCESS_ASSET_GENERATION = None
    _PROCESS_CATALOG = create_default_content_catalog(_PROCESS_ASSETS)


def _render_process_job(job: _CardJob) -> _CardPixels:
    """Render one card in the isolated process catalog."""
    if _PROCESS_CATALOG is None:
        raise RuntimeError("The card renderer process has no catalog.")
    global _PROCESS_ASSET_GENERATION
    if _PROCESS_ASSET_GENERATION != job.asset_generation:
        _PROCESS_ASSETS.long_term.prepared.clear_memory()
        _PROCESS_ASSET_GENERATION = job.asset_generation
    signatures = asset_signatures(_PROCESS_ASSETS, job.scene)
    return _render_catalog_job(_PROCESS_CATALOG, job, signatures)


def _render_catalog_job(catalog: ContentRendererCatalog, job: _CardJob, signatures=()) -> _CardPixels:
    """Render one serializable scene and return only pixel data."""
    rendered = catalog.render(job.context, ContentScene(job.scene, job.mode))
    image = rendered.image.convert("RGBA")
    return _CardPixels(image.width, image.height, image.tobytes(), signatures)


def _cacheable(request: _CardRequest) -> bool:
    """Keep only time-independent scrolling sports cards in the durable pane cache."""
    return (request.mode == "sports" and request.item.type == "scoreboard"
            and content_family(request.scene, request.mode) == "scoreboard"
            and request.scene.get("sports_presentation") != "pinned")


def _scene_mapping(content: Content) -> Mapping[str, Any]:
    """Retain immutable scene facts without serializing nested content for comparisons."""
    data = dict(content.data)
    data.setdefault("id", content.id)
    data.setdefault("type", content.type)
    data.setdefault("sport", content.sport)
    return MappingProxyType(data)
