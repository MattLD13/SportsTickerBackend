"""Scene and renderer contracts."""

from typing import Protocol, TypeVar

from .context import RenderContext


class Scene(Protocol):
    """Describe one render request."""

    @property
    def kind(self) -> str:
        """Return the registered scene kind."""


RenderOutput = TypeVar("RenderOutput", covariant=True)


class SceneRenderer(Protocol[RenderOutput]):
    """Render one scene kind."""

    def render(self, context: RenderContext, scene: Scene) -> RenderOutput:
        """Build the output for a scene."""
