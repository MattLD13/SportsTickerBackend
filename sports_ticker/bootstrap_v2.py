"""Compose the rewrite app from explicit database, providers, scheduler, and clock inputs."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from pathlib import Path

from flask import Flask

from sports_ticker.application import BackendApplication, RefreshScheduler, RefreshService
from sports_ticker.application.state_store import SnapshotStore
from sports_ticker.fleet import TickerRepository
from sports_ticker.firmware import FirmwareManifest
from sports_ticker.providers import Provider, WeatherLocationResolver


def create_backend_application(
    database_path: str | Path,
    provider_collection: Iterable[Provider],
    *,
    scheduler: RefreshScheduler | None = None,
    spotify_service: object | None = None,
    firmware_manifest: FirmwareManifest | dict[str, object] | None = None,
    firmware_directory: str | Path | None = None,
    clock: Callable[[], float] = time.time,
) -> Flask:
    """Build the rewrite Flask app without discovery, configuration, or startup side effects."""

    repository = TickerRepository(database_path)
    snapshot_store = SnapshotStore()
    refresh_service = RefreshService(provider_collection, snapshot_store)
    if scheduler is None:
        scheduler = RefreshScheduler(refresh_service)

    application = BackendApplication(
        repository,
        snapshot_store,
        scheduler=scheduler,
        spotify_service=spotify_service,
        weather_location_resolver=WeatherLocationResolver().resolve,
        clock=clock,
    )
    event_service = application.event_service

    from sports_ticker.api.app import create_app

    manifest = None if firmware_manifest is None else (
        firmware_manifest
        if isinstance(firmware_manifest, FirmwareManifest)
        else FirmwareManifest.from_mapping(firmware_manifest)
    )
    app = create_app(
        application,
        firmware_manifest=manifest,
        firmware_directory=firmware_directory,
    )
    app.extensions["sports_ticker.backend_application"] = application
    app.extensions["sports_ticker.repository"] = repository
    app.extensions["sports_ticker.snapshot_store"] = snapshot_store
    app.extensions["sports_ticker.refresh_service"] = refresh_service
    app.extensions["sports_ticker.event_service"] = event_service
    app.extensions["sports_ticker.scheduler"] = scheduler
    return app


__all__ = ["create_backend_application"]
