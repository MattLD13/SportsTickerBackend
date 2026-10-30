"""Pure data types for the Pi controller runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ticker.panel.content import DEFAULT_SCORE_ALERT_DURATION, Content


@dataclass(frozen=True, slots=True)
class PayloadSnapshot:
    """Store one complete server response at a monotonic time."""

    key: str
    strip_key: str
    received_at: float
    status: str
    pairing_code: str
    mode: str
    brightness: float
    scroll_interval: float
    inverted: bool
    content: tuple[Content, ...]
    source_received_at: float
    stale: bool = False
    cache_expires_at: float | None = None


@dataclass(frozen=True, slots=True)
class ContentClassification:
    """Separate static scenes from scrolling scenes."""

    scrolling: tuple[Content, ...]
    static: tuple[Content, ...]


@dataclass(frozen=True, slots=True)
class UpdateRequest:
    """Request one external updater run."""

    version: str
    command_id: str = ""


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Configure time limits and frame periods."""

    panel_width: int = 384
    frame_interval: float = 1 / 30
    pairing_interval: float = 0.1
    sleep_interval: float = 0.5
    offline_after: float = 60.0
    static_hold: float = 8.0
    alert_max_age: float = 60.0
    alert_dedupe_age: float = 600.0
    alert_duration: float = DEFAULT_SCORE_ALERT_DURATION
    news_max_age: float = 300.0
    news_dedupe_age: float = 3600.0
    news_duration: float = 6.0
    update_failure_duration: float = 10.0

    def __post_init__(self) -> None:
        if self.panel_width <= 0:
            raise ValueError("The panel width must be positive.")
        for value in (
            self.frame_interval,
            self.pairing_interval,
            self.sleep_interval,
            self.offline_after,
            self.static_hold,
            self.alert_max_age,
            self.alert_dedupe_age,
            self.alert_duration,
            self.news_max_age,
            self.news_dedupe_age,
            self.news_duration,
            self.update_failure_duration,
        ):
            if value < 0:
                raise ValueError("Runtime durations cannot be negative.")


def frozen_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Copy nested values before the runtime retains them."""
    return MappingProxyType({key: _freeze(child) for key, child in value.items()})


def _freeze(value: Any) -> Any:
    """Freeze JSON-like nested data for one payload snapshot."""
    if isinstance(value, Mapping):
        return frozen_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(child) for child in value)
    return value
