"""Persistent controller identity storage."""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Callable
from pathlib import Path


class DeviceIdentityStore:
    """Read or create one stable identifier across controller restarts."""

    def __init__(
        self,
        primary_path: Path | str,
        fallback_path: Path | str,
        *,
        create_identifier: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self.primary_path = Path(primary_path)
        self.fallback_path = Path(fallback_path)
        self._create_identifier = create_identifier

    @classmethod
    def default(cls) -> "DeviceIdentityStore":
        if os.name == "nt" or sys.platform == "win32":
            return cls("ticker_id.txt", "ticker_id.txt")
        return cls("/boot/ticker_id.txt", "ticker_id.txt")

    def load(self) -> str:
        """Return the saved identifier or persist a newly created identifier."""
        for path in (self.primary_path, self.fallback_path):
            identifier = self._read(path)
            if identifier:
                return identifier
        identifier = str(self._create_identifier())
        for path in (self.primary_path, self.fallback_path):
            if self._write(path, identifier):
                return identifier
        return identifier

    @staticmethod
    def _read(path: Path) -> str | None:
        try:
            identifier = path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return identifier or None

    @staticmethod
    def _write(path: Path, identifier: str) -> bool:
        temporary: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            temporary.write_text(identifier, encoding="utf-8")
            os.replace(temporary, path)
            return True
        except OSError:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            return False
