"""Root dashboard route."""

import time

from flask import render_template
from . import dashboard
from ..core import (
    state, tickers, data_lock,
    LEAGUE_OPTIONS,
    SERVER_VERSION, _VERSION_HASH,
)

_SERVER_START = time.time()


@dashboard.route('/')
def root():
    now      = time.time()
    uptime_s = int(now - _SERVER_START)
    h, rem   = divmod(uptime_s, 3600)
    m, s     = divmod(rem, 60)
    uptime_str = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

    with data_lock:
        active_sports = dict(state.get('active_sports', {}))
        global_mode   = state.get('mode', 'sports')

    sport_labels   = {item['id']: item['label'] for item in LEAGUE_OPTIONS}
    enabled_sports = [sport_labels.get(sid, sid) for sid, on in active_sports.items() if on]

    def _pill(label, on):
        cls = 'sp on' if on else 'sp off'
        return f'<span class="{cls}">{label}</span>'

    sport_html = ''.join(_pill(sport_labels.get(sid, sid), on) for sid, on in active_sports.items())

    return render_template(
        'dashboard/index.html',
        version_hash         = _VERSION_HASH,
        server_version       = SERVER_VERSION,
        uptime_str           = uptime_str,
        global_mode          = global_mode,
        enabled_sports_count = len(enabled_sports),
        sport_html           = sport_html,
    )
