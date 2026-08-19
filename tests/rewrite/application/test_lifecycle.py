"""Test the composed controller outage lifecycle."""

from datetime import datetime, timezone
from queue import Queue
from threading import Event
import pytest

from PIL import Image

from ticker_core.app import PollConnected, PollFailed, PollSucceeded, TickerApplication
from ticker_core.assets import ShortTermContentCache
from ticker_core.platform import HotspotDetails, WiFiSetupState
from ticker_core.runtime import FrameKind, FramePacer, RuntimeConfig, TickerRuntime
from ticker_core.protocol import TickerResponse, display_delta

pytestmark = pytest.mark.critical


def payload() -> dict:
    return {
        "api_version": "v2",
        "snapshot": {"ticker_id": "ticker-1", "revision": 1, "observed_at": "2026-08-11T00:00:00+00:00", "stale": False},
        "settings": {"mode": "sports", "sports_presentation": "rotation", "pinned_content_id": "", "brightness": 100, "scroll_speed": 0.05, "inverted": False},
        "content": {"sports": [{"id": "game", "family": "sports", "kind": "scoreboard", "is_shown": True, "data": {"sport": "nba"}}]},
        "events": {"alerts": [], "news": []}, "health": {"provider": "refresh", "healthy": True, "error": None},
        "meta": {"pairing": {"paired": True, "code": None}},
    }


class IdlePoller:
    """Wait for shutdown without making a backend request."""

    def run(self, stop: Event, events: Queue) -> None:
        del events
        stop.wait()


class Assets:
    """Record prefetch work without creating worker threads."""

    def __init__(self) -> None:
        self.payloads = []

    def start(self) -> None:
        pass

    def prefetch_payload(self, payload) -> None:
        self.payloads.append(payload)

    def close(self) -> None:
        pass


class Logger:
    """Record poll history without starting a writer thread."""

    def __init__(self) -> None:
        self.polls = []

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass

    def record_frame(self, **values) -> None:
        del values

    def record_tick(self, **values) -> None:
        del values

    def record_poll(self, **values) -> None:
        self.polls.append(values)

    def record_payload(self, response) -> None:
        del response

    def record_issue(self, source, error, **details) -> None:
        del source, error, details


class Viewport:
    """Avoid pixel work while testing lifecycle state."""

    def __init__(self) -> None:
        self.updates = 0

    def update(self, *args):
        self.updates += 1
        return None

    def install_completed(self):
        return None

    def invalidate(self) -> None:
        pass

    def close(self) -> None:
        pass


class Frames:
    """Return one visible panel for every runtime decision."""

    def visual_key(self, decision, *, asset_revision=None):
        return decision, asset_revision

    def build(self, decision):
        return Image.new("RGB", (384, 32), (1, 2, 3))


class Sink:
    """Record presented frame parameters."""

    width = 384
    height = 32

    def __init__(self) -> None:
        self.presented = []
        self.clear_calls = 0

    def present(self, image, *, brightness=100, inverted=False) -> None:
        self.presented.append((image, brightness, inverted))

    def clear(self) -> None:
        self.clear_calls += 1


class Client:
    """Supply the non-poll client methods used by the application."""

    def push_setting(self, *args) -> None:
        pass

    def close(self) -> None:
        pass


class Commands:
    """Avoid host actions during this test."""

    def reboot(self) -> None:
        pass

    def run_update(self, command) -> None:
        pass


class OfflineWiFiRecovery:
    """Return one deterministic offline state without probing the network."""

    def __init__(self) -> None:
        self.setup_started = Event()
        self.release_setup = Event()
        self.portal_started = Event()
        self.state = WiFiSetupState(
            internet_available=False,
            hotspot_active=True,
            hotspot=HotspotDetails("SportsTicker_Setup", "setup1234"),
        )

    def start_setup(self) -> WiFiSetupState:
        self.setup_started.set()
        self.release_setup.wait(1)
        return self.state

    def start_portal(self) -> bool:
        self.portal_started.set()
        return True


