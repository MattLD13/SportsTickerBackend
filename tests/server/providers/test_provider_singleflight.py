"""Verify provider cache coalescing, expiry, and loader failure recovery."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier, Event, Lock

import pytest

from ticker.server.providers.singleflight import SingleFlightCache

pytestmark = pytest.mark.critical


@dataclass(frozen=True)
class CachedValue:
    completed_at: float
    value: str


def test_concurrent_reads_share_one_completion_and_expire_from_completion_time():
    clock = [0.0]
    cache = SingleFlightCache[str, CachedValue](ttl=5.0, clock=lambda: clock[0])
    started = Event()
    release = Event()
    calls = [0]
    calls_lock = Lock()
    callers = Barrier(8)

    def load():
        with calls_lock:
            calls[0] += 1
        started.set()
        assert release.wait(timeout=2.0)
        clock[0] = 1.0
        return CachedValue(clock[0], "shared")

    def read():
        callers.wait(timeout=2.0)
        return cache.get("same-key", load)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(read) for _ in range(8)]
        assert started.wait(timeout=2.0)
        release.set()
        results = [future.result(timeout=2.0) for future in futures]

    assert calls[0] == 1
    assert all(result is results[0] for result in results)
    clock[0] = 5.9
    assert cache.get("same-key", lambda: CachedValue(clock[0], "fresh")) is results[0]
    clock[0] = 6.0
    assert cache.get("same-key", lambda: CachedValue(clock[0], "fresh")).value == "fresh"


def test_loader_exception_releases_the_key_for_a_later_attempt():
    cache = SingleFlightCache[str, CachedValue](ttl=5.0, clock=lambda: 0.0)
    attempts = [0]

    def load():
        attempts[0] += 1
        if attempts[0] == 1:
            raise RuntimeError("temporary failure")
        return CachedValue(0.0, "recovered")

    with pytest.raises(RuntimeError, match="temporary failure"):
        cache.get("same-key", load)

    assert cache.get("same-key", load).value == "recovered"
    assert attempts[0] == 2


def test_cache_accepts_values_without_a_completion_timestamp():
    clock = [2.0]
    cache = SingleFlightCache[str, str](ttl=5.0, clock=lambda: clock[0])
    assert cache.get("key", lambda: "first") == "first"
    clock[0] = 6.9
    assert cache.get("key", lambda: "second") == "first"
    clock[0] = 7.0
    assert cache.get("key", lambda: "second") == "second"
