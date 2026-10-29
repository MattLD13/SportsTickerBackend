"""The health of one provider job, as /health reports it."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class JobHealth:
    last_success: datetime | None = None
    last_error: str | None = None
    next_due: datetime | None = None
    consecutive_failures: int = 0
    refresh_calls: int = 0
    paused_refreshes: int = 0
