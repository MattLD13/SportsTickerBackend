"""Pure data types for the Pi controller runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any

from ticker_core._enum import StrEnum

class FrameKind(StrEnum):
    """Name one controller action for one frame."""

    STOPPED = "stopped"
    UPDATE = "update"
    PAIRING = "pairing"
    SLEEP = "sleep"
    OFFLINE = "offline"
    SCORE_ALERT = "score_alert"
    STATIC = "static"
    SCROLL = "scroll"
    EMPTY = "empty"


@dataclass(frozen=True, slots=True)
class Content:
    """Store one content item without a protocol dependency."""

    id: str
    type: str
    sport: str
    data: Mapping[str, Any]
    is_shown: bool = True


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
class StripSegment:
    """Describe one contiguous item range in a seamless strip."""

    item_id: str
    width: int

    def __post_init__(self) -> None:
        if not self.item_id:
            raise ValueError("A strip segment needs an item id.")
        if self.width <= 0:
            raise ValueError("A strip segment width must be positive.")


@dataclass(frozen=True, slots=True)
class StripLayout:
    """Describe a rendered strip without retaining image data."""

    width: int
    segments: tuple[StripSegment, ...]

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise ValueError("A strip width must be positive.")
        if not self.segments:
            raise ValueError("A strip needs at least one segment.")
        if sum(segment.width for segment in self.segments) != self.width:
            raise ValueError("Strip segment widths must equal the strip width.")


@dataclass(frozen=True, slots=True)
class FrameDecision:
    """Tell the outer loop which scene to render next."""

    kind: FrameKind
    interval: float
    brightness: int
    inverted: bool
    wall_time: datetime
    mode: str
    payload_key: str | None = None
    content: Content | None = None
    scroll_offset: int | None = None
    alert: Mapping[str, Any] | None = None
    alert_elapsed: float | None = None
    news: Mapping[str, Any] | None = None
    news_elapsed: float | None = None
    pairing_code: str | None = None
    update_version: str | None = None
    update_progress: float | None = None
    offline_for: float | None = None
    stale: bool = False
    stale_for: float = 0.0
    connection_lost: bool = False
    disconnected_for: float = 0.0


@dataclass(frozen=True, slots=True)
class UpdateRequest:
    """Request one external updater run."""

    version: str


@dataclass(frozen=True, slots=True)
class ModeRequest:
    """Request one backend mode change."""

    mode: str


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
    alert_duration: float = 4.0
    news_max_age: float = 300.0
    news_dedupe_age: float = 3600.0
    news_duration: float = 6.0

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
