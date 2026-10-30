"""Serve the ticker API with the Ticker 3 engine: python -m ticker.server

docs/api.md lists the routes. Provider workers push results, and the core
supervisor restarts, replaces, and rolls back those workers.

| Variable | Default | Meaning |
|---|---|---|
| `TICKER_DATABASE_PATH` | `ticker_data/ticker-v2.sqlite3` | The fleet database, as before |
| `TICKER3_SOCKET` | `<database folder>/ticker3.sock` | Worker socket. A Unix socket path must be at most 100 bytes. |
| `TICKER3_PROVIDERS` | all ten providers except clock | Providers that run in worker processes |
| `TICKER3_RELEASES` | none | Folder with one folder for each release. Without it, the release `dev` is this checkout. |
| `TICKER3_RELEASE` | the release folder of this checkout, else `dev` | The first active release of each provider |
| `TICKER_BIND_HOST`, `TICKER_PORT` | `127.0.0.1`, `5000` | The listen address |
| `TICKER_DEPLOY_TOKEN` | none | The operator secret. Without it, operator routes are closed. |
| `TICKER_INITIAL_TICKER_ID` | none | A ticker to create at the first start |
| `TICKER_FIRMWARE_DIR` | `<database folder>/firmware` | The Mini firmware binaries |
| `TICKER_HTTP_THREADS` | `8` | The number of HTTP requests that run at the same time |
"""
from __future__ import annotations

import asyncio
import faulthandler
import os
import secrets
import signal
import time
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask
from hypercorn.asyncio import serve
from hypercorn.config import Config

from ticker.ops.incidents import IncidentStore, release_id
from ticker.ops.public_status import summary as deployment_summary
from ticker.server.services import BackendApplication, RefreshService
from ticker.server.services.provider_demand import ProviderDemand
from ticker.server.services.provider_keys import provider_settings_key
from ticker.server.services.state_store import SnapshotStore
from ticker.server.mini_assets.mini_artwork import MiniArtworkService
from ticker.server.mini_assets.mini_service import MiniSpriteService
from ticker.server.firmware import FirmwareManifest
from ticker.server.store import PairingState, TickerRepository
from ticker.server.spotify import SpotifyConfig, SpotifyIntegrationService
from ticker.shared.leagues import TEAM_CATALOG_PATHS
from ticker.server.providers.catalog import EspnTeamCatalog
from ticker.server.providers.clock import ClockProvider
from ticker.server.providers.weather_location import WeatherLocationResolver

from ticker.server.api import create_app
from ticker.server.contract import WORKERS
from ticker.server.core.engine import Engine

PROVIDERS = WORKERS
CHECKOUT = Path(__file__).resolve().parents[2]


class EngineProvider:
    """Give a pull-style caller, such as the public demo, a provider port backed by the engine."""

    def __init__(self, engine: Engine, name: str) -> None:
        self.engine, self.name = engine, name

    def fetch_for_ticker(self, ticker_id, settings):
        return self.engine.read(self.name, ticker_id, settings)


def build_version() -> str:
    """Read the deployed build identifier without a Git process."""
    explicit = os.environ.get("TICKER_BUILD", "").strip()
    if explicit:
        return explicit
    try:
        return Path(os.environ.get("TICKER_VERSION_FILE", "VERSION")).read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def provision_initial_ticker(repository: TickerRepository) -> None:
    """Create the first local ticker once, when the deployment names its ID."""
    ticker_id = os.environ.get("TICKER_INITIAL_TICKER_ID", "").strip()
    if ticker_id and repository.get_ticker(ticker_id) is None:
        repository.create_ticker(ticker_id, name=os.environ.get("TICKER_INITIAL_TICKER_NAME", "Ticker"),
                                 pairing=PairingState(pairing_code=f"{secrets.randbelow(1_000_000):06d}"))


def initial_release() -> str:
    """Name the first release of each worker. A checkout inside the release folder is that release."""
    explicit = os.environ.get("TICKER3_RELEASE")
    if explicit:
        return explicit
    releases = os.environ.get("TICKER3_RELEASES")
    if releases and CHECKOUT.resolve().parent == Path(releases).resolve():
        return CHECKOUT.resolve().name
    return "dev"


