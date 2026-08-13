"""Immutable models for persistent multi-ticker configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from sports_ticker.domain import DisplaySettings


def _freeze(value: Any) -> Any:
    """Copy nested configuration values into immutable containers."""

    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)
    return value


def _display_settings(value: DisplaySettings | Mapping[str, Any] | None) -> DisplaySettings:
    if value is None:
        return DisplaySettings()
    if isinstance(value, DisplaySettings):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("display settings must be DisplaySettings, a mapping, or None")

    active_sports = value.get("active_sports", {})
    if not isinstance(active_sports, Mapping):
        active_sports = {}
    return DisplaySettings(
        active_sports=active_sports,
        my_teams=value.get("my_teams", ()),
        mode=value.get("mode", "sports"),
        sports_presentation=value.get("sports_presentation", "rotation"),
        pinned_content_id=value.get("pinned_content_id", ""),
        brightness=value.get("brightness", 100.0),
        inverted=value.get("inverted", False),
        timezone=value.get("timezone", ""),
        weather_city=value.get("weather_city", "New York"),
        weather_lat=value.get("weather_lat", 40.7128),
        weather_lon=value.get("weather_lon", -74.0060),
        airport_code_iata=value.get("airport_code_iata", "EWR"),
        airport_code_icao=value.get("airport_code_icao", "KEWR"),
        airport_name=value.get("airport_name", "Newark Liberty International"),
        track_flight_id=value.get("track_flight_id", ""),
        track_guest_name=value.get("track_guest_name", ""),
        live_delay_mode=value.get("live_delay_mode", False),
        live_delay_seconds=value.get("live_delay_seconds", 45.0),
        scroll_seamless=value.get("scroll_seamless", True),
        scroll_speed=value.get("scroll_speed", 0.03),
        score_alerts=value.get("score_alerts", True),
    )


@dataclass(frozen=True, slots=True)
class PairingState:
    """Describe optional pairing state for one ticker."""

    pairing_code: str | None = None
    paired: bool = False
    client_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Normalize pairing identifiers and remove duplicate clients."""

        code = None if self.pairing_code is None else str(self.pairing_code).strip()
        clients = tuple(dict.fromkeys(str(client).strip() for client in self.client_ids if str(client).strip()))
        object.__setattr__(self, "pairing_code", code or None)
        object.__setattr__(self, "paired", bool(self.paired))
        object.__setattr__(self, "client_ids", clients)


@dataclass(frozen=True, slots=True)
class DeviceMetadata:
    """Store the last check-in time and immutable device telemetry."""

    last_seen_at: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Copy device metadata and normalize its timestamp."""

        last_seen = None if self.last_seen_at is None else float(self.last_seen_at)
        object.__setattr__(self, "last_seen_at", last_seen)
        object.__setattr__(self, "metadata", _freeze(self.metadata or {}))


@dataclass(frozen=True, slots=True)
class TickerRecord:
    """Represent one isolated ticker configuration record."""

    ticker_id: str
    name: str = "Ticker"
    display_settings: DisplaySettings = field(default_factory=DisplaySettings)
    pairing: PairingState | None = None
    device: DeviceMetadata = field(default_factory=DeviceMetadata)
    created_at: float = 0.0
    updated_at: float = 0.0

    def __post_init__(self) -> None:
        """Normalize identifiers while preserving nested immutable models."""

        ticker_id = str(self.ticker_id).strip()
        if not ticker_id:
            raise ValueError("ticker_id must not be empty")
        object.__setattr__(self, "ticker_id", ticker_id)
        object.__setattr__(self, "name", str(self.name).strip() or "Ticker")
        object.__setattr__(self, "display_settings", _display_settings(self.display_settings))
        if self.pairing is not None and not isinstance(self.pairing, PairingState):
            raise TypeError("pairing must be PairingState or None")
        if not isinstance(self.device, DeviceMetadata):
            raise TypeError("device must be DeviceMetadata")
        object.__setattr__(self, "created_at", float(self.created_at))
        object.__setattr__(self, "updated_at", float(self.updated_at))

Ticker = TickerRecord


@dataclass(frozen=True, slots=True)
class SpotifyConnection:
    """Store one encrypted Spotify account link for one ticker."""

    ticker_id: str
    spotify_account_id: str
    display_name: str
    scopes: tuple[str, ...]
    refresh_token_ciphertext: str
    status: str = "connected"
    priority: bool = False
    connected_at: float = 0.0
    updated_at: float = 0.0

    def __post_init__(self) -> None:
        ticker_id = str(self.ticker_id).strip()
        account_id = str(self.spotify_account_id).strip()
        ciphertext = str(self.refresh_token_ciphertext).strip()
        if not ticker_id or not account_id or not ciphertext:
            raise ValueError("Spotify connection requires ticker, account, and token")
        status = str(self.status).strip().lower()
        if status not in {"connected", "reauthorization_required"}:
            raise ValueError("Spotify connection status is invalid")
        scopes = tuple(dict.fromkeys(str(item).strip() for item in self.scopes if str(item).strip()))
        object.__setattr__(self, "ticker_id", ticker_id)
        object.__setattr__(self, "spotify_account_id", account_id)
        object.__setattr__(self, "display_name", str(self.display_name).strip())
        object.__setattr__(self, "scopes", scopes)
        object.__setattr__(self, "refresh_token_ciphertext", ciphertext)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "priority", bool(self.priority))
        object.__setattr__(self, "connected_at", float(self.connected_at))
        object.__setattr__(self, "updated_at", float(self.updated_at))


@dataclass(frozen=True, slots=True)
class SpotifyOAuthAttempt:
    """Store one short-lived, one-use Spotify authorization attempt."""

    attempt_id: str
    ticker_id: str
    state_hash: str
    verifier_ciphertext: str
    expires_at: float
    created_at: float
    used_at: float | None = None

    def __post_init__(self) -> None:
        for value, name in ((self.attempt_id, "attempt"), (self.ticker_id, "ticker"), (self.state_hash, "state"), (self.verifier_ciphertext, "verifier")):
            if not str(value).strip():
                raise ValueError(f"Spotify OAuth {name} must not be empty")
        object.__setattr__(self, "attempt_id", str(self.attempt_id).strip())
        object.__setattr__(self, "ticker_id", str(self.ticker_id).strip())
        object.__setattr__(self, "state_hash", str(self.state_hash).strip())
        object.__setattr__(self, "verifier_ciphertext", str(self.verifier_ciphertext).strip())
        object.__setattr__(self, "expires_at", float(self.expires_at))
        object.__setattr__(self, "created_at", float(self.created_at))
        object.__setattr__(self, "used_at", None if self.used_at is None else float(self.used_at))


__all__ = [
    "DeviceMetadata",
    "PairingState",
    "Ticker",
    "TickerRecord",
    "SpotifyConnection",
    "SpotifyOAuthAttempt",
]
