"""Exercise scrolling cards without precomposing a long strip image."""

from datetime import datetime, timezone
from time import monotonic, sleep

from PIL import Image

from ticker_core.app.viewport import CardViewport
from ticker_core.context import RenderContext
from ticker_core.rendering import RenderedContent
from ticker_core.runtime import Content


class Catalog:
    """Render one colored card and record renderer work."""

    def __init__(self) -> None:
        self.calls = 0

    def render(self, context, scene):
        del context
        self.calls += 1
        color = (255, 0, 0) if scene.item.get("down") == "1st" else (0, 255, 0)
        return RenderedContent(Image.new("RGB", (96, 32), color), static=False)


def test_viewport_renders_only_changed_card() -> None:
    catalog = Catalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    old = (
        Content("game", "scoreboard", "nfl", {"down": "1st"}),
        Content("other", "scoreboard", "nfl", {"down": "1st"}),
    )
    new = (
        Content("game", "scoreboard", "nfl", {"down": "2nd"}),
        old[1],
    )
    try:
        viewport.update(old, context, "sports")
        _drain(viewport, catalog, 2)
        viewport.update(new, context, "sports")
        _drain(viewport, catalog, 3)

        assert catalog.calls == 3
        assert viewport.frame(0).getpixel((1, 1)) == (0, 255, 0)
    finally:
        viewport.close()


def _drain(viewport: CardViewport, catalog: Catalog, expected_calls: int) -> None:
    deadline = monotonic() + 1
    while catalog.calls < expected_calls and monotonic() < deadline:
        viewport.install_completed()
        sleep(0.005)
    viewport.install_completed()
    assert catalog.calls == expected_calls
