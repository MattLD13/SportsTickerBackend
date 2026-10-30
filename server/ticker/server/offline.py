"""Build the ticker application with in-process providers and no engine, for tests and offline tools.

A caller publishes snapshots itself through `app.extensions["ticker.refresh"]`.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from pathlib import Path

from flask import Flask

from ticker.server.services import BackendApplication, RefreshService, SnapshotStore
from ticker.server.mini_assets.mini_service import MiniSpriteService
from ticker.server.store import TickerRepository
from ticker.server.providers.weather_location import WeatherLocationResolver

from ticker.server.api import create_app


def create_offline_application(database_path: str | Path, providers: Iterable[object] = (), *, spotify_service=None,
                               firmware_manifest=None, firmware_directory: str | Path | None = None,
                               clock: Callable[[], float] = time.time, mini_sprites=None, mini_artwork=None,
                               stock_catalog=None, weather_location_resolver=None) -> Flask:
    repository = TickerRepository(database_path)
    snapshots = SnapshotStore()
    refresh = RefreshService(providers, snapshots)
    resolver = weather_location_resolver or WeatherLocationResolver()
    application = BackendApplication(
        repository, snapshots, spotify_service=spotify_service, weather_location_resolver=resolver.resolve,
        owned_resources=(resolver,) if weather_location_resolver is None else (), clock=clock,
        mini_sprites=mini_sprites or MiniSpriteService(Path(database_path).parent / "mini_sprites", clock=clock),
        mini_artwork=mini_artwork)
    app = create_app(application, firmware_manifest=firmware_manifest, firmware_directory=firmware_directory,
                     stock_catalog=stock_catalog)
    app.extensions["ticker.refresh"] = refresh
    return app
