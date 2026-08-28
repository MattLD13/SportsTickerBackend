"""Exercise the native compact and pinned sports renderers."""

from datetime import datetime, timezone

import pytest
from PIL import Image

from ticker_core.context import RenderContext
from ticker_core.features.sports import SportsRenderer
from ticker_core.rendering import ContentScene, load_default_font_set


class EmptyLogos:
    """Provide deterministic missing logos."""

    def get(self, url: str | None, size: tuple[int, int]) -> Image.Image | None:
        del url, size
        return None


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
