"""Compare deterministic rewrite frames against deployed renderer frames."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from PIL import Image

from ticker_core.context import RenderContext
from ticker_core.features.alerts import NewsBannerRenderer, ScoreAlertRenderer
from ticker_core.features.flight import FlightRenderer
from ticker_core.features.music import MusicAnimationState, MusicRenderer
from ticker_core.features.utility import UtilityRenderer
from ticker_core.features.weather import WeatherRenderer
from ticker_core.rendering import load_default_font_set


class EmptyLogos:
    """Provide no images for deterministic parity frames."""

    def get(self, value: object, size: tuple[int, int]) -> Image.Image | None:
        """Return no image."""
        del value, size
        return None


def changed_pixels(left: Image.Image, right: Image.Image) -> int:
    """Count pixels that differ after one common color conversion."""
    first = left.convert("RGBA")
    second = right.convert("RGBA")
    return sum(a != b for a, b in zip(first.getdata(), second.getdata()))


def test_non_sports_and_overlay_oracle_campaign(monkeypatch) -> None:
    """Keep ported panels equal and make weather drift visible."""
    from ticker_controller.controller import TickerStreamer
    from ticker_controller.modes.flight import FlightMixin
    from ticker_controller.modes.misc import MiscMixin
    from ticker_controller.modes.music import MusicMixin
    from ticker_controller.modes.news_banner import NewsBannerMixin
    from ticker_controller.modes.weather import WeatherMixin

    now = datetime(2026, 8, 11, 14, 30, 15)
    timestamp = now.timestamp()
    context = RenderContext(now)
    fonts = load_default_font_set()
    utility = UtilityRenderer(fonts, EmptyLogos())
    weather = WeatherRenderer(fonts)
    music = MusicRenderer(fonts, EmptyLogos())
    flight = FlightRenderer(fonts, EmptyLogos())
    deltas: dict[str, int] = {}

    clock = SimpleNamespace(now=lambda: now)
    monkeypatch.setattr("ticker_controller.modes.misc.datetime", clock)
    monkeypatch.setattr("ticker_controller.modes.misc.time.time", lambda: timestamp)
    system = SimpleNamespace(
        font=fonts.normal,
        big_font=fonts.big,
        huge_font=fonts.huge,
        clock_giant=fonts.clock,
        tiny=fonts.tiny,
        medium_font=fonts.medium,
        pairing_code="123456",
        get_logo=EmptyLogos().get,
    )
    system.draw_arrow = TickerStreamer.draw_arrow.__get__(system, TickerStreamer)
    deltas["pairing"] = changed_pixels(TickerStreamer.draw_pairing_screen(system), utility.pairing(context, "123456"))
    deltas["update"] = changed_pixels(MiscMixin.draw_update_screen(system, "Pulling", 0.5, "r100"), utility.update(context, "Pulling", 0.5, "r100"))
    deltas["offline"] = changed_pixels(MiscMixin.draw_offline_screen(system, 125), utility.offline(context, 125))
    deltas["empty"] = changed_pixels(MiscMixin.draw_no_games_screen(system), utility.empty(context))
    stock = {"home_abbr": "ACME", "home_score": "12.34", "away_score": "-1.2%", "situation": {"change": "-0.15"}}
    deltas["stock_down"] = changed_pixels(MiscMixin.draw_stock_card(system, stock), utility.stock(stock))
    leaderboard = {"sport": "f1", "tourney_name": "Monaco Grand Prix", "leaders": [{"name": "VER", "score": "LEADER"}, {"name": "LEC", "score": "+2"}]}
    deltas["leaderboard"] = changed_pixels(MiscMixin.draw_leaderboard_card(system, leaderboard), utility.leaderboard(leaderboard))

    monkeypatch.setattr("ticker_controller.modes.weather.datetime", clock)
    monkeypatch.setattr("ticker_controller.modes.weather.time.time", lambda: timestamp)
    legacy_weather = SimpleNamespace(big_font=fonts.big, tiny=fonts.tiny)
    legacy_weather.get_aqi_color = WeatherMixin.get_aqi_color.__get__(legacy_weather, WeatherMixin)
    legacy_weather.draw_weather_pixel_art = WeatherMixin.draw_weather_pixel_art.__get__(legacy_weather, WeatherMixin)
    weather_item = {"home_abbr": "72", "away_abbr": "Boston", "status": "RAIN", "situation": {"icon": "rain", "is_day": 1, "stats": {"feels": "70", "wind": "4", "humidity": "85", "aqi": "41"}, "forecast": [{"day": "Tue", "icon": "rain", "high": "72", "low": "61"}, {"day": "Wed", "icon": "cloud", "high": "69", "low": "58"}]}}
    deltas["weather_rain"] = changed_pixels(WeatherMixin.draw_weather_detailed(legacy_weather, weather_item), weather.detailed(context, weather_item))

    monkeypatch.setattr("ticker_controller.modes.music.time.time", lambda: timestamp)
    legacy_music = SimpleNamespace(VINYL_SIZE=51, COVER_SIZE=42, vinyl_mask=music._mask, scratch_layer=music._scratch, vinyl_rotation=0.0, text_scroll_pos=0.0, last_frame_time=timestamp, dominant_color=(29, 185, 84), spindle_color="black", last_cover_url="", vinyl_cache=None, prev_vinyl_cache=None, prev_dominant_color=(29, 185, 84), fade_alpha=1.0, transitioning_out=False, viz_heights=[2.0] * 16, viz_phase=list(music._phase), medium_font=fonts.medium, tiny=fonts.tiny, get_logo=EmptyLogos().get)
    legacy_music.draw_scrolling_text = MusicMixin.draw_scrolling_text.__get__(legacy_music, MusicMixin)
    legacy_music.render_visualizer = MusicMixin.render_visualizer.__get__(legacy_music, MusicMixin)
    music_item = {"home_abbr": "Artist", "away_abbr": "Song", "situation": {"is_playing": True, "progress": 10, "duration": 240, "fetch_ts": timestamp}}
    actual_music, _ = music.render_with_state(context, music_item, MusicAnimationState(previous_time=timestamp))
    noise = iter(0.5 + (index % 5) * 0.175 for index in range(16))
    monkeypatch.setattr("ticker_controller.modes.music.random.uniform", lambda low, high: next(noise))
    deltas["music_playing"] = changed_pixels(MusicMixin.draw_music_card(legacy_music, music_item), actual_music)

    legacy_flight = SimpleNamespace(C_RED=(255, 60, 60), C_GRN=(80, 255, 80), C_AMBER=(255, 170, 0), C_BLUE_TXT=(80, 180, 255), C_WHT=(220, 220, 230), C_GRY=(120, 120, 130), download_and_process_logo=lambda *args: None, get_logo=EmptyLogos().get)
    legacy_flight._pixel = FlightMixin._pixel.__get__(legacy_flight, FlightMixin)
    legacy_flight._icon_plane = FlightMixin._icon_plane.__get__(legacy_flight, FlightMixin)
    legacy_flight._flight_logo_url = FlightMixin._flight_logo_url.__get__(legacy_flight, FlightMixin)
    legacy_flight._airline_domain_for_code = FlightMixin._airline_domain_for_code
    visitor = {"type": "flight_visitor", "id": "UA12", "guest_name": "GUEST", "origin_city": "BOS", "dest_city": "ORD", "is_live": True, "progress": 50, "alt": 12000, "dist": 300, "speed": 500, "eta_str": "2:00"}
    deltas["flight_visitor"] = changed_pixels(FlightMixin.draw_flight_visitor(legacy_flight, visitor), flight.visitor(visitor))
    airport_weather = {"iata": "PDX", "city": "Portland", "away_abbr": "72", "status": "Cloudy"}
    arrivals = [{"away_abbr": "UA12", "other_iata": "ORD", "home_abbr": "Chicago", "altitude": 12000}]
    departures = [{"away_abbr": "DL7", "other_iata": "SEA", "home_abbr": "Seattle", "altitude": 0}]
    deltas["flight_airport"] = changed_pixels(FlightMixin.draw_flight_airport(legacy_flight, airport_weather, arrivals, departures), flight.airport(airport_weather, arrivals, departures))

    alert = {"team_abbr": "AAA", "team_color": "#006341", "away_abbr": "AAA", "home_abbr": "BBB", "away_score": 2, "home_score": 1, "headline": "GOAL"}
    legacy_alert = object.__new__(TickerStreamer)
    legacy_alert.medium_font = fonts.medium
    legacy_alert.get_logo = EmptyLogos().get
    for name in ("_parse_hex_color", "_is_near_black", "_is_near_white", "_logo_nonblack_dominant_colors", "draw_outlined_text", "shorten_status"):
        setattr(legacy_alert, name, getattr(TickerStreamer, name).__get__(legacy_alert, TickerStreamer))
    score = ScoreAlertRenderer(fonts, EmptyLogos())
    for elapsed in (0.2, 1.0, 3.9):
        expected = legacy_alert.draw_score_alert(alert, elapsed)
        actual = score.render(alert, elapsed)
        deltas[f"score_alert_{elapsed}"] = changed_pixels(expected, actual)
    news = {"kind": "TRADE", "from_abbr": "VAN", "to_abbr": "NYR", "text": "Miller for Kakko"}
    legacy_news = NewsBannerMixin()
    banner = NewsBannerRenderer(fonts)
    base = Image.new("RGB", (384, 32), (12, 34, 56))
    for elapsed in (0.1, 1.0, 6.9):
        deltas[f"news_{elapsed}"] = changed_pixels(legacy_news.apply_news_banner(base, news, elapsed), banner.apply(base, news, elapsed))

    assert deltas == {
        "pairing": 0, "update": 0, "offline": 0, "empty": 0,
        "stock_down": 0, "leaderboard": 0, "weather_rain": 0,
        "music_playing": 0, "flight_visitor": 0, "flight_airport": 0,
        "score_alert_0.2": 0, "score_alert_1.0": 0,
        "score_alert_3.9": 0, "news_0.1": 0, "news_1.0": 0,
        "news_6.9": 0,
    }
