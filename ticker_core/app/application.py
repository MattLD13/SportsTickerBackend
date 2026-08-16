"""Own the executable Pi controller lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
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
from ticker_core.platform import (
    AssetCoordinator,
    OtaUpdaterService,
    PlatformCommands,
    WiFiRecoveryService,
    WiFiSetupState,
)
from ticker_core.protocol import BackendClient, DisplayDelta, TickerResponse, apply_display_delta
from ticker_core.runtime import FrameDecision, FrameKind, FramePacer, TickerRuntime

from .frame_builder import FrameBuilder
from .poller import BackendPoller, PollConnected, PollEvent, PollFailed, PollSucceeded
from .viewport import CardViewport


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
        viewport: CardViewport,
        frames: FrameBuilder,
        pacer: FramePacer,
        sink: FrameSink,
        commands: PlatformCommands,
        device_id: str,
        repository: Path | str,
        wall_clock: Callable[[], datetime],
        update_command: Sequence[str] | None = None,
        update_service: OtaUpdaterService | None = None,
        wifi_recovery: WiFiRecoveryService | None = None,
        wifi_check_interval: float = 10.0,
        poll_in_process: bool = False,
        render_cpu: int | None = None,
        poll_cpu: int | None = None,
        logger: object | None = None,
    ) -> None:
        if not device_id.strip():
            raise ValueError("A device id is required.")
        if wifi_check_interval <= 0:
            raise ValueError("The Wi-Fi check interval must be positive.")
        self._client = client
        self._poller = poller
        self._cache = cache
        self._assets = assets
        self._runtime = runtime
        self._viewport = viewport
        self._frames = frames
        self._pacer = pacer
        self._sink = sink
        self._commands = commands
        self._device_id = device_id
        self._repository = Path(repository)
        self._wall_clock = wall_clock
        self._update_command = tuple(update_command or _default_update_command(self._repository))
        self._update_service = update_service
        self._wifi_recovery = wifi_recovery
        self._wifi_check_interval = wifi_check_interval
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
        self._wifi_thread: Thread | None = None
        self._wifi_portal_thread: Thread | None = None
        self._wifi_state: WiFiSetupState | None = None
        self._started = False
        self._disconnected = False
        self._reboot_latched = False
        self._pending_reboot_id: str | None = None
        self._update_latched = False
        self._asset_revision = self._asset_revision_now()
        self._last_response: TickerResponse | None = None
        self._logger = logger or _NullPiLogger()

    @property
    def runtime(self) -> TickerRuntime:
        """Expose runtime state for local controls and diagnostics."""
        return self._runtime

    @property
    def sink(self) -> FrameSink:
        """Expose the selected frame sink for debug callers."""
        return self._sink

    @property
    def wifi_state(self) -> WiFiSetupState | None:
        """Expose the last platform-owned Wi-Fi state for diagnostics and tests."""

        return self._wifi_state

    def start(self) -> None:
        """Start worker services after every dependency is composed."""
        if self._started:
            return
        self._started = True
        self._logger.start()
        _pin_to_cpu(self._render_cpu)
        self._start_wifi_lifecycle()
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
        self._install_completed_cards()
        self._refresh_cards_after_asset_change()
        self._install_completed_cards()
        self._push_requested_modes()
        decision = self._runtime.next_frame()
        wifi_state = self._wifi_state
        if wifi_state is not None and not wifi_state.internet_available:
            decision = replace(
                decision,
                kind=FrameKind.WIFI_SETUP,
                wifi_state=wifi_state,
                connection_lost=False,
            )
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
                if isinstance(response, DisplayDelta):
                    if self._last_response is None:
                        self._logger.record_issue("poll_delta", RuntimeError("Received a delta before a display snapshot."))
                        continue
                    self._accept_fresh(apply_display_delta(self._last_response, response), persist=False)
                else:
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
        if self._wifi_thread is not None and self._wifi_thread is not current_thread():
            self._wifi_thread.join(timeout=6)
            self._wifi_thread = None
        if self._poll_thread is not None and self._poll_thread is not current_thread():
            self._poll_thread.join(timeout=6)
            self._poll_thread = None
        close_cache = getattr(self._cache, "close", None)
        if callable(close_cache):
            close_cache()
        self._assets.close()
        self._viewport.close()
        self._client.close()
        self._sink.clear()
        close_sink = getattr(self._sink, "close", None)
        if callable(close_sink):
            close_sink()
        self._logger.close()
        self._started = False

    def _start_wifi_lifecycle(self) -> None:
        """Start platform Wi-Fi checks outside the render and poll paths."""

        if self._wifi_recovery is None or self._wifi_thread is not None:
            return
        self._wifi_thread = Thread(
            target=self._run_wifi_lifecycle,
            name="ticker-wifi-recovery",
            daemon=True,
        )
        self._wifi_thread.start()

    def _run_wifi_lifecycle(self) -> None:
        """Refresh Wi-Fi state and run the setup portal from a worker."""

        assert self._wifi_recovery is not None
        portal_started = False
        while not self._stop.is_set():
            try:
                state = self._wifi_recovery.start_setup()
                self._wifi_state = state
                if not state.internet_available and not portal_started:
                    portal_started = True
                    self._wifi_portal_thread = Thread(
                        target=self._wifi_recovery.start_portal,
                        name="ticker-wifi-portal",
                        daemon=True,
                    )
                    self._wifi_portal_thread.start()
                elif state.internet_available:
                    portal_started = False
            except Exception as error:
                self._logger.record_issue("wifi", error)
            if self._stop.wait(self._wifi_check_interval):
                return

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
        self._last_response = response
        self._refresh_viewport()

    def _accept_fresh(self, response: TickerResponse, *, persist: bool = True) -> None:
        """Persist, prefetch, accept, and render one validated backend response."""
        previous = self._runtime.snapshot
        if previous is not None and previous.key == response.payload_key:
            refresh = getattr(self._cache, "refresh", None)
            if callable(refresh):
                refresh()
            self._runtime.confirm_connection()
            self._disconnected = False
            return
        if persist:
            self._cache.store(response.data)
        self._logger.record_payload(response)
        self._assets.prefetch_payload(response)
        current = self._runtime.accept_response(response)
        self._disconnected = False
        self._pending_reboot_id = response.reboot_request_id
        self._last_response = response
        del previous
        self._refresh_viewport(current)

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

    def _refresh_viewport(self, snapshot=None) -> None:
        """Queue changed card scenes without composing a long strip image."""
        current = snapshot or self._runtime.snapshot
        if current is None:
            return
        layout = self._viewport.update(
            self._runtime.classification.scrolling,
            RenderContext(self._wall_clock()),
            self._runtime.mode,
        )
        self._runtime.install_strip(current.strip_key, layout)

    def _install_completed_cards(self) -> None:
        """Commit one rendered card at a frame boundary."""
        layout = self._viewport.install_completed()
        snapshot = self._runtime.snapshot
        if layout is not None and snapshot is not None:
            self._runtime.install_strip(snapshot.strip_key, layout)

    def _refresh_cards_after_asset_change(self) -> None:
        """Queue replacement cards when prepared assets become available."""
        revision = self._asset_revision_now()
        if revision != self._asset_revision:
            self._asset_revision = revision
            self._viewport.invalidate()

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
    """Send polling state across the process boundary."""

    def __init__(self, target) -> None:
        self._target = target

    def put(self, event: PollEvent) -> None:
        if isinstance(event, PollSucceeded):
            self._target.put(PollSucceeded(event.payload, event.elapsed_ms, event.response_bytes))
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
