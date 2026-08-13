from queue import Queue
from threading import Event

import pytest

from ticker_core.app import BackendPoller, PollFailed, PollSucceeded


class StopAfterWait(Event):
    def __init__(self):
        super().__init__()
        self.delays = []

    def wait(self, timeout=None):
        self.delays.append(timeout)
        self.set()
        return True


class Client:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def fetch_data(self, device_id, headers):
        self.calls.append((device_id, headers))
        if self.error:
            raise self.error
        return self.result


def test_poller_publishes_success_and_uses_regular_interval():
    payload = object()
    client = Client(result=payload)
    stop = StopAfterWait()
    events = Queue()
    BackendPoller(client, "ticker-1", telemetry_headers=lambda: {"X": "1"}).run(stop, events)
    event = events.get_nowait()
    assert isinstance(event, PollSucceeded)
    assert event.payload is payload
    assert stop.delays == [pytest.approx(0.5, abs=0.01)]
    assert client.calls == [("ticker-1", {"X": "1"})]


def test_poller_publishes_failure_and_uses_backoff():
    error = RuntimeError("offline")
    stop = StopAfterWait()
    events = Queue()
    BackendPoller(Client(error=error), "ticker-1", telemetry_headers=dict).run(stop, events)
    event = events.get_nowait()
    assert isinstance(event, PollFailed)
    assert event.error is error
    assert event.retry_in == 1.0
    assert stop.delays == [1.0]
