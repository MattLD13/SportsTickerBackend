from datetime import datetime

import pytest
from PIL import Image

from ticker_core.context import RenderContext
from ticker_core.rendering import (
    ContentRendererCatalog,
    ContentScene,
    DuplicateContentRendererError,
    RenderedContent,
    UnknownContentRendererError,
)

pytestmark = pytest.mark.critical


class SolidRenderer:
    def render(self, context, scene):
        return RenderedContent(Image.new("RGB", (64, 32), "red"))

def test_catalog_routes_by_content_family():
    catalog = ContentRendererCatalog()
    catalog.register("weather", SolidRenderer())
    rendered = catalog.render(
        RenderContext(datetime(2026, 1, 2, 3, 4)),
        ContentScene({"id": "weather", "type": "weather"}, "sports"),
    )
    assert rendered.image.size == (64, 32)


def test_catalog_rejects_duplicate_and_unknown_families():
    catalog = ContentRendererCatalog()
    catalog.register("weather", SolidRenderer())
    with pytest.raises(DuplicateContentRendererError):
        catalog.register("weather", SolidRenderer())
    with pytest.raises(UnknownContentRendererError):
        catalog.render(
            RenderContext(datetime(2026, 1, 2, 3, 4)),
            ContentScene({"id": "game", "type": "scoreboard"}, "sports"),
        )
