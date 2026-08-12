"""Scene renderer registration."""

from typing import Generic, TypeVar

from .context import RenderContext
from .scene import Scene, SceneRenderer


RenderOutput = TypeVar("RenderOutput")


class DuplicateSceneRendererError(ValueError):
    """Report a second renderer for one scene kind."""


class UnknownSceneKindError(KeyError):
    """Report a request for an unregistered scene kind."""


class SceneRegistry(Generic[RenderOutput]):
    """Map explicit scene kinds to their renderers."""

    def __init__(self) -> None:
        self._renderers: dict[str, SceneRenderer[RenderOutput]] = {}

    def register(self, kind: str, renderer: SceneRenderer[RenderOutput]) -> None:
        """Register the renderer for one scene kind."""
        if kind in self._renderers:
            raise DuplicateSceneRendererError(
                f"A renderer is already registered for scene kind {kind!r}."
            )
        self._renderers[kind] = renderer

    def get(self, kind: str) -> SceneRenderer[RenderOutput]:
        """Return the renderer for one scene kind."""
        try:
            return self._renderers[kind]
        except KeyError as error:
            raise UnknownSceneKindError(
                f"No renderer is registered for scene kind {kind!r}."
            ) from error

    def render(self, context: RenderContext, scene: Scene) -> RenderOutput:
        """Render a scene with its registered renderer."""
        return self.get(scene.kind).render(context, scene)
