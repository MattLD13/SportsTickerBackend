"""Clock scene definition."""

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class ClockScene:
    """A request for the full-panel clock frame."""

    kind: ClassVar[str] = "clock"
