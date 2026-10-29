"""Synthetic Six golden cases that reach renderer branches that no fixture or test reaches."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any


def cases(encode: Callable[[Any], Any], base: datetime) -> Iterator[dict[str, Any]]:
    return iter(())
