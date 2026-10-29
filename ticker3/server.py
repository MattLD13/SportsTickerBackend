"""Serve the unchanged V2 backend with the Ticker 3 engine: python -m ticker3.server

The Flask routes, the projections, the device stream, and every display stay
the same. Only the refresh engine changes: provider workers push results, and
the core supervisor restarts, replaces, and rolls back those workers.

| Variable | Default | Meaning |
|---|---|---|
| `TICKER_DATABASE_PATH` | `ticker_data/ticker-v2.sqlite3` | The fleet database, as before |
| `TICKER3_SOCKET` | `<database folder>/ticker3.sock` | Worker socket. A Unix socket path must be at most 100 bytes. |
| `TICKER3_PROVIDERS` | all ten providers except clock | Providers that run in worker processes |
| `TICKER3_RELEASES` | none | Folder with one folder for each release. Without it, the release `dev` is this checkout. |
| `TICKER3_RELEASE` | `dev` | The first active release of each provider |

Every other variable keeps its meaning from sports_ticker/production.py.
"""
from __future__ import annotations

import asyncio
import faulthandler
import os
import signal
from collections.abc import Callable
from pathlib import Path

from flask import Flask

from backend_ops.incidents import IncidentStore, release_id
from backend_ops.public_status import summary as deployment_summary
from sports_ticker.api.app import create_app
from sports_ticker.application import BackendApplication, RefreshService
from sports_ticker.application.provider_demand import ProviderDemand
from sports_ticker.application.provider_keys import provider_settings_key
from sports_ticker.application.state_store import SnapshotStore
from sports_ticker.assets.mini_artwork import MiniArtworkService
from sports_ticker.assets.mini_service import MiniSpriteService
from sports_ticker.firmware import FirmwareManifest
from sports_ticker.fleet import TickerRepository
from sports_ticker.integrations import SpotifyConfig, SpotifyIntegrationService
from sports_ticker.leagues import TEAM_CATALOG_PATHS
from sports_ticker.production import build_version, provision_initial_ticker
from sports_ticker.providers.catalog import EspnTeamCatalog
from sports_ticker.providers.clock import ClockProvider
from sports_ticker.providers.weather_location import WeatherLocationResolver

from .core.engine import Engine

PROVIDERS = ("espn", "fotmob", "weather", "golf", "racing", "stock", "flights", "music", "news")
CHECKOUT = Path(__file__).resolve().parents[1]


class EngineProvider:
    """Give a pull-style caller, such as the public demo, a provider port backed by the engine."""

    def __init__(self, engine: Engine, name: str) -> None:
        self.engine, self.name = engine, name

    def fetch_for_ticker(self, ticker_id, settings):
        return self.engine.read(self.name, ticker_id, settings)


def release_path(name: str) -> Path:
    releases = os.environ.get("TICKER3_RELEASES")
    if name == "dev" and not releases:
        return CHECKOUT
    if not releases or "/" in name or name.startswith("."):
        raise ValueError(f"release {name!r} has no folder")
    return Path(releases) / name


