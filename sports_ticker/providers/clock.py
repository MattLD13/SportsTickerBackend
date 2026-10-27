"""Read live clock content through an injected source."""
from __future__ import annotations

from collections.abc import Mapping
from sports_ticker.domain import DisplaySettings


class ClockProvider:
    """Publish the clock scene marker without a remote dependency."""

    def fetch(self, settings: DisplaySettings) -> Mapping[str, object]:
        del settings
        return {
            "content": [
                {
                    "id": "clock",
                    "type": "clock",
                    "sport": "clock",
                    "status": "active",
                }
            ]
        }


__all__ = ['ClockProvider']
