from __future__ import annotations

from PIL import Image
import pytest

from ticker.six.drivers import MemoryFrameSink, RgbMatrixFrameSink

pytestmark = pytest.mark.critical


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
    sink = RgbMatrixFrameSink(matrix, width=2, height=1)
    image = Image.new("RGB", (2, 1), (1, 2, 3))

    sink.present(image, brightness=-9)

    assert matrix.canvas.brightness == 0
    assert matrix.canvas.image is not None
    assert matrix.swaps == 1
    assert matrix.fraction == 1


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

    def SetImage(self, image: Image.Image, x: int = 0, y: int = 0) -> None:
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

    def SetImage(self, image: Image.Image, x: int = 0, y: int = 0) -> None:
        self.image = image


def test_memory_sink_retains_its_own_pixels_after_the_caller_changes_the_source() -> None:
    sink = MemoryFrameSink(width=2, height=1)
    source = Image.new("RGB", (2, 1), (1, 2, 3))
    sink.present(source)
    source.paste((255, 0, 0), (0, 0, 2, 1))
    assert sink.last_image.tobytes() == bytes([1, 2, 3]) * 2


@pytest.mark.parametrize("mode,inverted", [("RGB", False), ("RGB", True), ("RGBA", False), ("RGBA", True)])
def test_banded_transfer_preserves_all_pixels_across_reused_vsync_canvases(mode, inverted) -> None:
    class Canvas:
        def __init__(self):
            self.image = Image.new("RGB", (384, 32))
            self.brightness = 100

        def SetImage(self, image, x=0, y=0):
            self.image.paste(image, (x, y))

    class Matrix:
        def __init__(self):
            self.front, self.back = Canvas(), Canvas()
            self.swaps = 0

        def CreateFrameCanvas(self):
            return self.back

        def SwapOnVSync(self, canvas):
            old = self.front
            self.front = canvas
            self.swaps += 1
            return old

    matrix = Matrix()
    sink = RgbMatrixFrameSink(matrix)
    for index in range(3):
        image = Image.new(mode, (384, 32))
        image.putdata([((x + index * 17) % 256, (y * 19) % 256, (x * y + index) % 256, 255)[:len(mode)]
                       for y in range(32) for x in range(384)])
        before = image.tobytes()
        sink.present(image, brightness=20 + index * 30, inverted=inverted)
        expected = image.convert("RGB")
        if inverted:
            expected = expected.rotate(180)
        assert matrix.front.image.tobytes() == expected.tobytes()
        assert matrix.front.brightness == 20 + index * 30
        assert image.tobytes() == before
    assert matrix.swaps == 3
