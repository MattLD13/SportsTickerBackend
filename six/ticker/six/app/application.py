"""Own the executable Pi controller lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from multiprocessing import get_context
from threading import Event, Thread, current_thread
from time import monotonic, time as wall_time
import os
from typing import Protocol

from ticker.panel.frame import RenderContext
from ticker.six.drivers import FrameSink
from ticker.six.platform import (
    OtaUpdaterService,
    PlatformCommands,
    WiFiRecoveryService,
)
from ticker.panel.assets.storage import AssetCoordinator
from ticker.panel.content import WiFiSetupState
from ticker.six.protocol import BackendClient, TickerResponse
from ticker.six.platform.frame_health import PresentedFrameHealth
from ticker.panel.affinity import pin_to_cpu
from ticker.six.runtime import FramePacer, TickerRuntime
from ticker.panel.content import FrameDecision, FrameKind

from ticker.panel.frame_builder import FrameBuilder
from ticker.six.app.poller import PollConnected, PollEvent, PollFailed, PollStreamEvent, PollSucceeded, PollUpdateResult
from ticker.panel.viewport import CardViewport
from ticker.six.app.latency import DisplayLatencyTracker
from ticker.six.app.updates import PreparedEventQueue, PreparedUpdate, RejectedUpdate


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
        update_service: OtaUpdaterService | None = None,
        wifi_recovery: WiFiRecoveryService | None = None,
        wifi_check_interval: float = 10.0,
        poll_in_process: bool = False,
        render_cpu: int | None = None,
        poll_cpu: int | None = None,
        logger: object | None = None,
        frame_health: PresentedFrameHealth | None = None,
    ) -> None:
        if not device_id.strip():
            raise ValueError("A device id is required.")
        if wifi_check_interval <= 0:
            raise ValueError("The Wi-Fi check interval must be positive.")
        self._frame_health = frame_health
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
        self._update_service = update_service
        self._wifi_recovery = wifi_recovery
        self._wifi_check_interval = wifi_check_interval
        self._poll_in_process = poll_in_process and os.name != "nt"
        self._render_cpu = render_cpu
        self._poll_cpu = poll_cpu
        if self._poll_in_process:
            self._process_context = get_context("fork")
            self._incoming_events = self._process_context.Queue()
            self._stop = self._process_context.Event()
        else:
            self._process_context = None
            self._incoming_events = None
            self._stop = Event()
        self._poll_thread: Thread | object | None = None
        self._event_reader: Thread | None = None
        self._events = PreparedEventQueue(cache=cache, assets=assets)
        self._wifi_thread: Thread | None = None
        self._wifi_portal_thread: Thread | None = None
        self._wifi_state: WiFiSetupState | None = None
        self._started = False
        self._disconnected = False
        self._reboot_latched = False
        self._pending_reboot_id: str | None = None
        self._update_latched = False
        self._update_notice_ack: tuple[str, str] | None = None
        self._asset_revision = self._asset_revision_now()
        self._last_response: TickerResponse | None = None
        self._logger = logger or _NullPiLogger()
        self._latency = DisplayLatencyTracker(self._record_latency)
        set_issue_handler = getattr(self._viewport, "set_issue_handler", None)
        if callable(set_issue_handler):
            set_issue_handler(self._record_viewport_issue)
        self._last_visual_key: object | None = None
        self._last_base_visual_key: object | None = None
        self._last_frame = None
        self._last_presented_visible_ids: frozenset[str] | None = None
        self._last_present_at: float | None = None
        self._present_retry = False

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
        pin_to_cpu(self._render_cpu)
        self._start_wifi_lifecycle()
        if self._poll_in_process:
            assert self._process_context is not None
            self._poll_thread = self._process_context.Process(
                target=_run_poll_process,
                args=(self._poller, self._stop, self._incoming_events, self._poll_cpu),
                name="ticker-backend-poll",
                daemon=True,
            )
            self._poll_thread.start()
            self._event_reader = Thread(target=self._read_poll_events, name="ticker-event-prepare", daemon=True)
            self._event_reader.start()
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
        updates_finished_at = monotonic()
        self._refresh_local_hardware_content()
        self._install_completed_cards()
        self._refresh_cards_after_asset_change()
        self._install_completed_cards()
        installed_times = getattr(self._viewport, "installed_times", None)
        if self._latency.pending_ids and callable(installed_times):
            self._latency.ready(installed_times(self._latency.pending_ids))
        decision = self._runtime.next_frame()
        wifi_state = self._wifi_state
        if wifi_state is not None and not wifi_state.internet_available and wifi_state.local_setup_active:
            decision = replace(
                decision,
                kind=FrameKind.WIFI_SETUP,
                wifi_state=wifi_state,
                connection_lost=False,
                update_failure=None,
            )
        preparation_finished_at = monotonic()
        try:
            base_visual_key = self._frame_visual_key(decision)
            visual_key = (base_visual_key, decision.brightness, decision.inverted)
        except Exception as error:
            self._logger.record_issue("frame_key", error, kind=str(decision.kind), mode=decision.mode)
            self._record_tick(decision, presented=False)
            self._complete_step(decision)
            return decision
        if (
            self._last_frame is not None
            and visual_key == self._last_visual_key
            and not self._present_retry
        ):
            self._record_tick(decision, presented=False)
            self._complete_step(decision)
            return decision
        try:
            frame = self._last_frame if self._last_frame is not None and base_visual_key == self._last_base_visual_key else self._frames.build(decision)
            if _unintended_black(frame, decision):
                self._logger.record_issue("black_frame", "A non-sleep frame is fully black", kind=str(decision.kind), mode=decision.mode)
                self._present_retry = True
                self._record_tick(decision, presented=False)
                self._complete_step(decision)
                return decision
            present_started_at = monotonic()
            self._sink.present(frame, brightness=decision.brightness, inverted=decision.inverted)
            finished_at = monotonic()
            finished_ms = wall_time() * 1000.0
        except Exception as error:
            self._logger.record_issue("frame", error, kind=str(decision.kind), mode=decision.mode)
            self._present_retry = True
            self._record_tick(decision, presented=False)
            self._complete_step(decision)
            return decision
        if self._latency.pending_ids and decision.news is None and decision.update_failure is None:
            visible = {}
            if decision.kind is FrameKind.SCROLL:
                visible = self._viewport.visible_updates(decision.scroll_offset or 0, self._latency.pending_ids, getattr(self._sink, "width", 384))
            elif decision.kind is FrameKind.STATIC and decision.content is not None:
                visible = {decision.content.id: {"changed_visible": self._last_frame is None or self._last_frame.tobytes() != frame.tobytes(),
                                                  "installed_mono": present_started_at}}
            self._latency.presented(visible, at_ms=finished_ms, at_mono=finished_at, present_started=present_started_at)
        if self._frame_health is not None:
            self._frame_health.record(frame, decision.kind)
        self._last_presented_visible_ids = self._visible_ids_for_decision(decision)
        if decision.update_failure is not None:
            self._runtime.mark_update_failure_presented(decision.update_failure["id"])
        if decision.update_failure is not None and self._update_service is not None:
            identity = decision.update_failure["id"], decision.update_failure["status"]
            if identity != self._update_notice_ack:
                try:
                    self._update_service.mark_result_presented(dict(decision.update_failure))
                    self._update_notice_ack = identity
                except OSError as error:
                    self._logger.record_issue("update_notice", error)
        self._last_frame = frame
        self._last_visual_key = visual_key
        self._last_base_visual_key = base_visual_key
        self._last_present_at = finished_at
        self._present_retry = False
        self._record_tick(decision, presented=True)
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
            viewport=getattr(self._viewport, "status", None),
            last_present_age=0.0,
            work_stages=(
                (updates_finished_at - started_at) * 1000.0,
                (preparation_finished_at - updates_finished_at) * 1000.0,
                (present_started_at - preparation_finished_at) * 1000.0,
            ),
        )
        self._complete_step(decision)
        return decision

    def _frame_visual_key(self, decision: FrameDecision) -> object:
        """Ask the rendering boundary for one invalidation key."""
        return self._frames.visual_key(decision, asset_revision=self._asset_revision)

    def _record_tick(self, decision: FrameDecision, *, presented: bool) -> None:
        """Record loop activity while keeping presentation FPS separate."""
        record_tick = getattr(self._logger, "record_tick", None)
        if callable(record_tick):
            age = None if self._last_present_at is None else max(0.0, monotonic() - self._last_present_at)
            record_tick(
                interval=decision.interval,
                kind=decision.kind,
                mode=decision.mode,
                wall_time=decision.wall_time,
                presented=presented,
                last_present_age=age,
                viewport=getattr(self._viewport, "status", None),
            )

    def _complete_step(self, decision: FrameDecision) -> None:
        """Run lifecycle work after every frame, retry, or idle tick."""
        self._last_decision = decision
        self._launch_requested_update()
        self._launch_requested_reboot()

    def process_events(self) -> None:
        """Apply ordered events within a small drawing-loop budget."""
        deadline = monotonic() + 0.004
        processed = 0
        while processed < 16 and (not processed or monotonic() < deadline):
            try:
                event = self._events.get_nowait()
            except Empty:
                return
            processed += 1
            if isinstance(event, RejectedUpdate):
                self._logger.record_issue("poll_prepare", event.error)
                continue
            if isinstance(event, PreparedUpdate):
                event_mono = monotonic()
                visible_ids = self._visible_ids_at_accept()
                self._logger.record_poll(success=True, elapsed_ms=event.event.elapsed_ms, response_bytes=event.event.response_bytes)
                for source, error in event.issues:
                    self._logger.record_issue(source, error)
                self._accept_fresh(event.response, persist=False, prepared=event)
                settings = self._last_response.settings.data if self._last_response is not None else {}
                self._latency.accept(event.event.timing, event_mono=event_mono, accepted_mono=monotonic(),
                                     delay_seconds=float(settings.get("live_delay_seconds") or 0) if settings.get("live_delay_mode") else 0,
                                     visible_ids=visible_ids)
            elif isinstance(event, PollConnected):
                self._runtime.confirm_connection()
                self._disconnected = False
            elif isinstance(event, PollUpdateResult):
                self._runtime.observe_update_result(event.receipt, show_notice=event.show_notice)
                self._update_latched = False
                if self._update_service is not None:
                    self._update_service.finish_update()
            elif isinstance(event, PollStreamEvent):
                record_stream = getattr(self._logger, "record_stream", None)
                if callable(record_stream):
                    record_stream(
                        event.event,
                        message_type=event.message_type,
                        sequence=event.sequence,
                        response_bytes=event.response_bytes,
                        apply_ms=event.apply_ms,
                        reconnect=event.reconnect,
                        error_type=event.error_type,
                    )
            else:
                self._logger.record_poll(
                    success=False,
                    elapsed_ms=event.elapsed_ms,
                    error=event.error,
                    retry_in=event.retry_in,
                )
                self._logger.record_issue("backend_poll", event.error, retry_in=event.retry_in)
                self._handle_failure(event)

    def _visible_ids_at_accept(self) -> frozenset[str] | None:
        """Classify the last presented frame without inferring visibility from data."""
        return self._last_presented_visible_ids

    def _visible_ids_for_decision(self, decision: FrameDecision) -> frozenset[str] | None:
        """Capture the viewport geometry for a successfully presented frame."""
        if decision.news is not None or decision.update_failure is not None or decision.connection_lost:
            return None
        if decision.kind is FrameKind.SCROLL:
            visible_ids = getattr(self._viewport, "visible_ids", None)
            if callable(visible_ids):
                return visible_ids(decision.scroll_offset or 0, getattr(self._sink, "width", 384))
            return None
        if decision.kind is FrameKind.STATIC and decision.content is not None:
            return frozenset((decision.content.id,))
        return None

    def _read_poll_events(self) -> None:
        """Restore and prepare process messages outside the drawing thread."""
        pin_to_cpu(self._poll_cpu)
        while not self._stop.is_set():
            try:
                event = self._incoming_events.get(timeout=0.1)
            except Empty:
                continue
            except (EOFError, OSError, ValueError) as error:
                if not self._stop.is_set():
                    self._events.put(RejectedUpdate(error))
                return
            self._events.put(event)

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
            if self._poll_in_process and self._poll_thread.is_alive():
                self._poll_thread.terminate()
                self._poll_thread.join(timeout=2)
            self._poll_thread = None
        if self._event_reader is not None and self._event_reader is not current_thread():
            self._event_reader.join(timeout=6)
            self._event_reader = None
        if self._incoming_events is not None:
            self._incoming_events.close()
            self._incoming_events.join_thread()
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

    def _record_latency(self, value: Mapping[str, object]) -> None:
        self._logger.record_latency({**value, "device_id": self._device_id, "output_driver": type(self._sink).__name__})

    def _record_viewport_issue(self, details: Mapping[str, object]) -> None:
        """Forward card renderer failures to the application health stream."""
        values = dict(details)
        source = str(values.pop("source", "card_renderer"))
        error = str(values.pop("error", "card renderer failed"))
        self._logger.record_issue(source, error, **values)

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
                if not state.internet_available and state.local_setup_active and state.hotspot_active and not portal_started:
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
        current = self._runtime.accept_cached_response(
            response,
            stale_for=self._cache.age(entry),
            expires_in=self._cache.remaining(entry),
        )
        self._prefetch_runtime_assets(current)
        self._disconnected = True
        self._last_response = response
        self._refresh_viewport()

    def _accept_fresh(
        self,
        response: TickerResponse,
        *,
        persist: bool = True,
        asset_source: object | None = None,
        prepared: PreparedUpdate | None = None,
    ) -> None:
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
        if prepared is None:
            self._assets.prefetch_payload(response if asset_source is None else asset_source)
        current = self._runtime.accept_response(response, prepared_content=prepared.content if prepared is not None else None)
        self._prefetch_runtime_assets(current)
        self._disconnected = False
        self._pending_reboot_id = response.reboot_request_id
        self._last_response = response
        del previous
        self._refresh_viewport(current, changed_ids=prepared.changed_ids if prepared is not None and not prepared.settings_changed else None)

    def _refresh_local_hardware_content(self) -> None:
        """Refresh local calendar-controlled cards before the next frame."""

        if not self._runtime.refresh_local_date():
            return
        current = self._runtime.snapshot
        self._prefetch_runtime_assets(current)
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
        if entry is not None:
            expires_in = max(30.0, self._cache.remaining(entry))
        elif self._runtime.snapshot is not None:
            expires_in = 30.0
        else:
            expires_in = self._runtime.config.offline_after
        self._runtime.mark_disconnected(expires_in=expires_in)

    def _refresh_viewport(self, snapshot=None, *, changed_ids: frozenset[str] | None = None) -> None:
        """Queue changed card scenes without composing a long strip image."""
        current = snapshot or self._runtime.snapshot
        if current is None:
            return
        layout = self._viewport.update(
            self._runtime.classification.scrolling,
            RenderContext(self._wall_clock()),
            self._runtime.mode,
            changed_ids=changed_ids,
        )
        self._runtime.install_strip(current.strip_key, layout)

    def _prefetch_runtime_assets(self, snapshot) -> None:
        """Prefetch assets introduced by controller-owned content."""

        if snapshot is not None and any(item.type == "fan_duel_joke_ad" for item in snapshot.content):
            self._assets.prefetch_payload(snapshot.content)

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

    def _launch_requested_update(self) -> None:
        """Acknowledge one server request, then start the non-blocking updater."""

        request = self._runtime.take_update_request()
        if request is None or self._update_latched:
            return
        if not request.command_id or self._update_service is None:
            return
        try:
            self._update_latched = self._update_service.request_update(
                request.version, command_id=request.command_id, ticker_id=self._device_id,
            )
        except Exception as error:
            self._logger.record_issue("update_start", error, version=request.version)

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

    pin_to_cpu(cpu)
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
            self._target.put(PollSucceeded(event.payload, event.elapsed_ms, event.response_bytes, event.timing))
            return
        if isinstance(event, PollFailed):
            self._target.put(PollFailed(RuntimeError(str(event.error)), event.retry_in, event.elapsed_ms))
            return
        self._target.put(event)


class _NullPiLogger:
    """Keep custom and test compositions free from logging dependencies."""

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass

    def record_frame(self, **kwargs) -> None:
        del kwargs

    def record_tick(self, **kwargs) -> None:
        del kwargs

    def record_poll(self, **kwargs) -> None:
        del kwargs

    def record_stream(self, event, **kwargs) -> None:
        del event, kwargs

    def record_payload(self, response) -> None:
        del response

    def record_latency(self, value) -> None:
        del value

    def record_issue(self, source, error, **details) -> None:
        del source, error, details


def _unintended_black(frame: object, decision: FrameDecision) -> bool:
    """Detect an accidental all-black frame before matrix presentation."""
    if decision.kind in {FrameKind.STOPPED, FrameKind.SLEEP} or decision.brightness <= 0:
        return False
    getbbox = getattr(frame, "getbbox", None)
    if not callable(getbbox):
        return False
    return getbbox() is None


