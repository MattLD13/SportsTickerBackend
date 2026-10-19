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
