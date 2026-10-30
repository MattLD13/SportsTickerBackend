"""Name the input types that the panel draws: content items, frame decisions, strips, and setup screens."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ticker.shared.strenum import StrEnum


DEFAULT_SCORE_ALERT_DURATION = 8.0


@dataclass(frozen=True, slots=True)
class HotspotDetails:
    """Describe the hotspot used for Wi-Fi setup."""

    ssid: str
    password: str
    interface: str = "wlan0"


@dataclass(frozen=True, slots=True)
class WiFiSetupState:
    """Report the current Wi-Fi recovery state."""

    internet_available: bool
    hotspot_active: bool
    hotspot: HotspotDetails
    setup_url: str = "https://10.42.0.1"
    setup_code: str = "123456"
    ble_active: bool = False

    @property
    def local_setup_active(self) -> bool:
        """Return true when either local setup transport accepts credentials."""

        return self.hotspot_active or self.ble_active


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
    WIFI_SETUP = "wifi_setup"


@dataclass(frozen=True, slots=True)
class Content:
    """Store one content item without a protocol dependency."""

    id: str
    type: str
    sport: str
    data: Mapping[str, Any]
    is_shown: bool = True


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
    content_elapsed: float | None = None
    scroll_offset: int | None = None
    alert: Mapping[str, Any] | None = None
    alert_elapsed: float | None = None
    news: Mapping[str, Any] | None = None
    news_elapsed: float | None = None
    pairing_code: str | None = None
    update_version: str | None = None
    update_progress: float | None = None
    update_failure: Mapping[str, str] | None = None
    offline_for: float | None = None
    stale: bool = False
    stale_for: float = 0.0
    connection_lost: bool = False
    wifi_state: WiFiSetupState | None = None
