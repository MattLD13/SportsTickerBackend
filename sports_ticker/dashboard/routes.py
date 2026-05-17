"""Root dashboard route."""

import time
from pathlib import Path

from flask import Response, jsonify, render_template, request
from . import dashboard
from ..core import (
    state, tickers, data_lock,
    LEAGUE_OPTIONS,
    SERVER_VERSION, _VERSION_HASH,
)

_SERVER_START = time.time()

_MODE_COLORS = {
    'sports':         ('#ff8c00', '#1a0e00'),
    'sports_full':    ('#ff8c00', '#1a0e00'),
    'soccer_full':    ('#ff8c00', '#1a0e00'),
    'live':           ('#ff4444', '#1a0000'),
    'my_teams':       ('#ff6600', '#1a0a00'),
    'music':          ('#cc44ff', '#120018'),
    'weather':        ('#44aaff', '#00101a'),
    'clock':          ('#888888', '#111111'),
    'stocks':         ('#44dd88', '#001a0e'),
    'golf':           ('#88dd44', '#091a00'),
    'masters':        ('#ffdd00', '#1a1500'),
    'flights':        ('#00ddcc', '#001a18'),
    'flight_tracker': ('#00ddcc', '#001a18'),
}

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TICKER_CONTROLLER_ROOT = _REPO_ROOT / 'ticker_controller'


@dashboard.route('/')
def root():
    now       = time.time()
    uptime_s  = int(now - _SERVER_START)
    h, rem    = divmod(uptime_s, 3600)
    m, s      = divmod(rem, 60)
    uptime_str = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

    with data_lock:
        ticker_list   = list(tickers.items())
        active_sports = dict(state.get('active_sports', {}))
        global_mode   = state.get('mode', 'sports')
        weather_city  = state.get('weather_city', 'New York')
        airport_iata  = state.get('airport_code_iata', 'EWR')
        track_flight_id = state.get('track_flight_id', '')

    named_paired = [
        (tid, rec) for tid, rec in ticker_list
        if rec.get('paired') and (rec.get('name') or '').strip()
    ]
    first_ticker_id = named_paired[0][0] if named_paired else ''

    sport_labels    = {item['id']: item['label'] for item in LEAGUE_OPTIONS}
    enabled_sports  = [sport_labels.get(sid, sid) for sid, on in active_sports.items() if on]

    def _sport_pill(label, on):
        cls = 'sp on' if on else 'sp off'
        return f'<span class="{cls}">{label}</span>'

    sport_html = ''.join(_sport_pill(sport_labels.get(sid, sid), on) for sid, on in active_sports.items())

    return render_template(
        'dashboard/index.html',
        # server info
        version_hash         = _VERSION_HASH,
        server_version       = SERVER_VERSION,
        uptime_str           = uptime_str,
        global_mode          = global_mode,
        enabled_sports_count = len(enabled_sports),
        # ticker state
        weather_city    = weather_city,
        airport_iata    = airport_iata,
        track_flight_id = track_flight_id,
        ticker_id       = first_ticker_id,
        # pre-rendered HTML
        sport_html = sport_html,
    )


 
