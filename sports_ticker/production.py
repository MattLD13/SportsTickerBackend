"""Compose the complete production v2 backend without legacy runtime imports."""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Final

from flask import Flask

from sports_ticker.api.app import create_app
from sports_ticker.application import BackendApplication, BackendRuntime, RefreshScheduler, RefreshService
from sports_ticker.application.state_store import SnapshotStore
from sports_ticker.fleet import PairingState, TickerRepository
from sports_ticker.integrations import SpotifyConfig, SpotifyIntegrationService, SpotifyMusicSource
from sports_ticker.providers import (
    EspnScoreboardProvider,
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
_SCOREBOARD_PATHS: Final = {
    "nfl": "football/nfl",
    "mlb": "baseball/mlb",
    "nhl": "hockey/nhl",
    "nba": "basketball/nba",
    "ncf_fbs": "football/college-football",
    "ncf_fcs": "football/college-football",
    "march_madness": "basketball/mens-college-basketball",
    "soccer_epl": "soccer/eng.1",
    "soccer_fa_cup": "soccer/eng.fa",
    "soccer_champ": "soccer/eng.2",
    "soccer_champions_league": "soccer/uefa.champions",
    "soccer_mls": "soccer/usa.1",
}
_INTERVALS: Final = {
    "espn": 12.0,
    "weather": 300.0,
    "golf": 30.0,
    "racing": 15.0,
    "stock": 60.0,
    "flights": 30.0,
    "music": 10.0,
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
    )
    runtime = BackendRuntime(
        scheduler,
        application.event_service,
        poll_interval=_positive_float(os.environ.get("TICKER_REFRESH_TICK_SECONDS", "1")),
    )
    application.runtime = runtime
    app = create_app(application)
    app.extensions["sports_ticker.backend_application"] = application
    app.extensions["sports_ticker.repository"] = repository
    app.extensions["sports_ticker.snapshot_store"] = snapshots
    app.extensions["sports_ticker.scheduler"] = scheduler
    app.extensions["sports_ticker.runtime"] = runtime
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
        app.extensions["sports_ticker.backend_application"].close()

    return stop


def _providers(spotify: SpotifyIntegrationService) -> dict[str, object]:
    scoreboard_urls = {
        league: _scoreboard_url(league, path)
        for league, path in _SCOREBOARD_PATHS.items()
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


def _provision_initial_ticker(repository: TickerRepository) -> None:
    """Create the first local ticker once when a deployment declares its ID."""

    ticker_id = os.environ.get("TICKER_INITIAL_TICKER_ID", "").strip()
    if not ticker_id:
        return
    existing = repository.get_ticker(ticker_id)
    if existing is not None:
        if _initial_ticker_is_paired() and not existing.pairing.paired:
            repository.update_ticker(ticker_id, pairing=PairingState(paired=True))
        return
    repository.create_ticker(
        ticker_id,
        name=os.environ.get("TICKER_INITIAL_TICKER_NAME", "Ticker"),
        pairing=(
            PairingState(paired=True)
            if _initial_ticker_is_paired()
            else PairingState(pairing_code=f"{secrets.randbelow(1_000_000):06d}")
        ),
    )


def _initial_ticker_is_paired() -> bool:
    """Return the one-time migration setting for the known initial ticker."""

    value = os.environ.get("TICKER_INITIAL_TICKER_PAIRED", "").strip().lower()
    return value in {"1", "true", "yes"}


def _scoreboard_url(league: str, path: str) -> str:
    """Build each ESPN scoreboard URL with its own college grouping."""

    url = f"{_ESPN_BASE}/{path}/scoreboard"
    suffix = {
        "ncf_fbs": "?groups=80",
        "ncf_fcs": "?groups=81",
        "march_madness": "?groups=100&limit=100",
    }.get(league, "")
    return f"{url}{suffix}"


__all__ = ["create_production_application", "start_runtime"]
