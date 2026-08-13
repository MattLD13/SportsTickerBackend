"""Settings-scoped immutable provider result cache."""

from __future__ import annotations

import threading

from sports_ticker.domain import DisplaySettings

from .contracts import ProviderResult


class SettingsResultCache:
    """Keep the latest healthy result for every effective settings value."""

    def __init__(self) -> None:
        self._entries: list[tuple[DisplaySettings, ProviderResult]] = []
        self._lock = threading.RLock()

    def get(self, settings: DisplaySettings) -> ProviderResult | None:
        """Return the result produced with these exact immutable settings."""

        with self._lock:
            for cached_settings, result in self._entries:
                if cached_settings == settings:
                    return result
        return None

    def set(self, settings: DisplaySettings, result: ProviderResult) -> None:
        """Replace the result produced with these exact immutable settings."""

        with self._lock:
            for index, (cached_settings, _) in enumerate(self._entries):
                if cached_settings == settings:
                    self._entries[index] = (settings, result)
                    return
            self._entries.append((settings, result))


__all__ = ["SettingsResultCache"]
