"""Poll the backend and publish results without mutating runtime state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from queue import Queue
from threading import Event
from time import monotonic, time
from typing import Any, Protocol

import websocket
from .latency import received_timing

from ticker_core.protocol import (
    BackendClient,
    BackendHttpError,
    DisplayPayload,
    DeviceStreamState,
    PollBackoff,
    StreamMessage,
    display_delta,
)


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
    timing: dict[str, Any] | None = None


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


@dataclass(frozen=True, slots=True)
class PollStreamEvent:
    """Report one bounded stream lifecycle or message measurement."""

    event: str
    message_type: str | None = None
    sequence: int | None = None
    response_bytes: int | None = None
    apply_ms: float | None = None
    reconnect: bool = False
    error_type: str | None = None


@dataclass(frozen=True, slots=True)
class PollUpdateResult:
    """Deliver a durable updater result independently of server delivery."""

    receipt: dict[str, str]
    show_notice: bool


PollEvent = PollSucceeded | PollFailed | PollConnected | PollStreamEvent | PollUpdateResult


class BackendPoller:
    """Own the blocking backend poll loop."""

    def __init__(
        self,
        client: BackendClient,
        device_id: str,
        *,
        telemetry: Callable[[], object],
        device_name: str = "Ticker",
        profile: Mapping[str, Any] | None = None,
        heartbeat_interval: float = 30.0,
        registration_callback: Callable[[object], None] | None = None,
        update_journal: object | None = None,
    ) -> None:
        if not device_id:
            raise ValueError("A device id is required.")
        if not device_name.strip():
            raise ValueError("A device name is required.")
        if heartbeat_interval <= 0:
            raise ValueError("The heartbeat interval must be positive.")
        self._client = client
        self._device_id = device_id
        self._telemetry = telemetry
        self._device_name = device_name.strip()
        self._profile = dict(profile or {})
        self._heartbeat_interval = heartbeat_interval
        self._registration_callback = registration_callback
        self._update_journal = update_journal
        self._next_result_check = 0.0
        self._last_result_identity: tuple[str, str] | None = None

    def run(self, stop: Event, events: Queue[PollEvent]) -> None:
        """Bootstrap over HTTP, then receive sequenced updates over WebSocket."""
        backoff = PollBackoff()
        previous_payload: DisplayPayload | None = None
        stream_state = DeviceStreamState()
        registered = False
        bootstrapped = False
        stream_attempts = 0
        next_heartbeat = monotonic() + self._heartbeat_interval
        while not stop.is_set():
            self._publish_update_result(events)
            request_started = monotonic()
            connection = None
            connecting = False
            try:
                if not registered:
                    registration = {
                        "name": self._device_name,
                        "metadata": self._telemetry_metadata(),
                    }
                    if self._profile:
                        registration["profile"] = self._profile
                    registration_result = self._client.register_device(self._device_id, **registration)
                    if self._registration_callback is not None:
                        self._registration_callback(registration_result)
                    registered = True
                    self._flush_update_result()
                if not bootstrapped:
                    payload = self._client.fetch_data(self._device_id)
                    completed = monotonic()
                    timing = received_timing(payload, None, received_ms=time() * 1000.0, received_mono=completed,
                                             decoded_mono=completed, queued_mono=completed, item_ids=(item.id for item in payload.content))
                    previous_payload = payload
                    events.put(PollSucceeded(payload, (monotonic() - request_started) * 1000.0, self._client.last_response_bytes, timing))
                    bootstrapped = True
                cursor = stream_state.cursor
                reconnect = stream_attempts > 0
                stream_attempts += 1
                connecting = True
                connection = self._client.open_device_stream(
                    self._device_id,
                    stream_id=cursor[0] if cursor else None,
                    after_seq=cursor[1] if cursor else None,
                    timeout_seconds=0.5,
                )
                connecting = False
                events.put(PollStreamEvent("connected", reconnect=reconnect))
            except Exception as error:
                if connecting:
                    events.put(PollStreamEvent(
                        "connect_failed",
                        reconnect=stream_attempts > 1,
                        error_type=type(error).__name__,
                    ))
                if (isinstance(error, BackendHttpError) and error.status_code in {403, 404}) or (isinstance(error, websocket.WebSocketBadStatusException) and error.status_code == 403):
                    registered = False
                    previous_payload = None
                    bootstrapped = False
                    stream_state = DeviceStreamState()
                    stream_attempts = 0
                elapsed_ms = (monotonic() - request_started) * 1000.0
                backoff = backoff.after_failure()
                events.put(PollFailed(error, backoff.delay_seconds, elapsed_ms))
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        pass
                    connection = None
                if self._wait_with_update_results(stop, backoff.delay_seconds, events):
                    return
                continue
            try:
                backoff = backoff.after_success()
                while not stop.is_set():
                    self._publish_update_result(events)
                    try:
                        raw = connection.recv()
                    except websocket.WebSocketTimeoutException:
                        now = monotonic()
                        if now >= next_heartbeat:
                            self._send_heartbeat()
                            next_heartbeat = now + self._heartbeat_interval
                        continue
                    received_ms, received_mono = time() * 1000.0, monotonic()
                    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 2_000_000:
                        raise ValueError("device stream message is invalid or too large")
                    message_started = monotonic()
                    message = StreamMessage.from_payload(json.loads(raw))
                    current = stream_state.apply(message)
                    decoded_mono = monotonic()
                    events.put(PollStreamEvent(
                        "message",
                        message_type=message.kind,
                        sequence=message.sequence,
                        response_bytes=len(raw.encode("utf-8")),
                        apply_ms=(monotonic() - message_started) * 1000.0,
                    ))
                    elapsed_ms = (monotonic() - request_started) * 1000.0
                    if current is None:
                        if message.kind == "ready":
                            events.put(PollConnected(elapsed_ms, len(raw)))
                    else:
                        self._client.remember_stream_response(self._device_id, current)
                        if previous_payload is not None and current.payload_key == previous_payload.payload_key:
                            events.put(PollConnected(elapsed_ms, len(raw)))
                        else:
                            event_payload = current if previous_payload is None else display_delta(previous_payload, current)
                            changed_ids = (item.id for item in (event_payload.changed if previous_payload is not None else current.content))
                            timing = received_timing(current, message, received_ms=received_ms, received_mono=received_mono,
                                                     decoded_mono=decoded_mono, queued_mono=monotonic(), item_ids=changed_ids)
                            if previous_payload is not None:
                                current_ids = {item.id for item in current.content}
                                timing["removed_items"] = tuple(item.id for item in previous_payload.content if item.id not in current_ids)
                            events.put(PollSucceeded(event_payload, elapsed_ms, len(raw), timing))
                            previous_payload = current
                    backoff = backoff.after_success()
                    now = monotonic()
                    if now >= next_heartbeat:
                        self._send_heartbeat()
                        next_heartbeat = now + self._heartbeat_interval
                    request_started = now
            except Exception as error:
                events.put(PollStreamEvent(
                    "disconnected",
                    reconnect=stream_attempts > 1,
                    error_type=type(error).__name__,
                ))
                if (isinstance(error, BackendHttpError) and error.status_code in {403, 404}) or (isinstance(error, websocket.WebSocketBadStatusException) and error.status_code == 403):
                    registered = False
                    previous_payload = None
                    bootstrapped = False
                    stream_attempts = 0
                if isinstance(error, ValueError):
                    stream_state = DeviceStreamState()
                elapsed_ms = (monotonic() - request_started) * 1000.0
                backoff = backoff.after_failure()
                events.put(PollFailed(error, backoff.delay_seconds, elapsed_ms))
                try:
                    connection.close()
                except Exception:
                    pass
                connection = None
                if self._wait_with_update_results(stop, backoff.delay_seconds, events):
                    return
            finally:
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        pass

    def _publish_update_result(self, events: Queue[PollEvent]) -> None:
        """Read local results on the worker without blocking the render loop."""
        if self._update_journal is None or monotonic() < self._next_result_check:
            return
        self._next_result_check = monotonic() + 1.0
        try:
            receipt = self._update_journal.load()
            if not receipt or receipt.get("status") not in {"installed", "rolled_back", "download_failed"}:
                return
            identity = receipt["id"], receipt["status"]
            if identity == self._last_result_identity:
                return
            result = {key: str(receipt[key]) for key in ("id", "version", "status", "running_version", "reason")}
            events.put(PollUpdateResult(result, self._update_journal.notice_pending(receipt)))
            self._last_result_identity = identity
        except (OSError, ValueError, KeyError):
            return

    def _wait_with_update_results(self, stop: Event, delay: float, events: Queue[PollEvent]) -> bool:
        """Keep local failure delivery active during network retry delays."""
        if self._update_journal is None:
            return stop.wait(delay)
        deadline = monotonic() + delay
        while not stop.is_set():
            self._publish_update_result(events)
            remaining = deadline - monotonic()
            if remaining <= 0:
                return False
            if stop.wait(min(1.0, remaining)):
                return True
        return True

    def close(self) -> None:
        """Close the worker-owned HTTP session after a process poller exits."""

        self._client.close()

    def _send_heartbeat(self) -> None:
        """Report device facts without turning heartbeat failure into link loss."""

        self._flush_update_result()
        heartbeat = getattr(self._client, "heartbeat", None)
        if not callable(heartbeat):
            return
        metadata = self._telemetry_metadata()
        try:
            heartbeat(self._device_id, metadata)
        except Exception:
            return

    def _flush_update_result(self) -> None:
        if self._update_journal is not None:
            try:
                self._update_journal.flush(self._client, self._device_id)
            except Exception:
                pass

    def _telemetry_metadata(self) -> dict[str, Any]:
        """Copy bounded device facts for registration and heartbeat requests."""

        snapshot = self._telemetry()
        metadata: dict[str, Any] = {}
        for name in ("uptime_seconds", "build", "python", "temperature_c", "wifi_available", "wifi_setup_active"):
            value = getattr(snapshot, name, None)
            if value is not None:
                metadata[name] = value
        return metadata
