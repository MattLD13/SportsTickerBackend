"""Tests for the rendering core contracts."""

from dataclasses import FrozenInstanceError, dataclass
from datetime import datetime

import pytest

from ticker_core import (
    DuplicateSceneRendererError,
    RenderContext,
    SceneRegistry,
    UnknownSceneKindError,
)

pytestmark = pytest.mark.critical


@dataclass(frozen=True)
class SampleScene:
    """Provide a scene for tests."""

    value: str
    kind: str = "sample"


class SampleRenderer:
    """Record rendering inputs for tests."""

    def render(self, context: RenderContext, scene: SampleScene) -> str:
        """Return a stable rendering result."""
        return f"{context.now.isoformat()}:{scene.value}"


def test_context_keeps_the_injected_time() -> None:
    """The context uses the caller supplied time."""
    now = datetime(2026, 8, 11, 9, 30)

    context = RenderContext(now=now)

    assert context.now is now
    with pytest.raises(FrozenInstanceError):
        context.now = datetime(2026, 8, 11, 9, 31)


def test_registry_renders_a_scene_by_its_kind() -> None:
    """The registry selects the matching renderer."""
    registry = SceneRegistry[str]()
    registry.register("sample", SampleRenderer())
    context = RenderContext(now=datetime(2026, 8, 11, 9, 30))

    result = registry.render(context, SampleScene(value="ready"))

    assert result == "2026-08-11T09:30:00:ready"


def test_registry_rejects_duplicate_scene_kinds() -> None:
    """One scene kind has one renderer."""
    registry = SceneRegistry[str]()
    registry.register("sample", SampleRenderer())

    with pytest.raises(DuplicateSceneRendererError, match="sample"):
        registry.register("sample", SampleRenderer())


def test_registry_reports_unknown_scene_kinds() -> None:
    """A missing renderer raises a clear error."""
    registry = SceneRegistry[str]()

    with pytest.raises(UnknownSceneKindError, match="sample"):
        registry.get("sample")

    with pytest.raises(UnknownSceneKindError, match="sample"):
        registry.render(RenderContext(now=datetime(2026, 8, 11)), SampleScene(value="x"))
