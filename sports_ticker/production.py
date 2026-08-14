"""Compose the complete production v2 backend without legacy runtime imports."""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Final
from urllib.parse import urlencode

from flask import Flask

from sports_ticker.api.app import create_app
from sports_ticker.application import BackendApplication, BackendRuntime, RefreshScheduler, RefreshService
from sports_ticker.application.state_store import SnapshotStore
from sports_ticker.fleet import PairingState, TickerRepository
from sports_ticker.integrations import SpotifyConfig, SpotifyIntegrationService, SpotifyMusicSource
from sports_ticker.leagues import SCOREBOARD_PATHS, league_for
from sports_ticker.providers import (
    EspnScoreboardProvider,
    EspnTeamCatalog,
    FlightsProvider,
    GolfProvider,
    MusicProvider,
    NewsProvider,
    OpenMeteoWeatherProvider,
    RacingProvider,
    StockProvider,
)
from sports_ticker.providers.live_sources import (
    ClockProvider,
    EmptyNewsSource,
    EspnGolfSource,
    EspnRacingSource,
    FinnhubStockSource,
    FlightRadarSource,
)


_ESPN_BASE: Final = "https://site.api.espn.com/apis/site/v2/sports"
_INTERVALS: Final = {
    "espn": 12.0,
    "weather": 300.0,
    "golf": 30.0,
    "racing": 15.0,
    "stock": 30.0,
    "flights": 30.0,
    "music": 0.6,
    "news": 30.0,
    "clock": 3600.0,
}


def create_production_application(
    database_path: str | Path | None = None,
) -> Flask:
    """Build the server-owned v2 application and its live refresh runtime."""

    path = Path(database_path or os.environ.get("TICKER_DATABASE_PATH", "ticker_data/ticker-v2.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    repository = TickerRepository(path)
    _provision_initial_ticker(repository)
    spotify = SpotifyIntegrationService(repository, SpotifyConfig.from_environment())
    providers = _providers(spotify)
    snapshots = SnapshotStore()
    refresh = RefreshService(providers.values(), snapshots)
    scheduler = RefreshScheduler(refresh)
    for name, provider in providers.items():
        scheduler.register_provider(name, _INTERVALS[name], _provider_fetch(provider))
    application = BackendApplication(
        repository,
        snapshots,
        scheduler=scheduler,
        spotify_service=spotify,
        catalog=EspnTeamCatalog(SCOREBOARD_PATHS),
    )
    runtime = BackendRuntime(
        scheduler,
        application.event_service,
        poll_interval=_positive_float(os.environ.get("TICKER_REFRESH_TICK_SECONDS", "0.2")),
    )
    application.runtime = runtime
    app = create_app(application)
    app.extensions["sports_ticker.backend_application"] = application
    app.extensions["sports_ticker.repository"] = repository
    app.extensions["sports_ticker.snapshot_store"] = snapshots
    app.extensions["sports_ticker.scheduler"] = scheduler
    app.extensions["sports_ticker.runtime"] = runtime
    app.config["DASHBOARD_ASSET_CACHE"] = Path(
        os.environ.get("TICKER_DASHBOARD_ASSET_CACHE", path.parent / "dashboard-assets")
    )
    app.config["VERSION"] = _build_version()
    return app


def start_runtime(app: Flask) -> Callable[[], None]:
    """Start the one owned refresh loop and return its explicit stop function."""

    runtime = app.extensions["sports_ticker.runtime"]
    from threading import Thread

    thread = Thread(target=runtime.run, name="ticker-v2-refresh", daemon=True)
    thread.start()

    def stop() -> None:
        runtime.stop()
        thread.join(timeout=8)
        assets = app.extensions.get("sports_ticker.dashboard_assets")
        close_assets = getattr(assets, "close", None)
        if callable(close_assets):
            close_assets()
        app.extensions["sports_ticker.backend_application"].close()

    return stop


def _providers(spotify: SpotifyIntegrationService) -> dict[str, object]:
    scoreboard_urls = {
        league: _scoreboard_url(league, path)
        for league, path in SCOREBOARD_PATHS.items()
    }
    return {
        "espn": EspnScoreboardProvider(scoreboard_urls),
        "weather": OpenMeteoWeatherProvider(),
        "golf": GolfProvider(EspnGolfSource()),
        "racing": RacingProvider(EspnRacingSource()),
        "stock": StockProvider(FinnhubStockSource()),
        "flights": FlightsProvider(FlightRadarSource()),
        "music": MusicProvider(SpotifyMusicSource(spotify)),
        "news": NewsProvider(EmptyNewsSource()),
        "clock": ClockProvider(),
    }


def _provider_fetch(provider: object):
    """Expose ticker-scoped music while retaining ordinary provider ports."""

    scoped = getattr(provider, "fetch_for_ticker", None)
    if callable(scoped):
        return scoped
    fetch = getattr(provider, "fetch", None)
    if not callable(fetch):
        raise TypeError("production provider must define fetch")
    return fetch


def _positive_float(value: object) -> float:
    result = float(value)
    if result <= 0:
        raise ValueError("TICKER_REFRESH_TICK_SECONDS must be positive")
    return result


def _build_version() -> str:
    """Read the deployed Git build identifier without a Git process."""

    explicit = os.environ.get("TICKER_BUILD", "").strip()
    if explicit:
        return explicit
    path = Path(os.environ.get("TICKER_VERSION_FILE", "VERSION"))
    try:
        return path.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def _provision_initial_ticker(repository: TickerRepository) -> None:
    """Create the first local ticker once when a deployment declares its ID."""

    ticker_id = os.environ.get("TICKER_INITIAL_TICKER_ID", "").strip()
    if not ticker_id:
        return
    existing = repository.get_ticker(ticker_id)
    if existing is not None:
        return
    repository.create_ticker(
        ticker_id,
        name=os.environ.get("TICKER_INITIAL_TICKER_NAME", "Ticker"),
        pairing=PairingState(pairing_code=f"{secrets.randbelow(1_000_000):06d}"),
    )


def _scoreboard_url(league: str, path: str) -> str:
    """Build each ESPN scoreboard URL with its own college grouping."""

    url = f"{_ESPN_BASE}/{path}/scoreboard"
    query = dict(league_for(league).scoreboard_query)
    return f"{url}?{urlencode(query)}" if query else url


__all__ = ["create_production_application", "start_runtime"]
