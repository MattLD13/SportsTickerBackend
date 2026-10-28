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


def freeze_text_keys(value: object) -> object:
    """Copy common mutable containers into immutable values with text mapping keys."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze_text_keys(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze_text_keys(item) for item in value)
    if isinstance(value, tuple):
        return tuple(freeze_text_keys(item) for item in value)
    if isinstance(value, set):
        return frozenset(freeze_text_keys(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)
    return value
