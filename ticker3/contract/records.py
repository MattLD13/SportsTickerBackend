"""Validate records and find the references in their values.

A record is one item that a subscription produces:

    {"id": "nfl-401873023", "template": "sports.card", "order": 10,
     "values": {"away.score": "17", "home.score": "14", "status": "Q3 08:12"},
     "tags": ["nfl:gb", "nfl:car"], "expires_at": 1793000000.0}

A value is a string, a number, a boolean, null, or a reference:

    {"$ref": {"feature": "weather", "config": {...}, "record": "now"}}
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from . import ContractError
from .wire import canonical, finite

RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
VALUE_KEY = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")
TAG = re.compile(r"^[a-z0-9_:.-]{1,64}$")
FEATURE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
TEMPLATE_ID = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
MAX_VALUES = 128
MAX_TEXT = 512
MAX_TAGS = 32


@dataclass(frozen=True)
class Reference:
    """A value that points at one record of another feature."""

    feature: str
    config: dict[str, Any]
    record: str

    @property
    def identity(self) -> str:
        return canonical([self.feature, self.config, self.record])


def validate_record(record: Any) -> dict[str, Any]:
    """Return one record with defaults set. Raise ContractError for any invalid field."""
    if not isinstance(record, dict):
        raise ContractError("record must be an object")
    unknown = set(record) - {"id", "template", "values", "tags", "order", "expires_at", "overlay"}
    if unknown:
        raise ContractError(f"record has unknown fields: {', '.join(sorted(unknown))}")
    identifier = record.get("id")
    if not isinstance(identifier, str) or not RECORD_ID.match(identifier):
        raise ContractError(f"record id {identifier!r} is invalid")
    template = record.get("template")
    if not isinstance(template, str) or not TEMPLATE_ID.match(template):
        raise ContractError(f"record {identifier} has an invalid template id")
    values = record.get("values", {})
    if not isinstance(values, dict) or len(values) > MAX_VALUES:
        raise ContractError(f"record {identifier} must have at most {MAX_VALUES} values")
    for key, value in values.items():
        if not isinstance(key, str) or not VALUE_KEY.match(key):
            raise ContractError(f"record {identifier} has an invalid value key {key!r}")
        if reference(value) is None and not _scalar(value):
            raise ContractError(f"record {identifier} value {key} must be a scalar or a reference")
    tags = record.get("tags", [])
    if not isinstance(tags, list) or len(tags) > MAX_TAGS or not all(isinstance(tag, str) and TAG.match(tag) for tag in tags):
        raise ContractError(f"record {identifier} has invalid tags")
    order = record.get("order", 0)
    if isinstance(order, bool) or not isinstance(order, int):
        raise ContractError(f"record {identifier} order must be an integer")
    expires_at = record.get("expires_at")
    if expires_at is not None and not finite(expires_at):
        raise ContractError(f"record {identifier} expires_at must be a number")
    overlay = record.get("overlay")
    if overlay is not None and (not isinstance(overlay, dict) or set(overlay) != {"ttl"}
                                or isinstance(overlay["ttl"], bool) or not isinstance(overlay["ttl"], int)
                                or not 1 <= overlay["ttl"] <= 600):
        raise ContractError(f"record {identifier} overlay must be {{'ttl': 1..600}}")
    return {"id": identifier, "template": template, "values": dict(values), "tags": list(tags), "order": order,
            "expires_at": expires_at, "overlay": overlay}


def reference(value: Any) -> Reference | None:
    """Return the reference in one value, or None for a scalar value."""
    if not isinstance(value, dict):
        return None
    target = value.get("$ref")
    if set(value) != {"$ref"} or not isinstance(target, dict) or set(target) != {"feature", "config", "record"}:
        raise ContractError("a reference must be {'$ref': {'feature', 'config', 'record'}}")
    if not isinstance(target["feature"], str) or not FEATURE.match(target["feature"]):
        raise ContractError("a reference names an invalid feature")
    if not isinstance(target["config"], dict) or not isinstance(target["record"], str) or not RECORD_ID.match(target["record"]):
        raise ContractError("a reference needs a config object and a record id")
    return Reference(target["feature"], target["config"], target["record"])


def references(record: dict[str, Any]) -> list[tuple[str, Reference]]:
    """Return each value key that holds a reference, with its reference."""
    found = []
    for key, value in record["values"].items():
        target = reference(value)
        if target is not None:
            found.append((key, target))
    return found


def _scalar(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, str):
        return len(value) <= MAX_TEXT
    return finite(value)
