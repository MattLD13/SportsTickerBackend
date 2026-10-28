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


def as_sequence(value: Any) -> tuple[Any, ...]:
    """Return sequence entries and use an empty tuple for text or scalar values."""
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(value)
    return ()


def first_mapping(value: Any) -> Mapping[str, Any]:
    """Return the first sequence entry as a mapping, or an empty mapping."""
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and value:
        return as_mapping(value[0])
    return {}


def as_text(value: Any, default: str = "") -> str:
    """Return a value as text, or the default for None."""
    return default if value is None else str(value)
