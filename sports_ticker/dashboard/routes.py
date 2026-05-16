"""Root dashboard route."""

import time
from pathlib import Path

import requests
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

    def _ago(last):
        if not last: return 'never', 'offline'
        secs = int(now - last)
        if secs < 30:   return f'{secs}s ago', 'online'
        if secs < 300:  return f'{secs}s ago', 'recent'
        if secs < 3600: return f'{secs//60}m ago', 'idle'
        return f'{secs//3600}h ago', 'offline'

    def _ticker_cards(items):
        if not items:
            return '<p class="empty-note">None</p>'
        cards = []
        for tid, rec in sorted(items, key=lambda x: (x[1].get('last_seen') or 0), reverse=True):
            name     = (rec.get('name') or '').strip() or tid[:8]
            mode     = rec.get('settings', {}).get('mode') or rec.get('mode') or 'sports'
            city     = rec.get('settings', {}).get('weather_city') or '—'
            last     = rec.get('last_seen', 0)
            ago_str, status = _ago(last)
            mc, mbg  = _MODE_COLORS.get(mode, ('#888', '#111'))
            dot_color = {'online': '#44ff44', 'recent': '#ffaa00', 'idle': '#ff6600', 'offline': '#333'}.get(status, '#333')
            dot_glow  = {'online': '0 0 6px #44ff44', 'recent': '0 0 6px #ffaa00'}.get(status, 'none')
            cards.append(f'''<div class="tc">
  <div class="tc-header">
    <span class="dot" style="background:{dot_color};box-shadow:{dot_glow}"></span>
    <span class="tc-name">{name}</span>
    <span class="tc-mode" style="color:{mc};background:{mbg}">{mode.upper().replace("_"," ")}</span>
  </div>
  <div class="tc-meta">
    <span>{city}</span>
    <span style="color:{"#44ff44" if status=="online" else "#666"}">{ago_str}</span>
  </div>
</div>''')
        return '\n'.join(cards)

    sport_labels    = {item['id']: item['label'] for item in LEAGUE_OPTIONS}
    enabled_sports  = [sport_labels.get(sid, sid) for sid, on in active_sports.items() if on]

    def _sport_pill(label, on):
        cls = 'sp on' if on else 'sp off'
        return f'<span class="{cls}">{label}</span>'

    sport_html      = ''.join(_sport_pill(sport_labels.get(sid, sid), on) for sid, on in active_sports.items())
    ticker_cards_html = _ticker_cards(
        sorted(named_paired, key=lambda x: x[1].get('last_seen') or 0, reverse=True)[:1]
    )

    return render_template(
        'dashboard/index.html',
        # server info
        version_hash    = _VERSION_HASH,
        server_version  = SERVER_VERSION,
        uptime_str      = uptime_str,
        global_mode     = global_mode,
        named_paired_count   = len(named_paired),
        enabled_sports_count = len(enabled_sports),
        # ticker state
        weather_city    = weather_city,
        airport_iata    = airport_iata,
        track_flight_id = track_flight_id,
        ticker_id       = first_ticker_id,
        # pre-rendered HTML
        ticker_cards_html = ticker_cards_html,
        sport_html        = sport_html,
    )


@dashboard.route('/api/browser/ticker_controller_bundle')
def browser_ticker_bundle():
    files = {}
    if _TICKER_CONTROLLER_ROOT.exists():
        for path in sorted(_TICKER_CONTROLLER_ROOT.rglob('*.py')):
            rel_path = path.relative_to(_REPO_ROOT).as_posix()
            files[rel_path] = path.read_text(encoding='utf-8')
    return jsonify({
        'root': 'ticker_controller',
        'files': files,
    })


@dashboard.route('/api/browser/image_proxy')
def browser_image_proxy():
    url = request.args.get('url', '').strip()
    if not url:
        return Response(status=400)

    try:
        resp = requests.get(url, timeout=8, verify=False)
        content_type = resp.headers.get('Content-Type', 'application/octet-stream')
        proxy = Response(resp.content, mimetype=content_type)
        proxy.headers['Cache-Control'] = 'no-store'
        return proxy
    except Exception:
        return Response(status=502)
