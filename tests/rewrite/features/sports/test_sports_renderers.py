"""Exercise the independent sports renderer family."""

from __future__ import annotations

from PIL import Image, ImageDraw
from datetime import datetime, timezone

import pytest
from ticker_core.context import RenderContext
from ticker_core.features.alerts import NewsBannerRenderer, ScoreAlertRenderer
from ticker_core.features.sports import SportsRenderer
from ticker_core.features.sports import full_port as sports_full_port
from ticker_core.features.sports import stadium_port as sports_stadium_port
from ticker_core.features.sports.logo_badge import draw_missing_team_badge
from ticker_core.features.sports.logo_visibility import LogoOutlineMode, paste_team_logo
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


def test_campaign_ad_renders_as_a_compact_scroll_card(sports: SportsRenderer) -> None:
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    item = {
        "type": "fan_duel_joke_ad",
        "sport": "sports",
        "headline": "FANDUEL",
        "tagline": "HUNCHES",
        "detail": "PARODY",
        "style": "kick",
        "background": "#101c2a",
        "accent": "#18d26e",
    }

    image = sports.render(context, ContentScene(item=item, mode="sports")).image

    assert 112 <= image.width <= 160
    assert image.height == 32
    assert image.getbbox() == (0, 0, image.width, 32)
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


@pytest.mark.parametrize(
    ("background_color", "mark_color", "expected_outline"),
    [
        ((0, 0, 0, 255), (0, 0, 0, 255), (244, 247, 250)),
        ((0, 0, 0, 255), (0, 0, 8, 255), (244, 247, 250)),
        ((255, 255, 255, 255), (255, 255, 255, 255), (8, 12, 18)),
    ],
)
def test_team_logo_gets_adaptive_keyline_when_mark_blends_into_background(
    background_color: tuple[int, int, int, int],
    mark_color: tuple[int, int, int, int],
    expected_outline: tuple[int, int, int],
) -> None:
    canvas = Image.new("RGBA", (18, 18), background_color)
    logo = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    for y in range(2, 6):
        for x in range(2, 6):
            logo.putpixel((x, y), mark_color)

    assert paste_team_logo(canvas, logo, (5, 5)) is True
    assert canvas.getpixel((6, 8))[:3] == expected_outline
    assert canvas.getpixel((8, 8))[:3] == mark_color[:3]


def test_nyg_logo_color_stays_unoutlined_on_its_blue_background() -> None:
    canvas = Image.new("RGBA", (24, 24), (11, 34, 101, 255))
    logo = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
    ImageDraw.Draw(logo).polygon(
        ((4, 4), (12, 2), (20, 5), (19, 18), (12, 22), (4, 18)),
        fill=(0, 29, 103, 255),
    )

    assert paste_team_logo(canvas, logo, (0, 0)) is False


def test_team_logo_keeps_high_contrast_mark_unoutlined() -> None:
    canvas = Image.new("RGBA", (18, 18), (0, 0, 0, 255))
    logo = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    for y in range(2, 6):
        for x in range(2, 6):
            logo.putpixel((x, y), (255, 255, 255, 255))

    assert paste_team_logo(canvas, logo, (5, 5)) is False
    assert canvas.getpixel((6, 8))[:3] == (0, 0, 0)


def test_team_logo_keeps_visible_color_without_an_unneeded_keyline() -> None:
    canvas = Image.new("RGBA", (18, 18), (0, 0, 0, 255))
    logo = Image.new("RGBA", (10, 8), (0, 0, 0, 255))
    for y in range(8):
        for x in range(2, 6):
            logo.putpixel((x, y), (230, 20, 40, 255))

    assert paste_team_logo(canvas, logo, (4, 5)) is False


def test_team_logo_keeps_distinct_team_color_without_a_keyline() -> None:
    canvas = Image.new("RGBA", (18, 18), (15, 90, 35, 255))
    logo = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    for y in range(2, 6):
        for x in range(2, 6):
            logo.putpixel((x, y), (20, 72, 155, 255))

    assert paste_team_logo(canvas, logo, (5, 5)) is False


def test_crimson_ou_mark_stays_unoutlined_on_the_dark_ticker() -> None:
    canvas = Image.new("RGBA", (18, 18), (0, 0, 0, 255))
    logo = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    ImageDraw.Draw(logo).rectangle((2, 2, 5, 5), fill=(153, 0, 0, 255))

    assert paste_team_logo(canvas, logo, (5, 5)) is False
    assert canvas.getpixel((8, 8))[:3] == (153, 0, 0)


def test_team_logo_with_its_own_contrasting_edge_does_not_get_an_extra_keyline() -> None:
    background_color = (153, 0, 0, 255)
    canvas = Image.new("RGBA", (28, 28), background_color)
    logo = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    draw = ImageDraw.Draw(logo)
    draw.rectangle((1, 1, 18, 18), fill=(250, 250, 250, 255))
    draw.rectangle((2, 2, 17, 17), fill=background_color)

    assert paste_team_logo(canvas, logo, (4, 4)) is False


