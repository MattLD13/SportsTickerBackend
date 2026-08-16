"""Smoke test independent utility renderer families."""

from datetime import datetime
from ticker_core.context import RenderContext
from ticker_core.features.flight import FlightRenderer
from ticker_core.features.golf import GolfAnimationState, GolfRenderer
from ticker_core.features.music import MusicAnimationState, MusicRenderer
from ticker_core.features.utility import UtilityRenderer
from ticker_core.features.weather import WeatherRenderer
from ticker_core.rendering import ContentScene, load_default_font_set
from ticker_core.rendering.pixels import normalize_special_chars


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
    assert first.getpixel((60, 3)) == (0, 0, 0, 255)
    assert first.getpixel((0, 31)) == (198, 198, 204, 255)
    assert first.getpixel((383, 31)) == (42, 42, 48, 255)
    assert first.getpixel((196, 10)) == (48, 48, 54, 255)


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


def test_golf_names_use_led_safe_ascii() -> None:
    assert normalize_special_chars("Ludvig Åberg and Nicolai Højgaard") == "Ludvig Aberg and Nicolai Hojgaard"


def test_golf_renderer_transliterates_special_names() -> None:
    renderer = GolfRenderer(load_default_font_set())
    context = RenderContext(datetime(2026, 8, 14, 20, 50, 40))
    special = {"golf": {"players": [{"pos": "1", "name": "Ludvig Åberg", "total": -2, "holes": [4] * 18, "thru": 18}]}}
    ascii_name = {"golf": {"players": [{"pos": "1", "name": "Ludvig Aberg", "total": -2, "holes": [4] * 18, "thru": 18}]}}

    special_frame, _ = renderer.full(context, special, GolfAnimationState())
    ascii_frame, _ = renderer.full(context, ascii_name, GolfAnimationState())

    assert special_frame.tobytes() == ascii_frame.tobytes()


def test_golf_full_uses_pga_blue_page_dot_and_masters_green_palette() -> None:
    renderer = GolfRenderer(load_default_font_set())
    context = RenderContext(datetime(2026, 8, 14, 20, 50, 40))
    players = {"players": [{"pos": "1", "name": "A Player", "total": -1, "today": -1, "thru": 18, "holes": [4] * 18}]}
    pga, _ = renderer.full(context, {"golf": {"brand": "pga", **players}}, GolfAnimationState())
    masters, _ = renderer.full(context, {"golf": {"brand": "masters", **players}}, GolfAnimationState())

    assert pga.size == masters.size == (384, 32)
    assert pga.getpixel((0, 0)) == (0, 0, 0, 255)
    assert pga.getpixel((381, 1)) == (91, 171, 221, 255)
    assert masters.getpixel((0, 0)) == (0, 14, 8, 255)
    assert masters.getpixel((381, 1)) == (231, 199, 92, 255)


def test_golf_full_advances_the_five_page_leaderboard() -> None:
    renderer = GolfRenderer(load_default_font_set())
    first = RenderContext(datetime(2026, 8, 14, 20, 50, 40))
    later = RenderContext(datetime(2026, 8, 14, 20, 50, 45))
    players = [{"pos": str(index), "name": f"Player {index}", "total": -index, "today": -1, "thru": 18, "holes": [4] * 18} for index in range(1, 7)]
    item = {"golf": {"brand": "pga", "players": players}}

    _, state = renderer.full(first, item, GolfAnimationState())
    _, next_state = renderer.full(later, item, state)

    assert state.page == 1
    assert next_state.page == 2


def test_golf_pinned_scene_uses_exact_four_second_elapsed_pages() -> None:
    renderer = GolfRenderer(load_default_font_set())
    context = RenderContext(datetime(2026, 8, 14, 20, 50, 40))
    players = [
        {"pos": str(index), "name": f"Player {index}", "total": -index, "today": -1, "thru": 18, "holes": [4] * 18}
        for index in range(1, 10)
    ]
    item = {"type": "golf", "sport": "golf", "sports_presentation": "pinned", "golf": {"brand": "pga", "players": players}}

    first = renderer.render(context, ContentScene(item, "sports", 3.99)).image
    second = renderer.render(context, ContentScene(item, "sports", 4.0)).image
    same_page = renderer.render(context, ContentScene(item, "sports", 4.1)).image
    third = renderer.render(context, ContentScene(item, "sports", 8.0)).image

    assert first.tobytes() != second.tobytes()
    assert second.tobytes() == same_page.tobytes()
    assert second.tobytes() != third.tobytes()
