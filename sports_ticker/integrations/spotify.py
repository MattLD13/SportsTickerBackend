"""Server-owned Spotify OAuth and per-ticker music source."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from sports_ticker.tls import verified_https_context

from cryptography.fernet import Fernet, InvalidToken

from sports_ticker.domain import DisplaySettings
from sports_ticker.fleet import SpotifyConnection, SpotifyOAuthAttempt, TickerRepository


SPOTIFY_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_URL = "https://api.spotify.com/v1"
SPOTIFY_SCOPES = ("user-read-playback-state", "user-read-currently-playing")
SPOTIFY_PLAYING_REFRESH_SECONDS = 0.6
SPOTIFY_PAUSED_REFRESH_SECONDS = 1.5
SPOTIFY_IDLE_REFRESH_SECONDS = 3.0
SPOTIFY_ERROR_REFRESH_SECONDS = 15.0
SPOTIFY_RATE_LIMIT_INITIAL_BACKOFF_SECONDS = 30.0
SPOTIFY_RATE_LIMIT_MAX_BACKOFF_SECONDS = 900.0


class SpotifyIntegrationError(RuntimeError):
    """Report a safe Spotify integration failure."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class _SpotifyTrack:
    """Store normalized track metadata for active and cached tracks."""

    id: str
    name: str
    artist: str
    album: str
    cover: str
    duration: float = 0.0

    def to_mapping(self) -> dict[str, Any]:
        """Convert track metadata to a JSON-ready mapping."""
        return {
            "id": self.id,
            "name": self.name,
            "artist": self.artist,
            "album": self.album,
            "cover": self.cover,
            "duration": self.duration,
        }


@dataclass(frozen=True, slots=True)
class _PlaybackWindow:
    """Keep the current track, previous track, queued tracks, and last known record."""

    current_track: _SpotifyTrack | None
    previous_track: _SpotifyTrack | None
    next_tracks: tuple[_SpotifyTrack, ...]
    last_record: Mapping[str, Any] | None = None
    queue_refresh_pending: bool = False


@dataclass(frozen=True, slots=True)
class SpotifyConfig:
    """Contain deployment-owned Spotify OAuth configuration."""

    client_id: str
    callback_uri: str
    app_return_uri: str
    encryption_key: str
    attempt_ttl_seconds: float = 600.0

    def __post_init__(self) -> None:
        for value, name in (
            (self.client_id, "client ID"),
            (self.callback_uri, "callback URI"),
            (self.app_return_uri, "app return URI"),
            (self.encryption_key, "encryption key"),
        ):
            if not str(value).strip():
                raise ValueError(f"Spotify {name} must not be empty")
        callback = _https_uri(self.callback_uri, "callback URI")
        app_return = _app_return_uri(self.app_return_uri)
        if float(self.attempt_ttl_seconds) <= 0:
            raise ValueError("Spotify attempt TTL must be positive")
        try:
            Fernet(str(self.encryption_key).encode("ascii"))
        except (ValueError, UnicodeEncodeError) as error:
            raise ValueError("Spotify encryption key is not a Fernet key") from error
        object.__setattr__(self, "client_id", str(self.client_id).strip())
        object.__setattr__(self, "callback_uri", callback)
        object.__setattr__(self, "app_return_uri", app_return)
        object.__setattr__(self, "encryption_key", str(self.encryption_key).strip())
        object.__setattr__(self, "attempt_ttl_seconds", float(self.attempt_ttl_seconds))

    @classmethod
    def from_environment(cls) -> "SpotifyConfig":
        """Read required Spotify deployment configuration from environment."""

        return cls(
            client_id=os.environ.get("SPOTIFY_CLIENT_ID", ""),
            callback_uri=os.environ.get("SPOTIFY_CALLBACK_URI", ""),
            app_return_uri=os.environ.get("SPOTIFY_APP_RETURN_URI", ""),
            encryption_key=os.environ.get("SPOTIFY_TOKEN_ENCRYPTION_KEY", ""),
            attempt_ttl_seconds=float(os.environ.get("SPOTIFY_OAUTH_ATTEMPT_TTL_SECONDS", "600")),
        )


class SpotifyHttpPort(Protocol):
    """Perform Spotify OAuth and API requests without exposing tokens."""

    def exchange_code(self, code: str, config: SpotifyConfig, verifier: str) -> Mapping[str, Any]:
        """Exchange one code for Spotify tokens."""

    def refresh_access_token(self, refresh_token: str, config: SpotifyConfig) -> Mapping[str, Any]:
        """Refresh one server-owned Spotify access token."""

    def get_current_user(self, access_token: str) -> M