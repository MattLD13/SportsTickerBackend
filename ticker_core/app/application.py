"""Own the executable Pi controller lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
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
from .poller import BackendPoller, PollEvent, PollFailed, PollSucceeded
from .strips import StripRepository


class PollWorker(Protocol):
    """Run a backend polling loop with caller-owned stop state."""

    def run(self, stop: Event, events: Queue[PollEvent]) -> None:
        """Publish events until the stop event is set."""


class ContentCache(Protocol):
    """Store the valid response used during a short outage."""

    def store(self, payload: Mapping[str, object]):
        """Store one fresh backend payload."""

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
        self._events: Queue[PollEvent] = Queue()
        self._stop = Event()
        self._poll_thread: Thread | None = None
        self._started = False
        self._disconnected = False
        self._reboot_latched = False
        self._update_latched = False
        self._asset_revision = self._asset_revision_now()

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
        start_sink = getattr(self._sink, "start", None)
        if callable(start_sink):
            start_sink()
        self._assets.start()
        self._restore_cached_content()
        self._poll_thread = Thread(target=self._poller.run, args=(self._stop, self._events), name="ticker-backend-poll", daemon=True)
        self._poll_thread.start()

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
        if not self._started:
            self.start()
        self.process_events()
        self._rebuild_strip_after_asset_change()
        self._push_requested_modes()
        decision = self._runtime.next_frame()
        frame = self._frames.build(decision)
        self._sink.present(frame, brightness=decision.brightness, inverted=decision.inverted)
        self._last_decision = decision
        return decision

    def process_events(self) -> None:
        """Apply all completed poll events on the application thread."""
        while True:
            try:
                event = self._events.get_nowait()
            except Empty:
                return
            if isinstance(event, PollSucceeded):
                self._accept_fresh(event.payload)
            else:
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
        self._assets.close()
        self._client.close()
        self._sink.clear()
        close_sink = getattr(self._sink, "close", None)
        if callable(close_sink):
            close_sink()
        self._started = False

    def _restore_cached_content(self) -> None:
        entry = self._cache.load()
        if entry is None:
            return
        try:
            response = TickerResponse.from_payload(entry.payload)
        except Exception:
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
        self._cache.store(response.data)
        self._assets.prefetch_payload(response)
        self._runtime.accept_response(response)
        self._disconnected = False
        self._rebuild_strip()
        self._apply_global_commands(response)

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
        snapshot = self._runtime.snapshot
        if snapshot is None:
            return
        layout = self._strips.build(
            snapshot.key,
            self._runtime.classification.scrolling,
            RenderContext(self._wall_clock()),
            self._runtime.mode,
        )
        self._runtime.install_strip(snapshot.key, layout)
        self._asset_revision = self._asset_revision_now()

    def _rebuild_strip_after_asset_change(self) -> None:
        """Refresh scrolling cards after background asset work changes images."""
        revision = self._asset_revision_now()
        if revision != self._asset_revision:
            self._rebuild_strip()

    def _asset_revision_now(self) -> int | None:
        """Read the optional prepared-image revision without I/O."""
        value = getattr(self._assets, "revision", None)
        return int(value) if isinstance(value, int) else None

    def _push_requested_modes(self) -> None:
        while request := self._runtime.take_mode_request():
            try:
                self._client.push_setting(self._device_id, "mode", request.mode)
            except Exception:
                pass

    def _apply_global_commands(self, response: TickerResponse) -> None:
        global_config = response.global_config
        if global_config.reboot:
            if not self._reboot_latched:
                self._commands.reboot()
                self._reboot_latched = True
        else:
            self._reboot_latched = False
        update = self._runtime.take_update_request()
        if global_config.update:
            if update is not None and not self._update_latched:
                if self._update_service is not None:
                    self._update_service.request_update(update.version)
                else:
                    self._commands.run_update(self._update_command)
                    self._runtime.finish_update()
                self._update_latched = True
        else:
            self._update_latched = False
            if self._update_service is not None:
                self._update_service.finish_update()
            self._runtime.finish_update()


def _default_update_command(repository: Path) -> tuple[str, ...]:
    """Read one safe updater command from the environment."""
    configured = os.environ.get("TICKER_UPDATE_COMMAND", "").strip()
    if configured:
        return tuple(shlex.split(configured))
    return (sys.executable, str(repository / "updater.py"), "--no-display")
