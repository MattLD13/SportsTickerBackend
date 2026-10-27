"""Convert canonical settings between immutable models and JSON mappings."""
from collections.abc import Mapping
from dataclasses import fields
from typing import Any

from .models import DisplaySettings


_SETTINGS_FIELDS = tuple(field.name for field in fields(DisplaySettings))


def settings_from_mapping(value: DisplaySettings | Mapping[str, Any] | None) -> DisplaySettings:
    """Read known fields and let the domain model supply defaults and validation."""
    if isinstance(value, DisplaySettings):
        return value
    if value is None:
        return DisplaySettings()
    if not isinstance(value, Mapping):
        raise TypeError("settings must be DisplaySettings, a mapping, or None")
    return DisplaySettings(**{name: value[name] for name in _SETTINGS_FIELDS if name in value})


def settings_to_mapping(settings: DisplaySettings) -> dict[str, Any]:
    """Encode settings with JSON containers and canonical field names."""
    result = {}
    for name in _SETTINGS_FIELDS:
        value = getattr(settings, name)
        if isinstance(value, Mapping):
            value = dict(value)
        elif isinstance(value, tuple):
            value = list(value)
        result[name] = value
    return result
