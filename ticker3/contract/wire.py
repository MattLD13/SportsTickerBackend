"""Frame one JSON object on one line."""
from __future__ import annotations

import json
import math
from typing import Any

from . import ContractError

MAX_LINE = 4 * 1024 * 1024


def encode(message: dict[str, Any]) -> bytes:
    """Return one compact JSON line. A line longer than MAX_LINE is an error."""
    data = json.dumps(message, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode() + b"\n"
    if len(data) > MAX_LINE:
        raise ContractError(f"message is {len(data)} bytes, the limit is {MAX_LINE}")
    return data


def decode(line: bytes) -> dict[str, Any]:
    """Return the object on one line. The object must have a string type field `t`."""
    if len(line) > MAX_LINE:
        raise ContractError("message is longer than the line limit")
    try:
        message = json.loads(line, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError(f"message is not JSON: {error}") from error
    if not isinstance(message, dict) or not isinstance(message.get("t"), str):
        raise ContractError("message must be an object with a string field t")
    return message


def canonical(value: Any) -> str:
    """Return one stable JSON text for equal values."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _reject_constant(name: str) -> Any:
    raise ContractError(f"message contains {name}")
