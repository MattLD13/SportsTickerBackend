"""Root dashboard route."""

import os
import time

from flask import render_template
from . import dashboard
from ..core import (
    state, tickers, data_lock,
    normalize_mode,
    LEAGUE_OPTIONS, DEFAULT_TICKER_SETTINGS,
    SERVER_VERSION, _VERSION_HASH,
)

PANEL_W, PANEL_H = 384, 32

# Display modes shown on the landing page, in presentation order.
DISPLAY_MODES = [
    {'id': 'sports',         'name': 'Sports',         'desc': 'Every active league, rotating',            'group': 'Sports'},
    {'id': 'sports_full',    'name': 'Sports Full',    'desc': 'Full-bleed scoreboard for a pinned game',  'group': 'Sports'},
    {'id': 'live',           'name': 'Live',           'desc': 'Only games currently in progress',         'group': 'Sports'},
    {'id': 'my_teams',       'name': 'My Teams',       'desc': 'Only the teams you follow',                'group': 'Sports'},
    {'id': 'stocks',         'name': 'Stocks',         'desc': 'Market ticker scroll',                     'group': 'Data'},
    {'id': 'weather',        'name': 'Weather',        'desc': 'Detailed conditions card',                 'group': 'Data'},
    {'id': 'music',          'name': 'Music',          'desc': 'Spotify now playing, on vinyl',            'group': 'Data'},
    {'id': 'clock',          'name': 'Clock',          'desc': 'Full-screen clock and date',               'group': 'Data'},
    {'id': 'flights',        'name': 'Flights',        'desc': 'Airport arrivals / departures board',      'group': 'Flight'},
    {'id': 'flight_tracker', 'name': 'Flight Tracker', 'desc': 'A single tracked flight, gate to gate',    'group': 'Flight'},
]

# Modes the /api/preview/strip.png endpoint can render for the live demo.
# `kind` drives how the browser plays it back:
#   scroll — a wide strip that pans horizontally at the panel's native rate
#   static — one full-panel frame
#   canvas — drawn client-side to mirror the controller's own animation
DEMO_MODES = [
    {'id': 'sports',  'label': 'Sports',  'kind': 'scroll'},
    {'id': 'live',    'label': 'Live',    'kind': 'scroll'},
    {'id': 'stocks',  'label': 'Stocks',  'kind': 'scroll'},
    {'id': 'weather', 'label': 'Weather', 'kind': 'static'},
    {'id': 'music',   'label': 'Music',   'kind': 'canvas'},
    {'id': 'clock',   'label': 'Clock',   'kind': 'canvas'},
]

# Utility modes that map one-to-one onto a LEAGUE_OPTIONS entry.
_MODE_TO_UTIL = {
    'weather':        'weather',
    'clock':          'clock',
    'music':          'music',
    'flight_tracker': 'flight_tracker',
    'flights':        'flight_airport',
}


def _process_start_time() -> float:
    """Real process start time. Reads /proc on Linux so the number survives a
    module reload; falls back to import time everywhere else."""
    try:
        with open('/proc/uptime') as f:
            sys_uptime = float(f.read().split()[0])
        with open('/proc/self/stat') as f:
            fields = f.read().rsplit(') ', 1)[1].split()
        start_ticks = float(fields[19])              # field 22, after comm
        hz = os.sysconf('SC_CLK_TCK')
        return time.time() - (sys_uptime - start_ticks / hz)
    except Exception:
        return time.time()


_SERVER_START = _process_start_time()


def _uptime_str(seconds: float) -> str:
    d, rem = divmod(int(max(0, seconds)), 86400)
    h, rem = divmod(rem, 3600)
    m, s   = divmod(rem, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m {s}s"


def _scroll_rate_px_s() -> int:
    """The controller advances the strip one pixel per `scroll_speed` seconds,
    so the on-panel rate is its reciprocal. Prefer a live controller's setting
    over the shipped default."""
    speeds = [
        float(rec.get('settings', {}).get('scroll_speed') or 0)
        for rec in tickers.values()
    ]
    speeds = [s for s in speeds if s > 0]
    if not speeds:
        speeds = [float(DEFAULT_TICKER_SETTINGS.get('scroll_speed') or 0.03)]
    rates = [1.0 / s for s in speeds]            # seconds-per-pixel → pixels-per-second
    return max(1, round(sum(rates) / len(rates)))


def _on_air_ids(mode: str) -> set:
    """League / utility ids that actually have something on the panel right now,
    as opposed to merely being enabled and polled."""
    current = normalize_mode(mode)

    if current in _MODE_TO_UTIL:
        return {_MODE_TO_UTIL[current]}

    active = state.get('active_sports', {})
    if current == 'stocks':
        return {sid for sid, on in active.items() if on and sid.startswith('stock_')}

    try:
        from ..workers import fetcher
        games = fetcher.get_mode_snapshot(current, 0)
        # Reuse the strip renderer's own visibility rules so this agrees with
        # what the panel is actually scrolling — a league whose only game is
        # postponed or hidden is not "on the panel".
        from ..routes.preview import _filter_preview_games
        games = _filter_preview_games(games, current)
    except Exception:
        return set()

    ids = set()
    for g in games:
        sport = str(g.get('sport', '')).lower()
        if sport:
            ids.add('mlb' if sport == 'wbc' else sport)
    return ids


@dashboard.route('/demo')
def demo():
    return render_template(
        'demo_ticker.html',
        demo_modes  = DEMO_MODES,
        panel_w     = PANEL_W,
        panel_h     = PANEL_H,
        scroll_px_s = _scroll_rate_px_s(),
    )


@dashboard.route('/')
def root():
    now = time.time()

    with data_lock:
        active_sports = dict(state.get('active_sports', {}))
        global_mode   = state.get('mode', 'sports')

    on_air = _on_air_ids(global_mode)

    # Keep LEAGUE_OPTIONS order so related leagues stay grouped.
    #   live = on the panel now · on = enabled and polling · off = disabled
    leagues = []
    for item in LEAGUE_OPTIONS:
        enabled = bool(active_sports.get(item['id'], False))
        leagues.append({
            'id':    item['id'],
            'label': item['label'],
            'type':  item.get('type', 'sport'),
            'state': 'live' if (enabled and item['id'] in on_air) else ('on' if enabled else 'off'),
        })

    return render_template(
        'dashboard/index.html',
        version_hash    = _VERSION_HASH,
        server_version  = SERVER_VERSION,
        uptime_str      = _uptime_str(now - _SERVER_START),
        global_mode     = global_mode,
        sports_leagues  = [l for l in leagues if l['type'] == 'sport'],
        util_leagues    = [l for l in leagues if l['type'] == 'util'],
        market_leagues  = [l for l in leagues if l['type'] == 'stock'],
        live_count      = sum(1 for l in leagues if l['state'] == 'live'),
        active_count    = sum(1 for l in leagues if l['state'] != 'off'),
        league_count    = len(leagues),
        display_modes   = DISPLAY_MODES,
        demo_modes      = DEMO_MODES,
        panel_w         = PANEL_W,
        panel_h         = PANEL_H,
        scroll_px_s     = _scroll_rate_px_s(),
    )
