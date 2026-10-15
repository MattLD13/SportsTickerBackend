"""Fit source images for the Pi and Mini through one image preparation owner."""

from __future__ import annotations

import io
from PIL import Image


def prepare_contained(raw: bytes, size: tuple[int, int]) -> Image.Image:
    """Fit one source image inside a transparent target image."""
    return _prepare_contained(raw, size, Image.Resampling.LANCZOS)


def prepare_contained_native_grid(raw: bytes, size: tuple[int, int]) -> Image.Image:
    """Rasterize an image directly on the final logo pixel grid."""
    return _prepare_contained(raw, size, Image.Resampling.BICUBIC)


def _prepare_contained(raw: bytes, size: tuple[int, int], resampling: Image.Resampling) -> Image.Image:
    with Image.open(io.BytesIO(raw)) as source:
        image = source.convert("RGBA").convert("RGBa")
    image.thumbnail(size, resampling)
    image = image.convert("RGBA")
    target = Image.new("RGBA", size, (0, 0, 0, 0))
    target.alpha_composite(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return target
