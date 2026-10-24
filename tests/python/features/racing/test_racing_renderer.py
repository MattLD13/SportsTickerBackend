"""Exercise the native racing renderer without a legacy controller oracle."""

from datetime import datetime, timezone

import pytest

from ticker_core.context import RenderContext
from ticker_core.features.racing import MemoryRacingAssets, RacingRenderer
from ticker_core.rendering import ContentScene, load_default_font_set
from ticker_core.rendering.catalog import content_family


def _item(series: str) -> dict:
    return {
        "sport": series,
        "state": "in",
        series: {
            "short_name": "Test Grand Prix",
            "session_type": "Race",
            "flag": "GREEN",
            "drivers": [{"pos": "1", "abbr": "AAA", "name": "Driver AAA", "car": "1", "gap": ""}],
        },
    }


def test_each_racing_series_renders_a_panel_frame() -> None:
    renderer = RacingRenderer(load_default_font_set(), MemoryRacingAssets())
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))

    for series in ("indycar", "f1", "nascar", "wec", "imsa", "nbr24"):
        assert content_family({"sport": series, "type": series}, "sports") == "racing"
        scroll = renderer.render(context, ContentScene(_item(series), "sports")).image
        full = renderer.render(
            context,
            ContentScene({**_item(series), "sports_presentation": "pinned"}, "sports"),
        ).image

        assert scroll.height == full.height == 32
        assert scroll.width >= 128
        assert full.size == (384, 32)


def test_completed_f1_cards_show_leader_time_and_following_gaps(monkeypatch) -> None:
    import ticker_core.features.racing.renderer as rendering

    drawn = []
    original = rendering.draw_tiny_text

    def record(draw, x, y, text, color):
        drawn.append(str(text))
        return original(draw, x, y, text, color)

    monkeypatch.setattr(rendering, "draw_tiny_text", record)
    item = _item("f1")
    item.update(state="post", sports_presentation="pinned")
    item["f1"].update(session_type="Practice 1", drivers=[
        {"pos": 1, "abbr": "LEC", "name": "Charles Leclerc", "gap": "1:36.052", "best_time": "1:36.052"},
        {"pos": 2, "abbr": "VER", "name": "Max Verstappen", "gap": "+0.084", "best_time": "1:36.136"},
    ])
    renderer = RacingRenderer(load_default_font_set(), MemoryRacingAssets())
    renderer.render(RenderContext(datetime(2026, 10, 23, tzinfo=timezone.utc)), ContentScene(item, "sports"))
    assert "1:36.052" in drawn
    assert "+0.084" in drawn
    assert "1:36.136" not in drawn


@pytest.mark.parametrize("series,count", [("f1", 22), ("indycar", 27), ("nascar", 37), ("wec", 35), ("imsa", 54), ("nbr24", 161)])
def test_pinned_carousel_builds_the_entire_field(series, count):
    item = _item(series)
    item["sports_presentation"] = "pinned"
    item[series]["drivers"] = [
        {"pos": n, "car": str(n), "name": f"Car {n}", "gap": f"+{n}.123"}
        for n in range(1, count + 1)
    ]
    renderer = RacingRenderer(load_default_font_set(), MemoryRacingAssets())
    result = renderer.render(RenderContext(datetime(2026, 10, 23, tzinfo=timezone.utc)), ContentScene(item, "sports"))
    cards, strip, width = next(iter(renderer._strip_cache.values()))
    assert len(cards) == count
    assert width == sum(card.width + 6 for card in cards)
    assert strip.width > width
    assert result.image.size == (384, 32)


def test_indycar_race_uses_gap_instead_of_qualifying_speed(monkeypatch):
    import ticker_core.features.racing.renderer as rendering

    drawn = []
    original = rendering.draw_tiny_text

    def record(draw, x, y, text, color):
        drawn.append(str(text))
        return original(draw, x, y, text, color)

    monkeypatch.setattr(rendering, "draw_tiny_text", record)
    item = _item("indycar")
    item["sports_presentation"] = "pinned"
    item["indycar"]["drivers"] = [{"pos": 2, "car": "2", "name": "Driver", "gap": "+1.234", "speed": "220.123"}]
    RacingRenderer(load_default_font_set(), MemoryRacingAssets()).render(
        RenderContext(datetime(2026, 10, 23, tzinfo=timezone.utc)), ContentScene(item, "sports"))
    assert "+1.234" in drawn
    assert "220.123" not in drawn


def test_nurburgring_scroll_identifies_the_car_without_a_driver_abbreviation(monkeypatch):
    import ticker_core.features.racing.renderer as rendering

    drawn = []
    original = rendering.draw_tiny_text

    def record(draw, x, y, text, color):
        drawn.append(str(text))
        return original(draw, x, y, text, color)

    monkeypatch.setattr(rendering, "draw_tiny_text", record)
    item = _item("nbr24")
    item["nbr24"]["drivers"] = [{"pos": 1, "car": "1", "name": "ROWE Racing", "manufacturer": "BMW M4 GT3", "gap": "Leader"}]
    RacingRenderer(load_default_font_set(), MemoryRacingAssets()).render(
        RenderContext(datetime(2026, 5, 17, tzinfo=timezone.utc)), ContentScene(item, "sports"))
    assert "CAR" in drawn
    assert "BMW M4 GT3" in drawn
    assert "???" not in drawn
