"""Frame output implementations."""

from .emulator import TkFrameSink
from .frames import FrameSink
from .memory import MemoryFrameSink
from .rgbmatrix import RgbMatrixFrameSink, RgbMatrixSettings, RgbMatrixUnavailableError

__all__ = [
    "FrameSink",
    "MemoryFrameSink",
    "RgbMatrixFrameSink",
    "RgbMatrixSettings",
    "RgbMatrixUnavailableError",
    "TkFrameSink",
]
