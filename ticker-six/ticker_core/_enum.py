"""Provide string enum support on supported Pi Python versions."""

from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        """Match Python 3.11 string enum behavior on Python 3.10."""

        def __str__(self) -> str:
            return str(self.value)
