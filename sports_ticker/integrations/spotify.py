Warning: truncated output (original token count: 10297)
Total output lines: 1026

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
            with urlopen(request, timeout=8, context=verified_https_context()) as response:
                body = response.read()
                status = getattr(response, "status", 200)
        except HTTPError as error:
            try:
                response = json.loads(error.read())
                detail = str(response.get("error_description") or response.get("error") or "")
            except Exception:
                detail = ""
            suffix = f": {detail}" if detail else ""
            retry_after = _retry_after_seconds(error.headers) if error.code == 429 else None
            raise SpotifyIntegrationError(
                f"Spotify returned HTTP {error.code}{suffix}",
                status_code=error.code,
                retry_after=retry_after,
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise SpotifyIntegrationError("Spotify request failed") from error
        if status == 204:
            raise SpotifyIntegrationError("HTTP 204")
        if not 200 <= int(status) < 300:
            retry_after = _retry_after_seconds(getattr(response, "headers", None)) if status == 429 else None
            raise SpotifyIntegrationError(
                f"Spotify returned HTTP {status}",
                status_code=int(status),
                retry_after=retry_after,
            )
        try:
            value = json.loads(body)
        except (TypeError, json.JSONDecodeError) as error:
            raise SpotifyIntegrationError("Spotify returned invalid JSON") from error
        if not isinstance(value, Mapping):
            raise SpotifyIntegrationError("Spotify returned an invalid response")
        return value


class SpotifyIntegrationService:
    """Own encrypted Spotify links shared by every ticker in one controller group."""

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
        self._account_poll_locks: dict[str, Lock] = {}
        self._account_poll_locks_lock = Lock()
        self._access_tokens: dict[str, tuple[str, float]] = {}
        self._access_token_lock = Lock()
        self._api_cooldown_until = 0.0
        self._rate_limit_backoff_seconds = SPOTIFY_RATE_LIMIT_INITIAL_BACKOFF_SECONDS
        self._next_playback_poll_at: dict[str, float] = {}
        self._playback_failures: dict[str, SpotifyIntegrationError] = {}

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
        group_id = self._group_id(attempt.ticker_id)
        account_key = f"{group_id}:{account_id}"
        with self._account_poll_lock(account_key):
            self._repository.save_group_spotify_connection(
                group_id,
                SpotifyConnection(
                    ticker_id=group_id,
                    spotify_account_id=account_id,
                    display_name=display_name,
                    scopes=scopes,
                    refresh_token_ciphertext=self._encrypt(refresh_token),
                    connected_at=now,
                    updated_at=now,
                )
            )
            self._clear_account_cache(account_key)
        return {"attempt_id": attempt.attempt_id, "ticker_id": attempt.ticker_id, "status": "connected"}

    def status(self, ticker_id: str) -> dict[str, object]:
        """Return safe state for every Spotify account linked to the ticker's controller group."""

        identifier = _ticker_id(ticker_id)
        connections = self._repository.list_group_spotify_connections(
            self._group_id(identifier), fallback_ticker_id=identifier
        )
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
        """Remove one shared Spotify account, or all accounts in the controller group."""

        identifier = _ticker_id(ticker_id)
        group_id = self._group_id(identifier)
        if spotify_account_id:
            key = f"{group_id}:{spotify_account_id}"
            with self._account_poll_lock(key):
                deleted = self._repository.delete_group_spotify_connection(group_id, spotify_account_id)
                self._clear_account_cache(key)
            return deleted

        connections = self._repository.list_group_spotify_connections(group_id, fallback_ticker_id=identifier)
        deleted = self._repository.delete_group_spotify_connection(group_id)
        for connection in connections:
            key = _playback_window_key(connection)
            with self._account_poll_lock(key):
                self._clear_account_cache(key)
        with self._playback_lock:
            for key in tuple(self._playback_windows):
                if key.startswith(f"{group_id}:"):
                    self._playback_windows.pop(key, None)
                    self._next_playback_poll_at.pop(key, None)
        with self._access_token_lock:
            for key in tuple(self._access_tokens):
                if key.startswith(f"{group_id}:"):
                    self._access_tokens.pop(key, None)
        return deleted

    def set_priority(self, ticker_id: str, spotify_account_id: str | None) -> dict[str, object]:
        """Set the account that controls music selection for the controller group."""

        self._repository.set_group_spotify_priority(self._group_id(_ticker_id(ticker_id)), spotify_account_id)
        return self.status(ticker_id)

    def playback(self, ticker_id: str) -> Mapping[str, Any]:
        """Return the preferred account, or the first account now playing."""

        self._raise_if_api_cooling_down()
        identifier = _ticker_id(ticker_id)
        group_id = self._group_id(identifier)
        connections = self._repository.list_group_spotify_connections(group_id, fallback_ticker_id=identifier)
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
        window_key = _playback_window_key(connection)
        with self._account_poll_lock(window_key):
            return self._read_playback_for_connection(connection, window_key)

    def _read_playback_for_connection(
        self,
        connection: SpotifyConnection,
        window_key: str,
    ) -> Mapping[str, Any]:
        """Fetch playback while the account's single-flight lock is held."""

        self._raise_if_api_cooling_down()
        now = float(self._clock())
        with self._playback_lock:
            if now < self._next_playback_poll_at.get(window_key, 0.0):
                failure = self._playback_failures.get(window_key)
                if failure is not None:
                    raise failure
                window = self._playback_windows.get(window_key)
                if window is not None and window.last_record is not None:
                    return dict(window.last_record)
        try:
            group_id = connection.ticker_id if connection.ticker_id.startswith("cg_") else self._group_id(connection.ticker_id)
            refresh_token = self._decrypt(connection.refresh_token_ciphertext)
            access_token, next_refresh = self._access_token(group_id, connection, refresh_token)
            if next_refresh != refresh_token:
                self._repository.save_group_spotify_connection(
                    group_id,
                    SpotifyConnection(
                        ticker_id=group_id,
                        spotify_account_id=connection.spotify_account_id,
                        display_name=connectio…297 tokens truncated…record
        except SpotifyIntegrationError as error:
            self._remember_api_cooldown(error)
            if error.status_code != 429:
                with self._playback_lock:
                    self._playback_failures[window_key] = SpotifyIntegrationError(
                        str(error), status_code=error.status_code, retry_after=error.retry_after
                    )
                    self._next_playback_poll_at[window_key] = (
                        float(self._clock()) + SPOTIFY_ERROR_REFRESH_SECONDS
                    )
            if error.status_code == 401:
                self._evict_access_token(window_key)
            if "invalid_grant" in str(error).lower():
                self._mark_reauthorization(connection)
                return _connection_record("reauthorization_required", connection)
            raise
        except InvalidToken as error:
            self._mark_reauthorization(connection)
            raise SpotifyIntegrationError("Spotify stored authorization is invalid") from error

    def _access_token(
        self,
        group_id: str,
        connection: SpotifyConnection,
        refresh_token: str,
    ) -> tuple[str, str]:
        """Reuse one account access token until Spotify's expiry approaches."""

        key = f"{group_id}:{connection.spotify_account_id}"
        now = float(self._clock())
        with self._access_token_lock:
            cached = self._access_tokens.get(key)
            if cached is not None and now < cached[1]:
                return cached[0], refresh_token

            tokens = self._http.refresh_access_token(refresh_token, self._config)
            access_token = _required_text(tokens, "access_token")
            next_refresh = str(tokens.get("refresh_token") or refresh_token).strip()
            try:
                lifetime = float(tokens.get("expires_in", 3600))
            except (TypeError, ValueError):
                lifetime = 3600.0
            lifetime = max(0.0, lifetime - 60.0)
            if lifetime > 0:
                self._access_tokens[key] = (access_token, now + lifetime)
            return access_token, next_refresh

    def _raise_if_api_cooling_down(self) -> None:
        now = float(self._clock())
        with self._playback_lock:
            remaining = self._api_cooldown_until - now
        if remaining > 0:
            raise SpotifyIntegrationError(
                "Spotify Web API rate limit cooldown is active",
                status_code=429,
                retry_after=remaining,
            )

    def _account_poll_lock(self, account_key: str) -> Lock:
        """Return one stable single-flight lock for a shared account."""

        with self._account_poll_locks_lock:
            return self._account_poll_locks.setdefault(account_key, Lock())

    def _clear_account_cache(self, account_key: str) -> None:
        """Remove one account's access token, playback window, and cadence."""

        with self._playback_lock:
            self._playback_windows.pop(account_key, None)
            self._next_playback_poll_at.pop(account_key, None)
            self._playback_failures.pop(account_key, None)
        with self._access_token_lock:
            self._access_tokens.pop(account_key, None)

    def _evict_access_token(self, account_key: str) -> None:
        """Remove one early-rejected access token and retain other account state."""

        with self._access_token_lock:
            self._access_tokens.pop(account_key, None)

    def _remember_api_cooldown(self, error: SpotifyIntegrationError) -> None:
        if error.status_code != 429:
            return
        with self._playback_lock:
            if error.retry_after is None:
                retry_after = self._rate_limit_backoff_seconds
                self._rate_limit_backoff_seconds = min(
                    retry_after * 2.0,
                    SPOTIFY_RATE_LIMIT_MAX_BACKOFF_SECONDS,
                )
            else:
                retry_after = max(0.0, float(error.retry_after))
                self._rate_limit_backoff_seconds = SPOTIFY_RATE_LIMIT_INITIAL_BACKOFF_SECONDS
            until = float(self._clock()) + retry_after
            self._api_cooldown_until = max(self._api_cooldown_until, until)

    def _mark_reauthorization(self, connection: SpotifyConnection) -> None:
        now = float(self._clock())
        group_id = self._group_id(connection.ticker_id)
        self._clear_account_cache(f"{group_id}:{connection.spotify_account_id}")
        self._repository.save_group_spotify_connection(
            group_id,
            SpotifyConnection(
                ticker_id=group_id,
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
        """Keep the last played song and next three songs across polls."""

        item = playback.get("item") if isinstance(playback, Mapping) else None
        current_track = _extract_track(item) if isinstance(item, Mapping) else None
        key = _playback_window_key(connection)

        with self._playback_lock:
            cached = self._playback_windows.get(key)

        if current_track is None:
            if cached is not None and cached.last_record is not None:
                record = dict(cached.last_record)
                if cached.current_track is None:
                    return record
                record["is_playing"] = False
                record["status"] = "paused"
                with self._playback_lock:
                    self._playback_windows[key] = _PlaybackWindow(
                        current_track=cached.current_track,
                        previous_track=cached.previous_track,
                        next_tracks=cached.next_tracks,
                        last_record=record,
                        queue_refresh_pending=cached.queue_refresh_pending,
                    )
                return record
            record = _idle_record()
            with self._playback_lock:
                self._playback_windows[key] = _PlaybackWindow(None, None, (), record)
            return record

        need_queue = (
            cached is None
            or cached.current_track is None
            or cached.current_track.id != current_track.id
            or cached.queue_refresh_pending
        )
        queue_tracks: tuple[_SpotifyTrack, ...] = ()
        queue_refresh_pending = False
        if need_queue:
            try:
                queue_data = self._http.get_queue(access_token)
                queue_tracks = _extract_queue_tracks(queue_data)
            except SpotifyIntegrationError as error:
                self._remember_api_cooldown(error)
                if error.status_code == 401:
                    self._evict_access_token(key)
                queue_refresh_pending = True
                queue_tracks = ()
            except Exception:
                queue_refresh_pending = True
                queue_tracks = ()
        elif cached is not None:
            queue_tracks = cached.next_tracks

        with self._playback_lock:
            current_window = self._playback_windows.get(key)
            if (
                current_window is not None
                and current_window.current_track is not None
                and current_window.current_track.id == current_track.id
            ):
                prev_track = current_window.previous_track
                final_queue = queue_tracks if queue_tracks else current_window.next_tracks
            else:
                prev_track = current_window.current_track if current_window is not None else None
                final_queue = queue_tracks

            record = _build_playback_record(
                playback=playback,
                current=current_track,
                previous=prev_track,
                queued=final_queue,
            )
            window = _PlaybackWindow(
                current_track=current_track,
                previous_track=prev_track,
                next_tracks=final_queue,
                last_record=record,
                queue_refresh_pending=queue_refresh_pending,
            )
            self._playback_windows[key] = window

        return record

    def _encrypt(self, value: str) -> str:
        return self._cipher.encrypt(str(value).encode("utf-8")).decode("ascii")

    def _decrypt(self, value: str) -> str:
        return self._cipher.decrypt(str(value).encode("ascii")).decode("utf-8")

    def _group_id(self, ticker_id: str) -> str:
        """Resolve one ticker to its shared controller group or a legacy private scope."""

        identifier = _ticker_id(ticker_id)
        if identifier.startswith("cg_") or identifier.startswith("ticker:"):
            return identifier
        return self._repository.controller_group_id_for_ticker(identifier) or f"ticker:{identifier}"


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


def _extract_track(item: Mapping[str, Any] | None) -> _SpotifyTrack | None:
    """Extract normalized track metadata from one Spotify track mapping."""

    if not isinstance(item, Mapping):
        return None
    track_id = str(item.get("id") or "").strip()
    if not track_id:
        return None
    name = str(item.get("name") or "Unknown track").strip()
    album_data = item.get("album") if isinstance(item.get("album"), Mapping) else {}
    album_name = str(album_data.get("name") or "").strip()
    images = album_data.get("images") if isinstance(album_data, Mapping) else []
    cover = _image_url(images)
    artists_list = item.get("artists", [])
    artist = ", ".join(
        str(val.get("name", "")) for val in artists_list if isinstance(val, Mapping)
    ).strip()
    duration = float(item.get("duration_ms") or 0) / 1000.0
    return _SpotifyTrack(
        id=track_id,
        name=name,
        artist=artist,
        album=album_name,
        cover=cover,
        duration=duration,
    )


def _extract_queue_tracks(queue: Mapping[str, Any] | None) -> tuple[_SpotifyTrack, ...]:
    """Extract the next three track records from a Spotify queue response."""

    if not isinstance(queue, Mapping):
        return ()
    queue_items = queue.get("queue", [])
    if not isinstance(queue_items, list):
        return ()
    tracks: list[_SpotifyTrack] = []
    for item in queue_items:
        if isinstance(item, Mapping):
            track = _extract_track(item)
            if track is not None:
                tracks.append(track)
                if len(tracks) >= 3:
                    break
    return tuple(tracks)


def _build_playback_record(
    playback: Mapping[str, Any] | None,
    current: _SpotifyTrack,
    previous: _SpotifyTrack | None,
    queued: tuple[_SpotifyTrack, ...],
) -> dict[str, Any]:
    """Construct one music item projection from active, previous, and queued tracks."""

    is_playing = bool(playback.get("is_playing")) if isinstance(playback, Mapping) else False
    progress = float(playback.get("progress_ms") or 0) / 1000.0 if isinstance(playback, Mapping) else 0.0

    last_cover = previous.cover if previous is not None else ""
    last_song = previous.to_mapping() if previous is not None else None
    next_covers = [track.cover for track in queued if track.cover]
    next_songs = [track.to_mapping() for track in queued]

    return {
        "id": f"spotify:{current.id}",
        "family": "music",
        "kind": "spotify",
        "type": "music",
        "sport": "music",
        "status": "playing" if is_playing else "paused",
        "is_playing": is_playing,
        "name": current.name,
        "artist": current.artist,
        "album": current.album,
        "cover": current.cover,
        "last_cover": last_cover,
        "next_covers": next_covers,
        "last_song": last_song,
        "next_songs": next_songs,
        "home_logo": current.cover,
        "last_logo": last_cover,
        "next_logos": next_covers,
        "artwork": current.cover,
        "cover_url": current.cover,
        "album_art": current.cover,
        "away_abbr": current.name,
        "home_abbr": current.artist,
        "duration": current.duration,
        "progress": progress,
        "source": "spotify",
    }


def _idle_record() -> dict[str, Any]:
    """Return an empty placeholder card when no music has been played."""

    return {
        "id": "spotify:idle",
        "family": "music",
        "kind": "spotify",
        "type": "music",
        "sport": "music",
        "status": "idle",
        "is_playing": False,
        "name": "No active Spotify playback",
        "artist": "",
        "album": "",
        "cover": "",
        "last_cover": "",
        "next_covers": [],
        "last_song": None,
        "next_songs": [],
        "home_logo": "",
        "last_logo": "",
        "next_logos": [],
        "artwork": "",
        "cover_url": "",
        "album_art": "",
        "duration": 0.0,
        "progress": 0.0,
        "source": "spotify",
    }


def _playback_record(playback: Mapping[str, Any] | None, queue: Mapping[str, Any] | None) -> dict[str, Any]:
    """Legacy playback builder maintained for direct callers."""

    item = playback.get("item") if isinstance(playback, Mapping) else None
    current = _extract_track(item) if isinstance(item, Mapping) else None
    if current is None:
        return _idle_record()
    queued = _extract_queue_tracks(queue)
    return _build_playback_record(playback, current, None, queued)


def _connection_record(
    status: str, connection: SpotifyConnection | None = None
) -> dict[str, Any]:
    """Return a non-playing card that identifies its linked account when known."""

    record = {
        "id": "spotify:connection",
        "family": "music",
        "kind": "spotify",
        "type": "music",
        "sport": "music",
        "status": status,
        "is_playing": False,
        "name": "Connect Spotify" if status == "reauthorization_required" else "Spotify unavailable",
        "artist": "Open the ticker app to connect Spotify",
        "album": "",
        "cover": "",
        "last_cover": "",
        "next_covers": [],
        "last_song": None,
        "next_songs": [],
        "home_logo": "",
        "last_logo": "",
        "next_logos": [],
        "artwork": "",
        "cover_url": "",
        "album_art": "",
        "duration": 0.0,
        "progress": 0.0,
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

    scope = connection.ticker_id
    if not scope.startswith(("cg_", "ticker:")):
        scope = f"ticker:{scope}"
    return f"{scope}:{connection.spotify_account_id}"


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
    if not isinstance(images, list) or not images:
        return ""
    valid = [img for img in images if isinstance(img, Mapping) and str(img.get("url") or "").strip()]
    if not valid:
        return ""
    candidates: list[tuple[int, str]] = []
    for img in valid:
        width = int(img.get("width") or 0)
        candidates.append((width, str(img["url"])))
    adequate = sorted([c for c in candidates if c[0] >= 42], key=lambda c: c[0])
    if adequate:
        return adequate[0][1]
    return valid[0]["url"]


def _retry_after_seconds(headers: object) -> float | None:
    """Read Spotify's Retry-After value in seconds when one is present."""

    get = getattr(headers, "get", None)
    if not callable(get):
        return None
    raw = get("Retry-After") or get("retry-after")
    try:
        retry_after = float(raw)
    except (TypeError, ValueError):
        return None
    return retry_after if retry_after >= 0.0 and retry_after < float("inf") else None


def _playback_refresh_seconds(playback: Mapping[str, Any] | None) -> float:
    """Choose polling cadence from Spotify's observed state before retaining display metadata."""

    if not isinstance(playback, Mapping) or not playback.get("item"):
        return SPOTIFY_IDLE_REFRESH_SECONDS
    return SPOTIFY_PLAYING_REFRESH_SECONDS if bool(playback.get("is_playing")) else SPOTIFY_PAUSED_REFRESH_SECONDS


__all__ = [
    "SpotifyConfig",
    "SpotifyHttpPort",
    "SpotifyIntegrationError",
    "SpotifyIntegrationService",
    "SpotifyMusicSource",
    "SPOTIFY_IDLE_REFRESH_SECONDS",
    "SPOTIFY_PAUSED_REFRESH_SECONDS",
    "SPOTIFY_PLAYING_REFRESH_SECONDS",
    "SPOTIFY_SCOPES",
    "UrllibSpotifyHttpClient",
]
