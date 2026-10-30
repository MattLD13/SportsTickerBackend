"""Verify device bootstrap, sequenced stream delivery, and reconnect backoff."""

import json
from pathlib import Path
from queue import Queue
from threading import Event

import pytest

from ticker.six.app import BackendPoller, PollConnected, PollFailed, PollStreamEvent, PollSucceeded
from ticker.six.protocol import TickerResponse


pytestmark = pytest.mark.critical
SNAPSHOT = Path(__file__).resolve().parents[2] / "fixtures/display" / "render_snapshot.json"


def _payload():
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    payload["snapshot"]["ticker_id"] = "ticker-1"
    return payload


class FakeStream:
    def __init__(self, stop: Event, payload):
        self.stop = stop
        self.payload = payload
        self.closed = False

    def recv(self):
        self.stop.set()
        return json.dumps({
            "type": "snapshot",
            "stream_id": "stream-1",
            "seq": 1,
            "base_seq": 1,
            "server_time": "2026-10-14T00:00:00+00:00",
            "payload": self.payload,
        })

    def close(self):
        self.closed = True


class Client:
    def __init__(self, stop, *, stream_error=None):
        self.payload = _payload()
        self.result = TickerResponse.from_payload(self.payload)
        self.stop = stop
        self.stream_error = stream_error
        self.last_response_bytes = 123
        self.registration = None
        self.stream_options = None
        self.stream = None

    def register_device(self, device_id, *, name="Ticker", metadata=None, profile=None):
        self.registration = (device_id, name, metadata, profile)
        return object()

    def fetch_data(self, device_id):
        assert device_id == "ticker-1"
        return self.result

    def open_device_stream(self, device_id, **options):
        assert device_id == "ticker-1"
        self.stream_options = options
        if self.stream_error is not None:
            raise self.stream_error
        self.stream = FakeStream(self.stop, self.payload)
        return self.stream

    def remember_stream_response(self, device_id, response):
        assert device_id == "ticker-1"


class StopAfterWait(Event):
    def __init__(self):
        super().__init__()
        self.delays = []

    def wait(self, timeout=None):
        self.delays.append(timeout)
        self.set()
        return True


def test_poller_bootstraps_over_http_then_accepts_stream_snapshot():
    stop = Event()
    client = Client(stop)
    events = Queue()

    BackendPoller(client, "ticker-1", telemetry=lambda: {}, heartbeat_interval=3600).run(stop, events)

    boot = events.get_nowait()
    connected = events.get_nowait()
    message = events.get_nowait()
    stream = events.get_nowait()
    assert isinstance(boot, PollSucceeded)
    assert boot.payload.ticker_id == "ticker-1"
    assert connected == PollStreamEvent("connected")
    assert message.event == "message"
    assert message.message_type == "snapshot"
    assert message.sequence == 1
    assert message.response_bytes > 0
    assert message.apply_ms >= 0
    assert isinstance(stream, PollConnected)
    assert client.registration[0] == "ticker-1"
    assert client.stream_options == {"stream_id": None, "after_seq": None, "timeout_seconds": 0.5}
    assert client.stream.closed is True


def test_poller_reports_stream_failure_and_uses_backoff():
    stop = StopAfterWait()
    client = Client(stop, stream_error=RuntimeError("offline"))
    events = Queue()

    BackendPoller(client, "ticker-1", telemetry=dict, heartbeat_interval=3600).run(stop, events)

    assert isinstance(events.get_nowait(), PollSucceeded)
    connect_failure = events.get_nowait()
    failure = events.get_nowait()
    assert connect_failure.event == "connect_failed"
    assert connect_failure.error_type == "RuntimeError"
    assert isinstance(failure, PollFailed)
    assert str(failure.error) == "offline"
    assert failure.retry_in == 1.0
    assert stop.delays == [1.0]
