"""Exercise the native compact and pinned sports renderers."""

from datetime import datetime, timezone

import pytest
from PIL import Image, ImageDraw

from ticker_core.context import RenderContext
from ticker_core.features.sports import SportsRenderer
from ticker_core.rendering import ContentScene, load_default_font_set


class EmptyLogos:
    """Provide deterministic missing logos."""

    def get(self, url: str | None, size: tuple[int, int]) -> Image.Image | None:
        del url, size
        return None


class SolidLogos:
    """Provide team-color logos with transparent padding."""

    def get(self, url: str | None, size: tuple[int, int]) -> Image.Image | None:
        colors = {"home": (128, 0, 0, 255), "away": (128, 0, 0, 255)}
        logo = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(logo).rectangle((4, 4, size[0] - 5, size[1] - 5), fill=colors.get(url or "", (128, 0, 0, 255)))
        return logo


class WhiteLogos:
    """Provide logos that already contrast with the end-zone color."""

    def get(self, url: str | None, size: tuple[int, int]) -> Image.Image | None:
        del url
        logo = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(logo).rectangle((4, 4, size[0] - 5, size[1] - 5), fill=(255, 255, 255, 255))
        return logo


@pytest.fixture
def renderer() -> SportsRenderer:
    return SportsRenderer(load_default_font_set(), EmptyLogos())


def test_baseball_compact_and_pinned_frames_have_panel_geometry(renderer: SportsRenderer) -> None:
    game = {
        "sport": "mlb",
        "state": "in",
        "status": "Top 5th",
        "away_abbr": "NYY",
        "home_abbr": "BOS",
        "away_score": 2,
        "home_score": 1,
        "situation": {"activeTeam": "NYY", "balls": 2, "strikes": 1, "outs": 1, "onFirst": True},
    }
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))

    compact = renderer.render(context, ContentScene(game, "sports")).image
    pinned = renderer.render_full(game)

    assert compact.height == 32
    assert pinned.size == (384, 32)


def test_pinned_baseball_frame_renders_batter_and_pitcher_names(renderer: SportsRenderer) -> None:
    game = {
        "sport": "mlb",
        "state": "in",
        "status": "Bottom 7th",
        "away_abbr": "NYY",
        "home_abbr": "BOS",
        "away_score": 2,
        "home_score": 1,
        "situation": {
            "activeTeam": "BOS",
            "batter_name": "Austin Wells",
            "pitcher_name": "Garrett Acton",
            "batter_h": "2",
            "batter_ab": "4",
            "batter_avg": ".250",
            "pitcher_pitches": "24",
        },
    }

    without_names = {**game, "situation": {key: value for key, value in game["situation"].items() if "_name" not in key}}

    named = renderer.render_full(game)
    unlabeled = renderer.render_full(without_names)

    assert named.size == (384, 32)
    assert named.tobytes() != unlabeled.tobytes()


def test_football_active_team_changes_the_live_context_position(renderer: SportsRenderer) -> None:
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    base = {
        "sport": "nfl", "state": "in", "status": "Q2 5:12", "away_abbr": "AWY",
        "home_abbr": "HOM", "away_score": 7, "home_score": 3,
        "situation": {"downDist": "2nd & 4", "isRedZone": False},
    }
    away = renderer.render(context, ContentScene({**base, "situation": {**base["situation"], "activeTeam": "AWY"}}, "sports")).image
    home = renderer.render(context, ContentScene({**base, "situation": {**base["situation"], "activeTeam": "HOM"}}, "sports")).image

    assert away.size == home.size
    assert away.tobytes() != home.tobytes()


def test_pinned_football_missing_logos_show_team_abbreviations(renderer: SportsRenderer) -> None:
    image = renderer.render_full({
        "sport": "ncf_fcs", "state": "in", "status": "Q2 5:12",
        "away_abbr": "GLN", "home_abbr": "ELON", "away_score": 7, "home_score": 3,
        "away_color": "#800000", "home_color": "#800000",
        "away_alt_color": "#FFD700", "home_alt_color": "#FFD700",
        "situation": {"activeTeam": "GLN", "downDist": "2nd & 4"},
    })

    left_end_zone = image.crop((0, 0, 32, 32)).getcolors(32 * 32)

    assert any(red > 180 and green > 120 and blue < 120 for _, (red, green, blue) in left_end_zone)


def test_pinned_football_logos_use_alternate_color_contrast() -> None:
    renderer = SportsRenderer(load_default_font_set(), SolidLogos())
    game = {
        "sport": "nfl", "state": "in", "status": "Q2 5:12",
        "away_abbr": "AWY", "home_abbr": "HOM", "away_score": 7, "home_score": 3,
        "away_logo": "away", "home_logo": "home",
        "away_color": "#800000", "home_color": "#800000",
        "away_alt_color": "#FFD700", "home_alt_color": "#FFD700",
        "situation": {"activeTeam": "AWY", "downDist": "2nd & 4"},
    }

    image = renderer.render_full(game)

    assert image.size == (384, 32)
    assert any(
        red > 180 and green > 120 and blue < 120
        for _, (red, green, blue) in image.getcolors(image.width * image.height)
    )


def test_pinned_football_logos_skip_halo_when_contrast_is_sufficient() -> None:
    renderer = SportsRenderer(load_default_font_set(), WhiteLogos())
    game = {
        "sport": "nfl", "state": "in", "status": "Q2 5:12",
        "away_abbr": "AWY", "home_abbr": "HOM", "away_score": 7, "home_score": 3,
        "away_logo": "away", "home_logo": "home",
        "away_color": "#800000", "home_color": "#800000",
        "away_alt_color": "#FFD700", "home_alt_color": "#FFD700",
        "situation": {"activeTeam": "AWY", "downDist": "2nd & 4"},
    }

    image = renderer.render_full(game)
    end_zone_colors = image.crop((0, 0, 32, 32)).getcolors(32 * 32)

    assert not any(red > 180 and green > 120 and blue < 120 for _, (red, green, blue) in end_zone_colors)


@pytest.mark.parametrize("sport", ["ncf_fbs", "ncf_fcs"])
def test_college_football_scrolling_cards_match_nfl(renderer: SportsRenderer, sport: str) -> None:
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    game = {
        "state": "in", "status": "Q2 5:12", "away_abbr": "AWY",
        "home_abbr": "HOM", "away_score": 7, "home_score": 3,
        "situation": {
            "activeTeam": "AWY", "downDist": "2nd & 4", "isRedZone": False,
        },
    }

    nfl = renderer.render_card({**game, "sport": "nfl"})
    college = renderer.render_card({**game, "sport": sport})

    assert college.size == nfl.size
    assert college.tobytes() == nfl.tobytes()


@pytest.mark.parametrize("sport", ["ncf_fbs", "ncf_fcs"])
def test_college_football_rankings_overlay_the_logo_corners(renderer: SportsRenderer, sport: str) -> None:
    ranked = renderer.render_card({
        "sport": sport, "state": "in", "status": "Q2 5:12",
        "away_abbr": "AWY", "home_abbr": "HOM", "away_score": 7, "home_score": 3,
        "away_rank": "4", "home_rank": "12",
        "situation": {"activeTeam": "AWY", "downDist": "2nd & 4"},
    })

    assert ranked.size[1] == 32
    assert ranked.getcolors(ranked.width * ranked.height)
    assert (255, 220, 80) in {color for _, color in ranked.getcolors(ranked.width * ranked.height)}
