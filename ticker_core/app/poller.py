"""Poll the backend and publish results without mutating runtime state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from queue import Queue
from threading import Event
from typing import Protocol

from ticker_core.protocol import BackendClient, DisplayPayload, PollBackoff


class Waiter(Protocol):
    """Wait until a delay ends or a stop arrives."""

    def wait(self, timeout: float) -> bool:
        """Return true when a stop interrupts the delay."""


@dataclass(frozen=True, slots=True)
class PollSucceeded:
    """Deliver one parsed backend response to the main loop."""

    payload: DisplayPayload


@dataclass(frozen=True, slots=True)
class PollFailed:
    """Deliver one polling failure for logging and health state."""

    error: Exception
    retry_in: float


PollEvent = PollSucceeded | PollFailed


class BackendPoller:
    """Own the blocking backend poll loop."""

    def __init__(
        self,
        client: BackendClient,
        device_id: str,
        *,
        telemetry_headers: Callable[[], Mapping[str, str]],
        success_interval: float = 0.5,
    ) -> None:
        if not device_id:
            raise ValueError("A device id is required.")
        if success_interval < 0:
            raise ValueError("The poll interval cannot be negative.")
        self._client = client
        self._device_id = device_id
        self._telemetry_headers = telemetry_headers
        self._success_interval = success_interval

    def run(self, stop: Event, events: Queue[PollEvent]) -> None:
        """Poll until the stop event interrupts a delay."""
        backoff = PollBackoff()
        while not stop.is_set():
            try:
                payload = self._client.fetch_data(self._device_id, self._telemetry_headers())
            except Exception as error:
                backoff = backoff.after_failure()
                events.put(PollFailed(error, backoff.delay_seconds))
                if stop.wait(backoff.delay_seconds):
                    return
                continue
            backoff = backoff.after_success()
            events.put(PollSucceeded(payload))
            if stop.wait(self._success_interval):
                return
