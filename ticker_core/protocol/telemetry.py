"""Build telemetry headers for a backend poll."""

from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Callable


@dataclass(frozen=True, slots=True)
class TelemetrySnapshot:
    """Hold the health facts sent with a ticker poll."""

    uptime_seconds: int
    build: str
    python: str
    temperature_c: float | None = None


def build_poll_headers(snapshot: TelemetrySnapshot) -> dict[str, str]:
    """Return the backend header names used by the deployed ticker."""

    headers = {
        "X-Ticker-Uptime": str(max(0, snapshot.uptime_seconds)),
        "X-Ticker-Build": snapshot.build,
        "X-Ticker-Python": snapshot.python,
    }
    if snapshot.temperature_c is not None:
        headers["X-Ticker-Temp"] = str(snapshot.temperature_c)
    return headers


def current_python_version() -> str:
    """Return the runtime Python version in telemetry format."""

    return sys.version.split()[0]
