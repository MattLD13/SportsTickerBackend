"""Shared shape checks for provider payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def as_mapping(value: object) -> Mapping[str, Any]:
    """Return mapping values and use an empty mapping for other payload shapes."""
    return value if isinstance(value, Mapping) else {}


def mapping_values(value: object) -> tuple[Mapping[str, Any], ...]:
    """Return mapping entries from a sequence and ignore scalar or non-mapping values."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))
