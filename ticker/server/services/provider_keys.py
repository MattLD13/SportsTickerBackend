"""Name the settings that can change the result of each provider."""

from __future__ import annotations

from ticker.shared.domain import DisplaySettings
from ticker.shared.leagues import ESPN_SCOREBOARD_PATHS, FOTMOB_LEAGUES, TEAM_CATALOG_PATHS


def provider_settings_key(name: str):
    """Return only the settings that can change one provider result."""

    if name == "espn":
        return lambda settings: _sports_key(settings, ESPN_SCOREBOARD_PATHS) + (
            tuple(sorted(settings.active_conferences.items())),
            settings.my_teams,
            settings.score_alerts,
            settings.live_delay_mode,
            settings.live_delay_seconds,
        )
    if name == "fotmob":
        return lambda settings: _sports_key(settings, FOTMOB_LEAGUES) + (
            settings.my_teams,
            settings.score_alerts,
            settings.live_delay_mode,
            settings.live_delay_seconds,
        )
    if name == "news":
        return lambda settings: _sports_key(settings, TEAM_CATALOG_PATHS) + (
            settings.my_teams,
        )
    if name == "golf":
        return lambda settings: (settings.timezone, settings.active_sports.get("golf", True))
    if name == "racing":
        return lambda settings: _sports_key(settings, ("f1", "indycar"))
    if name == "stock":
        return lambda settings: (settings.custom_stock_symbols,)
    if name == "weather":
        return lambda settings: (settings.weather_lat, settings.weather_lon, settings.weather_city)
    if name == "flights":
        return lambda settings: (
            settings.airport_code_iata,
            settings.airport_code_icao,
            settings.airport_name,
            settings.track_flight_id,
            settings.track_guest_name,
        )
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


__all__ = ["provider_settings_key"]
