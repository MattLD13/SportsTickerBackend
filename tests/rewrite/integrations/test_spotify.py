"""Test Spotify integration caching, queueing, and resilience."""

from __future__ import annotations

from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import time
from threading import Event
from urllib.error import HTTPError
from io import BytesIO
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse
from cryptography.fernet import Fernet
from PIL import Image
import pytest

from sports_ticker.domain import DisplaySettings
from sports_ticker.fleet import PairingState, SpotifyConnection, TickerRepository
from sports_ticker.integrations.spotify import (
    SpotifyConfig,
    SpotifyIntegrationError,
    SpotifyHttpPort,
    SpotifyIntegrationService,
    SpotifyMusicSource,
)
from sports_ticker.integrations import spotify as spotify_module
from ticker_core.assets.planner import AssetPlanner
from ticker_core.context import RenderContext
from ticker_core.features.music.renderer import MusicAnimationState, MusicRenderer
from ticker_core.rendering import load_default_font_set


class FakeSpotifyHttp(SpotifyHttpPort):
    """Stub Spotify HTTP client providing deterministic playback and queue responses."""

    def __init__(self) -> None:
        self.playback_response: Mapping[str, Any] | None = None
        self.queue_response: Mapping[str, Any] | None = None
        self.queue_raises = False
        self.playback_error: SpotifyIntegrationError | None = None
        self.refresh_calls = 0
        self.playback_calls = 0
        self.queue_calls = 0
        self.token_lifetime = 3600

    def exchange_code(self, code: str, config: SpotifyConfig, verifier: str) -> Mapping[str, Any]:
        return {"access_token": "fake-access", "refresh_token": "fake-refresh"}

    def refresh_access_token(self, refresh_token: str, config: SpotifyConfig) -> Mapping[str, Any]:
        self.refresh_calls += 1
        return {
            "access_token": "fake-access",
            "refresh_token": refresh_token,
            "expires_in": self.token_lifetime,
        }

    def get_current_user(self, access_token: str) -> Mapping[str, Any]:
        return {"id": "user-1", "display_name": "Test User"}

    def get_playback(self, access_token: str) -> Mapping[str, Any] | None:
        self.playback_calls += 1
        if self.playback_error is not None:
            raise self.playback_error
        return self.playback_response

    def get_queue(self, access_token: str) -> Mapping[str, Any] | None:
        self.queue_calls += 1
        if self.queue_raises:
            raise RuntimeError("Queue endpoint failure")
        return self.queue_response


def _sample_track(track_id: str, title: str, artist: str, album: str, cover_url: str) -> dict[str, Any]:
    return {
        "id": track_id,
        "name": title,
        "duration_ms": 210000,
        "artists": [{"name": artist}],
        "album": {
            "name": album,
            "images": [{"url": cover_url, "height": 300, "width": 300}],
        },
    }


def _setup_service(
    tmp_path,
    http: FakeSpotifyHttp,
    *,
    clock=None,
    group_id: str = "ticker:ticker-1",
) -> tuple[SpotifyIntegrationService, TickerRepository]:
    key = Fernet.generate_key().decode("ascii")
    config = SpotifyConfig(
        client_id="test_client",
        callback_uri="https://localhost/callback",
        app_return_uri="https://localhost/app",
        encryption_key=key,
    )
    cipher = Fernet(key.encode("ascii"))
    repository = TickerRepository(tmp_path / "ticker.sqlite3")
    connection = SpotifyConnection(
        ticker_id=group_id,
        spotify_account_id="user-1",
        display_name="Test User",
        scopes=("user-read-playback-state",),
        refresh_token_ciphertext=cipher.encrypt(b"refresh-token-1").decode("ascii"),
        status="connected",
        priority=True,
    )
    repository.save_group_spotify_connection(group_id, connection)
    service = SpotifyIntegrationService(repository, config, http=http, clock=clock or time.time)
    return service, repository


