"""Serialize fleet values as stable JSON text for SQLite columns."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def _jsonable(value: Any) -> Any:
    """Convert immutable containers into JSON-compatible values."""

    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, frozenset, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, bytearray):
        return bytes(value).decode("utf-8")
    return value


def _dump(value: Any) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"))
