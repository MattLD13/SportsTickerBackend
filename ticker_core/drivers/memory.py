"""In-memory display output for tests and off-device runs."""

from __future__ import annotations

from PIL import Image

from .frames import FrameSink


class MemoryFrameSink(FrameSink):
    """Keep the most recently presented frame in memory."""

    def __init__(self, width: int = 384, height: int = 32) -> None:
        self.width = width
        self.height = height
        self.hardware_paced = False
        self.brightness = 100
        self.inverted = False
        self.last_image: Image.Image | None = None

    def present(
        self,
        image: Image.Image,
        *,
        brightness: int = 100,
        inverted: bool = False,
    ) -> None:
        frame = _prepare_frame(image, self.width, self.height, inverted)
        self.brightness = _brightness(brightness)
        self.inverted = inverted
        self.last_image = frame

    def clear(self) -> None:
        self.present(Image.new("RGB", (self.width, self.height)), brightness=self.brightness)


def _prepare_frame(image: Image.Image, width: int, height: int, inverted: bool) -> Image.Image:
    if image.size != (width, height):
        raise ValueError(f"Frame size must be {width}x{height}, not {image.width}x{image.height}.")
    frame = image.convert("RGB")
    if inverted:
        frame = frame.rotate(180)
    return frame


def _brightness(value: int) -> int:
    return max(0, min(100, int(value)))
