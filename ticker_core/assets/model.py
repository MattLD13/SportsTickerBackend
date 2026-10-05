"""Shared contracts for prepared ticker images."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from PIL import Image


@dataclass(frozen=True, slots=True)
class AssetRequest:
    """Describe one prepared image variant."""

    url: str
    processor: str
    size: tuple[int, int]

    def __post_init__(self) -> None:
        if not self.url:
            raise ValueError("An asset URL cannot be empty.")
        if not self.processor:
            raise ValueError("An asset processor cannot be empty.")
        if self.size[0] <= 0 or self.size[1] <= 0:
            raise ValueError("An asset size must be positive.")


@runtime_checkable
class AssetView(Protocol):
    """Read prepared images without triggering work."""

    @property
    def revision(self) -> int:
        """Return a revision that changes when prepared images change."""

    def image(self, url: str, processor: str, size: tuple[int, int]) -> Image.Image | None:
        """Return one prepared image from memory only."""


@dataclass(frozen=True, slots=True)
class LogoAssetView:
    """Adapt shared asset reads to existing logo renderer needs."""

    assets: AssetView

    def get(
        self,
        url: str | None,
        size: tuple[int, int] = (24, 24),
        rendering: Mapping[str, object] | None = None,
    ) -> Image.Image | None:
        """Return a prepared logo without starting I/O."""
        if not url:
            return None
        method = str(rendering.get("method") or "old").lower() if rendering else "old"
        processor = "logo_native_grid" if method == "new" else "logo"
        image = self.assets.image(url, processor, size)
        if image is None or not rendering:
            return image
        image = image.copy()
        image.logo_rendering_outline = str(rendering.get("outline") or "ticker")
        try:
            cutoff = float(rendering.get("cutoff", 35))
        except (TypeError, ValueError):
            cutoff = 35.0
        image.logo_rendering_cutoff = max(0.0, min(255.0, cutoff * 255 / 100))
        return image
