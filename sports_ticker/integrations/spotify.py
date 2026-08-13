"""Server-owned Spotify OAuth and per-ticker music source."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable, Protocol
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json

from cryptography.fernet import Fernet, InvalidToken

from sports_ticker.domain import DisplaySettings
from sports_ticker.fleet import SpotifyConnection, SpotifyOAuthAttempt, TickerRepository


SPOTIFY_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_URL = "https://api.spotify.com/v1"
SPOTIFY_SCOPES = ("user-read-playback-state", "user-read-currently-playing")


class SpotifyIntegrationError(RuntimeError):
    """Report a safe Spotify integration failure."""


@dataclass(frozen=True, slots=True)
class _PlaybackWindow:
    """Keep the prior cover and three queued covers for one ticker."""

    current_id: str
    current_cover: str
    previous_cover: str
    next_covers: tuple[str, ...]


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

    def get_current_user(self, access_token: str) -> Mapping[str, Any]:
        """Read the account identity for a newly linked user."""

    def get_playback(self, access_token: str) -> Mapping[str, Any] | None:
        """Read one user's current playback state."""

    def get_queue(self, access_token: str) -> Mapping[str, Any] | None:
        """Read one user's queue for the existing ticker music layout."""


class UrllibSpotifyHttpClient:
    """Call Spotify with standard-library HTTP only."""

    def exchange_code(self, code: str, config: SpotifyConfig, verifier: str) -> Mapping[str, Any]:
        return self._token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config.callback_uri,
                "code_verifier": verifier,
            },
            config,
        )

    def refresh_access_token(self, refresh_token: str, config: SpotifyConfig) -> Mapping[str, Any]:
        return self._token({"grant_type": "refresh_token", "refresh_token": refresh_token}, config)

    def get_current_user(self, access_token: str) -> Mapping[str, Any]:
        return self._get("/me", access_token) or {}

    def get_playback(self, access_token: str) -> Mapping[str, Any] | None:
        return self._get("/me/player", access_token)

    def get_queue(self, access_token: str) -> Mapping[str, Any] | None:
        return self._get("/me/player/queue", access_token)

    def _token(self, values: Mapping[str, str], config: SpotifyConfig) -> Mapping[str, Any]:
        payload = {"client_id": config.client_id, **values}
        request = Request(
            SPOTIFY_TOKEN_URL,
            data=urlencode(payload).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        return self._json(request)

    def _get(self, path: str, access_token: str) -> Mapping[str, Any] | None:
        request = Request(
            f"{SPOTIFY_API_URL}{path}",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        try:
            return self._json(request)
        except SpotifyIntegrationError as error:
            if "HTTP 204" in str(error):
                return None
            raise

    @staticmethod
    def _json(request: Request) -> Mapping[str, Any]:
        try:
            with urlopen(request, timeout=8) as response:
                body = response.read()
                status = getattr(response, "status", 200)
        except HTTPError as error:
            try:
                response = json.loads(error.read())
                detail = str(response.get("error_description") or response.get("error") or "")
            except Exception:
                detail = ""
            suffix = f": {detail}" if detail else ""
            raise SpotifyIntegrationError(f"Spotify returned HTTP {error.code}{suffix}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise SpotifyIntegrationError("Spotify request failed") from error
        if status == 204:
            raise SpotifyIntegrationError("HTTP 204")
        if not 200 <= int(status) < 300:
            raise SpotifyIntegrationError(f"Spotify returned HTTP {status}")
        try:
            value = json.loads(body)
        except (TypeError, json.JSONDecodeError) as error:
            raise SpotifyIntegrationError("Spotify returned invalid JSON") from error
        if not isinstance(value, Mapping):
            raise SpotifyIntegrationError("Spotify returned an invalid response")
        return value


class SpotifyIntegrationService:
    """Own encrypted Spotify links and use them for ticker-specific playback."""

    def __init__(
        self,
        repository: TickerRepository,
        config: SpotifyConfig,
        *,
        http: SpotifyHttpPort | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._repository = repository
        self._config = config
        self._http = http or UrllibSpotifyHttpClient()
        self._clock = clock
        self._cipher = Fernet(config.encryption_key.encode("ascii"))
        self._playback_windows: dict[str, _PlaybackWindow] = {}
        self._playback_lock = Lock()

    @property
    def callback_uri(self) -> str:
        """Return the fixed registered Spotify callback URI."""

        return self._config.callback_uri

    def app_completion_uri(self, attempt_id: str, status: str) -> str:
        """Build the fixed configured app return URI with safe result fields."""

        separator = "&" if "?" in self._config.app_return_uri else "?"
        return f"{self._config.app_return_uri}{separator}{urlencode({'attempt_id': attempt_id, 'status': status})}"

    def begin_authorization(self, ticker_id: str) -> dict[str, str | float]:
        """Create one short-lived authorization URL for an existing ticker."""

        identifier = _ticker_id(ticker_id)
        now = float(self._clock())
        attempt_id = secrets.token_urlsafe(18)
        state_secret = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        state = f"{attempt_id}.{state_secret}"
        challenge = _pkce_challenge(verifier)
        attempt = SpotifyOAuthAttempt(
            attempt_id=attempt_id,
            ticker_id=identifier,
            state_hash=_digest(state),
            verifier_ciphertext=self._encrypt(verifier),
            expires_at=now + self._config.attempt_ttl_seconds,
            created_at=now,
        )
        self._repository.create_spotify_oauth_attempt(attempt)
        query = urlencode(
            {
                "client_id": self._config.client_id,
                "response_type": "code",
                "redirect_uri": self._config.callback_uri,
                "scope": " ".join(SPOTIFY_SCOPES),
                "state": state,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
            }
        )
        return {
            "attempt_id": attempt_id,
            "authorization_url": f"{SPOTIFY_AUTHORIZE_URL}?{query}",
            "expires_at": attempt.expires_at,
        }

    def complete_authorization(self, code: str, state: str) -> dict[str, str]:
        """Validate state once, exchange code, and save the encrypted refresh token."""

        raw_code = str(code).strip()
        attempt_id = _attempt_id_from_state(state)
        if not raw_code:
            raise SpotifyIntegrationError("Spotify authorization code is missing")
        attempt = self._repository.consume_spotify_oauth_attempt(
            attempt_id, _digest(state), now=float(self._clock())
        )
        try:
            verifier = self._decrypt(attempt.verifier_ciphertext)
            tokens = self._http.exchange_code(raw_code, self._config, verifier)
            access_token = _required_text(tokens, "access_token")
            refresh_token = _required_text(tokens, "refresh_token")
            profile = self._http.get_current_user(access_token)
            account_id = _required_text(profile, "account_id", fallback="id")
            display_name = str(profile.get("display_name") or "Spotify user").strip()
            scopes = tuple(str(tokens.get("scope", "")).split()) or SPOTIFY_SCOPES
        except SpotifyIntegrationError:
            raise
        except Exception as error:
            raise SpotifyIntegrationError("Spotify authorization failed") from error
        now = float(self._clock())
        self._repository.save_spotify_connection(
            SpotifyConnection(
                ticker_id=attempt.ticker_id,
                spotify_account_id=account_id,
                display_name=display_name,
                scopes=scopes,
                refresh_token_ciphertext=self._encrypt(refresh_token),
                connected_at=now,
                updated_at=now,
            )
        )
        return {"attempt_id": attempt.attempt_id, "ticker_id": attempt.ticker_id, "status": "connected"}

    def status(self, ticker_id: str) -> dict[str, object]:
        """Return safe state for every Spotify account linked to one ticker."""

        connections = self._repository.list_spotify_connections(_ticker_id(ticker_id))
        accounts = [_connection_status_value(item) for item in connections]
        selected = next((item for item in connections if item.priority), None)
        primary = selected or (connections[0] if connections else None)
        return {
            "connected": any(item.status == "connected" for item in connections),
            "status": "connected" if any(item.status == "connected" for item in connections) else "not_connected",
            "accounts": accounts,
            "priority_account_id": selected.spotify_account_id if selected else None,
            "spotify_account_id": primary.spotify_account_id if primary else None,
            "display_name": primary.display_name if primary else None,
        }

    def disconnect(self, ticker_id: str, spotify_account_id: str | None = None) -> bool:
        """Remove one Spotify account, or all accounts when no account is named."""

        identifier = _ticker_id(ticker_id)
        deleted = self._repository.delete_spotify_connection(identifier, spotify_account_id)
        if spotify_account_id:
            with self._playback_lock:
                self._playback_windows.pop(f"{identifier}:{spotify_account_id}", None)
        else:
            with self._playback_lock:
                for key in tuple(self._playback_windows):
                    if key.startswith(f"{identifier}:"):
                        self._playback_windows.pop(key, None)
        return deleted

    def set_priority(self, ticker_id: str, spotify_account_id: str | None) -> dict[str, object]:
        """Set the account that controls ticker music selection."""

        self._repository.set_spotify_priority(_ticker_id(ticker_id), spotify_account_id)
        return self.status(ticker_id)

    def playback(self, ticker_id: str) -> Mapping[str, Any]:
        """Return the preferred account, or the first account now playing."""

        identifier = _ticker_id(ticker_id)
        connections = self._repository.list_spotify_connections(identifier)
        if not connections:
            return _connection_record("reauthorization_required")
        preferred = next((item for item in connections if item.priority), None)
        if preferred is not None:
            return self._playback_for_connection(preferred)
        fallback: Mapping[str, Any] | None = None
        for connection in connections:
            if connection.status != "connected":
                continue
            record = self._playback_for_connection(connection)
            if bool(record.get("is_playing")):
                return record
            if fallback is None:
                fallback = record
        return fallback or _connection_record("reauthorization_required")

    def _playback_for_connection(self, connection: SpotifyConnection) -> Mapping[str, Any]:
        """Fetch one account safely and preserve its distinct artwork window."""

        if connection.status != "connected":
            return _connection_record("reauthorization_required", connection)
        try:
            refresh_token = self._decrypt(connection.refresh_token_ciphertext)
            tokens = self._http.refresh_access_token(refresh_token, self._config)
            access_token = _required_text(tokens, "access_token")
            next_refresh = str(tokens.get("refresh_token") or refresh_token).strip()
            if next_refresh != refresh_token:
                now = float(self._clock())
                self._repository.save_spotify_connection(
                    SpotifyConnection(
                        ticker_id=connection.ticker_id,
                        spotify_account_id=connection.spotify_account_id,
                        display_name=connection.display_name,
                        scopes=connection.scopes,
                        refresh_token_ciphertext=self._encrypt(next_refresh),
                        status="connected",
                        priority=connection.priority,
                        connected_at=connection.connected_at,
                        updated_at=now,
                    )
                )
            playback = self._http.get_playback(access_token)
            record = self._windowed_playback(connection, playback, access_token)
            record["fetch_ts"] = float(self._clock())
            record["spotify_account_id"] = connection.spotify_account_id
            record["connection_name"] = connection.display_name
            record["priority"] = connection.priority
            return record
        except SpotifyIntegrationError as error:
            if "invalid_grant" in str(error).lower() or "unauthorized" in str(error).lower():
                self._mark_reauthorization(connection)
                return _connection_record("reauthorization_required", connection)
            raise
        except InvalidToken as error:
            self._mark_reauthorization(connection)
            raise SpotifyIntegrationError("Spotify stored authorization is invalid") from error

    def _mark_reauthorization(self, connection: SpotifyConnection) -> None:
        now = float(self._clock())
        self._repository.save_spotify_connection(
            SpotifyConnection(
                ticker_id=connection.ticker_id,
                spotify_account_id=connection.spotify_account_id,
                display_name=connection.display_name,
                scopes=connection.scopes,
                refresh_token_ciphertext=connection.refresh_token_ciphertext,
                status="reauthorization_required",
                priority=connection.priority,
                connected_at=connection.connected_at,
                updated_at=now,
            )
        )

    def _windowed_playback(
        self,
        connection: SpotifyConnection,
        playback: Mapping[str, Any] | None,
        access_token: str,
    ) -> dict[str, Any]:
        """Keep one previous cover and the next three covers across polls."""

        item = playback.get("item") if isinstance(playback, Mapping) else None
        if not isinstance(item, Mapping):
            return _playback_record(playback, None)
        identifier = str(item.get("id") or "").strip()
        if not identifier:
            return _playback_record(playback, None)
        with self._playback_lock:
            previous = self._playback_windows.get(_playback_window_key(connection))
        queue = self._http.get_queue(access_token) if previous is None or previous.current_id != identifier else None
        record = _playback_record(playback, queue)
        cover = str(record.get("cover") or "")
        queued = tuple(str(value) for value in record.get("next_covers", ()) if str(value))
        with self._playback_lock:
            key = _playback_window_key(connection)
            current = self._playback_windows.get(key)
            if current is not None and current.current_id == identifier:
                record["last_cover"] = current.previous_cover
                record["next_covers"] = list(current.next_covers)
                return record
            window = _PlaybackWindow(
                current_id=identifier,
                current_cover=cover,
                previous_cover=current.current_cover if current is not None else "",
                next_covers=queued[:3],
            )
            self._playback_windows[key] = window
        record["last_cover"] = window.previous_cover
        record["next_covers"] = list(window.next_covers)
        return record

    def _encrypt(self, value: str) -> str:
        return self._cipher.encrypt(str(value).encode("utf-8")).decode("ascii")

    def _decrypt(self, value: str) -> str:
        return self._cipher.decrypt(str(value).encode("ascii")).decode("utf-8")


class SpotifyMusicSource:
    """Expose server-owned Spotify playback through the v2 music source port."""

    def __init__(self, service: SpotifyIntegrationService) -> None:
        self._service = service

    def fetch_for_ticker(self, ticker_id: str, settings: DisplaySettings) -> Mapping[str, Any]:
        """Return music content for the requested ticker only."""

        if not isinstance(settings, DisplaySettings):
            raise TypeError("settings must be DisplaySettings")
        return {"content": [self._service.playback(ticker_id)]}

    def fetch(self, settings: DisplaySettings) -> Mapping[str, Any]:
        """Reject unscoped calls because music accounts belong to tickers."""

        raise SpotifyIntegrationError("Spotify music requires a ticker ID")


def _playback_record(playback: Mapping[str, Any] | None, queue: Mapping[str, Any] | None) -> dict[str, Any]:
    item = playback.get("item") if isinstance(playback, Mapping) else None
    if not isinstance(item, Mapping):
        return {
            "id": "spotify:idle",
            "family": "music",
            "kind": "spotify",
            "status": "idle",
            "is_playing": False,
            "name": "No active Spotify playback",
            "artist": "",
            "cover": "",
            "last_cover": "",
            "next_covers": [],
        }
    album = item.get("album") if isinstance(item.get("album"), Mapping) else {}
    images = album.get("images") if isinstance(album, Mapping) else []
    cover = _image_url(images)
    queue_items = queue.get("queue", []) if isinstance(queue, Mapping) else []
    next_covers = [_image_url(track.get("album", {}).get("images", [])) for track in queue_items[:3] if isinstance(track, Mapping)]
    artists = item.get("artists", [])
    artist = ", ".join(str(value.get("name", "")) for value in artists if isinstance(value, Mapping)).strip()
    return {
        "id": f"spotify:{str(item.get('id') or 'current')}",
        "family": "music",
        "kind": "spotify",
        "status": "playing" if bool(playback.get("is_playing")) else "paused",
        "is_playing": bool(playback.get("is_playing")),
        "name": str(item.get("name") or "Unknown track"),
        "artist": artist,
        "cover": cover,
        "last_cover": "",
        "next_covers": next_covers,
        "duration": float(item.get("duration_ms") or 0) / 1000.0,
        "progress": float(playback.get("progress_ms") or 0) / 1000.0,
        "source": "spotify",
    }


def _connection_record(
    status: str, connection: SpotifyConnection | None = None
) -> dict[str, Any]:
    """Return a non-playing card that identifies its linked account when known."""

    record = {
        "id": "spotify:connection",
        "family": "music",
        "kind": "spotify",
        "status": status,
        "is_playing": False,
        "name": "Connect Spotify" if status == "reauthorization_required" else "Spotify unavailable",
        "artist": "Open the ticker app to connect Spotify",
        "cover": "",
        "last_cover": "",
        "next_covers": [],
        "source": "spotify",
    }
    if connection is not None:
        record.update(
            {
                "spotify_account_id": connection.spotify_account_id,
                "connection_name": connection.display_name,
                "priority": connection.priority,
            }
        )
    return record


def _connection_status_value(connection: SpotifyConnection) -> dict[str, object]:
    """Project one Spotify connection without encrypted credential material."""

    return {
        "spotify_account_id": connection.spotify_account_id,
        "display_name": connection.display_name,
        "status": connection.status,
        "connected": connection.status == "connected",
        "priority": connection.priority,
        "scopes": list(connection.scopes),
        "updated_at": connection.updated_at,
    }


def _playback_window_key(connection: SpotifyConnection) -> str:
    """Return an artwork window key isolated by ticker and Spotify account."""

    return f"{connection.ticker_id}:{connection.spotify_account_id}"


def _required_text(value: Mapping[str, Any], key: str, *, fallback: str | None = None) -> str:
    result = str(value.get(key) or (value.get(fallback) if fallback else "")).strip()
    if not result:
        raise SpotifyIntegrationError(f"Spotify response omitted {key}")
    return result


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _digest(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _attempt_id_from_state(state: str) -> str:
    parts = str(state).split(".", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise SpotifyIntegrationError("Spotify authorization state is invalid")
    return parts[0]


def _ticker_id(value: str) -> str:
    identifier = str(value).strip()
    if not identifier:
        raise ValueError("ticker ID must not be empty")
    return identifier


def _https_uri(value: str, name: str) -> str:
    uri = str(value).strip()
    parsed = urlparse(uri)
    if parsed.scheme != "https" or not parsed.netloc or parsed.fragment:
        raise ValueError(f"Spotify {name} must be an HTTPS URI without a fragment")
    return uri


def _app_return_uri(value: str) -> str:
    uri = str(value).strip()
    parsed = urlparse(uri)
    if not parsed.scheme or not parsed.netloc or parsed.fragment:
        raise ValueError("Spotify app return URI is invalid")
    return uri


def _image_url(images: object) -> str:
    if not isinstance(images, list):
        return ""
    for image in images:
        if isinstance(image, Mapping) and str(image.get("url") or "").strip():
            return str(image["url"])
    return ""


__all__ = [
    "SpotifyConfig",
    "SpotifyHttpPort",
    "SpotifyIntegrationError",
    "SpotifyIntegrationService",
    "SpotifyMusicSource",
    "SPOTIFY_SCOPES",
    "UrllibSpotifyHttpClient",
]
