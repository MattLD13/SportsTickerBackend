"""Display output contracts."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from PIL import Image


@runtime_checkable
class FrameSink(Protocol):
    """Present complete frames on one display target."""

    width: int
    height: int

    def present(
        self,
        image: Image.Image,
        *,
        brightness: int = 100,
        inverted: bool = False,
    ) -> None:
        """Present one frame with the requested panel settings."""

    def clear(self) -> None:
        """Clear the display target."""
