"""Define data shared by content renderers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from PIL import Image


@dataclass(frozen=True, slots=True)
class ContentScene:
    """Request one content image for a display mode."""

    kind: ClassVar[str] = "content"
    item: Mapping[str, Any]
    mode: str
    elapsed: float = 0.0


@dataclass(frozen=True, slots=True)
class RenderedContent:
    """Return one rendered image and its scheduling role."""

    image: Image.Image
    static: bool

    def __post_init__(self) -> None:
        if self.image.height != 32:
            raise ValueError("Rendered content must be 32 pixels high.")