def test_wifi_recovery_starts_with_the_application_and_selects_setup_frame(tmp_path) -> None:
    """Select the Wi-Fi frame from platform state without network work in the render loop."""

    wall = datetime(2026, 8, 15, tzinfo=timezone.utc)
    recovery = OfflineWiFiRecovery()
    application = TickerApplication(
        client=Client(),
        poller=IdlePoller(),
        cache=ShortTermContentCache(tmp_path / "content.json"),
        assets=Assets(),
        runtime=TickerRuntime(monotonic=lambda: 0.0, wall_clock=lambda: wall),
        viewport=Viewport(),
        frames=Frames(),
        pacer=FramePacer(lambda: 0.0),
        sink=Sink(),
        commands=Commands(),
        device_id="ticker-1",
        repository=tmp_path,
        wall_clock=lambda: wall,
        wifi_recovery=recovery,
        wifi_check_interval=0.05,
    )
    try:
        application.start()
        assert recovery.setup_started.wait(1)
        recovery.release_setup.set()
        for _ in range(100):
            if application.wifi_state is not None:
                break
            Event().wait(0.01)

        decision = application.step()
        assert decision.kind is FrameKind.WIFI_SETUP
        assert decision.wifi_state == recovery.state
        assert recovery.portal_started.wait(1)
        assert application.sink.presented[-1][0].size == (384, 32)
    finally:
        application.close()


def test_fresh_content_keeps_connection_icon_until_cache_expiry(tmp_path) -> None:
    """Keep normal content first, then replace it with the offline screen."""
    clock = [0.0]
    wall = datetime(2026, 8, 11, tzinfo=timezone.utc)
    runtime = TickerRuntime(
        monotonic=lambda: clock[0],
        wall_clock=lambda: wall,
        config=RuntimeConfig(offline_after=60),
    )
    application = TickerApplication(
        client=Client(),
        poller=IdlePoller(),
        cache=ShortTermContentCache(tmp_path / "content.json", ttl=300, clock=lambda: clock[0]),
        assets=Assets(),
        runtime=runtime,
        viewport=Viewport(),
        frames=Frames(),
        pacer=FramePacer(lambda: clock[0]),
        sink=Sink(),
        commands=Commands(),
        device_id="ticker-1",
        repository=tmp_path,
        wall_clock=lambda: wall,
    )
    response = TickerResponse.from_payload(payload())
    try:
        application.start()
        application._events.put(PollSucceeded(response))
        application.step()
        application._events.put(PollFailed(RuntimeError("lost"), 1.0))
        cached = application.step()

        assert cached.connection_lost is True
        assert cached.kind is not FrameKind.OFFLINE

        clock[0] = 301.0
        expired = application.step()
        assert expired.kind is FrameKind.OFFLINE
    finally:
        application.close()


def test_same_poll_payload_does_not_update_scroll_cards(tmp_path) -> None:
    """Keep frame work outside unchanged backend polls."""
    wall = datetime(2026, 8, 11, tzinfo=timezone.utc)
    runtime = TickerRuntime(monotonic=lambda: 0.0, wall_clock=lambda: wall)
    viewport = Viewport()
    assets = Assets()
    application = TickerApplication(
        client=Client(),
        poller=IdlePoller(),
        cache=ShortTermContentCache(tmp_path / "content.json"),
        assets=assets,
        runtime=runtime,
        viewport=viewport,
        frames=Frames(),
        pacer=FramePacer(lambda: 0.0),
        sink=Sink(),
        commands=Commands(),
        device_id="ticker-1",
        repository=tmp_path,
        wall_clock=lambda: wall,
    )
    response = TickerResponse.from_payload(payload())
    try:
        application.start()
        application._events.put(PollSucceeded(response))
        application.step()
        application._events.put(PollSucceeded(response))
        application.step()

        assert viewport.updates == 1
        assert assets.payloads == [response]
    finally:
        application.close()


def test_static_frame_skips_unchanged_build_and_present(tmp_path) -> None:
    wall = datetime(2026, 8, 11, tzinfo=timezone.utc)
    runtime = TickerRuntime(monotonic=lambda: 0.0, wall_clock=lambda: wall)
    frames = Frames()
    frames.calls = 0
    original_build = frames.build
    frames.build = lambda decision: (setattr(frames, "calls", frames.calls + 1) or original_build(decision))
    sink = Sink()
    application = TickerApplication(
        client=Client(), poller=IdlePoller(), cache=ShortTermContentCache(tmp_path / "content.json"),
        assets=Assets(), runtime=runtime, viewport=Viewport(), frames=frames,
        pacer=FramePacer(lambda: 0.0), sink=sink, commands=Commands(), device_id="ticker-1",
        repository=tmp_path, wall_clock=lambda: wall,
    )
    pinned = payload()
    pinned["settings"]["sports_presentation"] = "pinned"
    try:
        application.start()
        application._events.put(PollSucceeded(TickerResponse.from_payload(pinned)))
        application.step()
        application.step()
        assert frames.calls == 1
        assert len(sink.presented) == 1
    finally:
        application.close()


