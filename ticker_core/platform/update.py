"""OTA update request service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

from .commands import PlatformCommands


@dataclass(frozen=True, slots=True)
class UpdateState:
    """Report the currently requested OTA update."""

    active: bool
    version: str


class OtaUpdaterService:
    """Launch one external OTA updater for each active request."""

    def __init__(
        self,
        commands: PlatformCommands,
        *,
        executable: str = sys.executable,
        updater_path: str | Path | None = None,
    ) -> None:
        self._commands = commands
        self._executable = executable
        self._updater_path = str(updater_path) if updater_path else str(Path(__file__).parents[2] / "updater.py")
        self._state = UpdateState(active=False, version="")

    def state(self) -> UpdateState:
        """Return the current OTA update state."""
        return self._state

    def request_update(self, version: str = "") -> bool:
        """Start the updater once and return true for a new request."""
        if self._state.active:
            return False
        self._state = UpdateState(active=True, version=version)
        self._commands.run_update((self._executable, self._updater_path, "--no-display"))
        return True

    def finish_update(self) -> None:
        """Clear active state after the updater returns or fails."""
        self._state = UpdateState(active=False, version="")
