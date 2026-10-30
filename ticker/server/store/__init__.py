"""Persistent configuration models for the ticker fleet."""

from ticker.server.store.models import (
    DeviceMetadata,
    PairingState,
    SpotifyConnection,
    SpotifyOAuthAttempt,
    Ticker,
    TickerRecord,
)
from ticker.server.store.profiles import DisplayGeometry, TickerCapabilities, TickerProfile, profile_from_metadata
from ticker.server.store.repository import TickerRepository

__all__ = [
    "DeviceMetadata",
    "PairingState",
    "SpotifyConnection",
    "SpotifyOAuthAttempt",
    "Ticker",
    "TickerRecord",
    "TickerRepository",
    "DisplayGeometry",
    "TickerCapabilities",
    "TickerProfile",
    "profile_from_metadata",
]
