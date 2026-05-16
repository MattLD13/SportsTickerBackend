import time
from flask import request, jsonify, make_response
from ..routes_runtime import app
from ..core import (
    state, tickers, data_lock,
    LEAGUE_OPTIONS, _league_sort_key, _auto_category_for_option, resolve_ticker_id,
    SERVER_VERSION, _VERSION_DATE, _VERSION_BUILD, _VERSION_HASH,
)
from ..workers import spotify_fetcher

_SERVER_START = time.time()

@app.route('/leagues', methods=['GET'])
def get_league_options():
    ticker_id = request.args.get('id')
    if not ticker_id:
        cid = request.headers.get('X-Client-ID')
        ticker_id = resolve_ticker_id(client_id=cid)

    league_meta = []
    for item in sorted(LEAGUE_OPTIONS, key=_league_sort_key):
        league_meta.append({
            'id': item['id'],
            'label': item['label'],
            'type': item['type'],
            'category': _auto_category_for_option(item),
            'enabled': state['active_sports'].get(item['id'], False)
        })
    # Add Music Option explicitly if not in list
    if not any(x['id'] == 'music' for x in league_meta):
        league_meta.append({'id': 'music', 'label': 'Music', 'type': 'util', 'enabled': state['active_sports'].get('music', False)})
        
    return jsonify(league_meta)


@app.route('/api/spotify/now', methods=['GET'])
def api_spotify():
    data = spotify_fetcher.get_cached_state()
    # If playing, calculate real-time progress based on elapsed time since last poll
    if data.get('is_playing') and data.get('last_fetch_ts'):
        elapsed = time.time() - data['last_fetch_ts']
        data['progress'] = min(data['progress'] + elapsed, data.get('duration', 0))
    return jsonify(data)


@app.route('/api/blank-logo.png', methods=['GET'])
def api_blank_logo():
    # 1x1 transparent PNG (keeps logo slot blank with no fallback text).
    png = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01'
        b'\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    resp = make_response(png)
    resp.headers['Content-Type'] = 'image/png'
    resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return resp


@app.route('/')
def root():
    uptime_s = int(time.time() - _SERVER_START)
    h, rem = divmod(uptime_s, 3600)
    m, s = divmod(rem, 60)
    uptime_str = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

    with data_lock:
        ticker_list = list(tickers.items())
        active_sports = dict(state.get('active_sports', {}))
        global_mode = state.get('mode', '—')
        weather_city = state.get('weather_city', '—')

    paired = [(tid, rec) for tid, rec in ticker_list if rec.get('paired')]
    unpaired = [(tid, rec) for tid, rec in ticker_list if not rec.get('paired')]

    def ticker_rows(items):
        if not items:
            return '<tr><td colspan="4" style="color:#555;text-align:center">none</td></tr>'
        rows = []
        for tid, rec in items:
            mode = rec.get('settings', {}).get('mode') or rec.get('mode') or '—'
            last = rec.get('last_seen', 0)
            ago = int(time.time() - last) if last else None
            ago_str = f"{ago}s ago" if ago is not None and ago < 3600 else ("never" if not last else f"{ago//60}m ago")
            city = rec.get('settings', {}).get('weather_city') or '—'
            rows.append(f'<tr><td>{tid}</td><td>{mode}</td><td>{city}</td><td style="color:{"#4f4" if ago is not None and ago < 30 else "#f84"}">{ago_str}</td></tr>')
        return ''.join(rows)

    sport_badges = []
    sport_labels = {item['id']: item['label'] for item in LEAGUE_OPTIONS}
    for sid, enabled in active_sports.items():
        label = sport_labels.get(sid, sid)
        color = '#1a4a2a' if enabled else '#2a2a2a'
        text_color = '#4f4' if enabled else '#555'
        sport_badges.append(f'<span style="background:{color};color:{text_color};padding:2px 7px;border-radius:3px;font-size:11px;margin:2px;display:inline-block">{label}</span>')

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="15">
<title>Sports Ticker</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0d0d0f; color: #ccc; font-family: 'Courier New', monospace; font-size: 13px; padding: 24px; }}
  h1 {{ color: #fff; font-size: 22px; letter-spacing: 2px; text-transform: uppercase; }}
  h2 {{ color: #aaa; font-size: 12px; letter-spacing: 3px; text-transform: uppercase; margin: 24px 0 8px; border-bottom: 1px solid #222; padding-bottom: 4px; }}
  .meta {{ color: #555; font-size: 11px; margin-top: 4px; }}
  .pill {{ display:inline-block; background:#1a2a1a; color:#4f4; border-radius:3px; padding:1px 8px; font-size:11px; margin-left:8px; }}
  .pill.warn {{ background:#2a1a0a; color:#f84; }}
  table {{ width:100%; border-collapse:collapse; margin-top:4px; }}
  th {{ color:#555; text-align:left; font-size:11px; padding:4px 8px; border-bottom:1px solid #222; }}
  td {{ padding:5px 8px; border-bottom:1px solid #161618; }}
  .card {{ background:#111113; border:1px solid #1e1e22; border-radius:6px; padding:16px; margin-bottom:16px; }}
  .stat {{ display:inline-block; margin-right:32px; }}
  .stat .val {{ font-size:22px; color:#fff; }}
  .stat .lbl {{ font-size:10px; color:#555; text-transform:uppercase; letter-spacing:1px; }}
  a {{ color:#4af; text-decoration:none; }}
</style>
</head>
<body>
<h1>⬛ Sports Ticker</h1>
<p class="meta">
  <strong style="color:#fff">{SERVER_VERSION}</strong>
  &nbsp;·&nbsp; commit <a href="https://github.com/MattLD13/SportsTickerBackend/commit/{_VERSION_HASH}" target="_blank">{_VERSION_HASH}</a>
  &nbsp;·&nbsp; {_VERSION_DATE}
  &nbsp;·&nbsp; build #{_VERSION_BUILD}
</p>

<div class="card" style="margin-top:20px">
  <div class="stat"><div class="val">{uptime_str}</div><div class="lbl">Uptime</div></div>
  <div class="stat"><div class="val">{len(paired)}</div><div class="lbl">Paired Tickers</div></div>
  <div class="stat"><div class="val">{len(unpaired)}</div><div class="lbl">Unpaired</div></div>
  <div class="stat"><div class="val" style="text-transform:uppercase">{global_mode}</div><div class="lbl">Global Mode</div></div>
  <div class="stat"><div class="val">{weather_city}</div><div class="lbl">Weather City</div></div>
</div>

<div class="card">
  <h2>Paired Tickers</h2>
  <table>
    <tr><th>ID</th><th>Mode</th><th>City</th><th>Last Seen</th></tr>
    {ticker_rows(paired)}
  </table>
  {"" if not unpaired else f'<h2 style="margin-top:12px">Unpaired / Registered</h2><table><tr><th>ID</th><th>Mode</th><th>City</th><th>Last Seen</th></tr>{ticker_rows(unpaired)}</table>'}
</div>

<div class="card">
  <h2>Active Sports &amp; Features</h2>
  <div style="margin-top:6px">{''.join(sport_badges)}</div>
</div>

<p style="color:#333;font-size:10px;margin-top:8px">Auto-refreshes every 15s &nbsp;·&nbsp; <a href="/api/state">api/state</a> &nbsp;·&nbsp; <a href="/api/debug">api/debug</a></p>
</body>
</html>"""
    return make_response(html, 200, {'Content-Type': 'text/html'})