def create_application(database_path: str | Path | None = None, *, providers: tuple[str, ...] | None = None,
                       worker_arguments: tuple[str, ...] = (), supervisor_options: dict | None = None) -> Flask:
    """Build the V2 application with the Ticker 3 engine. The engine starts in start_engine()."""
    path = Path(database_path or os.environ.get("TICKER_DATABASE_PATH", "ticker_data/ticker-v2.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    repository = TickerRepository(path)
    provision_initial_ticker(repository)
    spotify = SpotifyIntegrationService(repository, SpotifyConfig.from_environment())
    catalog = EspnTeamCatalog(TEAM_CATALOG_PATHS)
    weather_resolver = WeatherLocationResolver()
    snapshots = SnapshotStore()
    incidents = IncidentStore(Path(os.environ.get("TICKER_INCIDENT_DIR", path.parent / "backend-incidents")))
    names = providers or tuple(name.strip() for name in os.environ.get("TICKER3_PROVIDERS", ",".join(PROVIDERS)).split(",") if name.strip())
    # A worker runs in its release folder, so it gets the absolute database path.
    arguments = ("--database", str(path.resolve()), *worker_arguments)
    if os.environ.get("TICKER_ENV_FILE"):
        arguments += ("--env-file", os.environ["TICKER_ENV_FILE"])
    engine = Engine(RefreshService((), snapshots), providers=list(names), settings_key=provider_settings_key,
                    builtins={"clock": ClockProvider()},
                    socket_path=Path(os.environ.get("TICKER3_SOCKET") or path.parent / "ticker3.sock"),
                    state_path=path.parent / "ticker3-supervisor.json", release_path=release_path,
                    initial_release=os.environ.get("TICKER3_RELEASE", "dev"), log_directory=path.parent / "ticker3-logs",
                    worker_arguments=arguments, supervisor_options=supervisor_options)
    application = BackendApplication(
        repository, snapshots, scheduler=engine, runtime=engine, spotify_service=spotify, catalog=catalog,
        weather_location_resolver=weather_resolver.resolve, owned_resources=(catalog, weather_resolver),
        mini_sprites=MiniSpriteService(Path(os.environ.get("TICKER_MINI_ASSET_CACHE", path.parent / "mini_sprites"))),
        mini_artwork=MiniArtworkService(),
    )
    engine.event_service = application.event_service
    engine.set_provider_demand(ProviderDemand(repository, application.schedule_service))
    app = create_app(application, firmware_manifest=FirmwareManifest.from_environment(),
                     firmware_directory=Path(os.environ.get("TICKER_FIRMWARE_DIR", path.parent / "firmware")))
    app.extensions["sports_ticker.backend_application"] = application
    app.extensions["sports_ticker.repository"] = repository
    app.extensions["sports_ticker.snapshot_store"] = snapshots
    app.extensions["sports_ticker.scheduler"] = engine
    app.extensions["sports_ticker.runtime"] = engine
    app.extensions["ticker3.engine"] = engine
    from sports_ticker.dashboard_v2.live_demo import PublicDemoData
    app.extensions["sports_ticker.public_demo_data"] = PublicDemoData(
        {name: EngineProvider(engine, name) for name in ("stock", "weather", "flights") if name in names})
    app.extensions["sports_ticker.incidents"] = incidents
    app.config["BACKEND_RELEASE"] = release_id()
    app.config["DASHBOARD_ASSET_CACHE"] = Path(os.environ.get("TICKER_DASHBOARD_ASSET_CACHE", path.parent / "rewrite_assets"))
    app.config["VERSION"] = build_version()
    app.extensions["sports_ticker.deployment_status"] = lambda: deployment_summary(path.parent)
    return app


def start_engine(app: Flask) -> Callable[[], None]:
    """Start the engine and return the function that stops it and the application."""
    engine = app.extensions["ticker3.engine"]
    engine.start()

    def stop() -> None:
        engine.stop()
        app.extensions["sports_ticker.public_demo_data"].close()
        for name in ("sports_ticker.dashboard_assets", "sports_ticker.dashboard_preview_assets"):
            close = getattr(app.extensions.get(name), "close", None)
            if callable(close):
                close()
        app.extensions["sports_ticker.backend_application"].close()

    return stop


def main() -> None:
    from dotenv import load_dotenv
    from hypercorn.asyncio import serve

    from sports_ticker.asgi import BackendASGI
    from sports_ticker.server import server_config

    faulthandler.enable()
    if hasattr(signal, "SIGUSR2"):
        faulthandler.register(signal.SIGUSR2, all_threads=True)
    load_dotenv(os.environ.get("TICKER_ENV_FILE"))
    app = BackendASGI(create_application(), http_threads=int(os.environ.get("TICKER_HTTP_THREADS", "8")), start=start_engine)
    app.flask_app.config["STACK_DUMP_SIGNAL"] = "SIGUSR2" if hasattr(signal, "SIGUSR2") else None
    asyncio.run(serve(app, server_config(), mode="asgi"))


if __name__ == "__main__":
    main()
