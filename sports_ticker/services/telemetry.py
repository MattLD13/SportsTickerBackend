"""Fleet health: what each board reports, and what the server knows about it.

A board that goes dark looks the same from the outside whether it is asleep,
offline, unpaired, or simply showing an empty league. This module keeps the
facts that tell those apart, so /api/health and the dashboard can name the
reason instead of leaving someone to guess at it.

The board reports its own facts as headers on the /data poll it already makes.
See ticker_controller/telemetry.py for the sending half.
"""

import os
import threading
import time

from ..core import state, tickers, data_lock, normalize_mode

# A controller polls about twice a second. A board that has missed a few polls
# is still healthy, one that has missed a minute of them is not answering, and
# past the stale mark it is off, crashed, or cut off from the network.
ONLINE_WITHIN = 15.0
STALE_WITHIN = 120.0

_TELEMETRY_HEADERS = {
    'X-Ticker-Uptime': ('uptime', float),
    'X-Ticker-Temp':   ('temp_c', float),
    'X-Ticker-Build':  ('build', str),
    'X-Ticker-Python': ('python', str),
}


def record_from_request(rec, req) -> None:
    """Store the telemetry headers on a /data poll, if the board sent any.

    Absent headers leave the previous reading alone rather than clearing it, so
    one odd request cannot erase what a board reported a moment ago.
    """
    if not isinstance(rec, dict):
        return
    reported = {}
    for header, (key, cast) in _TELEMETRY_HEADERS.items():
        raw = req.headers.get(header)
        if raw is None or str(raw).strip() == '':
            continue
        try:
            reported[key] = cast(str(raw).strip())
        except (TypeError, ValueError):
            continue
    if not reported:
        return
    telemetry = dict(rec.get('telemetry') or {})
    telemetry.update(reported)
    telemetry['reported_at'] = time.time()
    rec['telemetry'] = telemetry


def _link_state(seconds_since_poll):
    if seconds_since_poll is None:
        return 'never'
    if seconds_since_poll <= ONLINE_WITHIN:
        return 'online'
    if seconds_since_poll <= STALE_WITHIN:
        return 'stale'
    return 'offline'


def _dark_reason(rec, link, settings):
    """Why this board shows nothing, or None when it should be showing content.

    Ordered by what a person would check first: a board that is not answering
    cannot be asleep in any way that matters, and one that never paired never
    got as far as a mode.
    """
    if link in ('offline', 'never'):
        return 'backend cannot reach it — the panel draws its offline screen'
    if not rec.get('paired') or not rec.get('clients'):
        return 'not paired — the panel shows its pairing code'
    try:
        brightness = float(settings.get('brightness', 100))
    except (TypeError, ValueError):
        brightness = 100.0
    if brightness <= 0:
        return 'brightness is 0 — asleep on purpose'
    return None


def ticker_health(tid, rec, now=None) -> dict:
    """One board's health, flat enough to render without further lookups."""
    now = time.time() if now is None else now
    settings = rec.get('settings') or {}
    telemetry = rec.get('telemetry') or {}

    last_seen = float(rec.get('last_seen', 0) or 0)
    since_poll = round(now - last_seen, 1) if last_seen else None
    link = _link_state(since_poll)

    reported_at = float(telemetry.get('reported_at', 0) or 0)
    return {
        'id': tid,
        'name': rec.get('name') or tid[:8],
        'link': link,
        'mode': normalize_mode(settings.get('mode') or state.get('mode', 'sports')),
        'last_poll_ago': since_poll,
        'uptime': telemetry.get('uptime'),
        'temp_c': telemetry.get('temp_c'),
        'build': telemetry.get('build'),
        'python': telemetry.get('python'),
        'telemetry_age': round(now - reported_at, 1) if reported_at else None,
        'brightness': settings.get('brightness'),
        'paired': bool(rec.get('paired') and rec.get('clients')),
        'dark_reason': _dark_reason(rec, link, settings),
    }


def fleet_health(now=None) -> list:
    """Every known board, worst link first, so trouble sorts to the top."""
    now = time.time() if now is None else now
    with data_lock:
        rows = [ticker_health(tid, rec, now) for tid, rec in tickers.items()]
    order = {'never': 0, 'offline': 1, 'stale': 2, 'online': 3}
    rows.sort(key=lambda r: (order.get(r['link'], 9), r['name'].lower()))
    return rows


def server_snapshot() -> dict:
    """Backend process health. Reads /proc on Linux, degrades elsewhere."""
    rss_mb = None
    fds = None
    try:
        with open('/proc/self/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    rss_mb = round(int(line.split()[1]) / 1024.0, 1)
                    break
    except Exception:
        pass
    try:
        fds = len(os.listdir('/proc/self/fd'))
    except Exception:
        pass
    with data_lock:
        ticker_count = len(tickers)
    return {
        'rss_mb': rss_mb,
        'threads': threading.active_count(),
        'fds': fds,
        'tickers': ticker_count,
    }


def server_snapshot_line(snapshot=None) -> str:
    """The one-line form the housekeeping worker writes to the log."""
    snap = server_snapshot() if snapshot is None else snapshot
    rss = 'n/a' if snap['rss_mb'] is None else f"{snap['rss_mb']}MB"
    fds = 'n/a' if snap['fds'] is None else str(snap['fds'])
    return (f"[HEALTH] rss={rss} threads={snap['threads']} "
            f"fds={fds} tickers={snap['tickers']}")
