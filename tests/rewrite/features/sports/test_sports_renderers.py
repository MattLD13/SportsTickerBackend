"""Exercise the independent sports renderer family."""

from __future__ import annotations

from PIL import Image
from datetime import datetime, timezone

import pytest
from ticker_core.context import RenderContext
from ticker_core.features.alerts import NewsBannerRenderer, ScoreAlertRenderer
from ticker_core.features.sports import SportsRenderer
from ticker_core.rendering import ContentScene, load_default_font_set


class EmptyLogos:
    """Provide deterministic missing logos for renderer tests."""

    def get(self, url: str | None, size: tuple[int, int]) -> Image.Image | None:
        """Return no logo."""
        return None


@pytest.fixture
def sports() -> SportsRenderer:
    """Create a renderer with deterministic resources."""
    return SportsRenderer(load_default_font_set(), EmptyLogos())


def test_scoreboard_is_deterministic_and_32_pixels_high(sports: SportsRenderer) -> None:
    """Keep representative scoreboard rendering deterministic."""
    from ticker_controller.stadium import StadiumRenderer

    game = {"sport": "baseball", "state": "in", "status": "Top 5th", "away_score": 2, "home_score": 1, "situation": {"onFirst": True, "outs": 1}}
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    first = sports.render(context, ContentScene(item=game, mode="sports")).image
    second, _ = StadiumRenderer().render(game)
    assert first.height == 32
    assert first.tobytes() == second.convert("RGB").tobytes()


@pytest.mark.parametrize(
    ("status", "situation"),
    [
        ("Top 9th", {"onFirst": True, "onSecond": False, "onThird": True, "balls": 3, "strikes": 2, "outs": 2}),
        ("Bottom 3rd", {"onFirst": False, "onSecond": True, "onThird": False, "balls": 1, "strikes": 0, "outs": 0}),
        ("Mid 7th", {"onFirst": True, "onSecond": True, "onThird": True, "balls": 0, "strikes": 0, "outs": 2}),
        ("Rain Delay", {"onFirst": False, "onSecond": False, "onThird": False, "balls": 0, "strikes": 0, "outs": 0}),
    ],
)
def test_baseball_compact_and_full_paths_match_legacy_oracle(
    sports: SportsRenderer,
    status: str,
    situation: dict[str, object],
) -> None:
    """Keep active, break, and delayed baseball layouts pixel-identical."""
    from ticker_controller.controller import TickerStreamer
    from ticker_controller.stadium import StadiumRenderer

    game = {
        "sport": "mlb",
        "state": "in",
        "status": status,
        "away_score": 4,
        "home_score": 3,
        "away_color": "#0C2340",
        "home_color": "#BD3039",
        "away_abbr": "NYY",
        "home_abbr": "BOS",
        "situation": situation,
    }
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    legacy_compact, _ = StadiumRenderer().render(game)
    assert sports.render(context, ContentScene(item=game, mode="sports")).image.tobytes() == legacy_compact.convert("RGB").tobytes()

    fonts = load_default_font_set()
    legacy_full = object.__new__(TickerStreamer)
    for target, source in {
        "big_font": "big",
        "clock_giant": "clock",
        "tiny": "tiny",
        "tiny_small": "tiny_small",
        "micro": "micro",
        "font": "normal",
    }.items():
        setattr(legacy_full, target, getattr(fonts, source))
    legacy_full.get_logo = lambda url, size: None
    for name in (
        "get_team_color",
        "draw_outlined_text",
        "shorten_status",
        "_parse_hex_color",
        "_is_near_black",
        "_is_near_white",
        "_resolve_challenge_strip_color",
        "draw_bat",
        "_draw_side_scrims",
        "_draw_baseball_diamond",
    ):
        setattr(legacy_full, name, getattr(TickerStreamer, name).__get__(legacy_full, TickerStreamer))
    assert sports.render_full(game).tobytes() == legacy_full.draw_sport_full_bleed(game).convert("RGB").tobytes()


def test_full_card_keeps_panel_geometry(sports: SportsRenderer) -> None:
    """Keep representative full-screen rendering at the panel size."""
    from ticker_controller.controller import TickerStreamer

    game = {"sport": "football", "state": "in", "status": "Q2 10:00", "away_score": 7, "home_score": 3, "away_color": "#00338D", "home_color": "#D50A0A", "situation": {}}
    fonts = load_default_font_set()
    legacy = object.__new__(TickerStreamer)
    legacy.big_font = fonts.big
    legacy.clock_giant = fonts.clock
    legacy.tiny = fonts.tiny
    legacy.tiny_small = fonts.tiny_small
    legacy.micro = fonts.micro
    legacy.font = fonts.normal
    legacy.get_logo = lambda url, size: None
    for name in ("get_team_color", "draw_outlined_text", "shorten_status", "_parse_hex_color", "_is_near_black", "_is_near_white", "_resolve_challenge_strip_color", "draw_bat"):
        setattr(legacy, name, getattr(TickerStreamer, name).__get__(legacy, TickerStreamer))
    image = sports.render_full(game)
    assert image.size == (384, 32)
    assert image.tobytes() == legacy.draw_sport_full_bleed(game).convert("RGB").tobytes()


def test_score_alert_uses_full_panel_and_is_deterministic() -> None:
    """Keep score takeovers stable for one elapsed time."""
    from ticker_controller.controller import TickerStreamer

    renderer = ScoreAlertRenderer(load_default_font_set(), EmptyLogos())
    alert = {"team_abbr": "AAA", "team_color": "#006341", "away_abbr": "AAA", "home_abbr": "AAA", "away_score": 2, "home_score": 1, "headline": "GOAL"}
    first = renderer.render(alert, 1.0)
    fonts = load_default_font_set()
    legacy = object.__new__(TickerStreamer)
    legacy.medium_font = fonts.medium
    legacy.get_logo = lambda url, size: None
    for name in ("_parse_hex_color", "_is_near_black", "_is_near_white", "_logo_nonblack_dominant_colors", "draw_outlined_text", "shorten_status"):
        setattr(legacy, name, getattr(TickerStreamer, name).__get__(legacy, TickerStreamer))
    second = legacy.draw_score_alert(alert, 1.0)
    assert first.size == (384, 32)
    assert first.tobytes() == second.tobytes()


def test_news_banner_keeps_live_frame_geometry() -> None:
    """Keep news overlay output at the panel size."""
    from ticker_controller.modes.news_banner import NewsBannerMixin

    renderer = NewsBannerRenderer(load_default_font_set())
    frame = Image.new("RGB", (384, 32), (0, 0, 0))
    item = {"kind": "TRADE", "from_abbr": "VAN", "to_abbr": "NYR", "text": "Miller for Kakko"}
    assert renderer.render(item).size == (192, 32)
    legacy = NewsBannerMixin()
    assert renderer.apply(frame, item, 1.0).tobytes() == legacy.apply_news_banner(frame, item, 1.0).tobytes()
