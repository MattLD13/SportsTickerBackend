"""Poll the backend and publish results without mutating runtime state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from queue import Queue
from threading import Event
from time import monotonic
from typing import Any, Protocol

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
        telemetry: Callable[[], object],
        success_interval: float = 0.5,
        heartbeat_interval: float = 30.0,
    ) -> None:
        if not device_id:
            raise ValueError("A device id is required.")
        if success_interval < 0:
            raise ValueError("The poll interval cannot be negative.")
        if heartbeat_interval <= 0:
            raise ValueError("The heartbeat interval must be positive.")
        self._client = client
        self._device_id = device_id
        self._telemetry = telemetry
        self._success_interval = success_interval
        self._heartbeat_interval = heartbeat_interval

    def run(self, stop: Event, events: Queue[PollEvent]) -> None:
        """Poll until the stop event interrupts a delay."""
        backoff = PollBackoff()
        next_poll = monotonic()
        next_heartbeat = next_poll
        while not stop.is_set():
            try:
                payload = self._client.fetch_data(self._device_id)
                now = monotonic()
                if now >= next_heartbeat:
                    self._send_heartbeat()
                    next_heartbeat = now + self._heartbeat_interval
            except Exception as error:
                backoff = backoff.after_failure()
                events.put(PollFailed(error, backoff.delay_seconds))
                if stop.wait(backoff.delay_seconds):
                    return
                continue
            backoff = backoff.after_success()
            events.put(PollSucceeded(payload))
            next_poll += self._success_interval
            now = monotonic()
            if next_poll <= now:
                next_poll = now
                delay = 0.0
            else:
                delay = next_poll - now
            if stop.wait(delay):
                return

    def _send_heartbeat(self) -> None:
        """Report device facts without turning heartbeat failure into link loss."""

        heartbeat = getattr(self._client, "heartbeat", None)
        if not callable(heartbeat):
            return
        snapshot = self._telemetry()
        metadata: dict[str, Any] = {}
        for name in ("uptime_seconds", "build", "python", "temperature_c"):
            value = getattr(snapshot, name, None)
            if value is not None:
                metadata[name] = value
        try:
            heartbeat(self._device_id, metadata)
        except Exception:
            return
