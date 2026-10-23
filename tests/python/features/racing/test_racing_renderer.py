"""Exercise the native racing renderer without a legacy controller oracle."""

from datetime import datetime, timezone

import pytest

from ticker_core.context import RenderContext
from ticker_core.features.racing import MemoryRacingAssets, RacingRenderer
from ticker_core.rendering import ContentScene, load_default_font_set


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

    for series in ("indycar", "f1", "nascar"):
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
