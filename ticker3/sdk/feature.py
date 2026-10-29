"""The interface that each feature implements."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .http import HttpClient


@dataclass
class Poll:
    """The records of one subscription and the seconds until the next read."""

    records: list[dict[str, Any]]
    next_seconds: float


@dataclass
class Context:
    """What the runner gives a feature."""

    http: HttpClient
    release: str
    wake: Callable[[Callable[[dict[str, Any]], bool]], int]
    subscriptions: Callable[[], dict[str, dict[str, Any]]]
    state: dict[str, Any] = field(default_factory=dict)


class Feature:
    """Read upstreams for subscriptions. A feature must not import the core."""

    manifest: dict[str, Any]

    async def start(self, context: Context) -> None:
        """Start push sources. The default starts nothing."""

    async def poll(self, config: dict[str, Any], context: Context) -> Poll:
        """Read the upstreams of one subscription and return its records."""
        raise NotImplementedError

    async def stop(self) -> None:
        """Stop push sources. The default stops nothing."""
