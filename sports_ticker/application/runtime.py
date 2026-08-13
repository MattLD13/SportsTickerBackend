"""Run scheduler passes and event cleanup on an externally owned cadence."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from threading import Event
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

        self.scheduler = scheduler
        self.event_service = event_service
        self.poll_interval = interval
        self._monotonic = monotonic
        self._stop_event = Event()
        self._wait = wait or self._stop_event

    def run_once(self) -> tuple[str, ...]:
        """Run one scheduler pass and remove expired durable events."""

        try:
            return self.scheduler.run_due(self._monotonic())
        finally:
            self.event_service.remove_expired()

    def run(self) -> None:
        """Run passes until the injected wait primitive reports shutdown."""

        while True:
            self.run_once()
            if self._wait_for_next_pass():
                return

    def stop(self) -> None:
        """Request shutdown when the runtime uses its default wait primitive."""

        self._stop_event.set()

    def _wait_for_next_pass(self) -> bool:
        wait = self._wait
        if callable(wait):
            return bool(wait(self.poll_interval))
        return bool(wait.wait(self.poll_interval))


__all__ = ["BackendRuntime", "MonotonicClock", "WaitStop", "WaitStopPrimitive"]
