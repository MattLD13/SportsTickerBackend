"""Poll the backend and publish results without mutating runtime state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from queue import Queue
from threading import Event
from time import monotonic
from typing import Any, Protocol

from ticker_core.protocol import BackendClient, BackendHttpError, DisplayPayload, PollBackoff, display_delta


class Waiter(Protocol):
    """Wait until a delay ends or a stop arrives."""

    def wait(self, timeout: float) -> bool:
        """Return true when a stop interrupts the delay."""


@dataclass(frozen=True, slots=True)
class PollSucceeded:
    """Deliver one parsed backend response to the main loop."""

    payload: DisplayPayload
    elapsed_ms: float = 0.0
    response_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class PollFailed:
    """Deliver one polling failure for logging and health state."""

    error: Exception
    retry_in: float
    elapsed_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class PollConnected:
    """Confirm a successful poll whose display data is unchanged."""

    elapsed_ms: float = 0.0
    response_bytes: int | None = None


PollEvent = PollSucceeded | PollFailed | PollConnected


class BackendPoller:
    """Own the blocking backend poll loop."""

    def __init__(
        self,
        client: BackendClient,
        device_id: str,
        *,
        telemetry: Callable[[], object],
        device_name: str = "Ticker",
        success_interval: float = 0.5,
        heartbeat_interval: float = 30.0,
    ) -> None:
        if not device_id:
            raise ValueError("A device id is required.")
        if not device_name.strip():
            raise ValueError("A device name is required.")
        if success_interval < 0:
            raise ValueError("The poll interval cannot be negative.")
        if heartbeat_interval <= 0:
            raise ValueError("The heartbeat interval must be positive.")
        self._client = client
        self._device_id = device_id
        self._telemetry = telemetry
        self._device_name = device_name.strip()
        self._success_interval = success_interval
        self._heartbeat_interval = heartbeat_interval

    def run(self, stop: Event, events: Queue[PollEvent]) -> None:
        """Poll until the stop event interrupts a delay."""
        backoff = PollBackoff()
        previous_key: str | None = None
        previous_payload: DisplayPayload | None = None
        registered = False
        next_poll = monotonic()
        next_heartbeat = next_poll + self._heartbeat_interval
        while not stop.is_set():
            request_started = monotonic()
            try:
                if not registered:
                    self._client.register_device(
                        self._device_id,
                        name=self._device_name,
                        metadata=self._telemetry_metadata(),
                    )
                    registered = True
                payload = self._client.fetch_data(self._device_id)
                now = monotonic()
                if now >= next_heartbeat:
                    self._send_heartbeat()
                    next_heartbeat = now + self._heartbeat_interval
            except Exception as error:
                if isinstance(error, BackendHttpError) and error.status_code == 404:
                    registered = False
                    previous_key = None
                    previous_payload = None
                elapsed_ms = (monotonic() - request_started) * 1000.0
                backoff = backoff.after_failure()
                events.put(PollFailed(error, backoff.delay_seconds, elapsed_ms))
                if stop.wait(backoff.delay_seconds):
                    return
                continue
            backoff = backoff.after_success()
            payload_key = getattr(payload, "payload_key", None)
            elapsed_ms = (now - request_started) * 1000.0
            response_bytes = getattr(self._client, "last_response_bytes", None)
            if payload_key is not None and payload_key == previous_key:
                events.put(PollConnected(elapsed_ms, response_bytes))
            else:
                event_payload = payload if previous_payload is None else display_delta(previous_payload, payload)
                events.put(PollSucceeded(event_payload, elapsed_ms, response_bytes))
                previous_key = payload_key
                previous_payload = payload
            next_poll += self._success_interval
            now = monotonic()
            if next_poll <= now:
                next_poll = now
                delay = 0.0
            else:
                delay = next_poll - now
            if stop.wait(delay):
                return

    def close(self) -> None:
        """Close the worker-owned HTTP session after a process poller exits."""

        self._client.close()

    def _send_heartbeat(self) -> None:
        """Report device facts without turning heartbeat failure into link loss."""

        heartbeat = getattr(self._client, "heartbeat", None)
        if not callable(heartbeat):
            return
        metadata = self._telemetry_metadata()
        try:
            heartbeat(self._device_id, metadata)
        except Exception:
            return

    def _telemetry_metadata(self) -> dict[str, Any]:
        """Copy bounded device facts for registration and heartbeat requests."""

        snapshot = self._telemetry()
        metadata: dict[str, Any] = {}
        for name in ("uptime_seconds", "build", "python", "temperature_c"):
            value = getattr(snapshot, name, None)
            if value is not None:
                metadata[name] = value
        return metadata