def release_path(name: str) -> Path:
    releases = os.environ.get("TICKER3_RELEASES")
    if name == "dev" and not releases:
        return CHECKOUT
    if not releases or "/" in name or name.startswith("."):
        raise ValueError(f"release {name!r} has no folder")
    return Path(releases) / name


def create_application(database_path: str | Path | None = None, *, providers: tuple[str, ...] | None = None,
                       worker_arguments: tuple[str, ...] = (), supervisor_options: dict | None = None,
                       clock: Callable[[], float] = time.time) -> Flask:
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
                    initial_release=initial_release(), log_directory=path.parent / "ticker3-logs",
                    worker_arguments=arguments, supervisor_options=supervisor_options)
    application = BackendApplication(
        repository, snapshots, scheduler=engine, runtime=engine, spotify_service=spotify, catalog=catalog,
        weather_location_resolver=weather_resolver.resolve, owned_resources=(catalog, weather_resolver),
        mini_sprites=MiniSpriteService(Path(os.environ.get("TICKER_MINI_ASSET_CACHE", path.parent / "mini_sprites"))),
        mini_artwork=MiniArtworkService(), clock=clock,
    )
    engine.event_service = application.event_service
    engine.set_provider_demand(ProviderDemand(repository, application.schedule_service))
    app = create_app(application, firmware_manifest=FirmwareManifest.from_environment(),
                     firmware_directory=Path(os.environ.get("TICKER_FIRMWARE_DIR", path.parent / "firmware")))
    app.extensions["ticker.runtime"] = engine
    app.extensions["ticker3.engine"] = engine
    from ticker.server.web.live_demo import PublicDemoData
    app.extensions["ticker.public_demo"] = PublicDemoData(
        {name: EngineProvider(engine, name) for name in ("stock", "weather", "flights") if name in names})
    app.extensions["ticker.incidents"] = incidents
    app.config["BACKEND_RELEASE"] = release_id()
    app.config["DASHBOARD_ASSET_CACHE"] = Path(os.environ.get("TICKER_DASHBOARD_ASSET_CACHE", path.parent / "rewrite_assets"))
    app.config["VERSION"] = build_version()
    app.extensions["ticker.deployment_status"] = lambda: deployment_summary(path.parent)
    return app


def start_engine(app: Flask) -> Callable[[], None]:
    """Start the engine and return the function that stops it and the application."""
    engine = app.extensions["ticker3.engine"]
    engine.start()

    def stop() -> None:
        engine.stop()
        app.extensions["ticker.public_demo"].close()
        close = getattr(app.extensions.get("ticker.dashboard_preview_assets"), "close", None)
        if callable(close):
            close()
        app.extensions["ticker.application"].close()

    return stop


def http_threads() -> int:
    """Read the HTTP concurrency limit. A bad value stops the start before the database opens."""
    value = int(os.environ.get("TICKER_HTTP_THREADS", "8"))
    if value < 1:
        raise ValueError("TICKER_HTTP_THREADS must be positive")
    return value


def server_config() -> Config:
    """Return the Hypercorn settings: one process on the configured address."""
    host, port = os.environ.get("TICKER_BIND_HOST", "127.0.0.1"), os.environ.get("TICKER_PORT", "5000")
    config = Config()
    config.bind = [f"[{host}]:{port}" if ":" in host else f"{host}:{port}"]
    config.workers = 1
    config.websocket_ping_interval = 20.0
    return config


def create_asgi_application(database_path: str | Path | None = None):
    """Build the ASGI application. The engine starts in the ASGI lifespan."""
    from ticker.server.api.asgi import TickerASGI

    threads = http_threads()
    return TickerASGI(create_application(database_path), start=start_engine, http_threads=threads)


def main() -> None:
    faulthandler.enable()
    if hasattr(signal, "SIGUSR2"):
        faulthandler.register(signal.SIGUSR2, all_threads=True)
    load_dotenv(os.environ.get("TICKER_ENV_FILE"))
    application = create_asgi_application()
    application.app.config["STACK_DUMP_SIGNAL"] = "SIGUSR2" if hasattr(signal, "SIGUSR2") else None
    asyncio.run(serve(application, server_config(), mode="asgi"))


if __name__ == "__main__":
    main()
