"""Validate each message of the worker protocol and the device protocol."""
from __future__ import annotations

import re
from typing import Any

from . import PROTOCOL, ContractError
from .manifest import validate_manifest
from .records import FEATURE, RECORD_ID, validate_record
from .templates import PANEL

SUB_KEY = re.compile(r"^[0-9a-f]{16}$")
RELEASE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
MAX_RECORDS = 512


def worker_message(message: dict[str, Any]) -> dict[str, Any]:
    """Validate one message that a worker sends to the core."""
    kind = message["t"]
    if kind == "hello":
        _fields(message, {"t", "protocol", "feature", "release", "pid", "manifest"})
        if message["protocol"] != PROTOCOL:
            raise ContractError(f"worker protocol {message['protocol']!r} is not {PROTOCOL}")
        if not isinstance(message["feature"], str) or not FEATURE.match(message["feature"]):
            raise ContractError("hello names an invalid feature")
        if not isinstance(message["release"], str) or not RELEASE.match(message["release"]):
            raise ContractError("hello names an invalid release")
        if isinstance(message["pid"], bool) or not isinstance(message["pid"], int) or message["pid"] < 1:
            raise ContractError("hello needs a process ID")
        manifest = validate_manifest(message["manifest"])
        if manifest["feature"] != message["feature"]:
            raise ContractError("hello feature and manifest feature differ")
        return {**message, "manifest": manifest}
    if kind == "sync":
        _fields(message, {"t", "sub", "records"})
        _sub(message["sub"])
        records = _records(message["records"])
        return {**message, "records": records}
    if kind == "delta":
        _fields(message, {"t", "sub", "upsert", "remove"})
        _sub(message["sub"])
        remove = message["remove"]
        if not isinstance(remove, list) or not all(isinstance(item, str) and RECORD_ID.match(item) for item in remove):
            raise ContractError("delta remove must be a list of record IDs")
        return {**message, "upsert": _records(message["upsert"])}
    if kind == "health":
        _fields(message, {"t", "ok", "errors", "rss_mb"})
        if not isinstance(message["ok"], bool) or not isinstance(message["errors"], dict):
            raise ContractError("health needs ok and errors")
        for key, error in message["errors"].items():
            _sub(key)
            if not isinstance(error, str):
                raise ContractError("health errors must be text")
        return {**message, "errors": {key: error[:300] for key, error in message["errors"].items()}}
    raise ContractError(f"unknown worker message type {kind!r}")


def core_message(message: dict[str, Any]) -> dict[str, Any]:
    """Validate one message that the core sends to a worker."""
    kind = message["t"]
    if kind == "welcome":
        _fields(message, {"t", "ok"}, {"reason"})
    elif kind == "subscribe":
        _fields(message, {"t", "subs"})
        if not isinstance(message["subs"], dict) or not all(isinstance(config, dict) for config in message["subs"].values()):
            raise ContractError("subscribe needs subs as key to config")
        for key in message["subs"]:
            _sub(key)
    elif kind == "wake":
        _fields(message, {"t", "subs"})
        if not isinstance(message["subs"], list):
            raise ContractError("wake needs a list of subscription keys")
        for key in message["subs"]:
            _sub(key)
    elif kind == "drain":
        _fields(message, {"t"})
    else:
        raise ContractError(f"unknown core message type {kind!r}")
    return message


def device_message(message: dict[str, Any]) -> dict[str, Any]:
    """Validate one message that a device sends to the core."""
    kind = message["t"]
    if kind == "hello":
        _fields(message, {"t", "protocol", "token", "panel"}, {"bundle", "firmware"})
        if message["protocol"] != PROTOCOL:
            raise ContractError(f"device protocol {message['protocol']!r} is not {PROTOCOL}")
        if not isinstance(message["token"], str) or not 16 <= len(message["token"]) <= 128:
            raise ContractError("hello needs a device token")
        if not isinstance(message["panel"], str) or not PANEL.match(message["panel"]):
            raise ContractError("hello needs a panel size such as w64h32")
        for name in ("bundle", "firmware"):
            if name in message and (not isinstance(message[name], str) or len(message[name]) > 64):
                raise ContractError(f"hello {name} must be short text")
        return message
    if kind == "pong":
        _fields(message, {"t"})
        return message
    raise ContractError(f"unknown device message type {kind!r}")


def _fields(message: dict[str, Any], required: set[str], optional: frozenset[str] | set[str] = frozenset()) -> None:
    keys = set(message)
    if not required <= keys or not keys <= required | set(optional):
        raise ContractError(f"{message['t']} needs {sorted(required - {'t'})}")


def _sub(key: Any) -> None:
    if not isinstance(key, str) or not SUB_KEY.match(key):
        raise ContractError(f"invalid subscription key {key!r}")


def _records(records: Any) -> list[dict[str, Any]]:
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ContractError(f"a message can carry at most {MAX_RECORDS} records")
    validated = [validate_record(record) for record in records]
    identifiers = [record["id"] for record in validated]
    if len(set(identifiers)) != len(identifiers):
        raise ContractError("a message lists one record ID twice")
    return validated