def test_spotify_playback_caches_last_played_and_next_three_songs(tmp_path) -> None:
    """Retain the previous song and next three queue songs across track transitions."""
    http = FakeSpotifyHttp()
    now = [1000.0]
    service, repository = _setup_service(tmp_path, http, clock=lambda: now[0])

    try:
        # Song 1 is playing with queue of songs 2, 3, 4, 5
        http.playback_response = {
            "is_playing": True,
            "progress_ms": 30000,
            "item": _sample_track("t1", "Track One", "Artist One", "Album One", "https://img.spotify.com/t1.jpg"),
        }
        http.queue_response = {
            "queue": [
                _sample_track("t2", "Track Two", "Artist Two", "Album Two", "https://img.spotify.com/t2.jpg"),
                _sample_track("t3", "Track Three", "Artist Three", "Album Three", "https://img.spotify.com/t3.jpg"),
                _sample_track("t4", "Track Four", "Artist Four", "Album Four", "https://img.spotify.com/t4.jpg"),
                _sample_track("t5", "Track Five", "Artist Five", "Album Five", "https://img.spotify.com/t5.jpg"),
            ]
        }

        first_read = service.playback("ticker-1")
        assert http.queue_calls == 1
        assert first_read["name"] == "Track One"
        assert first_read["artist"] == "Artist One"
        assert first_read["album"] == "Album One"
        assert first_read["cover"] == "https://img.spotify.com/t1.jpg"
        assert first_read["last_cover"] == ""
        assert first_read["last_song"] is None
        assert len(first_read["next_covers"]) == 3
        assert first_read["next_covers"] == [
            "https://img.spotify.com/t2.jpg",
            "https://img.spotify.com/t3.jpg",
            "https://img.spotify.com/t4.jpg",
        ]
        assert len(first_read["next_songs"]) == 3
        assert first_read["next_songs"][0]["name"] == "Track Two"
        assert first_read["next_songs"][1]["name"] == "Track Three"
        assert first_read["next_songs"][2]["name"] == "Track Four"

        # Advance to Song 2
        http.playback_response = {
            "is_playing": True,
            "progress_ms": 10000,
            "item": _sample_track("t2", "Track Two", "Artist Two", "Album Two", "https://img.spotify.com/t2.jpg"),
        }
        http.queue_response = {
            "queue": [
                _sample_track("t3", "Track Three", "Artist Three", "Album Three", "https://img.spotify.com/t3.jpg"),
                _sample_track("t4", "Track Four", "Artist Four", "Album Four", "https://img.spotify.com/t4.jpg"),
                _sample_track("t5", "Track Five", "Artist Five", "Album Five", "https://img.spotify.com/t5.jpg"),
            ]
        }

        now[0] += 15.0
        second_read = service.playback("ticker-1")
        assert http.queue_calls == 2
        assert second_read["name"] == "Track Two"
        assert second_read["last_cover"] == "https://img.spotify.com/t1.jpg"
        assert second_read["last_song"] is not None
        assert second_read["last_song"]["id"] == "t1"
        assert second_read["last_song"]["name"] == "Track One"
        assert second_read["last_song"]["artist"] == "Artist One"
        assert second_read["last_song"]["album"] == "Album One"
        assert second_read["last_song"]["cover"] == "https://img.spotify.com/t1.jpg"
        assert second_read["next_covers"] == [
            "https://img.spotify.com/t3.jpg",
            "https://img.spotify.com/t4.jpg",
            "https://img.spotify.com/t5.jpg",
        ]
    finally:
        repository.close()


