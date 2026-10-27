"""Freeze nested values at server ownership boundaries."""

from collections.abc import Mapping
from types import MappingProxyType


def freeze(value: object) -> object:
    """Copy common mutable containers into immutable values."""
    if isinstance(value, Mapping):
        return MappingProxyType({freeze(key): freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(freeze(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)
    return value
