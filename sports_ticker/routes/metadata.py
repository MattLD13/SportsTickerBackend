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


@app.route('/')
def root():
    now = time.time()
    uptime_s = int(now - _SERVER_START)
    h, rem = divmod(uptime_s, 3600)
    m, s = divmod(rem, 60)
    uptime_str = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

    with data_lock:
        ticker_list = list(tickers.items())
        active_sports = dict(state.get('active_sports', {}))
        global_mode = state.get('mode', 'sports')
        weather_city = state.get('weather_city', 'New York')
        airport_iata = state.get('airport_code_iata', 'EWR')
        track_flight_id = state.get('track_flight_id', '')

    # Only show named tickers — unnamed ones are transient/anonymous
    named_paired   = [(tid, rec) for tid, rec in ticker_list if rec.get('paired') and (rec.get('name') or '').strip()]
    named_unpaired = [(tid, rec) for tid, rec in ticker_list if not rec.get('paired') and (rec.get('name') or '').strip()]

    first_ticker_id = named_paired[0][0] if named_paired else ''
    # Escape for safe JS string embedding
    first_ticker_id_js = first_ticker_id.replace('\\', '\\\\').replace("'", "\\'")

    def _ago(last):
        if not last: return 'never', 'offline'
        secs = int(now - last)
        if secs < 30:   return f'{secs}s ago', 'online'
        if secs < 300:  return f'{secs}s ago', 'recent'
        if secs < 3600: return f'{secs//60}m ago', 'idle'
        return f'{secs//3600}h ago', 'offline'

    def ticker_cards(items):
        if not items:
            return '<p style="color:#333;font-size:12px;padding:8px 0">None</p>'
        cards = []
        for tid, rec in sorted(items, key=lambda x: (x[1].get('last_seen') or 0), reverse=True):
            name = (rec.get('name') or '').strip() or tid[:8]
            mode = rec.get('settings', {}).get('mode') or rec.get('mode') or 'sports'
            city = rec.get('settings', {}).get('weather_city') or '—'
            last = rec.get('last_seen', 0)
            ago_str, status = _ago(last)
            mc, mbg = _MODE_COLORS.get(mode, ('#888', '#111'))
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

    sport_labels = {item['id']: item['label'] for item in LEAGUE_OPTIONS}
    enabled_sports  = [sport_labels.get(sid, sid) for sid, on in active_sports.items() if on]

    def sport_pill(label, on):
        if on:
            return f'<span class="sp on">{label}</span>'
        return f'<span class="sp off">{label}</span>'

    sport_html = ''.join(sport_pill(sport_labels.get(sid, sid), on) for sid, on in active_sports.items())

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sports Ticker</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#09090b;color:#a1a1aa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:13px;min-height:100vh}}
a{{color:#60a5fa;text-decoration:none}}
a:hover{{text-decoration:underline}}

/* ── Top Bar ── */
.topbar{{background:#0f0f12;border-bottom:1px solid #1c1c1f;padding:16px 24px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px}}
.logo{{font-size:18px;font-weight:700;color:#fff;letter-spacing:-.5px;display:flex;align-items:center;gap:10px}}
.logo-led{{display:flex;gap:2px}}
.led{{width:6px;height:6px;border-radius:1px;animation:pulse 2s ease-in-out infinite}}
.led:nth-child(1){{background:#ff4500;animation-delay:0s}}
.led:nth-child(2){{background:#ff8c00;animation-delay:.15s}}
.led:nth-child(3){{background:#ffd700;animation-delay:.3s}}
.led:nth-child(4){{background:#44ff44;animation-delay:.45s}}
.led:nth-child(5){{background:#00ccff;animation-delay:.6s}}
.led:nth-child(6){{background:#8844ff;animation-delay:.75s}}
@keyframes pulse{{0%,100%{{opacity:.3}}50%{{opacity:1}}}}
.build{{font-size:11px;color:#3f3f46;font-family:'Courier New',monospace}}

/* ── Layout ── */
.content{{max-width:1000px;margin:0 auto;padding:24px}}

/* ── LED Canvas Section ── */
.led-section{{background:#0a0a0d;border:1px solid #1c1c1f;border-radius:10px;padding:16px;margin-bottom:20px}}
.led-section-title{{font-size:10px;font-weight:600;color:#3f3f46;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:10px;display:flex;align-items:center;gap:8px}}
.led-section-title span{{color:#1c1c1f}}
.canvas-wrap{{position:relative;width:100%;background:#060608;border-radius:6px;overflow:hidden;border:1px solid #111116;cursor:pointer;line-height:0}}
#ticker-canvas{{width:100%;max-width:768px;height:64px;display:block;image-rendering:pixelated}}
.pause-badge{{position:absolute;top:6px;right:8px;font-size:16px;opacity:0;transition:opacity .2s;pointer-events:none;line-height:1}}
.pause-badge.visible{{opacity:1}}
.fetch-status{{font-size:10px;color:#3f3f46;margin-top:6px;text-align:right;font-family:'Courier New',monospace}}

/* ── Mode Filter Buttons ── */
.mode-filters{{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}}
.mf-btn{{font-size:10px;font-weight:700;letter-spacing:.8px;padding:4px 10px;border-radius:4px;border:1px solid #1c1c1f;background:#111;color:#52525b;cursor:pointer;transition:all .15s;text-transform:uppercase}}
.mf-btn:hover{{border-color:#2d2d35;color:#888}}
.mf-btn.active{{border-color:var(--c);color:var(--c);background:color-mix(in srgb,var(--c) 12%,transparent);box-shadow:0 0 8px color-mix(in srgb,var(--c) 20%,transparent)}}

/* ── Controls Bar ── */
.ctrl-bar{{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin-top:12px;padding:10px 12px;background:#0d0d10;border:1px solid #1c1c1f;border-radius:6px}}
.ctrl-label{{font-size:10px;font-weight:600;color:#52525b;text-transform:uppercase;letter-spacing:.8px;white-space:nowrap}}
.ctrl-row{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.ctrl-input{{background:#111;border:1px solid #1c1c1f;border-radius:4px;color:#e4e4e7;font-size:12px;padding:4px 8px;outline:none;transition:border-color .15s;width:160px}}
.ctrl-input:focus{{border-color:#3f3f46}}
.ctrl-input.sm{{width:100px}}
.ctrl-btn{{font-size:10px;font-weight:700;letter-spacing:.5px;padding:4px 12px;border-radius:4px;border:1px solid #1c1c1f;background:#111;color:#a1a1aa;cursor:pointer;transition:all .15s;text-transform:uppercase}}
.ctrl-btn:hover{{border-color:#52525b;color:#fff}}
.ctrl-btn.primary{{border-color:#3f3f46;color:#fff}}
.ctrl-btn.primary:hover{{border-color:#60a5fa;color:#60a5fa}}
.ctrl-btn.danger{{border-color:#7f1d1d;color:#ef4444}}
.ctrl-btn.danger:hover{{border-color:#ef4444}}
.speed-wrap{{display:flex;align-items:center;gap:8px}}
input[type=range]{{-webkit-appearance:none;width:100px;height:3px;background:#1c1c1f;border-radius:2px;outline:none}}
input[type=range]::-webkit-slider-thumb{{-webkit-appearance:none;width:12px;height:12px;border-radius:50%;background:#60a5fa;cursor:pointer}}
.ctrl-sep{{width:1px;height:20px;background:#1c1c1f;flex-shrink:0}}
.ctrl-panel{{display:none}}.ctrl-panel.active{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.now-playing{{display:flex;align-items:center;gap:10px;padding:6px 10px;background:#120018;border:1px solid #4a1a6a;border-radius:6px}}
.np-art{{width:32px;height:32px;border-radius:3px;object-fit:cover;flex-shrink:0;background:#1a1a1a}}
.np-info{{line-height:1.3}}
.np-title{{font-size:12px;font-weight:600;color:#e4e4e7}}
.np-artist{{font-size:11px;color:#a855f7}}
.np-bar{{display:flex;align-items:center;gap:6px;margin-top:4px}}
.np-prog{{flex:1;height:3px;background:#1c1c1f;border-radius:2px;overflow:hidden}}
.np-fill{{height:100%;background:#a855f7;border-radius:2px;transition:width .5s linear}}
.np-time{{font-size:10px;color:#52525b;font-family:monospace}}
.pin-badge{{display:inline-block;font-size:9px;font-weight:700;padding:2px 6px;border-radius:3px;background:#1a1500;color:#ffdd00;border:1px solid #3a2e00;margin-left:6px;cursor:pointer}}
.pin-badge:hover{{background:#2a2000}}

/* ── Detail Panel ── */
.detail-panel{{margin-bottom:24px}}
.detail-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px}}
.dc{{background:#0f0f12;border:1px solid #1c1c1f;border-radius:8px;padding:12px 14px;cursor:pointer;transition:border-color .2s,background .2s}}
.dc:hover{{border-color:#2a2a32}}
.dc.active{{border-color:#2d2d35;background:#111116}}
.dc-badge{{display:inline-block;font-size:9px;font-weight:700;letter-spacing:.7px;padding:2px 7px;border-radius:3px;margin-bottom:8px}}
.dc-teams{{font-size:15px;font-weight:700;color:#e4e4e7;line-height:1.2;margin-bottom:4px}}
.dc-score{{font-size:22px;font-weight:800;color:#fff;font-variant-numeric:tabular-nums;margin-bottom:2px}}
.dc-status{{font-size:11px;color:#52525b}}
.dc-detail{{display:none;margin-top:8px;padding-top:8px;border-top:1px solid #1c1c1f;font-size:11px;color:#52525b;line-height:1.6}}
.dc.active .dc-detail{{display:block}}
.dc-detail .row{{display:flex;justify-content:space-between}}

/* ── Stats Bar ── */
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin-bottom:24px}}
.stat{{background:#0f0f12;border:1px solid #1c1c1f;border-radius:8px;padding:14px 16px}}
.stat .val{{font-size:20px;font-weight:700;color:#fff;line-height:1}}
.stat .lbl{{font-size:10px;color:#3f3f46;text-transform:uppercase;letter-spacing:.8px;margin-top:4px}}

/* ── Section Titles ── */
.section-title{{font-size:11px;font-weight:600;color:#3f3f46;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #1c1c1f}}

/* ── Ticker Cards ── */
.ticker-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-bottom:24px}}
.tc{{background:#0f0f12;border:1px solid #1c1c1f;border-radius:8px;padding:14px;transition:border-color .2s}}
.tc:hover{{border-color:#2d2d35}}
.tc-header{{display:flex;align-items:center;gap:8px;margin-bottom:8px}}
.dot{{width:7px;height:7px;border-radius:50%;flex-shrink:0}}
.tc-name{{font-weight:600;color:#e4e4e7;font-size:14px;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.tc-mode{{font-size:9px;font-weight:700;letter-spacing:.8px;padding:2px 6px;border-radius:3px;white-space:nowrap;flex-shrink:0}}
.tc-meta{{display:flex;justify-content:space-between;font-size:11px;color:#52525b}}

/* ── Sports Pills ── */
.sports-grid{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:24px}}
.sp{{font-size:11px;padding:3px 9px;border-radius:4px;font-weight:500}}
.sp.on{{background:#1a2e1a;color:#4ade80;border:1px solid #1a3a1a}}
.sp.off{{background:#111;color:#3f3f46;border:1px solid #1c1c1f}}

.footer{{font-size:11px;color:#27272a;text-align:center;padding:16px}}

/* ── Mobile responsive ── */
@media(max-width:640px){{
  .content{{padding:12px}}
  .topbar{{padding:12px 16px}}
  #ticker-canvas{{height:48px}}
  .canvas-wrap canvas{{height:48px}}
  .stats{{grid-template-columns:repeat(2,1fr);gap:8px}}
  .detail-grid{{grid-template-columns:1fr}}
  .ticker-grid{{grid-template-columns:1fr}}
  .ctrl-bar{{flex-direction:column;align-items:flex-start;gap:8px}}
  .ctrl-input{{width:130px}}
  .ctrl-input.sm{{width:80px}}
  .mode-filters{{gap:4px}}
  .mf-btn{{font-size:9px;padding:3px 7px}}
}}
</style>
</head>
<body>

<div class="topbar">
  <div class="logo">
    <div class="logo-led">
      <div class="led"></div><div class="led"></div><div class="led"></div>
      <div class="led"></div><div class="led"></div><div class="led"></div>
    </div>
    Sports Ticker
  </div>
  <div class="build">
    <a href="https://github.com/MattLD13/SportsTickerBackend/commit/{_VERSION_HASH}" target="_blank">{_VERSION_HASH}</a>
    &nbsp;·&nbsp; {SERVER_VERSION}
  </div>
</div>

<div class="content">

  <!-- ═══════════════════════════════════════════
       SECTION 1 — LED TICKER CANVAS
  ════════════════════════════════════════════ -->
  <div class="led-section">
    <div class="led-section-title">
      Live Ticker Simulation
      <span>&#9632; 384×32 LED Matrix · 2× scale</span>
    </div>
    <div class="canvas-wrap" id="canvas-wrap">
      <canvas id="ticker-canvas" width="768" height="64"></canvas>
      <div class="pause-badge" id="pause-badge">&#9646;&#9646;</div>
    </div>
    <div class="fetch-status" id="fetch-status">fetching…</div>
    <div class="mode-filters" id="mode-filters">
      <button class="mf-btn active" data-mode="sports"         style="--c:#FF8C00">ALL SPORTS</button>
      <button class="mf-btn"        data-mode="live"           style="--c:#FF4444">LIVE</button>
      <button class="mf-btn"        data-mode="stocks"         style="--c:#44DD88">STOCKS</button>
      <button class="mf-btn"        data-mode="music"          style="--c:#CC44FF">MUSIC</button>
      <button class="mf-btn"        data-mode="flights"        style="--c:#00DDCC">FLIGHTS</button>
      <button class="mf-btn"        data-mode="flight_tracker" style="--c:#00AACC">TRACKER</button>
      <button class="mf-btn"        data-mode="weather"        style="--c:#44AAFF">WEATHER</button>
      <button class="mf-btn"        data-mode="clock"          style="--c:#888888">CLOCK</button>
    </div>

    <div class="ctrl-bar">
      <!-- Speed: always visible -->
      <div class="ctrl-row">
        <span class="ctrl-label">Speed</span>
        <div class="speed-wrap">
          <input type="range" id="speed-range" min="0.1" max="4" step="0.1" value="0.5">
          <span class="ctrl-label" id="speed-val">0.5×</span>
        </div>
      </div>
      <div class="ctrl-sep"></div>

      <!-- Sports / Live: pin game -->
      <div class="ctrl-panel" id="ctrl-sports">
        <span class="ctrl-label">Click a game card below to pin it</span>
        <button class="ctrl-btn danger" id="unpin-btn" onclick="unpinGame()" style="display:none">✕ Unpin</button>
      </div>

      <!-- Weather -->
      <div class="ctrl-panel" id="ctrl-weather">
        <span class="ctrl-label">City</span>
        <input class="ctrl-input sm" id="weather-city" placeholder="New York" value="{weather_city}">
        <button class="ctrl-btn primary" onclick="setWeather()">Set</button>
      </div>

      <!-- Flights airport -->
      <div class="ctrl-panel" id="ctrl-flights">
        <span class="ctrl-label">Airport</span>
        <input class="ctrl-input sm" id="airport-code" placeholder="EWR" maxlength="4" value="{airport_iata}">
        <button class="ctrl-btn primary" onclick="setAirport()">Set</button>
      </div>

      <!-- Flight tracker -->
      <div class="ctrl-panel" id="ctrl-flight_tracker">
        <span class="ctrl-label">Flight ID</span>
        <input class="ctrl-input sm" id="flight-id" placeholder="UA123" value="{track_flight_id}">
        <span class="ctrl-label">Guest</span>
        <input class="ctrl-input sm" id="guest-name" placeholder="John">
        <button class="ctrl-btn primary" onclick="setFlightTracker()">Track</button>
        <button class="ctrl-btn danger" onclick="clearFlight()">Clear</button>
      </div>

      <!-- Music: now-playing card -->
      <div class="ctrl-panel" id="ctrl-music">
        <div class="now-playing" id="now-playing">
          <img class="np-art" id="np-art" src="" alt="">
          <div class="np-info">
            <div class="np-title" id="np-title">Loading…</div>
            <div class="np-artist" id="np-artist"></div>
            <div class="np-bar">
              <div class="np-prog"><div class="np-fill" id="np-fill" style="width:0%"></div></div>
              <span class="np-time" id="np-time">0:00</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Stocks: no extra controls needed -->
      <div class="ctrl-panel" id="ctrl-stocks">
        <span class="ctrl-label">Live market data · refreshes every 20s</span>
      </div>

      <!-- Clock: no controls needed -->
      <div class="ctrl-panel" id="ctrl-clock">
        <span class="ctrl-label" id="clock-display">--:--:--</span>
      </div>
    </div>
  </div>

  <!-- ═══════════════════════════════════════════
       SECTION 2 — DETAIL PANEL
  ════════════════════════════════════════════ -->
  <div class="detail-panel">
    <div class="section-title" id="detail-title">Live Items</div>
    <div class="detail-grid" id="detail-grid">
      <p style="color:#333;font-size:12px">Loading data…</p>
    </div>
  </div>

  <!-- ═══════════════════════════════════════════
       SECTION 3 — SERVER DASHBOARD
  ════════════════════════════════════════════ -->
  <div class="stats">
    <div class="stat"><div class="val">{uptime_str}</div><div class="lbl">Uptime</div></div>
    <div class="stat"><div class="val">{len(named_paired)}</div><div class="lbl">Paired</div></div>
    <div class="stat"><div class="val" style="text-transform:uppercase">{global_mode.replace("_"," ")}</div><div class="lbl">Global Mode</div></div>
    <div class="stat"><div class="val">{weather_city}</div><div class="lbl">Weather City</div></div>
    <div class="stat"><div class="val">{len(enabled_sports)}</div><div class="lbl">Active Feeds</div></div>
  </div>

  <div class="section-title">Active Ticker</div>
  <div class="ticker-grid">
    {ticker_cards(sorted(named_paired, key=lambda x: x[1].get('last_seen') or 0, reverse=True)[:1])}
  </div>

  <div class="section-title">Active Sports &amp; Features</div>
  <div class="sports-grid">{sport_html}</div>

</div>

<div class="footer">
  Data refreshes every 30s &nbsp;·&nbsp;
  <a href="/api/state">api/state</a> &nbsp;·&nbsp;
  <a href="/api/debug">api/debug</a>
</div>

<script>
(function () {{
'use strict';

// ─── Configuration ───────────────────────────────────────────────────────────
const TICKER_ID   = '{first_ticker_id_js}';
const LED_W       = 384;
const LED_H       = 32;
const SCALE       = 2;        // screen pixels per LED pixel
const SCROLL_SPD  = 0.5;      // LED source pixels per rAF frame
const FETCH_EVERY = 20000;

// ─── Canvas + state ──────────────────────────────────────────────────────────
const canvas      = document.getElementById('ticker-canvas');
const ctx         = canvas.getContext('2d');
const pauseBadge  = document.getElementById('pause-badge');
const fetchStatus = document.getElementById('fetch-status');

ctx.imageSmoothingEnabled = false; // pixel-perfect nearest-neighbour upscale

let stripBitmap   = null;  // ImageBitmap of the server-rendered strip
let stripSrcW     = 0;     // source pixels wide
let scrollSrcX    = 0;     // fractional source-pixel scroll offset
let paused        = false;
let currentApiMode = 'sports';
let allItems      = [];    // from /api/state for the detail panel

// ─── LED grid overlay ─────────────────────────────────────────────────────────
function drawLedGrid() {{
  // Dim dot at top-left corner of every 2×2 LED cell
  ctx.fillStyle = 'rgba(0,0,0,0.45)';
  for (let sy = 0; sy < LED_H * SCALE; sy += SCALE) {{
    for (let sx = 0; sx < LED_W * SCALE; sx += SCALE) {{
      ctx.fillRect(sx, sy, 1, 1);
    }}
  }}
}}

// ─── Render frame ─────────────────────────────────────────────────────────────
function renderFrame() {{
  ctx.fillStyle = '#060608';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  if (!stripBitmap || stripSrcW === 0) {{
    // Show placeholder
    ctx.fillStyle = '#1a1a1a';
    for (let sy = 0; sy < LED_H * SCALE; sy += SCALE) {{
      for (let sx = 0; sx < LED_W * SCALE; sx += SCALE) {{
        ctx.fillRect(sx + 1, sy + 1, SCALE - 1, SCALE - 1);
      }}
    }}
    drawLedGrid();
    return;
  }}

  const sx = Math.floor(scrollSrcX) % stripSrcW;
  const canvasW = LED_W * SCALE;
  const canvasH = LED_H * SCALE;

  // First slice (sx → end of strip, or full LED_W if no wrap)
  const firstW = Math.min(stripSrcW - sx, LED_W);
  ctx.drawImage(stripBitmap,
    sx, 0, firstW, LED_H,          // src
    0,  0, firstW * SCALE, canvasH  // dst
  );

  // Second slice (wrap from beginning) if needed
  if (firstW < LED_W) {{
    const remW = LED_W - firstW;
    ctx.drawImage(stripBitmap,
      0, 0, remW, LED_H,
      firstW * SCALE, 0, remW * SCALE, canvasH
    );
  }}

  drawLedGrid();
}}

// ─── Animation loop ───────────────────────────────────────────────────────────
window._scrollSpd = SCROLL_SPD;
function tick() {{
  if (!paused && stripBitmap && stripSrcW > LED_W) {{
    scrollSrcX += window._scrollSpd || SCROLL_SPD;
    if (scrollSrcX >= stripSrcW) scrollSrcX -= stripSrcW;
  }}
  renderFrame();
  requestAnimationFrame(tick);
}}

// ─── Strip fetching ───────────────────────────────────────────────────────────
async function fetchStrip() {{
  try {{
    const url = '/api/preview/strip.png?mode=' + encodeURIComponent(currentApiMode);
    const resp = await fetch(url, {{ cache: 'no-store' }});
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const blob  = await resp.blob();
    const bmp   = await createImageBitmap(blob);
    stripBitmap = bmp;
    stripSrcW   = bmp.width;
    scrollSrcX  = 0;
    fetchStatus.textContent = 'Updated ' + new Date().toLocaleTimeString() +
      '  ·  strip ' + bmp.width + '×' + bmp.height + 'px  ·  ' + allItems.length + ' items';
  }} catch(e) {{
    fetchStatus.textContent = 'Strip error: ' + e.message;
  }}
}}

// ─── Detail panel data (separate /api/state call) ─────────────────────────────
async function fetchItems() {{
  try {{
    const params = [];
    if (TICKER_ID)      params.push('id='   + encodeURIComponent(TICKER_ID));
    if (currentApiMode) params.push('mode=' + encodeURIComponent(currentApiMode));
    const resp = await fetch('/api/state' + (params.length ? '?' + params.join('&') : ''));
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    allItems = (data && Array.isArray(data.games)) ? data.games : [];
    updateDetailPanel();
  }} catch(e) {{
    console.warn('Items fetch error:', e.message);
  }}
}}

async function fetchAll() {{
  await Promise.all([fetchStrip(), fetchItems()]);
}}

// ─── Sport color helper ───────────────────────────────────────────────────────
const SPORT_COLORS = {{
  NFL:'#FF6B35', NBA:'#C9082A', NHL:'#00B2E3', MLB:'#003DA5',
  NCF_FBS:'#FF8C00', NCF_FCS:'#FF8C00',
  SOCCER_EPL:'#3D195B', SOCCER_FA_CUP:'#3D195B', SOCCER_CHAMP:'#003DA5',
  SOCCER_CHAMPIONS_LEAGUE:'#003366', SOCCER_EUROPA_LEAGUE:'#FF6B00',
  SOCCER_MLS:'#C0392B', SOCCER_WC:'#C09A2A',
  GOLF:'#66BB44', MASTERS:'#FFDD00',
  WEATHER:'#44AAFF', STOCK_TICKER:'#44DD88',
  MUSIC:'#CC44FF', CLOCK:'#888888',
  FLIGHT:'#00DDCC', FLIGHT_VISITOR:'#00AACC',
  DEFAULT:'#FF8C00'
}};
function sportColor(item) {{
  const sp = (item.sport || '').toUpperCase();
  const ty = (item.type  || '').toUpperCase();
  return SPORT_COLORS[sp] || SPORT_COLORS[ty] ||
    (sp.startsWith('SOCCER') ? '#4CAF50' : SPORT_COLORS.DEFAULT);
}}

// ─── Detail panel ─────────────────────────────────────────────────────────────
function updateDetailPanel() {{
  const grid  = document.getElementById('detail-grid');
  const title = document.getElementById('detail-title');
  const label = document.querySelector('.mf-btn.active')?.textContent || currentApiMode;
  title.textContent = label + ' — ' + allItems.length + ' items';
  if (!allItems.length) {{
    grid.innerHTML = '<p style="color:#333;font-size:12px">No data for this mode.</p>';
    return;
  }}
  grid.innerHTML = allItems.map((item, idx) => makeDetailCard(item, idx)).join('');
}}

window.toggleCard = function(el) {{
  const was = el.classList.contains('active');
  document.querySelectorAll('.dc.active').forEach(c => c.classList.remove('active'));
  if (!was) el.classList.add('active');
}};

function makeDetailCard(item, idx) {{
  const color = sportColor(item);
  const bgC   = color + '22';
  const itype = (item.type  || '').toLowerCase();
  const sport = (item.sport || itype || 'game').toUpperCase();
  let badge = sport.slice(0, 10);
  let teams = '', score = '', status = '', detail = '';

  if (itype === 'weather') {{
    teams  = item.city || item.location || 'Weather';
    score  = item.temp != null ? Math.round(item.temp) + '°F' : '';
    status = item.condition || item.description || '';
    detail = `<div class="row"><span>Humidity</span><span>${{item.humidity != null ? item.humidity+'%' : '—'}}</span></div>
              <div class="row"><span>Wind</span><span>${{item.wind||'—'}}</span></div>`;
  }} else if (itype === 'stock_ticker') {{
    const pct      = item.change_pct != null ? (+item.change_pct).toFixed(2)+'%' : '';
    const pctColor = (item.change_pct||0) >= 0 ? '#44dd88' : '#ff4444';
    teams  = item.symbol || '';
    score  = item.price != null ? '$'+(+item.price).toFixed(2) : '';
    status = `<span style="color:${{pctColor}}">${{pct}}</span>`;
    detail = `<div class="row"><span>Change</span><span style="color:${{pctColor}}">${{item.change||pct}}</span></div>`;
  }} else if (itype === 'music') {{
    teams  = item.artist || item.artist_name || 'Unknown Artist';
    score  = item.title  || item.song || '';
    status = item.album  || '';
  }} else if (itype === 'clock') {{
    teams  = 'Clock';
    score  = item.time   || item.clock_str || '';
  }} else if (itype === 'flight_visitor') {{
    teams  = item.flight || item.id || '';
    score  = (item.origin && item.dest) ? item.origin + ' → ' + item.dest : '';
    status = item.status || '';
    detail = `<div class="row"><span>Arrival</span><span>${{item.arrive||'—'}}</span></div>`;
  }} else if ((item.sport||'').toLowerCase() === 'flight') {{
    teams  = (item.airline||'') + ' ' + (item.flight_number||item.flight||'');
    score  = item.destination || item.dest || '';
    status = item.status || '';
    detail = `<div class="row"><span>Gate</span><span>${{item.gate||'—'}}</span></div>
              <div class="row"><span>Time</span><span>${{item.time||item.scheduled||'—'}}</span></div>`;
  }} else {{
    const away   = item.away || item.away_name || '';
    const home   = item.home || item.home_name || '';
    const aScore = item.away_score != null ? item.away_score : '';
    const hScore = item.home_score != null ? item.home_score : '';
    const isFinal = /final|ft|full/i.test(item.status||'');
    const isLive  = !isFinal && (item.period || item.clock);
    score  = (aScore !== '' && hScore !== '') ? aScore + ' – ' + hScore : '';
    status = `<span style="color:${{isLive ? color : isFinal ? '#555' : '#888'}}">${{item.status||item.clock||''}}</span>`;
    detail = `<div class="row"><span>League</span><span>${{item.league||sport}}</span></div>
              <div class="row"><span>Venue</span><span>${{item.venue||'—'}}</span></div>`;
    const awayLogo = item.away_logo ? `<img src="${{item.away_logo}}" style="width:18px;height:18px;object-fit:contain;vertical-align:middle;margin-right:4px" onerror="this.style.display='none'">` : '';
    const homeLogo = item.home_logo ? `<img src="${{item.home_logo}}" style="width:18px;height:18px;object-fit:contain;vertical-align:middle;margin-left:4px"  onerror="this.style.display='none'">` : '';
    teams = awayLogo + away + ' vs ' + home + homeLogo;
    if (item.id) teams += `<span class="pin-badge" onclick="event.stopPropagation();pinGame('${{item.id}}')" title="Pin this game">📌</span>`;
  }}

  return `<div class="dc" data-idx="${{idx}}" onclick="toggleCard(this)">
    <div class="dc-badge" style="background:${{bgC}};color:${{color}};border:1px solid ${{color}}40">${{badge}}</div>
    <div class="dc-teams">${{teams}}</div>
    ${{score  ? `<div class="dc-score">${{score}}</div>` : ''}}
    ${{status ? `<div class="dc-status">${{status}}</div>` : ''}}
    ${{detail ? `<div class="dc-detail">${{detail}}</div>` : ''}}
  </div>`;
}}

// ─── Canvas click — pause ─────────────────────────────────────────────────────
document.getElementById('canvas-wrap').addEventListener('click', function() {{
  paused = !paused;
  pauseBadge.classList.toggle('visible', paused);
}});

// ─── Mode filter buttons ──────────────────────────────────────────────────────
document.getElementById('mode-filters').addEventListener('click', function(e) {{
  const btn = e.target.closest('.mf-btn');
  if (!btn) return;
  document.querySelectorAll('.mf-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  currentApiMode = btn.dataset.mode;
  scrollSrcX = 0;
  showCtrlPanel(currentApiMode);
  if (currentApiMode === 'music') fetchNowPlaying();
  fetchAll();
}});

// ─── Speed slider ─────────────────────────────────────────────────────────────
const speedRange = document.getElementById('speed-range');
const speedVal   = document.getElementById('speed-val');
speedRange.addEventListener('input', function() {{
  const v = parseFloat(this.value);
  window._scrollSpd = v;
  speedVal.textContent = v.toFixed(1) + '×';
}});

// ─── Controls panel visibility ────────────────────────────────────────────────
function showCtrlPanel(mode) {{
  document.querySelectorAll('.ctrl-panel').forEach(p => p.classList.remove('active'));
  const map = {{
    sports: 'ctrl-sports', live: 'ctrl-sports',
    weather: 'ctrl-weather',
    flights: 'ctrl-flights', flight_tracker: 'ctrl-flight_tracker',
    music: 'ctrl-music',
    stocks: 'ctrl-stocks',
    clock: 'ctrl-clock',
  }};
  const id = map[mode];
  if (id) document.getElementById(id)?.classList.add('active');
}}

// ─── Weather ──────────────────────────────────────────────────────────────────
window.setWeather = async function() {{
  const city = document.getElementById('weather-city').value.trim();
  if (!city) return;
  try {{
    await fetch('/api/config', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ weather_city: city, mode: 'weather' }})
    }});
    fetchAll();
  }} catch(e) {{ console.error(e); }}
}};

// ─── Airport ─────────────────────────────────────────────────────────────────
window.setAirport = async function() {{
  const code = document.getElementById('airport-code').value.trim().toUpperCase();
  if (!code) return;
  try {{
    await fetch('/api/config', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ airport_code_iata: code, mode: 'flights', flight_submode: 'airport' }})
    }});
    fetchAll();
  }} catch(e) {{ console.error(e); }}
}};

// ─── Flight tracker ───────────────────────────────────────────────────────────
window.setFlightTracker = async function() {{
  const flt   = document.getElementById('flight-id').value.trim().toUpperCase();
  const guest = document.getElementById('guest-name').value.trim();
  if (!flt) return;
  try {{
    await fetch('/api/config', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ track_flight_id: flt, track_guest_name: guest, mode: 'flight_tracker', flight_submode: 'track' }})
    }});
    fetchAll();
  }} catch(e) {{ console.error(e); }}
}};
window.clearFlight = async function() {{
  document.getElementById('flight-id').value = '';
  document.getElementById('guest-name').value = '';
  try {{
    await fetch('/api/config', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ track_flight_id: '', track_guest_name: '' }})
    }});
  }} catch(e) {{ console.error(e); }}
}};

// ─── Pin game ─────────────────────────────────────────────────────────────────
window.pinGame = async function(gameId) {{
  try {{
    const payload = {{ game_ids: gameId ? [gameId] : [] }};
    if ('{first_ticker_id_js}') payload.ticker_id = '{first_ticker_id_js}';
    await fetch('/api/pin_games', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(payload)
    }});
    document.getElementById('unpin-btn').style.display = gameId ? '' : 'none';
    fetchAll();
  }} catch(e) {{ console.error(e); }}
}};
window.unpinGame = function() {{ window.pinGame(''); }};

// ─── Music: iTunes top chart + fake progress ──────────────────────────────────
let _npSong = null;
let _npStart = 0;
let _npDuration = 210;  // default 3:30

async function fetchNowPlaying() {{
  // First try Spotify
  try {{
    const r = await fetch('/api/spotify/now');
    if (r.ok) {{
      const d = await r.json();
      if (d && d.title) {{
        _npSong = d;
        _npDuration = (d.duration || 210000) / 1000;
        _npStart = Date.now() / 1000 - (d.progress || 0) / 1000;
        renderNowPlaying(d.title, d.artist, d.album_art || '', d.progress/1000, _npDuration);
        return;
      }}
    }}
  }} catch(e) {{}}

  // Fallback: iTunes top songs RSS
  try {{
    const r = await fetch('https://itunes.apple.com/us/rss/topsongs/limit=10/json');
    if (r.ok) {{
      const d = await r.json();
      const entries = d?.feed?.entry || [];
      if (entries.length) {{
        const song = entries[Math.floor(Math.random() * Math.min(5, entries.length))];
        const title  = song['im:name']?.label || 'Unknown';
        const artist = song['im:artist']?.label || '';
        const art    = song['im:image']?.[2]?.label || '';
        _npDuration = 200 + Math.floor(Math.random() * 60);
        _npStart = Date.now() / 1000 - Math.floor(Math.random() * _npDuration * 0.8);
        renderNowPlaying(title, artist, art, Date.now()/1000 - _npStart, _npDuration);
        return;
      }}
    }}
  }} catch(e) {{}}

  renderNowPlaying('No song data', '', '', 0, 1);
}}

function renderNowPlaying(title, artist, art, progressSec, durationSec) {{
  document.getElementById('np-title').textContent  = title;
  document.getElementById('np-artist').textContent = artist;
  const artEl = document.getElementById('np-art');
  if (art) {{ artEl.src = art; artEl.style.display=''; }} else {{ artEl.style.display='none'; }}
  updateNpProgress(progressSec, durationSec);
}}

function updateNpProgress(progressSec, durationSec) {{
  const pct = durationSec > 0 ? Math.min(100, progressSec / durationSec * 100) : 0;
  document.getElementById('np-fill').style.width = pct + '%';
  const fmt = s => Math.floor(s/60) + ':' + String(Math.floor(s%60)).padStart(2,'0');
  document.getElementById('np-time').textContent = fmt(progressSec) + ' / ' + fmt(durationSec);
}}

// Progress ticker for now-playing bar
setInterval(() => {{
  if (_npStart > 0 && document.getElementById('ctrl-music').classList.contains('active')) {{
    const elapsed = Date.now() / 1000 - _npStart;
    updateNpProgress(Math.min(elapsed, _npDuration), _npDuration);
  }}
}}, 1000);

// ─── Clock display ────────────────────────────────────────────────────────────
setInterval(() => {{
  const el = document.getElementById('clock-display');
  if (el && document.getElementById('ctrl-clock').classList.contains('active')) {{
    el.textContent = new Date().toLocaleTimeString();
  }}
}}, 1000);

// ─── Boot ─────────────────────────────────────────────────────────────────────
showCtrlPanel('sports');
fetchAll();
fetchNowPlaying();
setInterval(fetchAll, FETCH_EVERY);
setInterval(fetchNowPlaying, 30000);
tick();

}})();
</script>
</body>
</html>"""
    return make_response(html, 200, {'Content-Type': 'text/html'})


