"""Own settings-scoped fetcher pause and retry decisions."""
from dataclasses import dataclass
from threading import RLock


@dataclass
class Circuit:
    settings_key: object
    failures: int = 0
    until: float = 0.0
    openings: int = 0


class ProviderRecovery:
    """Keep one failing ticker setting from stopping unrelated provider users."""

    def __init__(self, threshold=3, initial_pause=30.0, maximum_pause=300.0):
        self.threshold, self.initial_pause, self.maximum_pause = threshold, initial_pause, maximum_pause
        self._circuits = {}
        self._lock = RLock()

    def _state(self, provider, ticker, settings_key):
        identity = provider, ticker
        state = self._circuits.get(identity)
        if state is None or state.settings_key != settings_key:
            state = self._circuits[identity] = Circuit(settings_key)
        return state

    def permitted(self, provider, ticker, settings_key, now):
        with self._lock:
            return now >= self._state(provider, ticker, settings_key).until

    def failed(self, provider, ticker, settings_key, now):
        with self._lock:
            state = self._state(provider, ticker, settings_key)
            state.failures += 1
            if state.failures >= self.threshold:
                pause = min(self.maximum_pause, self.initial_pause * 2 ** min(state.openings, 10))
                state.until = now + pause
                state.openings += 1
            return state.until

    def succeeded(self, provider, ticker, settings_key):
        with self._lock:
            state = self._state(provider, ticker, settings_key)
            recovered = state.failures > 0
            state.failures = state.openings = 0
            state.until = 0.0
            return recovered

    def snapshot(self, now):
        with self._lock:
            result = {}
            for (provider, _), state in self._circuits.items():
                entry = result.setdefault(provider, {"open_circuits": 0, "retry_in_seconds": 0.0})
                if state.until > now:
                    entry["open_circuits"] += 1
                    entry["retry_in_seconds"] = max(entry["retry_in_seconds"], state.until - now)
            return result
