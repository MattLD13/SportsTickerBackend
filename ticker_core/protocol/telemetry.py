"""Build telemetry headers for a backend poll."""

from __future__ import annotations

from dataclasses import dataclass
import sys


@dataclass(frozen=True, slots=True)
class TelemetrySnapshot:
    """Hold the health facts sent with a ticker poll."""

    uptime_seconds: int
    build: str
    python: str
    temperature_c: float | None = None


def current_python_version() -> str:
    """Return the runtime Python version in telemetry format."""

    return sys.version.split()[0]
