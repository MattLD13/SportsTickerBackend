"""Coalesce concurrent reads and cache their completed responses."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from threading import Event, Lock
from typing import Generic, TypeVar


K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


class SingleFlightCache(Generic[K, V]):
    """Cache completed loader results and share one in-progress load per key."""

    def __init__(self, *, ttl: float, clock: Callable[[], float]) -> None:
        self._ttl = float(ttl)
        self._clock = clock
        self._lock = Lock()
        self._values: dict[K, tuple[float, V]] = {}
        self._inflight: dict[K, Event] = {}

    def get(self, key: K, loader: Callable[[], V]) -> V:
        """Return a fresh value or run one loader while matching callers wait."""
        while True:
            with self._lock:
                now = self._clock()
                cached = self._values.get(key)
                if cached is not None and 0 <= now - cached[0] < self._ttl:
                    return cached[1]
                waiter = self._inflight.get(key)
                if waiter is None:
                    waiter = Event()
                    self._inflight[key] = waiter
                    break
            waiter.wait()

        try:
            value = loader()
            completed_at = self._clock()
        except BaseException:
            with self._lock:
                active = self._inflight.pop(key, None)
                if active is not None:
                    active.set()
            raise

        with self._lock:
            self._values[key] = (completed_at, value)
            active = self._inflight.pop(key, None)
            if active is not None:
                active.set()
        return value
