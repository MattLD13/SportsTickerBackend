"""Root dashboard route."""

import json
import os
import time

from flask import render_template
from . import dashboard
from ..core import (
    state, tickers, data_lock,
    normalize_mode, resolve_ticker_id, effective_active_sports,
    LEAGUE_OPTIONS, DEFAULT_TICKER_SETTINGS,
    SERVER_VERSION, _VERSION_HASH,
)
from ..services.telemetry import fleet_health, server_snapshot

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


def _ago_str(seconds) -> str:
    """How long ago something happened, short enough for a table cell."""
    if seconds is None:
        return 'never'
    secs = int(max(0, seconds))
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _fleet_rows() -> list:
    """Every board, formatted for the page.

    A missing value prints as a dash rather than a zero. A board that never
    reported a temperature and a board sitting at 0 °C must not read the same.
    """
    rows = []
    for board in fleet_health():
        rows.append({
            'name':        board['name'],
            'id':          board['id'][:8],
            'link':        board['link'],
            'mode':        board['mode'].replace('_', ' '),
            'last_poll':   _ago_str(board['last_poll_ago']),
            'uptime':      _uptime_str(board['uptime']) if board['uptime'] else '—',
            'temp':        f"{board['temp_c']:.0f}C" if board['temp_c'] is not None else '—',
            'build':       board['build'] or '—',
            'dark_reason': board['dark_reason'],
        })
    return rows


def _active_ticker() -> dict:
    """The controller whose display this page is describing. Mirrors how
    /api/state resolves one; with several paired, the one that checked in most
    recently is the one worth reporting."""
    tid = resolve_ticker_id()
    if tid and tid in tickers:
        return tickers[tid]
    if not tickers:
        return {}
    return max(tickers.values(), key=lambda r: float(r.get('last_seen', 0) or 0))


def _display_mode() -> str:
    """The mode actually on the panel.

    state['mode'] is only the server-wide default. A paired ticker keeps its
    own mode in its settings and that is what it renders, so reading the global
    value reports whatever was last set globally rather than what is on screen.
    """
    settings = _active_ticker().get('settings') or {}
    return normalize_mode(settings.get('mode') or state.get('mode', 'sports'))


def _scroll_rate_px_s() -> int:
    """The controller advances the strip one pixel per `scroll_speed` seconds,
    so the on-panel rate is its reciprocal. Read it off the same ticker the
    rest of the page describes."""
    settings = _active_ticker().get('settings') or {}
    try:
        speed = float(settings.get('scroll_speed') or 0)
    except (TypeError, ValueError):
        speed = 0
    if speed <= 0:
        speed = float(DEFAULT_TICKER_SETTINGS.get('scroll_speed') or 0.03)
    return max(1, round(1.0 / speed))


def _on_air_ids(mode: str, active: dict) -> set:
    """League / utility ids that actually have something on the panel right now,
    as opposed to merely being enabled and polled."""
    current = normalize_mode(mode)

    if current in _MODE_TO_UTIL:
        return {_MODE_TO_UTIL[current]}

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


# Presets for the alert tester. One per team that gets tested by hand, with the
# play that shows the widest layout for its sport. Both St. Louis clubs are here
# on purpose: they share the abbreviation STL, so they also test that the
# league-qualified team match works.
ALERT_PRESETS = [
    {'name': 'Rangers',   'team': 'nhl:NYR', 'color': '#0038A8',
     'headline': 'POWER PLAY GOAL', 'detail': 'PANARIN', 'status': 'P2 6:03'},
    {'name': 'Giants',    'team': 'nfl:NYG', 'color': '#0B2265',
     'headline': 'RUSHING TD',      'detail': 'BARKLEY', 'status': 'Q3 8:42'},
    {'name': 'Cardinals', 'team': 'mlb:STL', 'color': '#C41E3A',
     'headline': '3-RUN HOME RUN',  'detail': 'GOLDSCHMIDT - 401 FT - 9TH HR', 'status': 'Bottom 6'},
    {'name': 'Blues',     'team': 'nhl:STL', 'color': '#002F87',
     'headline': 'HAT TRICK',       'detail': 'KYROU',   'status': 'P3 11:47'},
]


