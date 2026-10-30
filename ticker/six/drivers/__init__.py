"""Frame output implementations."""

from ticker.six.drivers.emulator import TkFrameSink
from ticker.six.drivers.frames import FrameSink
from ticker.six.drivers.memory import MemoryFrameSink
from ticker.six.drivers.rgbmatrix import RgbMatrixFrameSink, RgbMatrixSettings, RgbMatrixUnavailableError

__all__ = [
    "FrameSink",
    "MemoryFrameSink",
    "RgbMatrixFrameSink",
    "RgbMatrixSettings",
    "RgbMatrixUnavailableError",
    "TkFrameSink",
]
