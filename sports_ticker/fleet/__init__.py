"""Persistent configuration models for the ticker fleet."""

from .models import (
    DeviceMetadata,
    PairingState,
    SpotifyConnection,
    SpotifyOAuthAttempt,
    Ticker,
    TickerRecord,
)
from .profiles import DisplayGeometry, TickerCapabilities, TickerProfile, profile_from_metadata
from .repository import TickerRepository

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