def test_spotify_playback_preserves_last_played_song_when_idle(tmp_path) -> None:
    """Preserve track details and queue when Spotify playback is paused or returns 204."""
    http = FakeSpotifyHttp()
    now = [1000.0]
    service, repository = _setup_service(tmp_path, http, clock=lambda: now[0])

    try:
        http.playback_response = {
            "is_playing": True,
            "progress_ms": 45000,
            "item": _sample_track("t1", "Track One", "Artist One", "Album One", "https://img.spotify.com/t1.jpg"),
        }
        http.queue_response = {
            "queue": [
                _sample_track("t2", "Track Two", "Artist Two", "Album Two", "https://img.spotify.com/t2.jpg"),
            ]
        }

        active = service.playback("ticker-1")
        assert active["status"] == "playing"
        assert active["is_playing"] is True

        # Now Spotify becomes idle / no active item (e.g. paused / stopped playback)
        http.playback_response = None
        http.queue_response = None

        now[0] += 15.0
        idle = service.playback("ticker-1")
        assert idle["status"] == "paused"
        assert idle["is_playing"] is False
        assert idle["name"] == "Track One"
        assert idle["artist"] == "Artist One"
        assert idle["album"] == "Album One"
        assert idle["cover"] == "https://img.spotify.com/t1.jpg"
        assert idle["next_covers"] == ["https://img.spotify.com/t2.jpg"]
        assert len(idle["next_songs"]) == 1
        assert idle["next_songs"][0]["name"] == "Track Two"
    finally:
        repository.close()


def test_spotify_queue_error_does_not_crash_playback(tmp_path) -> None:
    """Handle queue fetch failures gracefully without failing playback reads."""
    http = FakeSpotifyHttp()
    service, repository = _setup_service(tmp_path, http)

    try:
        http.playback_response = {
            "is_playing": True,
            "progress_ms": 15000,
            "item": _sample_track("t1", "Track One", "Artist One", "Album One", "https://img.spotify.com/t1.jpg"),
        }
        http.queue_raises = True

        record = service.playback("ticker-1")
        assert record["name"] == "Track One"
        assert record["cover"] == "https://img.spotify.com/t1.jpg"
        assert record["next_covers"] == []
        assert record["next_songs"] == []
    finally:
        repository.close()


def test_asset_planner_plans_last_song_and_next_three_songs() -> None:
    """Ensure AssetPlanner extracts all cover URLs from music payloads."""
    planner = AssetPlanner()
    item = {
        "type": "music",
        "cover": "https://img.spotify.com/current.jpg",
        "last_cover": "https://img.spotify.com/last.jpg",
        "last_song": {"cover": "https://img.spotify.com/last_song.jpg"},
        "next_covers": ["https://img.spotify.com/next1.jpg", "https://img.spotify.com/next2.jpg"],
        "next_songs": [{"cover": "https://img.spotify.com/next3.jpg"}],
    }
    requests = planner.plan([item]).requests
    urls = {req.url for req in requests}

    assert "https://img.spotify.com/current.jpg" in urls
    assert "https://img.spotify.com/last.jpg" in urls
    assert "https://img.spotify.com/last_song.jpg" in urls
    assert "https://img.spotify.com/next1.jpg" in urls
    assert "https://img.spotify.com/next2.jpg" in urls
    assert "https://img.spotify.com/next3.jpg" in urls
    for req in requests:
        assert req.size == (42, 42)
        assert req.processor == "logo"


class FakeLogoSource:
    """Supply test image surfaces for requested logo URLs."""

    def __init__(self) -> None:
        self._images: dict[str, Image.Image] = {}

    def add(self, url: str, color: tuple[int, int, int]) -> None:
        img = Image.new("RGBA", (42, 42), (*color, 255))
        self._images[url] = img

    def get(self, url: str, size: tuple[int, int]) -> Image.Image | None:
        return self._images.get(url)


