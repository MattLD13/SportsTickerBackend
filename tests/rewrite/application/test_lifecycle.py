"""Test the composed controller outage lifecycle."""

from datetime import datetime, timezone
from queue import Queue
from threading import Event

from PIL import Image

from ticker_core.app import PollFailed, PollSucceeded, TickerApplication
from ticker_core.assets import ShortTermContentCache
from ticker_core.platform import HotspotDetails, WiFiSetupState
from ticker_core.runtime import FrameKind, FramePacer, RuntimeConfig, TickerRuntime
from ticker_core.protocol import TickerResponse


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
    """Return one valid blank panel for every runtime decision."""

    def build(self, decision):
        return Image.new("RGB", (384, 32))


class Sink:
    """Record presented frame parameters."""

    width = 384
    height = 32

    def __init__(self) -> None:
        self.presented = []

    def present(self, image, *, brightness=100, inverted=False) -> None:
        self.presented.append((image, brightness, inverted))

    def clear(self) -> None:
        pass


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
