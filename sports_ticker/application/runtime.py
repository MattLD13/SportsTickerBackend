"""Run scheduler passes and event cleanup on an externally owned cadence."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from threading import Event, Lock
from typing import Protocol, TypeAlias

from .events import EventService
from .scheduler import RefreshScheduler


class WaitStopPrimitive(Protocol):
    """Wait for one interval and report whether shutdown was requested."""

    def wait(self, timeout: float) -> bool:
        """Wait for the interval and return true when shutdown was requested."""


WaitStop: TypeAlias = WaitStopPrimitive | Callable[[float], bool]
MonotonicClock: TypeAlias = Callable[[], float]


class BackendRuntime:
    """Own the blocking cadence around one loop-free refresh scheduler."""

    def __init__(
        self,
        scheduler: RefreshScheduler,
        event_service: EventService,
        poll_interval: float,
        *,
        monotonic: MonotonicClock = time.monotonic,
        wait: WaitStop | None = None,
        incidents=None,
        stall_seconds: float = 90.0,
    ) -> None:
        """Capture scheduler, cleanup, clock, and wait ports without starting work."""

        interval = float(poll_interval)
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("poll_interval must be finite and positive")
        if not callable(monotonic):
            raise TypeError("monotonic must be callable")
        if not callable(getattr(scheduler, "run_due", None)):
            raise TypeError("scheduler must provide run_due(now)")
        if not callable(getattr(event_service, "remove_expired", None)):
            raise TypeError("event_service must provide remove_expired()")
        if wait is not None and not callable(wait) and not callable(getattr(wait, "wait", None)):
            raise TypeError("wait must be callable or provide wait(timeout)")

        self._incidents = incidents
        self._lock = Lock()
        self._running = False
        self._started_at = None
        self._completed_at = None
        self._cycles = 0
        self._last_error = None
        self._stall_seconds = stall_seconds
        self.scheduler = scheduler
        self.event_service = event_service
        self.poll_interval = interval
        self._monotonic = monotonic
        self._stop_event = Event()
        self._wait = wait or self._stop_event

    def run_once(self) -> tuple[str, ...]:
        """Run one scheduler pass and remove expired durable events."""

        with self._lock:
            self._started_at = self._monotonic()
        try:
            try:
                result = self.scheduler.run_due(self._monotonic())
            finally:
                self.event_service.remove_expired()
        except Exception as error:
            with self._lock:
                self._last_error = type(error).__name__
            if self._incidents is not None:
                self._incidents.record("runtime_failure", component="refresh_runtime", error=error,
                                       context={"active_provider": getattr(self.scheduler, "active_provider", None)})
            raise
        else:
            with self._lock:
                self._completed_at = self._monotonic()
                self._cycles += 1
                self._last_error = None
            return result

    def run(self) -> None:
        """Run passes until the injected wait primitive reports shutdown."""

        with self._lock:
            self._running = True
        try:
            while True:
                self.run_once()
                if self._wait_for_next_pass():
                    return
        finally:
            with self._lock:
                self._running = False

    def status(self) -> dict:
        """Report local loop progress independently of upstream provider availability."""
        with self._lock:
            now = self._monotonic()
            age = None if self._completed_at is None else max(0, now - self._completed_at)
            return {"enabled": True, "running": self._running,
                    "ready": self._running and age is not None and age < self._stall_seconds,
                    "last_completed_age_seconds": age, "cycles": self._cycles,
                    "active_provider": getattr(self.scheduler, "active_provider", None),
                    "cycle_age_seconds": None if self._started_at is None else max(0, now - self._started_at),
                    "last_error_type": self._last_error}

    def stop(self) -> None:
        """Request shutdown when the runtime uses its default wait primitive."""

        self._stop_event.set()

    def _wait_for_next_pass(self) -> bool:
        wait = self._wait
        if callable(wait):
            return bool(wait(self.poll_interval))
        return bool(wait.wait(self.poll_interval))


__all__ = ["BackendRuntime", "MonotonicClock", "WaitStop", "WaitStopPrimitive"]
