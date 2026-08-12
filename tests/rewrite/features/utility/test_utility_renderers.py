"""Smoke test independent utility renderer families."""

from datetime import datetime
from types import SimpleNamespace

from PIL import Image, ImageDraw

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


def test_representative_legacy_pixel_oracles(monkeypatch) -> None:
    """Keep selected replacement panels pixel-equal to deployed layouts."""
    from ticker_controller.controller import TickerStreamer
    from ticker_controller.modes.flight import FlightMixin
    from ticker_controller.modes.golf import GolfMixin
    from ticker_controller.modes.misc import MiscMixin
    from ticker_controller.modes.music import MusicMixin
    from ticker_controller.modes.weather import WeatherMixin

    fonts = load_default_font_set()
    now = datetime(2026, 8, 11, 14, 30, 15)
    context = RenderContext(now)
    clock = SimpleNamespace(now=lambda: now)
    monkeypatch.setattr("ticker_controller.modes.misc.datetime", clock)
    monkeypatch.setattr("ticker_controller.controller.time.time", lambda: now.timestamp())
    legacy_system = SimpleNamespace(font=fonts.normal, huge_font=fonts.huge, clock_giant=fonts.clock, tiny=fonts.tiny, pairing_code="123456")
    utility = UtilityRenderer(fonts)
    assert TickerStreamer.draw_pairing_screen(legacy_system).tobytes() == utility.pairing(context, "123456").tobytes()
    assert MiscMixin.draw_offline_screen(legacy_system, 125).tobytes() == utility.offline(context, 125).tobytes()
    assert MiscMixin.draw_no_games_screen(legacy_system).tobytes() == utility.empty(context).tobytes()

    legacy_weather = Image.new("RGBA", (384, 32), (0, 0, 0, 255))
    old_draw = ImageDraw.Draw(legacy_weather)
    WeatherMixin.draw_weather_pixel_art(SimpleNamespace(), old_draw, "cloud", 3, 11, t=now.timestamp())
    new_weather = Image.new("RGBA", (384, 32), (0, 0, 0, 255))
    WeatherRenderer(fonts)._icon(ImageDraw.Draw(new_weather), "cloud", 3, 11, now.timestamp())
    assert legacy_weather.tobytes() == new_weather.tobytes()

    music_time = SimpleNamespace(time=lambda: now.timestamp())
    monkeypatch.setattr("ticker_controller.modes.music.time", music_time)
    legacy_music = SimpleNamespace(
        VINYL_SIZE=51, COVER_SIZE=42, vinyl_mask=MusicRenderer(fonts)._mask,
        scratch_layer=MusicRenderer(fonts)._scratch, vinyl_rotation=0.0, text_scroll_pos=0.0,
        last_frame_time=now.timestamp(), dominant_color=(29, 185, 84), spindle_color="black",
        last_cover_url="", vinyl_cache=None, prev_vinyl_cache=None, prev_dominant_color=(29, 185, 84),
        fade_alpha=1.0, transitioning_out=False, viz_heights=[2.0] * 16, viz_phase=[0.0] * 16,
        medium_font=fonts.medium, tiny=fonts.tiny,
    )
    legacy_music.draw_scrolling_text = MusicMixin.draw_scrolling_text.__get__(legacy_music)
    legacy_music.render_visualizer = MusicMixin.render_visualizer.__get__(legacy_music)
    game = {"home_abbr": "ARTIST", "away_abbr": "SONG", "situation": {"is_playing": False, "progress": 10, "duration": 240, "fetch_ts": now.timestamp()}}
    expected_music = MusicMixin.draw_music_card(legacy_music, game)
    actual_music, _ = MusicRenderer(fonts).render_with_state(context, game, MusicAnimationState(previous_time=now.timestamp()))
    assert expected_music.tobytes() == actual_music.tobytes()

    legacy_flight = SimpleNamespace(C_RED=(255, 60, 60), C_GRN=(80, 255, 80), C_AMBER=(255, 170, 0), C_BLUE_TXT=(80, 180, 255), C_WHT=(220, 220, 230), C_GRY=(120, 120, 130), download_and_process_logo=lambda *args: None, get_logo=lambda *args: None)
    legacy_flight._pixel = FlightMixin._pixel.__get__(legacy_flight)
    legacy_flight._icon_plane = FlightMixin._icon_plane.__get__(legacy_flight)
    legacy_flight._flight_logo_url = FlightMixin._flight_logo_url.__get__(legacy_flight)
    legacy_flight._airline_domain_for_code = FlightMixin._airline_domain_for_code
    flight = {"type": "flight_visitor", "id": "123", "guest_name": "GUEST", "origin_city": "BOS", "dest_city": "ORD", "is_live": True, "progress": 50, "alt": 12000, "dist": 300, "speed": 500, "eta_str": "2:00"}
    assert FlightMixin.draw_flight_visitor(legacy_flight, flight).tobytes() == FlightRenderer(fonts).visitor(flight).tobytes()

    monkeypatch.setattr("ticker_controller.modes.golf.time.time", lambda: now.timestamp())
    legacy_golf = SimpleNamespace()
    legacy_golf._golf_colors = GolfMixin._golf_colors.__get__(legacy_golf)
    golf = {"away_color": "C8A84B", "away_alt_color": "004C35", "golf": {"event_name": "PGA TOUR", "year": "2026", "pars": [4] * 18, "players": [{"name": "Ada Player", "pos": "1", "total": -2, "today": -1, "thru": 18, "holes": [4] * 18}]}}
    assert GolfMixin.draw_golf_mode(legacy_golf, golf).tobytes() == GolfRenderer(fonts).full(context, golf, GolfAnimationState())[0].tobytes()
