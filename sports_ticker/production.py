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
from sports_ticker.domain import DisplaySettings
from sports_ticker.fleet import PairingState, TickerRepository
from sports_ticker.integrations import SpotifyConfig, SpotifyIntegrationService, SpotifyMusicSource
from sports_ticker.leagues import ESPN_SCOREBOARD_PATHS, FOTMOB_LEAGUES, TEAM_CATALOG_PATHS, league_for
from sports_ticker.providers import (
    EspnScoreboardProvider,
    EspnTeamCatalog,
    FotMobSoccerProvider,
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
    EspnNewsSource,
    EspnGolfSource,
    EspnRacingSource,
    FinnhubStockSource,
    FlightRadarSource,
)


_ESPN_BASE: Final = "https://site.api.espn.com/apis/site/v2/sports"
_INTERVALS: Final = {
    "espn": 5.0,
    "fotmob": 5.0,
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
        scheduler.register_provider(
            name,
            _INTERVALS[name],
            _provider_fetch(provider),
            settings_key=_provider_settings_key(name),
        )
    application = BackendApplication(
        repository,
        snapshots,
        scheduler=scheduler,
        spotify_service=spotify,
        catalog=EspnTeamCatalog(TEAM_CATALOG_PATHS),
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
        for league, path in ESPN_SCOREBOARD_PATHS.items()
    }
    return {
        "espn": EspnScoreboardProvider(scoreboard_urls),
        "fotmob": FotMobSoccerProvider(FOTMOB_LEAGUES),
        "weather": OpenMeteoWeatherProvider(),
        "golf": GolfProvider(EspnGolfSource()),
        "racing": RacingProvider(EspnRacingSource()),
        "stock": StockProvider(FinnhubStockSource()),
        "flights": FlightsProvider(FlightRadarSource()),
        "music": MusicProvider(SpotifyMusicSource(spotify)),
        "news": NewsProvider(
            EspnNewsSource(
                {
                    league: f"{_ESPN_BASE}/{path}/news?limit=20"
                    for league, path in ESPN_SCOREBOARD_PATHS.items()
                }
            )
        ),
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


def _provider_settings_key(name: str):
    """Return only the settings that can change one provider result."""

    if name == "espn":
        return lambda settings: _sports_key(settings, ESPN_SCOREBOARD_PATHS) + (
            settings.my_teams,
            settings.score_alerts,
            settings.live_delay_mode,
            settings.live_delay_seconds,
        )
    if name == "fotmob":
        return lambda settings: _sports_key(settings, FOTMOB_LEAGUES)
    if name == "golf":
        return lambda settings: (settings.timezone, settings.active_sports.get("golf", True))
    if name == "racing":
        return lambda settings: _sports_key(settings, ("f1", "indycar"))
    if name == "stock":
        return lambda settings: ()
    if name == "weather":
        return lambda settings: (settings.weather_lat, settings.weather_lon, settings.weather_city)
    if name == "flights":
        return lambda settings: (
            settings.airport_code_iata,
            settings.airport_code_icao,
            settings.track_flight_id,
            settings.track_guest_name,
        )
    if name == "news":
        return lambda settings: (settings.mode, settings.my_teams)
    if name == "clock":
        return lambda settings: (settings.timezone,)
    return lambda settings: ()


def _sports_key(settings: DisplaySettings, identifiers) -> tuple[object, ...]:
    """Return active settings for one fixed sports provider collection."""

    return (
        settings.timezone,
        tuple(
            (str(identifier), settings.active_sports.get(str(identifier), True))
            for identifier in identifiers
        ),
    )


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
