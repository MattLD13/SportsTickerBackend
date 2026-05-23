"""Shared constants and helpers for sports mode buffer building."""

from .. import core as _core

globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})

spotify_fetcher = None
flight_tracker = None

SPORTS_LIKE_MODES = frozenset({'sports', 'live', 'my_teams', 'soccer'})


def _mode_builder_registry(mixin):
    """Single dispatch table for mode buffer builders (update + on-demand preview)."""
    return {
        'sports': mixin._build_sports_buffer,
        'live': mixin._build_sports_buffer,
        'my_teams': mixin._build_sports_buffer,
        'soccer': mixin._build_sports_buffer,
        'stocks': mixin._build_stocks_buffer,
        'weather': mixin._build_weather_buffer,
        'music': mixin._build_music_buffer,
        'clock': mixin._build_clock_buffer,
        'golf': mixin._build_golf_buffer,
        'masters': mixin._build_golf_buffer,
        'flights': mixin._build_flights_buffer,
        'flight_tracker': mixin._build_flight_tracker_buffer,
        'indycar': mixin._build_indycar_buffer,
        'f1': mixin._build_f1_buffer,
        'nascar': mixin._build_nascar_buffer,
    }


def _racing_loading_game(sport, payload_key, away_abbr, home_abbr, payload_extra):
    game = {
        'id': f'{sport}_loading',
        'type': 'racing',
        'sport': sport,
        'state': 'pre',
        'status': 'Loading',
        'is_shown': True,
        'startTimeUTC': '',
        'away_abbr': away_abbr,
        'home_abbr': home_abbr,
        'away_score': '',
        'home_score': '',
    }
    game[payload_key] = payload_extra
    return game
