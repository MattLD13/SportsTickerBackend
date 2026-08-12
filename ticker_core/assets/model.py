"""Shared contracts for prepared ticker images."""

from __future__ import annotations

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

    def get(self, url: str | None, size: tuple[int, int] = (24, 24)) -> Image.Image | None:
        """Return a prepared logo without starting I/O."""
        return self.assets.image(url, "logo", size) if url else None