def test_music_renderer_blends_dominant_color_from_previous_song() -> None:
    """Music renderer extracts dominant color from previous artwork during transitions."""
    fonts = load_default_font_set()
    logos = FakeLogoSource()
    logos.add("https://img.spotify.com/song1.jpg", (255, 0, 0))    # Red
    logos.add("https://img.spotify.com/song2.jpg", (0, 0, 255))    # Blue

    renderer = MusicRenderer(fonts, logos)
    context = RenderContext(datetime(2026, 8, 16, 12, 0, 0))

    # Frame 1: Song 2 with last_song Song 1
    item = {
        "type": "music",
        "name": "Song 2",
        "artist": "Artist 2",
        "cover": "https://img.spotify.com/song2.jpg",
        "last_cover": "https://img.spotify.com/song1.jpg",
        "is_playing": True,
        "duration": 200.0,
        "progress": 10.0,
    }
    image, state = renderer.render_with_state(context, item, MusicAnimationState())
    assert image.size == (384, 32)
    assert state.artwork is not None
    assert state.previous_artwork is not None
    assert state.previous_dominant != (29, 185, 84)  # Computed from red image


def test_spotify_image_url_selects_optimal_resolution_for_led_panel() -> None:
    """Choose the compact 64x64 or 300x300 image instead of the heavyweight 640x640 image."""
    from sports_ticker.integrations.spotify import _image_url

    images = [
        {"url": "https://img.spotify.com/640.jpg", "height": 640, "width": 640},
        {"url": "https://img.spotify.com/300.jpg", "height": 300, "width": 300},
        {"url": "https://img.spotify.com/64.jpg", "height": 64, "width": 64},
    ]
    assert _image_url(images) == "https://img.spotify.com/64.jpg"


def test_asset_planner_recognizes_family_and_kind_without_explicit_type() -> None:
    """Ensure AssetPlanner extracts (42, 42) covers when item only has family='music' and kind='spotify'."""
    planner = AssetPlanner()
    item = {
        "family": "music",
        "kind": "spotify",
        "cover": "https://img.spotify.com/current.jpg",
        "last_cover": "https://img.spotify.com/last.jpg",
        "next_covers": ["https://img.spotify.com/next.jpg"],
    }
    requests = planner.plan({"content": {"music": [item]}}).requests
    urls = {req.url for req in requests}
    assert "https://img.spotify.com/current.jpg" in urls
    assert "https://img.spotify.com/last.jpg" in urls
    assert "https://img.spotify.com/next.jpg" in urls
    for req in requests:
        assert req.size == (42, 42)
        assert req.processor == "logo"


def test_production_spotify_refresh_interval_limits_api_polling() -> None:
    """Wake the music source often enough to support its adaptive poll cadence."""
    from sports_ticker.production import _INTERVALS

    assert _INTERVALS["music"] == 0.6


def test_spotify_api_cooldown_honors_retry_after_and_resumes_at_expiry(tmp_path) -> None:
    """Skip every upstream call during a shared cooldown, then resume after expiry."""
    now = [1000.0]
    http = FakeSpotifyHttp()
    service, repository = _setup_service(tmp_path, http, clock=lambda: now[0])
    http.playback_error = SpotifyIntegrationError(
        "Spotify returned HTTP 429",
        status_code=429,
        retry_after=45.0,
    )

    try:
        with pytest.raises(SpotifyIntegrationError) as first_error:
            service.playback("ticker-1")
        assert first_error.value.retry_after == 45.0
        first_counts = (http.refresh_calls, http.playback_calls, http.queue_calls)
        assert first_counts == (1, 1, 0)

        now[0] += 44.0
        with pytest.raises(SpotifyIntegrationError) as cooldown_error:
            service.playback("ticker-1")
        assert cooldown_error.value.retry_after == 1.0
        assert (http.refresh_calls, http.playback_calls, http.queue_calls) == first_counts

        now[0] += 1.0
        http.playback_error = None
        http.playback_response = {
            "is_playing": True,
            "progress_ms": 30000,
            "item": _sample_track("t1", "Track One", "Artist One", "Album One", "https://img.spotify.com/t1.jpg"),
        }
        resumed = service.playback("ticker-1")
        assert resumed["name"] == "Track One"
        assert http.refresh_calls == 1
        assert http.playback_calls == 2
        assert http.queue_calls == 1
    finally:
        repository.close()


