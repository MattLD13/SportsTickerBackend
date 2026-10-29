"""Features with no upstream. The core makes their records itself."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import clock


@dataclass(frozen=True)
class Builtin:
    manifest: dict[str, Any]
    records: Callable[[dict[str, Any]], list[dict[str, Any]]]


BUILTINS = {"clock": Builtin(clock.MANIFEST, clock.records)}
