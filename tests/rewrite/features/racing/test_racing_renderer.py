from datetime import datetime, timezone

import pytest
from PIL import Image, ImageChops

from ticker_controller.modes.f1 import F1Mixin
from ticker_controller.modes.nascar import NascarMixin
from ticker_controller.modes.racing import RacingMixin
from ticker_core.context import RenderContext
from ticker_core.features.racing import MemoryRacingAssets, RacingRenderer
from ticker_core.rendering import ContentScene, load_default_font_set


class LegacyRacing(RacingMixin, F1Mixin, NascarMixin):
    """Supply the legacy renderer dependencies for output comparisons."""

    def __init__(self) -> None:
        fonts = load_default_font_set()
        self.font = fonts.normal
        self.medium_font = fonts.medium
        self.tiny = fonts.tiny
        self.tiny_small = fonts.tiny_small
        self.scroll_sleep = 0.05

    def get_logo(self, _url, _size):
        """Keep parity data independent from logo files."""
        return None

    def download_and_process_logo(self, _url, _size):
        """Keep parity data independent from network work."""


def racing_item(series: str, drivers: list[dict] | None = None) -> dict:
    payload = {
        "short_name": "Test Grand Prix",
        "event_name": "Test Grand Prix",
        "session_type": "Race",
        "flag": "GREEN",
        "weather": {"air_temp": "82", "wind_mph": "5", "wind_dir": "180"},
        "drivers": drivers or [],
    }
    return {"sport": series, "state": "in", series: payload}


@pytest.mark.parametrize("series", ["indycar", "f1", "nascar"])
def test_scroll_cards_match_the_existing_series_adapters(series: str) -> None:
    item = racing_item(
        series,
        [
            {"pos": "1", "abbr": "AAA", "name": "Driver AAA", "car": "1", "gap": ""},
            {"pos": "2", "abbr": "BBB", "name": "Driver BBB", "car": "2", "gap": "+1.2"},
        ],
    )
    legacy = LegacyRacing()
    expected = (
        legacy.draw_racing_scroll_card(item)
        if series == "indycar"
        else legacy.draw_f1_scroll_card(item)
        if series == "f1"
        else legacy.draw_nascar_scroll_card(item)
    )
    renderer = RacingRenderer(load_default_font_set(), MemoryRacingAssets())
    actual = renderer.render(RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc)), ContentScene(item, "sports")).image

    assert ImageChops.difference(expected, actual).getbbox() is None


def test_full_view_matches_the_existing_indycar_empty_leaderboard(monkeypatch) -> None:
    import ticker_controller.modes.racing as legacy_module

    monkeypatch.setattr(legacy_module.time, "time", lambda: 0.0)
    item = racing_item("indycar")
    expected = LegacyRacing().draw_racing_full(item)
    renderer = RacingRenderer(load_default_font_set(), MemoryRacingAssets())
    actual = renderer.render(RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc)), ContentScene(item, "sports_full", elapsed=0.0)).image

    assert ImageChops.difference(expected, actual).getbbox() is None


@pytest.mark.parametrize("series", ["indycar", "f1", "nascar"])
@pytest.mark.parametrize(
    ("state", "session", "flag", "drivers"),
    [
        ("pre", "Practice", "", []),
        ("in", "Qualifying", "DOUBLE YELLOW", [{"pos": "1", "abbr": "AAA", "gap": "", "interval": "1:20.000"}, {"pos": "2", "abbr": "BBB", "gap": "+0.120", "interval": "1:20.120"}]),
        ("post", "Race", "CHECKERED", [{"pos": "1", "abbr": "AAA", "gap": ""}]),
    ],
)
def test_racing_series_state_matrix_matches_legacy(
    monkeypatch,
    series: str,
    state: str,
    session: str,
    flag: str,
    drivers: list[dict],
) -> None:
    """Keep practice, qualifying, and race frames identical for every series."""
    import ticker_controller.modes.racing as legacy_module

    monkeypatch.setattr(legacy_module.time, "time", lambda: 0.0)
    payload = {
        "short_name": "Test Grand Prix",
        "event_name": "Test Grand Prix",
        "session_type": session,
        "flag": flag,
        "weather": {"air_temp": "82", "wind_mph": "5", "wind_dir": "180"},
        "drivers": drivers,
    }
    if series == "nascar":
        payload.update(total_laps=100, laps_remaining=0 if state == "post" else 50)
    item = {"sport": series, "state": state, "status": "FINAL" if state == "post" else "12:00", series: payload}
    legacy = LegacyRacing()
    expected_scroll = legacy.draw_racing_scroll_card(item) if series == "indycar" else legacy.draw_f1_scroll_card(item) if series == "f1" else legacy.draw_nascar_scroll_card(item)
    expected_full = legacy.draw_racing_full(item) if series == "indycar" else legacy.draw_f1_full(item) if series == "f1" else legacy.draw_nascar_full(item)
    renderer = RacingRenderer(load_default_font_set(), MemoryRacingAssets())
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))

    actual_scroll = renderer.render(context, ContentScene(item, "sports")).image
    actual_full = renderer.render(context, ContentScene(item, "sports_full", elapsed=0.0)).image

    assert ImageChops.difference(expected_scroll.convert("RGB"), actual_scroll.convert("RGB")).getbbox() is None
    assert ImageChops.difference(expected_full.convert("RGB"), actual_full.convert("RGB")).getbbox() is None


def test_full_view_matches_legacy_with_prepared_badge_and_car_assets(monkeypatch) -> None:
    """Keep prepared team badges and cars identical to the established layout."""
    import ticker_controller.modes.racing as legacy_module

    monkeypatch.setattr(legacy_module.time, "time", lambda: 0.0)
    logo_url, car_url = "asset://badge", "asset://car"
    badge = Image.new("RGBA", (21, 21))
    car = Image.new("RGBA", (120, 19))
    for x in range(3, 18):
        for y in range(3, 18):
            badge.putpixel((x, y), (210, 20, 30, 255) if x < 11 else (20, 60, 210, 255))
    for x in range(5, 115):
        for y in range(8, 15):
            car.putpixel((x, y), (20, 100, 230, 255))
    item = racing_item(
        "indycar",
        [
            {"pos": "1", "abbr": "AAA", "name": "Alpha", "car": "1", "gap": "", "team_logo": logo_url},
            {"pos": "2", "abbr": "BBB", "name": "Beta", "car": "2", "gap": "+1.2", "car_illustration": car_url, "livery_primary": "#1464E6"},
        ],
    )
    legacy = LegacyRacing()
    legacy.get_logo = lambda url, size: badge if url == logo_url else car if url == car_url else None
    assets = MemoryRacingAssets()
    assets.put_image(logo_url, "logo", (18, 18), badge)
    assets.put_image(logo_url, "logo", (21, 21), badge)
    assets.put_image(car_url, "image", (120, 19), car)
    expected = legacy.draw_racing_full(item)
    actual = RacingRenderer(load_default_font_set(), assets).render(
        RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc)),
        ContentScene(item, "sports_full", elapsed=0.0),
    ).image

    assert ImageChops.difference(expected.convert("RGB"), actual.convert("RGB")).getbbox() is None
