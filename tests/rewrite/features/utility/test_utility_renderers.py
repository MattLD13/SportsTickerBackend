"""Smoke test independent utility renderer families."""

from datetime import datetime
from ticker_core.context import RenderContext
from ticker_core.features.flight import FlightRenderer
from ticker_core.features.golf import GolfAnimationState, GolfRenderer
from ticker_core.features.music import MusicAnimationState, MusicRenderer
from ticker_core.features.utility import UtilityRenderer
from ticker_core.features.weather import WeatherRenderer
from ticker_core.rendering import ContentScene, load_default_font_set


def test_utility_and_weather_render_deterministically() -> None:
    """Render deterministic status and weather frames."""
    context = RenderContext(datetime(2026, 8, 11, 14, 30, 15))
    fonts = load_default_font_set()
    utility = UtilityRenderer(fonts)
    weather = WeatherRenderer(fonts)
    stock = utility.render(context, ContentScene({"type": "stock_ticker", "home_abbr": "ACME", "home_score": "12.34", "away_score": "1.2%"}, "sports"))
    forecast = weather.detailed(context, {"type": "weather", "home_abbr": "72", "away_abbr": "Boston", "situation": {"icon": "rain", "stats": {"aqi": "41"}}})
    assert stock.image.size == (128, 32)
    assert forecast.size == (384, 32)
    assert forecast.tobytes() == weather.detailed(context, {"type": "weather", "home_abbr": "72", "away_abbr": "Boston", "situation": {"icon": "rain", "stats": {"aqi": "41"}}}).tobytes()


def test_no_games_panel_uses_clock_hierarchy_and_minute_progress() -> None:
    """Keep the no-games concept full width, deterministic, and clock-led."""
    utility = UtilityRenderer(load_default_font_set())
    first = utility.empty(RenderContext(datetime(2026, 8, 14, 13, 42, 17)))
    second = utility.empty(RenderContext(datetime(2026, 8, 14, 13, 42, 18)))

    assert first.size == (384, 32)
    assert first.tobytes() != second.tobytes()
    assert first.getpixel((0, 31)) == (198, 198, 204, 255)
    assert first.getpixel((383, 31)) == (42, 42, 48, 255)
    assert first.getpixel((213, 10)) == (48, 48, 54, 255)


def test_media_and_flight_keep_explicit_animation_state() -> None:
    """Render representative media, golf, and flight panels."""
    fonts = load_default_font_set()
    first = RenderContext(datetime(2026, 8, 11, 14, 30, 15))
    second = RenderContext(datetime(2026, 8, 11, 14, 30, 16))
    music = MusicRenderer(fonts)
    image, state = music.render_with_state(first, {"home_abbr": "Artist", "away_abbr": "Song", "situation": {"is_playing": True, "duration": 240, "fetch_ts": first.now.timestamp()}}, MusicAnimationState())
    later, next_state = music.render_with_state(second, {"home_abbr": "Artist", "away_abbr": "Song", "situation": {"is_playing": True, "duration": 240, "fetch_ts": first.now.timestamp()}}, state)
    golf, golf_state = GolfRenderer(fonts).full(first, {"golf": {"players": [{"name": "A Player", "total": -1, "holes": [4] * 18, "thru": 18}]}}, GolfAnimationState())
    flight = FlightRenderer(fonts).visitor({"type": "flight_visitor", "id": "UA12", "guest_name": "Guest", "origin_city": "BOS", "dest_city": "ORD", "is_live": True, "progress": 50})
    assert image.height == later.height == golf.height == flight.height == 32
    assert next_state.rotation != state.rotation
    assert golf_state.pair == 0
