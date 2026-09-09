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
    game = {"sport": "baseball", "state": "in", "status": "Top 5th", "away_score": 2, "home_score": 1, "situation": {"onFirst": True, "outs": 1}}
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    first = sports.render(context, ContentScene(item=game, mode="sports")).image
    second = sports.render(context, ContentScene(item=game, mode="sports")).image
    assert first.height == 32
    assert first.tobytes() == second.tobytes()


def test_fan_duel_joke_ad_renders_as_a_compact_scroll_card(sports: SportsRenderer) -> None:
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    item = {
        "type": "fan_duel_joke_ad",
        "sport": "sports",
        "headline": "FAN DUAL",
        "tagline": "ODDS? JUST SCORES.",
        "detail": "PARODY / NO BETS",
        "background": "#101c2a",
        "accent": "#18d26e",
    }

    image = sports.render(context, ContentScene(item=item, mode="sports")).image

    assert image.size == (174, 32)
    assert image.getbbox() == (0, 0, 174, 32)
    assert image.tobytes() == sports.render(context, ContentScene(item=item, mode="sports")).image.tobytes()


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
    """Keep active, break, and delayed baseball layouts deterministic."""

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
    compact = sports.render(context, ContentScene(item=game, mode="sports")).image
    compact_repeat = sports.render(context, ContentScene(item=game, mode="sports")).image
    full = sports.render_full(game)
    full_repeat = sports.render_full(game)
    assert compact.tobytes() == compact_repeat.tobytes()
    assert full.size == (384, 32)
    assert full.tobytes() == full_repeat.tobytes()


def test_full_card_keeps_panel_geometry(sports: SportsRenderer) -> None:
    """Keep representative full-screen rendering at the panel size."""
    game = {"sport": "football", "state": "in", "status": "Q2 10:00", "away_score": 7, "home_score": 3, "away_color": "#00338D", "home_color": "#D50A0A", "situation": {}}
    image = sports.render_full(game)
    assert image.size == (384, 32)
    assert image.tobytes() == sports.render_full(game).tobytes()


def test_full_baseball_renders_live_details_and_scales_long_names(sports: SportsRenderer) -> None:
    """Keep MLB live detail fields visible and shrink oversized player names."""
    calls: list[tuple[str, int | None]] = []
    original = sports._full.draw_outlined_text

    def capture(draw, x, y, text, font, fill, outline, anchor="mm"):
        calls.append((str(text), getattr(font, "size", None)))
        return original(draw, x, y, text, font, fill, outline, anchor)

    sports._full.draw_outlined_text = capture
    image = sports.render_full(
        {
            "sport": "mlb",
            "state": "in",
            "status": "Top 9th",
            "away_score": 3,
            "home_score": 2,
            "away_abbr": "CHC",
            "home_abbr": "MIA",
            "away_color": "#0e3386",
            "home_color": "#ff6600",
            "situation": {
                "batter_name": "John Longlastnamehere",
                "batter_avg": ".285",
                "batter_h": "2",
                "batter_ab": "4",
                "pitcher_name": "Edward Cabrera",
                "pitcher_pitches": 73,
                "last_pitch_speed": 97,
                "last_pitch_type_full": "Slider",
            },
        }
    )

    assert image.size == (384, 32)
    assert ("2/4", 8) in calls
    assert (".285", 8) in calls
    assert ("P:73", 8) in calls
    assert ("97 Slider", 8) in calls
    assert any(text.startswith("LONG") for text, _ in calls)


def test_full_baseball_preserves_zero_stats_and_pitcher_era(sports: SportsRenderer) -> None:
    calls: list[str] = []
    original = sports._full.draw_outlined_text

    def capture(draw, x, y, text, font, fill, outline, anchor="mm"):
        calls.append(str(text))
        return original(draw, x, y, text, font, fill, outline, anchor)

    sports._full.draw_outlined_text = capture
    image = sports.render_full(
        {
            "sport": "mlb",
            "state": "in",
            "status": "Top 5th",
            "away_score": 2,
            "home_score": 1,
            "away_abbr": "NYY",
            "home_abbr": "BOS",
            "situation": {
                "batter_name": "Coby Mayo",
                "batter_h": 0,
                "batter_ab": 0,
                "batter_avg": ".224",
                "pitcher_name": "Grant Wolfram",
                "pitcher_pitches": 0,
                "pitcher_era": "4.96",
            },
        }
    )

    assert image.size == (384, 32)
    assert "0/0" in calls
    assert "P:0" in calls
    assert "ERA:4.96" in calls


def test_full_baseball_draws_abs_challenge_markers_from_situation(sports: SportsRenderer) -> None:
    image = sports.render_full(
        {
            "sport": "mlb",
            "state": "in",
            "status": "Top 5th",
            "away_abbr": "NYY",
            "home_abbr": "BOS",
            "away_score": 2,
            "home_score": 1,
            "away_color": "#654321",
            "home_color": "#123456",
            "situation": {
                "activeTeam": "NYY",
                "away_challenges": 1,
                "away_challenges_used": 1,
                "home_challenges": 2,
                "home_challenges_used": 0,
            },
        }
    )

    assert image.getpixel((1, 5)) == (0, 0, 0)
    assert image.getpixel((382, 5)) == (18, 52, 86)


def test_full_baseball_draws_second_abs_challenge_marker(sports: SportsRenderer) -> None:
    image = sports.render_full(
        {
            "sport": "mlb",
            "state": "in",
            "status": "Top 5th",
            "away_abbr": "NYY",
            "home_abbr": "BOS",
            "away_score": 2,
            "home_score": 1,
            "away_color": "#654321",
            "home_color": "#123456",
            "situation": {
                "away_challenges": 0,
                "away_challenges_used": 2,
                "home_challenges": 1,
                "home_challenges_used": 1,
            },
        }
    )

    assert image.getpixel((1, 5)) == (0, 0, 0)
    assert image.getpixel((1, 25)) == (0, 0, 0)
    assert image.getpixel((382, 5)) == (0, 0, 0)


def test_score_alert_uses_full_panel_and_is_deterministic() -> None:
    """Keep score takeovers stable for one elapsed time."""
    renderer = ScoreAlertRenderer(load_default_font_set(), EmptyLogos())
    alert = {"team_abbr": "AAA", "team_color": "#006341", "away_abbr": "AAA", "home_abbr": "AAA", "away_score": 2, "home_score": 1, "headline": "GOAL"}
    first = renderer.render(alert, 1.0)
    second = renderer.render(alert, 1.0)
    assert first.size == (384, 32)
    assert first.tobytes() == second.tobytes()


def test_news_banner_keeps_live_frame_geometry() -> None:
    """Keep news overlay output at the panel size."""
    renderer = NewsBannerRenderer(load_default_font_set())
    frame = Image.new("RGB", (384, 32), (0, 0, 0))
    item = {"kind": "TRADE", "from_abbr": "VAN", "to_abbr": "NYR", "text": "Miller for Kakko"}
    assert renderer.render(item).size == (192, 32)
    first = renderer.apply(frame, item, 1.0)
    second = renderer.apply(frame, item, 1.0)
    assert first.size == (384, 32)
    assert first.tobytes() == second.tobytes()