def test_delta_prefetches_only_changed_asset_scenes(tmp_path) -> None:
    """Keep full payload asset scans outside ordinary live score updates."""

    wall = datetime(2026, 8, 11, tzinfo=timezone.utc)
    assets = Assets()
    application = TickerApplication(
        client=Client(),
        poller=IdlePoller(),
        cache=ShortTermContentCache(tmp_path / "content.json"),
        assets=assets,
        runtime=TickerRuntime(monotonic=lambda: 0.0, wall_clock=lambda: wall),
        viewport=Viewport(),
        frames=Frames(),
        pacer=FramePacer(lambda: 0.0),
        sink=Sink(),
        commands=Commands(),
        device_id="ticker-1",
        repository=tmp_path,
        wall_clock=lambda: wall,
    )
    before_payload = payload()
    before_payload["settings"]["my_teams"] = ["nba:NY"]
    before = TickerResponse.from_payload(before_payload)
    updated_payload = payload()
    updated_payload["settings"]["my_teams"] = ["nba:NY"]
    updated_payload["content"]["sports"][0]["data"]["status"] = "Q2 08:14"
    updated = TickerResponse.from_payload(updated_payload)
    delta = display_delta(before, updated)
    try:
        application.start()
        application._events.put(PollSucceeded(before))
        application.step()
        application._events.put(PollSucceeded(delta))
        application.step()

        assert len(delta.changed) == 1
        assert not delta.settings_changed
        assert assets.payloads == [before, (delta.changed[0].data,)]

        mode_payload = payload()
        mode_payload["settings"]["my_teams"] = ["nba:NY"]
        mode_payload["content"]["sports"][0]["data"]["status"] = "Q2 08:14"
        mode_payload["settings"]["mode"] = "clock"
        mode_response = TickerResponse.from_payload(mode_payload)
        mode_delta = display_delta(updated, mode_response)
        application._events.put(PollSucceeded(mode_delta))
        application.step()

        assert mode_delta.settings_changed
        assert assets.payloads[-1].payload_key == mode_response.payload_key
    finally:
        application.close()


def test_unchanged_success_does_not_write_poll_history(tmp_path) -> None:
    """Keep half-second unchanged polls away from disk-backed history."""

    wall = datetime(2026, 8, 11, tzinfo=timezone.utc)
    logger = Logger()
    application = TickerApplication(
        client=Client(), poller=IdlePoller(), cache=ShortTermContentCache(tmp_path / "content.json"),
        assets=Assets(), runtime=TickerRuntime(monotonic=lambda: 0.0, wall_clock=lambda: wall),
        viewport=Viewport(), frames=Frames(), pacer=FramePacer(lambda: 0.0), sink=Sink(),
        commands=Commands(), device_id="ticker-1", repository=tmp_path, wall_clock=lambda: wall,
        logger=logger,
    )
    try:
        application.start()
        application._events.put(PollConnected(elapsed_ms=42.0, response_bytes=55_000))
        application.step()

        assert logger.polls == []
    finally:
        application.close()


def test_frame_failure_does_not_stop_step_or_clear_matrix(tmp_path) -> None:
    class FailingFrames(Frames):
        def build(self, decision):
            raise RuntimeError("render failed")

    sink = Sink()
    application = TickerApplication(
        client=Client(), poller=IdlePoller(), cache=ShortTermContentCache(tmp_path / "content.json"),
        assets=Assets(), runtime=TickerRuntime(monotonic=lambda: 0.0, wall_clock=lambda: datetime.now(timezone.utc)),
        viewport=Viewport(), frames=FailingFrames(), pacer=FramePacer(lambda: 0.0), sink=sink,
        commands=Commands(), device_id="ticker-1", repository=tmp_path, wall_clock=lambda: datetime.now(timezone.utc),
    )
    try:
        application.start()
        application.step()
        application.step()
        assert sink.clear_calls == 0
    finally:
        application.close()


