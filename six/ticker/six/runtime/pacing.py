"""Frame deadlines for a paced controller loop."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True)
class FramePacer:
    """Calculate deadlines without owning a render loop."""

    monotonic: Callable[[], float]
    _deadline: float | None = None

    def reset(self) -> None:
        """Clear the next frame deadline."""
        self._deadline = None

    def next_delay(self, interval: float) -> float:
        """Return the sleep time before the next frame."""
        if interval < 0:
            raise ValueError("A frame interval cannot be negative.")
        now = self.monotonic()
        deadline = (now if self._deadline is None else self._deadline) + interval
        if deadline < now:
            deadline = now
        self._deadline = deadline
        return max(0.0, deadline - now)
