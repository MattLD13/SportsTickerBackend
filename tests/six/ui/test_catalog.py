from datetime import datetime

import pytest
from PIL import Image

from ticker.six.ui.frame import RenderContext
from ticker.six.ui import (
    CardCatalog,
    ContentScene,
    DuplicateCardError,
    RenderedContent,
    UnknownCardError,
)

pytestmark = pytest.mark.critical


class SolidRenderer:
    def render(self, context, scene):
        return RenderedContent(Image.new("RGB", (64, 32), "red"))

def test_catalog_routes_by_content_family():
    catalog = CardCatalog()
    catalog.register("weather", SolidRenderer())
    rendered = catalog.render(
        RenderContext(datetime(2026, 1, 2, 3, 4)),
        ContentScene({"id": "weather", "type": "weather"}, "sports"),
    )
    assert rendered.image.size == (64, 32)


def test_catalog_rejects_duplicate_and_unknown_families():
    catalog = CardCatalog()
    catalog.register("weather", SolidRenderer())
    with pytest.raises(DuplicateCardError):
        catalog.register("weather", SolidRenderer())
    with pytest.raises(UnknownCardError):
        catalog.render(
            RenderContext(datetime(2026, 1, 2, 3, 4)),
            ContentScene({"id": "game", "type": "scoreboard"}, "sports"),
        )
