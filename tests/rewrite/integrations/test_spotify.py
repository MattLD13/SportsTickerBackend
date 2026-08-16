"""Test Spotify integration caching, queueing, and resilience."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from cryptography.fernet import Fernet
from PIL import Image

from sports_ticker.domain import DisplaySettings
from sports_ticker.fleet import SpotifyConnection, TickerRepository
from sports_ticker.integrations.spotify import (
    SpotifyConfig,
    SpotifyHttpPort,
    SpotifyIntegrationService,
    SpotifyMusicSource,
)
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

    def exchange_code(self, code: str, config: SpotifyConfig, verifier: str) -> Mapping[str, Any]:
        return {"access_token": "fake-access", "refresh_token": "fake-refresh"}

    def refresh_access_token(self, refresh_token: str, config: SpotifyConfig) -> Mapping[str, Any]:
        return {"access_token": "fake-access", "refresh_token": refresh_token}

    def get_current_user(self, access_token: str) -> Mapping[str, Any]:
        return {"id": "user-1", "display_name": "Test User"}

    def get_playback(self, access_token: str) -> Mapping[str, Any] | None:
        return self.playback_response

    def get_queue(self, access_token: str) -> Mapping[str, Any] | None:
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


def _setup_service(tmp_path, http: FakeSpotifyHttp) -> tuple[SpotifyIntegrationService, TickerRepository]:
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
        ticker_id="ticker-1",
        spotify_account_id="user-1",
        display_name="Test User",
        scopes=("user-read-playback-state",),
        refresh_token_ciphertext=cipher.encrypt(b"refresh-token-1").decode("ascii"),
        status="connected",
        priority=True,
    )
    repository.save_group_spotify_connection("ticker:ticker-1", connection)
    service = SpotifyIntegrationService(repository, config, http=http)
    return service, repository


def test_spotify_playback_caches_last_played_and_next_three_songs(tmp_path) -> None:
    """Retain the previous song and next three queue songs across track transitions."""
    http = FakeSpotifyHttp()
    service, repository = _setup_service(tmp_path, http)

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

        second_read = service.playback("ticker-1")
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
    service, repository = _setup_service(tmp_path, http)

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

