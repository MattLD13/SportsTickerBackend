"""Integration tests for the rewrite scene registry."""

from datetime import datetime
import pytest

from ticker_core import RenderContext
from ticker_core.bootstrap import create_default_scene_registry
from ticker_core.features.clock import ClockRenderer, ClockScene

pytestmark = pytest.mark.critical


def test_default_registry_resolves_and_renders_clock_scene():
    """The default registry renders a full-panel clock scene."""
    registry = create_default_scene_registry()
    scene = ClockScene()

    assert isinstance(registry.get(scene.kind), ClockRenderer)

    image = registry.render(RenderContext(datetime(2026, 7, 4, 12, 30, 0)), scene)

    assert image.mode == "RGBA"
    assert image.size == (384, 32)
