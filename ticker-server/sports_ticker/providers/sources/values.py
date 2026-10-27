"""Validate numeric source values shared by live providers."""
from __future__ import annotations

from math import isfinite


def _timeout(value: float) -> float:
    result = float(value)
    if not isfinite(result) or result <= 0:
        raise ValueError("timeout must be finite and positive")
    return result


def _number(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
