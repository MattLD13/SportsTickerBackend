"""Logical display geometry for profile-aware frame composition."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FrameGeometry:
    """Describe one frame surface accepted by a display driver."""

    width: int = 384
    height: int = 32
    fit_mode: str = "scale"

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("frame geometry dimensions must be positive")
        mode = str(self.fit_mode).strip().lower() or "scale"
        if mode not in {"scale", "crop", "letterbox"}:
            raise ValueError("frame geometry fit_mode must be scale, crop, or letterbox")
        object.__setattr__(self, "fit_mode", mode)