def test_spotify_adaptive_polling_and_access_token_cache(tmp_path) -> None:
    """Poll playing, paused, and idle playback at bounded adaptive intervals."""
    now = [2000.0]
    http = FakeSpotifyHttp()
    service, repository = _setup_service(tmp_path, http, clock=lambda: now[0])
    http.playback_response = {
        "is_playing": True,
        "progress_ms": 30000,
        "item": _sample_track("t1", "Track One", "Artist One", "Album One", "https://img.spotify.com/t1.jpg"),
    }

    try:
        assert service.playback("ticker-1")["status"] == "playing"
        now[0] = 2000.5
        assert service.playback("ticker-1")["status"] == "playing"
        assert http.playback_calls == 1
        now[0] = 2000.6
        http.queue_response = {"queue": []}
        http.playback_response = {"is_playing": False, "item": _sample_track(
            "t1", "Track One", "Artist One", "Album One", "https://img.spotify.com/t1.jpg"
        )}
        assert service.playback("ticker-1")["status"] == "paused"
        assert http.playback_calls == 2
        assert http.queue_calls == 1
        assert http.refresh_calls == 1

        now[0] += 4.0
        assert service.playback("ticker-1")["status"] == "paused"
        assert http.playback_calls == 2
        now[0] += 1.0
        http.playback_response = None
        assert service.playback("ticker-1")["status"] == "paused"
        assert http.playback_calls == 3
        assert http.refresh_calls == 1
    finally:
        repository.close()


def test_spotify_adaptive_idle_polling_uses_cached_record(tmp_path) -> None:
    """Poll an idle account every 30 seconds and reuse its record between polls."""
    now = [3000.0]
    http = FakeSpotifyHttp()
    service, repository = _setup_service(tmp_path, http, clock=lambda: now[0])

    try:
        assert service.playback("ticker-1")["status"] == "idle"
        now[0] += 29.0
        assert service.playback("ticker-1")["status"] == "idle"
        assert http.playback_calls == 1
        now[0] += 1.0
        assert service.playback("ticker-1")["status"] == "idle"
        assert http.playback_calls == 2
        assert http.refresh_calls == 1
    finally:
        repository.close()


def test_spotify_access_token_refreshes_after_cached_lifetime(tmp_path) -> None:
    """Reuse the account access token until the one-minute expiry safety margin."""
    now = [5000.0]
    http = FakeSpotifyHttp()
    service, repository = _setup_service(tmp_path, http, clock=lambda: now[0])
    http.playback_response = {
        "is_playing": True,
        "progress_ms": 30000,
        "item": _sample_track("t1", "Track One", "Artist One", "Album One", "https://img.spotify.com/t1.jpg"),
    }

    try:
        service.playback("ticker-1")
        now[0] += 3539.0
        service.playback("ticker-1")
        assert http.refresh_calls == 1
        now[0] += 5.0
        service.playback("ticker-1")
        assert http.refresh_calls == 2
    finally:
        repository.close()


def test_spotify_unauthorized_cached_access_token_is_refreshed_on_next_poll(tmp_path) -> None:
    """Evict an access token rejected with HTTP 401 and refresh it at the next cadence."""
    now = [5500.0]
    http = FakeSpotifyHttp()
    service, repository = _setup_service(tmp_path, http, clock=lambda: now[0])
    http.playback_response = {
        "is_playing": True,
        "progress_ms": 30000,
        "item": _sample_track("t1", "Track One", "Artist One", "Album One", "https://img.spotify.com/t1.jpg"),
    }

    try:
        service.playback("ticker-1")
        now[0] += 5.0
        http.playback_error = SpotifyIntegrationError(
            "Spotify returned HTTP 401",
            status_code=401,
        )
        with pytest.raises(SpotifyIntegrationError):
            service.playback("ticker-1")
        assert http.refresh_calls == 1
        assert service.status("ticker-1")["connected"] is True

        http.playback_error = None
        now[0] += 14.0
        with pytest.raises(SpotifyIntegrationError):
            service.playback("ticker-1")
        assert http.refresh_calls == 1
        now[0] += 1.0
        service.playback("ticker-1")
        assert http.refresh_calls == 2
    finally:
        repository.close()


