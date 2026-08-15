"""Exercise uninterrupted scrolling while a fresh strip is prepared."""

from datetime import datetime, timezone

from PIL import Image

from ticker_core.app.strips import StripRepository
from ticker_core.context import RenderContext
from ticker_core.rendering import RenderedContent
from ticker_core.runtime import Content


class Catalog:
    """Render a fixed card without assets or I/O."""

    def __init__(self) -> None:
        self.calls = 0

    def render(self, context, scene):
        del context, scene
        self.calls += 1
        return RenderedContent(Image.new("RGB", (128, 32), "white"), static=False)


def test_same_mode_rebuild_keeps_the_active_strip_visible() -> None:
    strips = StripRepository(Catalog())
    prepared = strips.prepare(
        "old",
        (Content("game", "scoreboard", "nfl", {}),),
        RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc)),
        "sports",
    )
    strips.install(prepared)

    assert strips.get("old", "sports") is not None
    assert strips.get("new", "sports") is not None
    assert strips.get("new", "stock") is None


def test_rebuild_reuses_unchanged_cards() -> None:
    catalog = Catalog()
    strips = StripRepository(catalog)
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    old = (
        Content("game", "scoreboard", "nfl", {"down": "1st"}),
        Content("other", "scoreboard", "nfl", {"down": "2nd"}),
    )
    new = (
        Content("game", "scoreboard", "nfl", {"down": "2nd"}),
        old[1],
    )

    strips.prepare("old", old, context, "sports")
    strips.prepare("new", new, context, "sports")

    assert catalog.calls == 3
