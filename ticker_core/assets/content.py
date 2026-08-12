"""Short-term last-known-good display payload storage."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
from time import time
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class CachedContent:
    """Describe one still-valid last-known-good payload."""

    payload: Mapping[str, Any]
    saved_at: float
    expires_at: float

    @property
    def remaining(self) -> float:
        """Return the cache lifetime remaining at creation time."""
        return self.expires_at - self.saved_at


class ShortTermContentCache:
    """Keep the last valid display payload through brief backend outages."""

    def __init__(
        self,
        path: Path | str,
        *,
        ttl: float = 300.0,
        clock: Callable[[], float] = time,
    ) -> None:
        if ttl <= 0:
            raise ValueError("Content cache TTL must be positive.")
        self.path = Path(path)
        self.ttl = ttl
        self._clock = clock
        self._memory: CachedContent | None = None

    def store(self, payload: Mapping[str, Any]) -> CachedContent:
        """Replace cached content after a fresh parsed backend response."""
        saved_at = self._clock()
        frozen_payload = _thaw_mapping(payload)
        entry = CachedContent(frozen_payload, saved_at, saved_at + self.ttl)
        # The Pi polls twice per second. Avoid a synchronous disk replace when
        # the backend repeats the same payload, because it steals frame time.
        if self._memory is None or self._memory.payload != frozen_payload:
            self._write(entry)
        self._memory = entry
        return entry

    def load(self) -> CachedContent | None:
        """Return valid cached content or no content after expiry."""
        entry = self._memory or self._read()
        if entry is None:
            return None
        if entry.expires_at <= self._clock():
            self._memory = None
            return None
        self._memory = entry
        return entry

    def remaining(self, entry: CachedContent) -> float:
        """Return remaining validity for one cached entry."""
        return max(0.0, entry.expires_at - self._clock())

    def age(self, entry: CachedContent) -> float:
        """Return staleness age for one cached entry."""
        return max(0.0, self._clock() - entry.saved_at)

    def _read(self) -> CachedContent | None:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            payload = value["payload"]
            saved_at = float(value["saved_at"])
            expires_at = float(value["expires_at"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        return CachedContent(_thaw_mapping(payload), saved_at, expires_at) if isinstance(payload, Mapping) else None

    def _write(self, entry: CachedContent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        data = json.dumps({"payload": entry.payload, "saved_at": entry.saved_at, "expires_at": entry.expires_at}, separators=(",", ":"), sort_keys=True).encode("utf-8")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)


def _thaw_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Copy frozen protocol mappings into JSON-compatible data."""
    return {str(key): _thaw(child) for key, child in value.items()}


def _thaw(value: Any) -> Any:
    """Convert nested protocol data into plain JSON values."""
    if isinstance(value, Mapping):
        return _thaw_mapping(value)
    if isinstance(value, tuple):
        return [_thaw(child) for child in value]
    if isinstance(value, list):
        return [_thaw(child) for child in value]
    return value
