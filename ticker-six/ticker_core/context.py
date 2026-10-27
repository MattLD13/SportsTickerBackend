"""Render context types."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RenderContext:
    """Provide immutable inputs that every renderer can use."""

    now: datetime
