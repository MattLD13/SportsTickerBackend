"""Expose shared rendering contracts and resources."""

from .catalog import ContentRenderer, ContentRendererCatalog, DuplicateContentRendererError, UnknownContentRendererError
from .fonts import FontSet, load_default_font_set
from .geometry import FrameGeometry
from .model import ContentScene, RenderedContent

__all__ = [
    "ContentRenderer",
    "ContentRendererCatalog",
    "ContentScene",
    "DuplicateContentRendererError",
    "FontSet",
    "FrameGeometry",
    "RenderedContent",
    "UnknownContentRendererError",
    "load_default_font_set",
]