def test_present_failure_keeps_last_good_matrix_frame_and_retries(tmp_path) -> None:
    class FlakySink(Sink):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False

        def present(self, image, *, brightness=100, inverted=False) -> None:
            if not self.failed:
                self.failed = True
                raise RuntimeError("matrix unavailable")
            super().present(image, brightness=brightness, inverted=inverted)

    sink = FlakySink()
    application = TickerApplication(
        client=Client(), poller=IdlePoller(), cache=ShortTermContentCache(tmp_path / "content.json"),
        assets=Assets(), runtime=TickerRuntime(monotonic=lambda: 0.0, wall_clock=lambda: datetime.now(timezone.utc)),
        viewport=Viewport(), frames=Frames(), pacer=FramePacer(lambda: 0.0), sink=sink,
        commands=Commands(), device_id="ticker-1", repository=tmp_path, wall_clock=lambda: datetime.now(timezone.utc),
    )
    try:
        application.start()
        application.step()
        assert sink.presented == []
        assert sink.clear_calls == 0
        application.step()
        assert len(sink.presented) == 1
        assert sink.clear_calls == 0
    finally:
        application.close()


def test_present_failure_retries_even_when_visual_key_is_unchanged(tmp_path) -> None:
    class RetrySink(Sink):
        def __init__(self) -> None:
            super().__init__()
            self.fail_next = False

        def present(self, image, *, brightness=100, inverted=False) -> None:
            if self.fail_next:
                self.fail_next = False
                raise RuntimeError("temporary matrix failure")
            super().present(image, brightness=brightness, inverted=inverted)

    sink = RetrySink()
    application = TickerApplication(
        client=Client(), poller=IdlePoller(), cache=ShortTermContentCache(tmp_path / "content.json"),
        assets=Assets(), runtime=TickerRuntime(monotonic=lambda: 0.0, wall_clock=lambda: datetime.now(timezone.utc)),
        viewport=Viewport(), frames=Frames(), pacer=FramePacer(lambda: 0.0), sink=sink,
        commands=Commands(), device_id="ticker-1", repository=tmp_path, wall_clock=lambda: datetime.now(timezone.utc),
    )
    try:
        application.start()
        application.step()
        sink.fail_next = True
        application.step()
        assert len(sink.presented) == 1
        application.step()
        assert len(sink.presented) == 2
    finally:
        application.close()


def test_unintended_black_frame_is_rejected_and_retried(tmp_path) -> None:
    class BlackThenVisibleFrames(Frames):
        def __init__(self) -> None:
            self.calls = 0

        def build(self, decision):
            self.calls += 1
            return Image.new("RGB", (384, 32), "black" if self.calls == 1 else (1, 2, 3))

    sink = Sink()
    frames = BlackThenVisibleFrames()
    application = TickerApplication(
        client=Client(), poller=IdlePoller(), cache=ShortTermContentCache(tmp_path / "content.json"),
        assets=Assets(), runtime=TickerRuntime(monotonic=lambda: 0.0, wall_clock=lambda: datetime.now(timezone.utc)),
        viewport=Viewport(), frames=frames, pacer=FramePacer(lambda: 0.0), sink=sink,
        commands=Commands(), device_id="ticker-1", repository=tmp_path, wall_clock=lambda: datetime.now(timezone.utc),
    )
    try:
        application.start()
        application.step()
        assert sink.presented == []
        application.step()
        assert len(sink.presented) == 1
        assert sink.presented[0][0].getbbox() is not None
    finally:
        application.close()


def test_poll_failure_grants_grace_period_for_disconnected_content(tmp_path) -> None:
    """Retain content with connection_lost overlay during temporary poll outages."""
    from ticker_core.app.poller import PollFailed

    wall = datetime.now(timezone.utc)
    now = [0.0]
    runtime = TickerRuntime(monotonic=lambda: now[0], wall_clock=lambda: wall)
    application = TickerApplication(
        client=Client(),
        poller=IdlePoller(),
        cache=ShortTermContentCache(tmp_path / "content.json"),
        assets=Assets(),
        runtime=runtime,
        viewport=Viewport(),
        frames=Frames(),
        pacer=FramePacer(lambda: now[0]),
        sink=Sink(),
        commands=Commands(),
        device_id="ticker-1",
        repository=tmp_path,
        wall_clock=lambda: wall,
    )
    try:
        application.start()
        application._events.put(PollFailed(RuntimeError("temporary timeout"), retry_in=1.0))
        decision = application.step()
        assert decision.connection_lost is True
        assert decision.kind != FrameKind.OFFLINE

        now[0] = 30.0
        active_decision = application.step()
        assert active_decision.kind != FrameKind.OFFLINE

        now[0] = 61.0
        expired_decision = application.step()
        assert expired_decision.kind == FrameKind.OFFLINE
    finally:
        application.close()