# Presets for the news tester, one per league so each fetcher's own shape can
# be seen on the panel. The two St. Louis clubs are here on purpose: they share
# the abbreviation STL, so they also test the league-qualified team match.
NEWS_PRESETS = [
    {'kind': 'TRADE', 'css': 'trade', 'label': 'Blues (NHL)', 'detail': 'CHI to STL',
     'body': {'kind': 'TRADE', 'sport': 'nhl', 'from': 'CHI', 'to': 'STL',
              'text': 'Andre Burakovsky for a 2027 second'}},
    {'kind': 'TRADE', 'css': 'trade', 'label': 'Rangers (NHL)', 'detail': 'VAN to NYR',
     'body': {'kind': 'TRADE', 'sport': 'nhl', 'from': 'VAN', 'to': 'NYR',
              'text': 'J.T. Miller for Kakko and a 2027 first'}},
    {'kind': 'TRADE', 'css': 'trade', 'label': 'Cardinals (MLB)', 'detail': 'TB to STL',
     'body': {'kind': 'TRADE', 'sport': 'mlb', 'from': 'TB', 'to': 'STL',
              'text': 'RHP Ryan Helsley for two prospects'}},
    {'kind': 'TRADE', 'css': 'trade', 'label': 'Giants (NFL)', 'detail': 'JAX to NYG',
     'body': {'kind': 'TRADE', 'sport': 'nfl', 'from': 'JAX', 'to': 'NYG',
              'text': 'RB Tank Bigsby for a 2026 fifth'}},
    {'kind': 'SIGNS', 'css': 'trade', 'label': 'Signing (NFL)', 'detail': 'FA to NYG',
     'body': {'kind': 'SIGNS', 'sport': 'nfl', 'from': 'FA', 'to': 'NYG',
              'text': 'Saquon Barkley to a three-year deal'}},
    {'kind': 'NEWS', 'css': 'news', 'label': 'Stock news', 'detail': 'stocks mode only',
     'body': {'domain': 'stocks', 'kind': 'NEWS', 'symbol': 'NVDA',
              'text': 'Nvidia beats on earnings as data centre demand holds'}},
]


@dashboard.route('/debug/news')
def news_tester():
    """Serve the page that pushes test news banners.

    The same shape as the score alert tester: the server renders the ticker
    list, the page calls the API on the same origin, and the response says
    which boards follow a club in the item.
    """
    return render_template('dashboard/news_tester.html',
                           tickers=_ticker_rows(),
                           presets=[dict(p, body=json.dumps(p['body'])) for p in NEWS_PRESETS])


def _ticker_rows():
    """Name, mode, and followed clubs for every ticker this backend knows."""
    with data_lock:
        rows = []
        for tid, rec in tickers.items():
            settings = rec.get('settings', {})
            teams = rec.get('my_teams')
            teams = list(state.get('my_teams', [])) if teams is None else list(teams)
            rows.append({
                'id': tid,
                'name': rec.get('name') or tid[:8],
                'mode': normalize_mode(settings.get('mode') or state.get('mode', 'sports')),
                'teams': ', '.join(teams[:4]),
            })
    return rows


@dashboard.route('/debug/alerts')
def alert_tester():
    """Serve the page that sends test score alerts.

    The page runs on the backend and not as a separate file. It calls
    /api/debug/score_alert on the same origin, so it needs no key and no CORS
    header. The ticker list comes from the server, so the page always shows the
    tickers that this backend knows.
    """
    return render_template('dashboard/alert_tester.html',
                           tickers=_ticker_rows(), presets=ALERT_PRESETS)


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
        # The page describes one board, so it must read that board's leagues.
        # Reading the global map showed a league as enabled that this panel had
        # switched off for itself.
        active_sports = effective_active_sports(_active_ticker())
        display_mode  = _display_mode()

    on_air = _on_air_ids(display_mode, active_sports)

    # The two flight utilities are not entries in active_sports — there is
    # nothing to toggle, they run off the tracked flight number and the airport
    # code. Reading them from active_sports made them permanently "Disabled",
    # including while Flight Tracker was the live mode. Treat them as enabled
    # when they are configured.
    configured = {}
    try:
        from ..workers import flight_tracker as _tracker
        if _tracker is not None:
            configured['flight_tracker'] = bool(str(getattr(_tracker, 'track_flight_id', '') or '').strip())
            configured['flight_airport'] = bool(str(getattr(_tracker, 'airport_code_iata', '') or '').strip()
                                                or str(getattr(_tracker, 'airport_code_icao', '') or '').strip())
    except Exception:
        pass

    # Keep LEAGUE_OPTIONS order so related leagues stay grouped.
    #   live = on the panel now · on = enabled and polling · off = disabled
    leagues = []
    for item in LEAGUE_OPTIONS:
        if item['id'] in configured:
            enabled = configured[item['id']]
        else:
            enabled = bool(active_sports.get(item['id'], False))
        leagues.append({
            'id':    item['id'],
            'label': item['label'],
            'type':  item.get('type', 'sport'),
            'state': 'live' if (enabled and item['id'] in on_air) else ('on' if enabled else 'off'),
        })

    fleet = _fleet_rows()

    return render_template(
        'dashboard/index.html',
        version_hash    = _VERSION_HASH,
        server_version  = SERVER_VERSION,
        uptime_str      = _uptime_str(now - _SERVER_START),
        fleet           = fleet,
        fleet_online    = sum(1 for b in fleet if b['link'] == 'online'),
        fleet_dark      = sum(1 for b in fleet if b['dark_reason']),
        server_health   = server_snapshot(),
        global_mode     = display_mode,
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
