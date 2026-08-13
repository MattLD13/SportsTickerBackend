"""Immutable models for canonical ticker content and display settings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any
CONTENT_FAMILIES: tuple[str, ...] = (
    "sports",
    "weather",
    "music",
    "flights",
    "airports",
    "golf",
    "racing",
    "clock",
    "status",
    "stock",
)

DISPLAY_MODES: tuple[str, ...] = (
    "sports",
    "weather",
    "music",
    "flights",
    "airports",
    "stock",
    "clock",
)

SPORTS_PRESENTATIONS: tuple[str, ...] = ("rotation", "pinned")


def _freeze(value: Any) -> object:
    """Copy nested source values into immutable containers."""

    if isinstance(value, Mapping):
        return MappingProxyType(
            {_freeze(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)
    return value


@dataclass(frozen=True, slots=True)
class ContentItem:
    """Represent one canonical item from any ticker display family."""

    id: str = ""
    family: str = "sports"
    kind: str = "scoreboard"
    is_shown: bool = True
    data: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize canonical text and freeze family-specific source facts."""

        family = str(self.family).strip().lower() or "sports"
        kind = str(self.kind).strip().lower() or "item"
        identifier = str(self.id).strip() or f"{family}:{kind}"
        if not isinstance(self.data, Mapping):
            raise TypeError("content data must be a mapping")
        frozen_data = _freeze(self.data)
        if not isinstance(frozen_data, Mapping):
            raise TypeError("content data must produce a mapping")
        object.__setattr__(self, "id", identifier)
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "is_shown", bool(self.is_shown))
        object.__setattr__(self, "data", frozen_data)


@dataclass(frozen=True, slots=True)
class DisplaySettings:
    """Represent the complete immutable settings needed by ticker modes."""

    active_sports: Mapping[str, bool] = field(default_factory=dict)
    mode: str = "sports"
    sports_presentation: str = "rotation"
    pinned_content_id: str = ""
    brightness: float = 100.0
    inverted: bool = False
    timezone: str = ""
    weather_city: str = "New York"
    weather_lat: float = 40.7128
    weather_lon: float = -74.0060
    airport_code_iata: str = "EWR"
    airport_code_icao: str = "KEWR"
    airport_name: str = "Newark Liberty International"
    track_flight_id: str = ""
    track_guest_name: str = ""
    live_delay_mode: bool = False
    live_delay_seconds: float = 45.0
    scroll_seamless: bool = True
    scroll_speed: float = 0.03
    score_alerts: bool = True

    def __post_init__(self) -> None:
        """Copy mutable input and normalize scalar settings."""

        active_sports = self.active_sports if hasattr(self.active_sports, "items") else {}
        normalized = {
            str(sport).strip().lower(): bool(enabled)
            for sport, enabled in active_sports.items()
        }
        object.__setattr__(self, "active_sports", MappingProxyType(normalized))
        mode = str(self.mode).strip().lower() or "sports"
        if mode not in DISPLAY_MODES:
            choices = ", ".join(DISPLAY_MODES)
            raise ValueError(f"mode must be one of: {choices}")
        sports_presentation = str(self.sports_presentation).strip().lower() or "rotation"
        if sports_presentation not in SPORTS_PRESENTATIONS:
            choices = ", ".join(SPORTS_PRESENTATIONS)
            raise ValueError(f"sports_presentation must be one of: {choices}")
        pinned_content_id = "" if self.pinned_content_id is None else str(self.pinned_content_id).strip()
        if sports_presentation == "pinned" and mode != "sports":
            raise ValueError("pinned sports presentation requires mode sports")
        if sports_presentation == "pinned" and not pinned_content_id:
            raise ValueError("pinned sports presentation requires pinned_content_id")
        if mode != "sports" and pinned_content_id:
            raise ValueError("pinned_content_id requires mode sports")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "sports_presentation", sports_presentation)
        object.__setattr__(self, "pinned_content_id", pinned_content_id)
        object.__setattr__(self, "brightness", float(self.brightness))
        object.__setattr__(self, "inverted", bool(self.inverted))
        object.__setattr__(self, "timezone", str(self.timezone).strip())
        object.__setattr__(self, "weather_city", str(self.weather_city).strip())
        object.__setattr__(self, "weather_lat", float(self.weather_lat))
        object.__setattr__(self, "weather_lon", float(self.weather_lon))
        object.__setattr__(self, "airport_code_iata", str(self.airport_code_iata).strip().upper())
        object.__setattr__(self, "airport_code_icao", str(self.airport_code_icao).strip().upper())
        object.__setattr__(self, "airport_name", str(self.airport_name).strip())
        object.__setattr__(self, "track_flight_id", str(self.track_flight_id).strip())
        object.__setattr__(self, "track_guest_name", str(self.track_guest_name).strip())
        object.__setattr__(self, "live_delay_mode", bool(self.live_delay_mode))
        object.__setattr__(self, "live_delay_seconds", float(self.live_delay_seconds))
        object.__setattr__(self, "scroll_seamless", bool(self.scroll_seamless))
        object.__setattr__(self, "scroll_speed", float(self.scroll_speed))
        object.__setattr__(self, "score_alerts", bool(self.score_alerts))

__all__ = [
    "CONTENT_FAMILIES",
    "DISPLAY_MODES",
    "ContentItem",
    "DisplaySettings",
    "SPORTS_PRESENTATIONS",
]