@pytest.mark.parametrize("previous_success", (False, True))
def test_spotify_transient_error_waits_for_retry_with_or_without_cached_playback(tmp_path, previous_success) -> None:
    """Retain failed health and skip upstream calls until the transient retry deadline."""
    now = [8000.0]
    http = FakeSpotifyHttp()
    service, repository = _setup_service(tmp_path, http, clock=lambda: now[0])
    http.playback_response = {
        "is_playing": True, "progress_ms": 30000,
        "item": _sample_track("t1", "Track One", "Artist One", "Album One", "https://img.spotify.com/t1.jpg"),
    }
    try:
        if previous_success:
            service.playback("ticker-1")
            now[0] += 1.0
        http.playback_error = SpotifyIntegrationError("Spotify returned HTTP 503", status_code=503)
        with pytest.raises(SpotifyIntegrationError):
            service.playback("ticker-1")
        calls = http.playback_calls
        retry_at = now[0] + 15.0
        http.playback_error = None
        now[0] = retry_at - 0.1
        with pytest.raises(SpotifyIntegrationError):
            service.playback("ticker-1")
        assert http.playback_calls == calls
        now[0] = retry_at
        assert service.playback("ticker-1")["name"] == "Track One"
        assert http.playback_calls == calls + 1
    finally:
        repository.close()


def test_spotify_playback_cadence_is_shared_by_tickers_in_one_group(tmp_path) -> None:
    """Reuse one account's fresh playback result across every ticker in its group."""
    now = [4000.0]
    http = FakeSpotifyHttp()
    service, repository = _setup_service(
        tmp_path,
        http,
        clock=lambda: now[0],
        group_id="cg_shared",
    )
    repository.create_ticker(
        "ticker-one",
        pairing=PairingState(controller_group_id="cg_shared", paired=True),
    )
    repository.create_ticker(
        "ticker-two",
        pairing=PairingState(controller_group_id="cg_shared", paired=True),
    )
    http.playback_response = {
        "is_playing": True,
        "progress_ms": 30000,
        "item": _sample_track("t1", "Track One", "Artist One", "Album One", "https://img.spotify.com/t1.jpg"),
    }

    try:
        assert service.playback("ticker-one")["name"] == "Track One"
        assert service.playback("ticker-two")["name"] == "Track One"
        assert http.playback_calls == 1
        assert http.refresh_calls == 1
    finally:
        repository.close()


def test_spotify_http_error_exposes_retry_after_header(monkeypatch) -> None:
    """Carry Spotify's HTTP Retry-After response into the integration error."""
    response_error = HTTPError(
        "https://api.spotify.com/v1/me/player",
        429,
        "Too Many Requests",
        {"Retry-After": "47"},
        BytesIO(b'{"error":{"message":"Too many requests"}}'),
    )

    def fail_request(*args, **kwargs):
        raise response_error

    monkeypatch.setattr(spotify_module, "urlopen", fail_request)
    with pytest.raises(SpotifyIntegrationError) as error:
        spotify_module.UrllibSpotifyHttpClient._json(spotify_module.Request("https://example.com"))

    assert error.value.status_code == 429
    assert error.value.retry_after == 47.0


