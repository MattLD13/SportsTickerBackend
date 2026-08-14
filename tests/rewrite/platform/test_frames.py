from __future__ import annotations

from PIL import Image
import pytest

from ticker_core.drivers import MemoryFrameSink, RgbMatrixFrameSink


def test_memory_sink_converts_inverts_and_clamps_brightness() -> None:
    sink = MemoryFrameSink(width=2, height=1)
    source = Image.new("RGBA", (2, 1))
    source.putdata([(10, 20, 30, 255), (40, 50, 60, 255)])

    sink.present(source, brightness=150, inverted=True)

    assert sink.brightness == 100
    assert sink.last_image is not None
    assert sink.last_image.mode == "RGB"
    assert list(sink.last_image.getdata()) == [(40, 50, 60), (10, 20, 30)]


def test_frame_sink_rejects_wrong_display_size() -> None:
    sink = MemoryFrameSink(width=2, height=1)

    with pytest.raises(ValueError, match="Frame size"):
        sink.present(Image.new("RGB", (1, 1)))


def test_rgb_matrix_sink_uses_vsync_canvas_and_brightness() -> None:
    matrix = _Matrix()
    sink = RgbMatrixFrameSink(matrix, width=2, height=1, vsync_fraction=3)
    image = Image.new("RGB", (2, 1), (1, 2, 3))

    sink.present(image, brightness=-9)

    assert matrix.canvas.brightness == 0
    assert matrix.canvas.image is not None
    assert matrix.swaps == 1
    assert matrix.fraction == 3
    assert sink.hardware_paced


def test_rgb_matrix_sink_uses_direct_output_without_vsync() -> None:
    matrix = _DirectMatrix()
    sink = RgbMatrixFrameSink(matrix, width=2, height=1)
    image = Image.new("RGB", (2, 1), (1, 2, 3))

    sink.present(image, brightness=45)

    assert matrix.brightness == 45
    assert matrix.image is not None


class _Canvas:
    brightness = 100
    image: Image.Image | None = None

    def SetImage(self, image: Image.Image) -> None:
        self.image = image


class _Matrix:
    def __init__(self) -> None:
        self.canvas = _Canvas()
        self.swaps = 0
        self.fraction = 0

    def CreateFrameCanvas(self) -> _Canvas:
        return self.canvas

    def SwapOnVSync(self, canvas: _Canvas, fraction: int = 1) -> _Canvas:
        self.swaps += 1
        self.fraction = fraction
        return canvas


class _DirectMatrix:
    brightness = 100
    image: Image.Image | None = None

    def SetImage(self, image: Image.Image) -> None:
        self.image = image
