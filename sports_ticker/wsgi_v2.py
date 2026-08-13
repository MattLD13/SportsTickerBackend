"""Deployment must call ``create_app(database_path, provider_collection, ...)`` explicitly."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from pathlib import Path

from flask import Flask

from sports_ticker.application import RefreshScheduler
from sports_ticker.bootstrap_v2 import create_backend_application
from sports_ticker.providers import Provider


def create_app(
    database_path: str | Path,
    provider_collection: Iterable[Provider],
    *,
    scheduler: RefreshScheduler | None = None,
    clock: Callable[[], float] = time.time,
) -> Flask:
    """Return one explicitly composed WSGI app without constructing it at import time."""

    return create_backend_application(
        database_path,
        provider_collection,
        scheduler=scheduler,
        clock=clock,
    )


__all__ = ["create_app"]