def test_team_logo_with_visible_color_details_does_not_get_an_unneeded_keyline() -> None:
    background_color = (0, 53, 148, 255)
    canvas = Image.new("RGBA", (18, 18), background_color)
    logo = Image.new("RGBA", (8, 8), background_color)
    draw = ImageDraw.Draw(logo)
    draw.line((0, 0, 6, 0), fill=(255, 255, 255, 255), width=1)
    draw.rectangle((2, 3, 4, 5), fill=(255, 255, 255, 255))

    assert paste_team_logo(canvas, logo, (5, 5), outline_mode=LogoOutlineMode.FULL) is False
    assert canvas.getpixel((4, 8))[:3] == background_color[:3]


def test_full_logo_policy_outlines_a_mark_that_scroll_leaves_clean() -> None:
    full_canvas = Image.new("RGBA", (18, 18), (0, 0, 0, 255))
    scroll_canvas = Image.new("RGBA", (18, 18), (0, 0, 0, 255))
    logo = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    for y in range(2, 6):
        for x in range(2, 6):
            logo.putpixel((x, y), (0, 0, 0, 255))
    logo.putpixel((6, 3), (0, 0, 0, 255))
    for point in ((2, 2), (3, 2), (4, 2), (3, 3)):
        logo.putpixel(point, (255, 255, 255, 255))

    assert paste_team_logo(full_canvas, logo, (5, 5), outline_mode=LogoOutlineMode.FULL) is True
    assert paste_team_logo(scroll_canvas, logo, (5, 5), outline_mode=LogoOutlineMode.SCROLL) is False
    assert full_canvas.getpixel((6, 9))[:3] != (0, 0, 0)
    assert scroll_canvas.getpixel((6, 9))[:3] == (0, 0, 0)


def test_missing_logo_badge_uses_team_color_and_acronym() -> None:
    image = Image.new("RGBA", (24, 24), (40, 40, 40, 255))
    team_color = (220, 30, 55)

    draw_missing_team_badge(image, (0, 0), 24, team_color, "NOVA")

    assert image.getpixel((12, 5))[:3] == team_color
    assert image.getpixel((0, 0))[:3] == (40, 40, 40)
    assert image.getpixel((2, 12))[:3] == team_color
    visible_acronym_pixels = sum(
        1
        for red, green, blue, _ in image.crop((2, 8, 22, 17)).getdata()
        if red >= 240 and green >= 240 and blue >= 240
    )
    assert visible_acronym_pixels >= 20

    bright_image = Image.new("RGBA", (24, 24), (40, 40, 40, 255))
    draw_missing_team_badge(bright_image, (0, 0), 24, (255, 210, 0), "MIA")
    dark_acronym_pixels = sum(
        1
        for red, green, blue, _ in bright_image.crop((2, 8, 22, 17)).getdata()
        if red <= 24 and green <= 24 and blue <= 24
    )
    assert dark_acronym_pixels >= 20


def test_missing_logo_badge_has_smooth_symmetric_rounded_edges() -> None:
    image = Image.new("RGBA", (24, 24), (0, 0, 0, 0))

    draw_missing_team_badge(image, (0, 0), 24, (220, 30, 55), "NOVA")

    alpha = image.getchannel("A")
    assert alpha.getpixel((0, 0)) == 0
    assert any(0 < value < 255 for value in alpha.getdata())
    assert alpha.tobytes() == alpha.transpose(Image.Transpose.FLIP_LEFT_RIGHT).tobytes()
    assert alpha.tobytes() == alpha.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()


def test_scroll_sports_uses_colored_acronym_badges_when_logos_are_missing(
    sports: SportsRenderer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    badges: list[tuple[str, tuple[int, int, int]]] = []
    original = sports_stadium_port.draw_missing_team_badge

    def capture(image, xy, size, team_color, abbreviation):
        badges.append((str(abbreviation), tuple(team_color)))
        return original(image, xy, size, team_color, abbreviation)

    monkeypatch.setattr(sports_stadium_port, "draw_missing_team_badge", capture)
    image = sports.render_card(
        {
            "sport": "mlb",
            "state": "in",
            "status": "Top 5th",
            "away_abbr": "NYY",
            "home_abbr": "BOS",
            "away_color": "#0C2340",
            "home_color": "#BD3039",
            "away_score": 2,
            "home_score": 1,
        }
    )

    assert image.height == 32
    assert ("NYY", (12, 35, 64)) in badges
    assert ("BOS", (189, 48, 57)) in badges


def test_full_sports_uses_colored_acronym_badges_when_logos_are_missing(
    sports: SportsRenderer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    badges: list[tuple[str, tuple[int, int, int]]] = []
    original = sports_full_port.draw_missing_team_badge

    def capture(image, xy, size, team_color, abbreviation):
        badges.append((str(abbreviation), tuple(team_color)))
        return original(image, xy, size, team_color, abbreviation)

    monkeypatch.setattr(sports_full_port, "draw_missing_team_badge", capture)
    image = sports.render_full(
        {
            "sport": "ncf_fcs",
            "state": "in",
            "status": "Q1 10:00",
            "away_abbr": "POI",
            "home_abbr": "NOVA",
            "away_color": "#00338D",
            "home_color": "#841617",
            "away_score": 0,
            "home_score": 0,
        }
    )

    assert image.size == (384, 32)
    assert ("POI", (0, 51, 141)) in badges
    assert ("NOVA", (132, 22, 23)) in badges


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
