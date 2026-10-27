"""Convert frozen renderer data to ordinary serializable values."""

from collections.abc import Mapping
from typing import Any


def plain_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a frozen mapping and its nested containers."""
    return {str(key): plain(item) for key, item in value.items()}


def plain(value: Any) -> Any:
    """Convert nested mappings and sequences without changing scalar values."""
    if isinstance(value, Mapping):
        return plain_mapping(value)
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value
