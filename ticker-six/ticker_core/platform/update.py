"""OTA update request service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
from .update_journal import UpdateJournal
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
        journal: UpdateJournal | None = None,
    ) -> None:
        self._journal = journal or UpdateJournal(Path(os.environ.get("TICKER_DATA_DIR", "/home/mld/ticker")))
        self._commands = commands
        self._executable = executable
        self._updater_path = str(updater_path) if updater_path else str(Path(__file__).parents[3] / "updater.py")
        self._state = UpdateState(active=False, version="")

    def state(self) -> UpdateState:
        """Return the current OTA update state."""
        return self._state

    def request_update(self, version: str, *, command_id: str, ticker_id: str) -> bool:
        """Start the updater once and return true for a new request."""
        if self._state.active:
            return False
        if not all((version.strip(), command_id.strip(), ticker_id.strip())):
            raise ValueError("Update requires a version, command id, and ticker id")
        journal = self._journal.load()
        if journal and journal.get("id") == command_id and journal.get("status") in {"started", "installed", "rolled_back", "download_failed"}:
            if journal["status"] != "started":
                return False
            self._state = UpdateState(active=True, version=version)
            return True
        self._commands.run_update((self._executable, self._updater_path, "--version", version,
                                   "--command-id", command_id, "--ticker-id", ticker_id))
        self._state = UpdateState(active=True, version=version)
        return True

    def mark_result_presented(self, receipt: dict[str, str]) -> None:
        """Persist acknowledgement after a failure frame reaches the matrix."""
        self._journal.mark_notice_shown(receipt)

    def finish_update(self) -> None:
        """Clear active state after the updater returns or fails."""
        self._state = UpdateState(active=False, version="")
