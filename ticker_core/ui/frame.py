"""Define the frame geometry, the content render request, and the plain data that renderers read."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from PIL import Image


@dataclass(frozen=True, slots=True)
class FrameGeometry:
    """Describe one frame surface accepted by a display driver."""

    width: int = 384
    height: int = 32
    fit_mode: str = "scale"

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("frame geometry dimensions must be positive")
        mode = str(self.fit_mode).strip().lower() or "scale"
        if mode not in {"scale", "crop", "letterbox"}:
            raise ValueError("frame geometry fit_mode must be scale, crop, or letterbox")
        object.__setattr__(self, "fit_mode", mode)


@dataclass(frozen=True, slots=True)
class ContentScene:
    """Request one content image for a display mode."""

    kind: ClassVar[str] = "content"
    item: Mapping[str, Any]
    mode: str
    elapsed: float = 0.0


@dataclass(frozen=True, slots=True)
class RenderedContent:
    """Return one rendered image."""

    image: Image.Image

    def __post_init__(self) -> None:
        if self.image.height != 32:
            raise ValueError("Rendered content must be 32 pixels high.")


def plain_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a frozen mapping and its nested containers."""
    return {str(key): plain(item) for key, item in value.items()}


def plain(value: Any) -> Any:
    """Convert nested mappings and sequences without changing scalar values."""
    if isinstance(value, Mapping):
        return plain_mapping(value)
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value
