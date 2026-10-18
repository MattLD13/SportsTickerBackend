"""Settings-scoped immutable provider result cache."""

from __future__ import annotations

import threading

from sports_ticker.domain import DisplaySettings

from .contracts import ProviderResult


class SettingsResultCache:
    """Keep the latest healthy result for each settings value and owner scope."""

    def __init__(self) -> None:
        self._entries: list[tuple[str, DisplaySettings, ProviderResult]] = []
        self._lock = threading.RLock()

    def get(self, settings: DisplaySettings, *, scope: str = "") -> ProviderResult | None:
        """Return the result produced for this owner and exact settings."""

        with self._lock:
            for cached_scope, cached_settings, result in self._entries:
                if cached_scope == scope and cached_settings == settings:
                    return result
        return None

    def set(self, settings: DisplaySettings, result: ProviderResult, *, scope: str = "") -> None:
        """Replace the result produced for this owner and exact settings."""

        with self._lock:
            for index, (cached_scope, cached_settings, _) in enumerate(self._entries):
                if cached_scope == scope and cached_settings == settings:
                    self._entries[index] = (scope, settings, result)
                    return
            self._entries.append((scope, settings, result))


__all__ = ["SettingsResultCache"]
