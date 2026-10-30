"""Validate each message between the core and a provider worker."""
from __future__ import annotations

import re
from typing import Any

from ticker.server.contract import PROTOCOL, ContractError

SUB_KEY = re.compile(r"^[0-9a-f]{16}$")
NAME = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
RELEASE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def worker_message(message: dict[str, Any]) -> dict[str, Any]:
    """Validate one message that a worker sends to the core."""
    kind = message["t"]
    if kind == "hello":
        _fields(message, {"t", "protocol", "provider", "release", "pid"})
        if message["protocol"] != PROTOCOL:
            raise ContractError(f"worker protocol {message['protocol']!r} is not {PROTOCOL}")
        if not isinstance(message["provider"], str) or not NAME.match(message["provider"]):
            raise ContractError("hello names an invalid provider")
        if not isinstance(message["release"], str) or not RELEASE.match(message["release"]):
            raise ContractError("hello names an invalid release")
        if isinstance(message["pid"], bool) or not isinstance(message["pid"], int) or message["pid"] < 1:
            raise ContractError("hello needs a process ID")
    elif kind == "result":
        # The result is one ProviderResult in the ticker.server.contract.results encoding.
        _fields(message, {"t", "sub", "result", "started_ms"})
        _sub(message["sub"])
        if not isinstance(message["result"], dict):
            raise ContractError("result must be an encoded provider result object")
    elif kind == "health":
        # job holds the JobHealth fields of the provider job. recovery holds its paused circuits.
        _fields(message, {"t", "ok", "errors", "rss_mb", "busy_seconds", "job", "recovery"})
        if not isinstance(message["job"], dict) or not isinstance(message["recovery"], dict):
            raise ContractError("health needs job and recovery objects")
        if not isinstance(message["ok"], bool) or not isinstance(message["errors"], dict):
            raise ContractError("health needs ok and errors")
        for key, error in message["errors"].items():
            _sub(key)
            if not isinstance(error, str):
                raise ContractError("health errors must be text")
        message = {**message, "errors": {key: error[:300] for key, error in message["errors"].items()}}
    else:
        raise ContractError(f"unknown worker message type {kind!r}")
    return message


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
    elif kind == "drain":
        _fields(message, {"t"})
    else:
        raise ContractError(f"unknown core message type {kind!r}")
    return message


def _fields(message: dict[str, Any], required: set[str], optional: set[str] | frozenset[str] = frozenset()) -> None:
    keys = set(message)
    if not required <= keys or not keys <= required | set(optional):
        raise ContractError(f"{message['t']} needs {sorted(required - {'t'})}")


def _sub(key: Any) -> None:
    if not isinstance(key, str) or not SUB_KEY.match(key):
        raise ContractError(f"invalid subscription key {key!r}")