def test_spotify_retries_failed_queue_fetch_for_the_same_track(tmp_path) -> None:
    """Retry a failed queue read while avoiding repeated reads of a valid empty queue."""
    now = [6000.0]
    http = FakeSpotifyHttp()
    http.queue_raises = True
    service, repository = _setup_service(tmp_path, http, clock=lambda: now[0])
    http.playback_response = {
        "is_playing": True,
        "progress_ms": 30000,
        "item": _sample_track("t1", "Track One", "Artist One", "Album One", "https://img.spotify.com/t1.jpg"),
    }

    try:
        first = service.playback("ticker-1")
        assert first["next_songs"] == []
        assert http.queue_calls == 1
        http.queue_raises = False
        http.queue_response = {"queue": [
            _sample_track("t2", "Track Two", "Artist Two", "Album Two", "https://img.spotify.com/t2.jpg"),
        ]}
        now[0] += 5.0
        retried = service.playback("ticker-1")
        assert retried["next_songs"][0]["name"] == "Track Two"
        assert http.queue_calls == 2
    finally:
        repository.close()


def test_spotify_reauthorization_clears_playback_window_and_cadence(tmp_path) -> None:
    """Use a fresh upstream track immediately after linking the same account again."""
    now = [7000.0]
    http = FakeSpotifyHttp()
    service, repository = _setup_service(tmp_path, http, clock=lambda: now[0])
    http.playback_response = {
        "is_playing": True,
        "progress_ms": 30000,
        "item": _sample_track("t1", "Track One", "Artist One", "Album One", "https://img.spotify.com/t1.jpg"),
    }

    try:
        assert service.playback("ticker-1")["id"] == "spotify:t1"
        repository.create_ticker("ticker-1")
        authorization = service.begin_authorization("ticker-1")
        state = parse_qs(urlparse(authorization["authorization_url"]).query)["state"][0]
        service.complete_authorization("fake-code", state)
        http.playback_response = {
            "is_playing": True,
            "progress_ms": 1000,
            "item": _sample_track("t2", "Track Two", "Artist Two", "Album Two", "https://img.spotify.com/t2.jpg"),
        }

        refreshed = service.playback("ticker-1")
        assert refreshed["id"] == "spotify:t2"
        assert refreshed["last_song"] is None
        assert http.refresh_calls == 2
        assert http.playback_calls == 2
    finally:
        repository.close()


def test_spotify_shared_group_poll_uses_single_flight(tmp_path) -> None:
    """Allow one concurrent upstream playback and queue read for a shared account."""
    class BlockingSpotifyHttp(FakeSpotifyHttp):
        def __init__(self) -> None:
            super().__init__()
            self.first_started = Event()
            self.second_started = Event()
            self.release_first = Event()

        def get_playback(self, access_token: str) -> Mapping[str, Any] | None:
            self.playback_calls += 1
            if self.playback_calls == 1:
                self.first_started.set()
                assert self.release_first.wait(timeout=3.0)
            else:
                self.second_started.set()
            return self.playback_response

    now = [8000.0]
    http = BlockingSpotifyHttp()
    service, repository = _setup_service(
        tmp_path,
        http,
        clock=lambda: now[0],
        group_id="cg_shared",
    )
    repository.create_ticker(
        "ticker-one",
        pairing=PairingState(controller_group_id="cg_shared", paired=True),
    )
    repository.create_ticker(
        "ticker-two",
        pairing=PairingState(controller_group_id="cg_shared", paired=True),
    )
    http.playback_response = {
        "is_playing": True,
        "progress_ms": 30000,
        "item": _sample_track("t1", "Track One", "Artist One", "Album One", "https://img.spotify.com/t1.jpg"),
    }

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(service.playback, "ticker-one")
            assert http.first_started.wait(timeout=3.0)
            second = executor.submit(service.playback, "ticker-two")
            assert not http.second_started.wait(timeout=0.1)
            http.release_first.set()
            assert first.result(timeout=3.0)["name"] == "Track One"
            assert second.result(timeout=3.0)["name"] == "Track One"
        assert http.playback_calls == 1
        assert http.queue_calls == 1
        assert http.refresh_calls == 1
    finally:
        http.release_first.set()
        repository.close()
