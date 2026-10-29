"""Smoke test independent utility renderer families."""

from datetime import datetime


from ticker_core.ui.frame import RenderContext
from ticker_core.ui.cards.flight import FlightCard
from ticker_core.features.golf import GolfAnimationState, GolfRenderer
from ticker_core.ui.cards.music import MusicCard, MusicState
from ticker_core.features.utility import UtilityRenderer
from ticker_core.features.weather import WeatherRenderer
from ticker_core.ui import ContentScene, load_default_font_set


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


def test_clear_weather_uses_moon_at_night() -> None:
    """Render a lunar icon for clear night conditions and retain the sun by day."""
    context = RenderContext(datetime(2026, 8, 11, 14, 30, 15))
    fonts = load_default_font_set()
    weather = WeatherRenderer(fonts)
    day = {"type": "weather", "home_abbr": "72", "away_abbr": "Boston", "status": "CLEAR", "situation": {"icon": "sun", "is_day": 1}}
    night = {"type": "weather", "home_abbr": "72", "away_abbr": "Boston", "status": "CLEAR", "situation": {"icon": "sun", "is_day": 0}}

    day_image = weather.detailed(context, day)
    night_image = weather.detailed(context, night)
    day_pixels = list(day_image.crop((0, 0, 24, 24)).getdata())
    night_pixels = list(night_image.crop((0, 0, 24, 24)).getdata())

    assert (255, 200, 0, 255) in day_pixels
    assert (255, 200, 0, 255) not in night_pixels
    assert (184, 184, 184, 255) in night_pixels

def test_media_and_flight_keep_explicit_animation_state() -> None:
    """Render representative media, golf, and flight panels."""
    fonts = load_default_font_set()
    first = RenderContext(datetime(2026, 8, 11, 14, 30, 15))
    second = RenderContext(datetime(2026, 8, 11, 14, 30, 16))
    music = MusicCard(fonts)
    image, state = music.frame(first.now, {"home_abbr": "Artist", "away_abbr": "Song", "situation": {"is_playing": True, "duration": 240, "fetch_ts": first.now.timestamp()}}, MusicState())
    later, next_state = music.frame(second.now, {"home_abbr": "Artist", "away_abbr": "Song", "situation": {"is_playing": True, "duration": 240, "fetch_ts": first.now.timestamp()}}, state)
    golf, golf_state = GolfRenderer(fonts).full(first, {"golf": {"players": [{"name": "A Player", "total": -1, "holes": [4] * 18, "thru": 18}]}}, GolfAnimationState())
    flight = FlightCard(fonts).visitor({"type": "flight_visitor", "id": "UA12", "guest_name": "Guest", "origin_city": "BOS", "dest_city": "ORD", "is_live": True, "progress": 50})
    assert image.height == later.height == golf.height == flight.height == 32
    assert next_state.rotation != state.rotation
    assert golf_state.pair == 0


def test_system_status_panels_render_at_matrix_size() -> None:
    """Render current pairing, offline, and empty states at panel size."""
    context = RenderContext(datetime(2026, 8, 11, 14, 30, 15))
    utility = UtilityRenderer(load_default_font_set())

    for image in (
        utility.pairing(context, "123456"),
        utility.offline(context, 125),
        utility.empty(context),
    ):
        assert image.size == (384, 32)
        assert len(set(image.getdata())) > 1