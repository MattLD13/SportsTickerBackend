"""Own the executable Pi controller lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from concurrent.futures import Future, ThreadPoolExecutor
from multiprocessing import get_context
from threading import Event, Thread, current_thread
from time import monotonic
import os
import shlex
import sys
from typing import Protocol

from ticker_core.assets import ShortTermContentCache
from ticker_core.context import RenderContext
from ticker_core.drivers import FrameSink
from ticker_core.platform import AssetCoordinator, OtaUpdaterService, PlatformCommands
from ticker_core.protocol import BackendClient, TickerResponse
from ticker_core.runtime import FrameDecision, FramePacer, TickerRuntime

from .frame_builder import FrameBuilder
from .poller import BackendPoller, PollConnected, PollEvent, PollFailed, PollSucceeded
from .strips import StripRepository


class PollWorker(Protocol):
    """Run a backend polling loop with caller-owned stop state."""

    def run(self, stop: Event, events: Queue[PollEvent]) -> None:
        """Publish events until the stop event is set."""


class ContentCache(Protocol):
    """Store the valid response used during a short outage."""

    def store(self, payload: Mapping[str, object]):
        """Store one fresh backend payload."""

    def refresh(self):
        """Extend the in-memory lifetime of unchanged payload data."""

    def load(self):
        """Return one non-expired saved payload."""

    def age(self, entry) -> float:
        """Return saved payload age."""

    def remaining(self, entry) -> float:
        """Return saved payload lifetime."""


class TickerApplication:
    """Connect protocol, state, rendering, output, and platform actions."""

    def __init__(
        self,
        *,
        client: BackendClient,
        poller: PollWorker,
        cache: ContentCache,
        assets: AssetCoordinator,
        runtime: TickerRuntime,
        strips: StripRepository,
        frames: FrameBuilder,
        pacer: FramePacer,
        sink: FrameSink,
        commands: PlatformCommands,
        device_id: str,
        repository: Path | str,
        wall_clock: Callable[[], datetime],
        update_command: Sequence[str] | None = None,
        update_service: OtaUpdaterService | None = None,
        poll_in_process: bool = False,
        render_cpu: int | None = None,
        poll_cpu: int | None = None,
        logger: object | None = None,
    ) -> None:
        if not device_id.strip():
            raise ValueError("A device id is required.")
        self._client = client
        self._poller = poller
        self._cache = cache
        self._assets = assets
        self._runtime = runtime
        self._strips = strips
        self._frames = frames
        self._pacer = pacer
        self._sink = sink
        self._commands = commands
        self._device_id = device_id
        self._repository = Path(repository)
        self._wall_clock = wall_clock
        self._update_command = tuple(update_command or _default_update_command(self._repository))
        self._update_service = update_service
        self._poll_in_process = poll_in_process and os.name != "nt"
        self._render_cpu = render_cpu
        self._poll_cpu = poll_cpu
        if self._poll_in_process:
            self._process_context = get_context("fork")
            self._events = self._process_context.Queue()
            self._stop = self._process_context.Event()
        else:
            self._process_context = None
            self._events: Queue[PollEvent] = Queue()
            self._stop = Event()
        self._poll_thread: Thread | object | None = None
        self._started = False
        self._disconnected = False
        self._reboot_latched = False
        self._pending_reboot_id: str | None = None
        self._update_latched = False
        self._asset_revision = self._asset_revision_now()
        self._asset_dirty_at: float | None = None
        self._strip_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ticker-strip")
        self._strip_future: Future[object] | None = None
        self._pending_strip: tuple[str, tuple[object, ...], RenderContext, str] | None = None
        self._logger = logger or _NullPiLogger()

    @property
    def runtime(self) -> TickerRuntime:
        """Expose runtime state for local controls and diagnostics."""
        return self._runtime

    @property
    def sink(self) -> FrameSink:
        """Expose the selected frame sink for debug callers."""
        return self._sink

    def start(self) -> None:
        """Start worker services after every dependency is composed."""
        if self._started:
            return
        self._started = True
        self._logger.start()
        _pin_to_cpu(self._render_cpu)
        if self._poll_in_process:
            assert self._process_context is not None
            self._poll_thread = self._process_context.Process(
                target=_run_poll_process,
                args=(self._poller, self._stop, self._events, self._poll_cpu),
                name="ticker-backend-poll",
                daemon=True,
            )
            self._poll_thread.start()
        else:
            self._poll_thread = Thread(target=self._poller.run, args=(self._stop, self._events), name="ticker-backend-poll", daemon=True)
            self._poll_thread.start()
        start_sink = getattr(self._sink, "start", None)
        if callable(start_sink):
            start_sink()
        self._assets.start()
        self._restore_cached_content()

    def run(self) -> None:
        """Run frames until shutdown or a runtime stop request."""
        self.start()
        try:
            while self._runtime.running and not self._stop.is_set():
                self.step()
                decision = self._last_decision
                if self._stop.wait(self._pacer.next_delay(decision.interval)):
                    break
        finally:
            self.close()

    def step(self) -> FrameDecision:
        """Process queued backend work and present one paced frame decision."""
        started_at = monotonic()
        if not self._started:
            self.start()
        self.process_events()
        self._install_completed_strip()
        self._rebuild_strip_after_asset_change()
        self._install_completed_strip()
        self._push_requested_modes()
        decision = self._runtime.next_frame()
        try:
            frame = self._frames.build(decision)
            present_started_at = monotonic()
            self._sink.present(frame, brightness=decision.brightness, inverted=decision.inverted)
            finished_at = monotonic()
        except Exception as error:
            self._logger.record_issue("frame", error, kind=str(decision.kind), mode=decision.mode)
            raise
        self._logger.record_frame(
            started_at=started_at,
            present_started_at=present_started_at,
            finished_at=finished_at,
            interval=decision.interval,
            kind=decision.kind,
            mode=decision.mode,
            brightness=decision.brightness,
            inverted=decision.inverted,
            stale=decision.stale,
            connection_lost=decision.connection_lost,
            wall_time=decision.wall_time,
            width=getattr(self._sink, "width", 0),
            height=getattr(self._sink, "height", 0),
        )
        self._last_decision = decision
        self._launch_requested_update()
        self._launch_requested_reboot()
        return decision

    def process_events(self) -> None:
        """Apply all completed poll events on the application thread."""
        while True:
            try:
                event = self._events.get_nowait()
            except Empty:
                return
            if isinstance(event, PollSucceeded):
                self._logger.record_poll(success=True, elapsed_ms=event.elapsed_ms, response_bytes=event.response_bytes)
                response = event.payload
                if isinstance(response, Mapping):
                    response = TickerResponse.from_payload(response)
                self._accept_fresh(response)
            elif isinstance(event, PollConnected):
                self._logger.record_poll(success=True, elapsed_ms=event.elapsed_ms, response_bytes=event.response_bytes)
                self._runtime.confirm_connection()
                self._disconnected = False
            else:
                self._logger.record_poll(
                    success=False,
                    elapsed_ms=event.elapsed_ms,
                    error=event.error,
                    retry_in=event.retry_in,
                )
                self._logger.record_issue("backend_poll", event.error, retry_in=event.retry_in)
                self._handle_failure(event)

    def request_mode(self, mode: str) -> None:
        """Queue one local mode change and one backend setting push."""
        self._runtime.request_mode(mode)

    def close(self) -> None:
        """Stop owned workers and close owned external resources."""
        if self._stop.is_set() and not self._started:
            return
        self._stop.set()
        if self._poll_thread is not None and self._poll_thread is not current_thread():
            self._poll_thread.join(timeout=6)
            self._poll_thread = None
        close_cache = getattr(self._cache, "close", None)
        if callable(close_cache):
            close_cache()
        self._assets.close()
        self._strip_worker.shutdown(wait=True, cancel_futures=True)
        self._client.close()
        self._sink.clear()
        close_sink = getattr(self._sink, "close", None)
        if callable(close_sink):
            close_sink()
        self._logger.close()
        self._started = False

    def _restore_cached_content(self) -> None:
        entry = self._cache.load()
        if entry is None:
            return
        try:
            response = TickerResponse.from_payload(entry.payload)
        except Exception as error:
            self._logger.record_issue("cache_restore", error)
            return
        self._assets.prefetch_payload(response)
        self._runtime.accept_cached_response(
            response,
            stale_for=self._cache.age(entry),
            expires_in=self._cache.remaining(entry),
        )
        self._disconnected = True
        self._rebuild_strip()

    def _accept_fresh(self, response: TickerResponse) -> None:
        """Persist, prefetch, accept, and render one validated backend response."""
        previous = self._runtime.snapshot
        if previous is not None and previous.key == response.payload_key:
            refresh = getattr(self._cache, "refresh", None)
            if callable(refresh):
                refresh()
            self._runtime.confirm_connection()
            self._disconnected = False
            return
        self._cache.store(response.data)
        self._logger.record_payload(response)
        self._assets.prefetch_payload(response)
        current = self._runtime.accept_response(response)
        self._disconnected = False
        self._pending_reboot_id = response.reboot_request_id
        if _strip_changed(previous, current):
            self._rebuild_strip()

    def _handle_failure(self, event: PollFailed) -> None:
        """Keep content during one outage and go offline after cache expiry."""
        del event
        if self._disconnected:
            return
        self._disconnected = True
        entry = self._cache.load()
        if self._runtime.snapshot is None and entry is not None:
            self._restore_cached_content()
            return
        expires_in = self._cache.remaining(entry) if entry is not None else 0.0
        self._runtime.mark_disconnected(expires_in=expires_in)

    def _rebuild_strip(self) -> None:
        """Queue one replacement strip without delaying the next frame."""
        snapshot = self._runtime.snapshot
        if snapshot is None:
            return
        request = (
            snapshot.strip_key,
            tuple(self._runtime.classification.scrolling),
            RenderContext(self._wall_clock()),
            self._runtime.mode,
        )
        prepare = getattr(self._strips, "prepare", None)
        install = getattr(self._strips, "install", None)
        if not callable(prepare) or not callable(install):
            layout = self._strips.build(*request)
            self._runtime.install_strip(snapshot.strip_key, layout)
            self._asset_revision = self._asset_revision_now()
            return
        self._pending_strip = request
        self._start_pending_strip()

    def _start_pending_strip(self) -> None:
        """Start the newest queued strip after the active build finishes."""
        if self._strip_future is not None and not self._strip_future.done():
            return
        if self._pending_strip is None:
            return
        request = self._pending_strip
        self._pending_strip = None
        prepare = getattr(self._strips, "prepare")
        self._strip_future = self._strip_worker.submit(prepare, *request)

    def _install_completed_strip(self) -> None:
        """Swap a completed strip only when it still matches current content."""
        future = self._strip_future
        if future is None or not future.done():
            return
        self._strip_future = None
        try:
            prepared = future.result()
        except Exception as error:
            self._logger.record_issue("strip_prepare", error)
            self._start_pending_strip()
            return
        snapshot = self._runtime.snapshot
        if snapshot is not None and getattr(prepared, "key", None) == snapshot.strip_key:
            install = getattr(self._strips, "install")
            install(prepared)
            self._runtime.install_strip(snapshot.strip_key, getattr(prepared, "layout", None))
        self._start_pending_strip()

    def _rebuild_strip_after_asset_change(self) -> None:
        """Refresh scrolling cards after background asset work changes images."""
        revision = self._asset_revision_now()
        if revision != self._asset_revision:
            self._asset_revision = revision
            self._asset_dirty_at = monotonic()
        if self._asset_dirty_at is not None and monotonic() - self._asset_dirty_at >= 0.15:
            self._rebuild_strip()
            self._asset_dirty_at = None

    def _asset_revision_now(self) -> int | None:
        """Read the optional prepared-image revision without I/O."""
        value = getattr(self._assets, "revision", None)
        return int(value) if isinstance(value, int) else None

    def _push_requested_modes(self) -> None:
        while request := self._runtime.take_mode_request():
            try:
                self._client.push_setting(self._device_id, "mode", request.mode)
            except Exception as error:
                self._logger.record_issue("mode_push", error, mode=request.mode)
                pass

    def _launch_requested_update(self) -> None:
        """Acknowledge one server request, then start the non-blocking updater."""

        request = self._runtime.take_update_request()
        if request is None or self._update_latched:
            return
        acknowledge = getattr(self._client, "acknowledge_update", None)
        if not callable(acknowledge):
            return
        try:
            result = acknowledge(self._device_id, request.version)
        except Exception as error:
            self._logger.record_issue("update_ack", error, version=request.version)
            return
        if not bool(result.get("acknowledged")):
            return
        self._update_latched = True
        if self._update_service is not None:
            self._update_service.request_update(request.version)
            return
        self._commands.run_update(self._update_command)

    def _launch_requested_reboot(self) -> None:
        """Acknowledge one server reboot command, then restart the host once."""

        command_id = self._pending_reboot_id
        if not command_id or self._reboot_latched:
            return
        acknowledge = getattr(self._client, "acknowledge_reboot", None)
        if not callable(acknowledge):
            return
        try:
            result = acknowledge(self._device_id, command_id)
        except Exception as error:
            self._logger.record_issue("reboot_ack", error, command_id=command_id)
            return
        if not bool(result.get("acknowledged")):
            return
        self._reboot_latched = True
        self._commands.reboot()



def _strip_changed(previous, current) -> bool:
    """Return if scrolling pixels or the selected renderer can change."""

    if previous is None:
        return True
    return previous.mode != current.mode or previous.strip_key != current.strip_key


def _run_poll_process(poller: PollWorker, stop, events, cpu: int | None) -> None:
    """Run network polling outside the renderer process."""

    _pin_to_cpu(cpu)
    try:
        poller.run(stop, _ProcessPollEvents(events))
    finally:
        close = getattr(poller, "close", None)
        if callable(close):
            close()


class _ProcessPollEvents:
    """Send only serializable polling state across the process boundary."""

    def __init__(self, target) -> None:
        self._target = target

    def put(self, event: PollEvent) -> None:
        if isinstance(event, PollSucceeded):
            self._target.put(PollSucceeded(event.payload.to_payload(), event.elapsed_ms, event.response_bytes))
            return
        if isinstance(event, PollFailed):
            self._target.put(PollFailed(RuntimeError(str(event.error)), event.retry_in, event.elapsed_ms))
            return
        self._target.put(event)


def _pin_to_cpu(cpu: int | None) -> None:
    """Limit this process to one configured Linux CPU when available."""

    if cpu is None or not hasattr(os, "sched_setaffinity"):
        return
    try:
        os.sched_setaffinity(0, {cpu})
    except OSError:
        return


class _NullPiLogger:
    """Keep custom and test compositions free from logging dependencies."""

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass

    def record_frame(self, **kwargs) -> None:
        del kwargs

    def record_poll(self, **kwargs) -> None:
        del kwargs

    def record_payload(self, response) -> None:
        del response

    def record_issue(self, source, error, **details) -> None:
        del source, error, details


def _default_update_command(repository: Path) -> tuple[str, ...]:
    """Read one safe updater command from the environment."""
    configured = os.environ.get("TICKER_UPDATE_COMMAND", "").strip()
    if configured:
        return tuple(shlex.split(configured))
    return (sys.executable, str(repository / "updater.py"), "--no-display")
