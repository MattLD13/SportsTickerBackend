"""Collect health facts for backend poll headers."""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from ticker_core.protocol import TelemetrySnapshot


class HealthCollector:
    """Collect process, checkout, and Pi temperature facts."""

    def __init__(
        self,
        repository: Path | str,
        *,
        temperature_path: Path | str = "/sys/class/thermal/thermal_zone0/temp",
        wall_clock: Callable[[], float] = time.time,
        run: Callable[..., bytes] = subprocess.check_output,
    ) -> None:
        self._repository = Path(repository)
        self._temperature_path = Path(temperature_path)
        self._wall_clock = wall_clock
        self._run = run
        self._started_at = wall_clock()
        self._build: str | None = None

    def snapshot(self) -> TelemetrySnapshot:
        """Return current health values."""
        return TelemetrySnapshot(
            uptime_seconds=max(0, int(self._wall_clock() - self._started_at)),
            build=self._build_id(),
            python=sys.version.split()[0],
            temperature_c=self._temperature(),
        )

    def _temperature(self) -> float | None:
        try:
            return round(int(self._temperature_path.read_text(encoding="utf-8").strip()) / 1000.0, 1)
        except (OSError, ValueError):
            return None

    def _build_id(self) -> str:
        if self._build is not None:
            return self._build
        try:
            count = self._git(("rev-list", "--count", "HEAD"))
            sha = self._git(("rev-parse", "--short", "HEAD"))
            self._build = f"r{count}+{sha}"
        except (OSError, subprocess.SubprocessError, UnicodeError):
            self._build = "unknown"
        return self._build

    def _git(self, arguments: Sequence[str]) -> str:
        result = self._run(
            ["git", *arguments],
            cwd=self._repository,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return result.decode("utf-8").strip()
