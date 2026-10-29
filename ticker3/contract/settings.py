"""Validate app settings and expand them into subscription configs.

A settings schema is {"fields": {name: field}}. Each field has a type and a role.

| Role | Effect |
|---|---|
| `fetch` | The value is part of each subscription config. |
| `fanout` | A list. Each item gives one subscription. The config holds the item under the name in `as`. |
| `filter` | A list. If it is not empty, the core keeps only records with a tag in the list. |
| `view` | The core adds the value to each screen of the app as `app.<name>`. |
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from . import ContractError
from .wire import canonical, finite

FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
TYPES = {"string", "int", "float", "bool", "enum", "list"}
ROLES = {"fetch", "fanout", "filter", "view"}
MAX_LIST = 64
MAX_STRING = 256


@dataclass(frozen=True)
class Expansion:
    """The subscriptions, filters, and view values of one app."""

    configs: tuple[dict[str, Any], ...]
    filters: dict[str, tuple[str, ...]]
    view: dict[str, Any]


def validate_schema(schema: Any) -> dict[str, Any]:
    """Return the schema when it is valid. Each default must pass its own field."""
    if not isinstance(schema, dict) or set(schema) != {"fields"} or not isinstance(schema["fields"], dict):
        raise ContractError("settings schema must be {'fields': {...}}")
    fanouts = 0
    for name, field in schema["fields"].items():
        if not FIELD_NAME.match(str(name)) or not isinstance(field, dict):
            raise ContractError(f"invalid settings field {name!r}")
        _validate_field_type(name, field)
        role = field.get("role", "fetch")
        if role not in ROLES:
            raise ContractError(f"field {name} has unknown role {role!r}")
        if role in {"fanout", "filter"} and field["type"] != "list":
            raise ContractError(f"field {name} with role {role} must be a list")
        if role == "fanout":
            fanouts += 1
            target = field.get("as")
            if not isinstance(target, str) or not FIELD_NAME.match(target) or target in schema["fields"]:
                raise ContractError(f"fanout field {name} needs a new config name in 'as'")
        if "default" in field:
            _value(name, field, field["default"])
        elif not field.get("required"):
            raise ContractError(f"field {name} needs a default or required: true")
    if fanouts > 1:
        raise ContractError("a schema can have at most one fanout field")
    return schema


def normalize(schema: dict[str, Any], settings: Any) -> dict[str, Any]:
    """Return settings with each field validated and each missing field set to its default."""
    if not isinstance(settings, dict):
        raise ContractError("settings must be an object")
    fields = schema["fields"]
    unknown = set(settings) - set(fields)
    if unknown:
        raise ContractError(f"unknown settings: {', '.join(sorted(unknown))}")
    result = {}
    for name, field in fields.items():
        if name in settings:
            result[name] = _value(name, field, settings[name])
        elif "default" in field:
            result[name] = _value(name, field, field["default"])
        else:
            raise ContractError(f"setting {name} is required")
    return result


def expand(schema: dict[str, Any], settings: dict[str, Any]) -> Expansion:
    """Expand normalized settings into subscription configs, filters, and view values."""
    base, filters, view, fanout = {}, {}, {}, None
    for name, field in schema["fields"].items():
        role = field.get("role", "fetch")
        if role == "fetch":
            base[name] = settings[name]
        elif role == "filter":
            filters[name] = tuple(settings[name])
        elif role == "view":
            view[name] = settings[name]
        else:
            fanout = (field["as"], settings[name])
    if fanout is None:
        configs = (base,)
    else:
        target, items = fanout
        configs = tuple({**base, target: item} for item in dict.fromkeys(items))
    return Expansion(configs, {key: value for key, value in filters.items() if value}, view)


def normalize_config(schema: dict[str, Any], config: Any) -> dict[str, Any]:
    """Validate one subscription config, such as the config of a reference."""
    if not isinstance(config, dict):
        raise ContractError("config must be an object")
    allowed, result = {}, {}
    for name, field in schema["fields"].items():
        role = field.get("role", "fetch")
        if role == "fetch":
            allowed[name] = field
        elif role == "fanout":
            allowed[field["as"]] = {**field["items"], "required": True}
    unknown = set(config) - set(allowed)
    if unknown:
        raise ContractError(f"unknown config keys: {', '.join(sorted(unknown))}")
    for name, field in allowed.items():
        if name in config:
            result[name] = _value(name, field, config[name])
        elif "default" in field:
            result[name] = _value(name, field, field["default"])
        else:
            raise ContractError(f"config key {name} is required")
    return result


def subscription_key(config: dict[str, Any]) -> str:
    """Return the shared key of one normalized config."""
    return hashlib.sha256(canonical(config).encode()).hexdigest()[:16]


def _validate_field_type(name: str, field: dict[str, Any]) -> None:
    kind = field.get("type")
    if kind not in TYPES:
        raise ContractError(f"field {name} has unknown type {kind!r}")
    if kind == "enum":
        values = field.get("values")
        if not isinstance(values, list) or not values or not all(isinstance(value, str) for value in values):
            raise ContractError(f"enum field {name} needs a list of string values")
    if kind == "list":
        items = field.get("items")
        if not isinstance(items, dict) or items.get("type") not in TYPES - {"list"}:
            raise ContractError(f"list field {name} needs scalar items")
        _validate_field_type(name, items)
    for bound in ("min", "max"):
        if bound in field and not finite(field[bound]):
            raise ContractError(f"field {name} has an invalid {bound}")


def _value(name: str, field: dict[str, Any], value: Any) -> Any:
    kind = field["type"]
    if kind == "list":
        if not isinstance(value, list) or len(value) > field.get("max_items", MAX_LIST):
            raise ContractError(f"setting {name} must be a list of at most {field.get('max_items', MAX_LIST)} items")
        if len(value) < field.get("min_items", 0):
            raise ContractError(f"setting {name} needs at least {field['min_items']} items")
        return [_value(name, field["items"], item) for item in value]
    if kind == "bool":
        if not isinstance(value, bool):
            raise ContractError(f"setting {name} must be true or false")
        return value
    if kind == "string":
        if not isinstance(value, str):
            raise ContractError(f"setting {name} must be a string")
        text = value.strip()
        if len(text) > field.get("max_length", MAX_STRING):
            raise ContractError(f"setting {name} is too long")
        if field.get("lower"):
            text = text.lower()
        pattern = field.get("pattern")
        if pattern and not re.fullmatch(pattern, text):
            raise ContractError(f"setting {name} has an invalid format")
        return text
    if kind == "enum":
        if value not in field["values"]:
            raise ContractError(f"setting {name} must be one of {', '.join(field['values'])}")
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ContractError(f"setting {name} must be an integer")
    elif not finite(value):
        raise ContractError(f"setting {name} must be a number")
    if "min" in field and value < field["min"]:
        raise ContractError(f"setting {name} must be at least {field['min']}")
    if "max" in field and value > field["max"]:
        raise ContractError(f"setting {name} must be at most {field['max']}")
    return value if kind == "int" else float(value)
