"""Test the composed controller outage lifecycle."""

from datetime import datetime, timezone
from queue import Queue
from threading import Event

from PIL import Image

from ticker_core.app import PollFailed, PollSucceeded, TickerApplication
from ticker_core.assets import ShortTermContentCache
from ticker_core.runtime import FrameKind, FramePacer, RuntimeConfig, TickerRuntime
from ticker_core.protocol import TickerResponse


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


class Strips:
    """Avoid pixel work while testing lifecycle state."""

    def build(self, *args):
        return None


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
        strips=Strips(),
        frames=Frames(),
        pacer=FramePacer(lambda: clock[0]),
        sink=Sink(),
        commands=Commands(),
        device_id="ticker-1",
        repository=tmp_path,
        wall_clock=lambda: wall,
    )
    response = TickerResponse.from_payload(
        {
            "status": "ok",
            "local_config": {"mode": "sports"},
            "global_config": {},
            "content": {"sports": [{"id": "game", "type": "game", "sport": "nba"}]},
            "alerts": [],
            "news": [],
        }
    )
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
