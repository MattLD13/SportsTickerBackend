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
        weather_city = state.get('weather_city', '—')

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

    sport_labels = {{item['id']: item['label'] for item in LEAGUE_OPTIONS}}
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
      <button class="mf-btn active" data-mode="ALL" style="--c:#FFAA44">ALL</button>
      <button class="mf-btn" data-mode="NFL"     style="--c:#FF6B35">NFL</button>
      <button class="mf-btn" data-mode="NBA"     style="--c:#C9082A">NBA</button>
      <button class="mf-btn" data-mode="NHL"     style="--c:#00B2E3">NHL</button>
      <button class="mf-btn" data-mode="MLB"     style="--c:#003DA5">MLB</button>
      <button class="mf-btn" data-mode="SOCCER"  style="--c:#4CAF50">SOCCER</button>
      <button class="mf-btn" data-mode="GOLF"    style="--c:#66BB44">GOLF</button>
      <button class="mf-btn" data-mode="WEATHER" style="--c:#44AAFF">WEATHER</button>
      <button class="mf-btn" data-mode="STOCKS"  style="--c:#44DD88">STOCKS</button>
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

  <div class="section-title">Paired Tickers</div>
  <div class="ticker-grid">
    {ticker_cards(named_paired)}
  </div>

  {"" if not named_unpaired else f'<div class="section-title">Registered (Unpaired)</div><div class="ticker-grid">{ticker_cards(named_unpaired)}</div>'}

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
const TICKER_ID    = '{first_ticker_id_js}';
const LED_W        = 384;   // LED matrix width
const LED_H        = 32;    // LED matrix height
const SCALE        = 2;     // screen pixels per LED pixel
const FPS_SCROLL   = 0.4;   // LED pixels scrolled per rAF frame
const FETCH_EVERY  = 30000; // ms

// ─── Bitmap Font ─────────────────────────────────────────────────────────────
const FONT = {{
  'A':[0x6,0x9,0xF,0x9,0x9],'B':[0xE,0x9,0xE,0x9,0xE],'C':[0x6,0x9,0x8,0x9,0x6],
  'D':[0xE,0x9,0x9,0x9,0xE],'E':[0xF,0x8,0xE,0x8,0xF],'F':[0xF,0x8,0xE,0x8,0x8],
  'G':[0x6,0x9,0xB,0x9,0x6],'H':[0x9,0x9,0xF,0x9,0x9],'I':[0xE,0x4,0x4,0x4,0xE],
  'J':[0x7,0x2,0x2,0xA,0x4],'K':[0x9,0xA,0xC,0xA,0x9],'L':[0x8,0x8,0x8,0x8,0xF],
  'M':[0x9,0xF,0xF,0x9,0x9],'N':[0x9,0xD,0xF,0xB,0x9],'O':[0x6,0x9,0x9,0x9,0x6],
  'P':[0xE,0x9,0xE,0x8,0x8],'Q':[0x6,0x9,0x9,0xA,0x5],'R':[0xE,0x9,0xE,0xA,0x9],
  'S':[0x7,0x8,0x6,0x1,0xE],'T':[0xF,0x4,0x4,0x4,0x4],'U':[0x9,0x9,0x9,0x9,0x6],
  'V':[0x9,0x9,0x9,0xA,0x4],'W':[0x9,0x9,0xF,0xF,0x9],'X':[0x9,0x9,0x6,0x9,0x9],
  'Y':[0x9,0x9,0x6,0x2,0x2],'Z':[0xF,0x1,0x6,0x8,0xF],
  '0':[0x6,0x9,0x9,0x9,0x6],'1':[0x4,0xC,0x4,0x4,0xE],'2':[0xE,0x1,0x6,0x8,0xF],
  '3':[0xE,0x1,0x6,0x1,0xE],'4':[0x9,0x9,0xF,0x1,0x1],'5':[0xF,0x8,0xE,0x1,0xE],
  '6':[0x6,0x8,0xE,0x9,0x6],'7':[0xF,0x1,0x2,0x4,0x4],'8':[0x6,0x9,0x6,0x9,0x6],
  '9':[0x6,0x9,0x7,0x1,0x6],
  '-':[0x0,0x0,0xE,0x0,0x0],'.':[0x0,0x0,0x0,0x0,0x4],' ':[0x0,0x0,0x0,0x0,0x0],
  ':':[0x0,0x4,0x0,0x4,0x0],'/':[0x1,0x2,0x4,0x8,0x0],"'":[0x4,0x4,0x0,0x0,0x0],
  '+':[0x0,0x4,0xE,0x4,0x0],'%':[0x9,0x2,0x4,0x8,0x9],'!':[0x4,0x4,0x4,0x0,0x4],
  '&':[0x4,0xA,0x5,0xA,0x5],'>':[0x4,0x2,0x1,0x2,0x4],'<':[0x1,0x2,0x4,0x2,0x1],
}};

// ─── Sport Colors ─────────────────────────────────────────────────────────────
const SPORT_COLORS = {{
  NFL:'#FF6B35', NBA:'#C9082A', NHL:'#00B2E3', MLB:'#003DA5',
  SOCCER:'#4CAF50', EPL:'#3D195B', GOLF:'#66BB44',
  WEATHER:'#44AAFF', STOCKS:'#44DD88', FLIGHT:'#00DDCC',
  DEFAULT:'#FFAA44'
}};

function sportColor(sport) {{
  const k = (sport || '').toUpperCase();
  return SPORT_COLORS[k] || SPORT_COLORS.DEFAULT;
}}

// ─── Canvas setup ─────────────────────────────────────────────────────────────
const canvas  = document.getElementById('ticker-canvas');
const ctx     = canvas.getContext('2d');
const pauseBadge = document.getElementById('pause-badge');
const fetchStatus = document.getElementById('fetch-status');

// ─── Font drawing helpers ─────────────────────────────────────────────────────
/**
 * Draw one character at LED grid position (ledX, ledY).
 * Each glyph is 4 LED-pixels wide × 5 LED-pixels tall.
 * Returns LED pixels consumed (4 char + 1 gap = 5).
 */
function drawChar(ctx, ch, ledX, ledY, color) {{
  const rows = FONT[ch.toUpperCase()] || FONT[' '];
  ctx.fillStyle = color;
  ctx.shadowBlur  = 3;
  ctx.shadowColor = color;
  for (let row = 0; row < 5; row++) {{
    const bits = rows[row];
    for (let col = 0; col < 4; col++) {{
      if (bits & (0x8 >> col)) {{
        ctx.fillRect((ledX + col) * SCALE, (ledY + row) * SCALE, SCALE, SCALE);
      }}
    }}
  }}
  ctx.shadowBlur = 0;
  return 5; // 4 wide + 1 gap
}}

/**
 * Draw a string. Returns total LED pixel width consumed.
 */
function drawText(ctx, text, ledX, ledY, color) {{
  let x = ledX;
  for (const ch of text) {{
    x += drawChar(ctx, ch, x, ledY, color);
  }}
  return x - ledX;
}}

/**
 * Measure text width in LED pixels without drawing.
 */
function measureText(text) {{
  return text.length * 5;
}}

// ─── State ───────────────────────────────────────────────────────────────────
let allItems      = [];   // parsed from API
let segments      = [];   // [{{text, color, item}}]
let totalLedWidth = 0;
let scrollLedX    = 0;    // fractional LED pixels scrolled
let paused        = false;
let activeMode    = 'ALL';
let itemRects     = [];   // [{{item, startX, endX}}] in absolute LED coords each frame
let selectedItem  = null;
let rafId         = null;

// ─── Data Fetching ────────────────────────────────────────────────────────────
function buildApiUrl() {{
  if (TICKER_ID) return '/api/state?id=' + encodeURIComponent(TICKER_ID);
  return '/api/state';
}}

function parseSports(data) {{
  const sports = (data && data.content && data.content.sports) ? data.content.sports : [];
  const items = [];
  for (const item of sports) {{
    items.push(item);
  }}
  return items;
}}

function itemToSegment(item) {{
  const type = (item.type || item.sport || '').toUpperCase();
  const color = sportColor(type);
  let text = '';

  if (type === 'WEATHER') {{
    const city  = (item.city  || item.location || '').toUpperCase().slice(0, 12);
    const temp  = item.temp  != null ? Math.round(item.temp)  + 'F' : '';
    const cond  = (item.condition || item.description || '').toUpperCase().slice(0, 10);
    text = [city, temp, cond].filter(Boolean).join('  ');
  }} else if (type === 'STOCKS' || type === 'STOCK') {{
    const sym = (item.symbol || '').toUpperCase();
    const price = item.price != null ? '$' + (+item.price).toFixed(2) : '';
    const pct   = item.change_pct != null
      ? (item.change_pct >= 0 ? '+' : '') + (+item.change_pct).toFixed(1) + '%'
      : '';
    text = [sym, price, pct].filter(Boolean).join('  ');
  }} else if (type === 'FLIGHT') {{
    const flt  = (item.flight || item.id || '').toUpperCase();
    const orig = (item.origin || '').toUpperCase();
    const dest = (item.dest   || item.destination || '').toUpperCase();
    const stat = (item.status || '').toUpperCase().slice(0, 8);
    const route = orig && dest ? orig + '>' + dest : '';
    text = [flt, route, stat].filter(Boolean).join('  ');
  }} else {{
    // Generic game / sports item
    const sport  = type.slice(0, 4);
    const away   = (item.away_abbr  || item.away   || '').toUpperCase().slice(0, 4);
    const home   = (item.home_abbr  || item.home   || '').toUpperCase().slice(0, 4);
    const aScore = item.away_score != null ? String(item.away_score) : '';
    const hScore = item.home_score != null ? String(item.home_score) : '';
    const score  = (aScore !== '' && hScore !== '') ? aScore + '-' + hScore : '';
    const status = (item.status || item.clock || item.period || '').toUpperCase().slice(0, 8);
    const parts  = [sport];
    if (away)   parts.push(away);
    if (score)  parts.push(score);
    if (home)   parts.push(home);
    if (status) parts.push(status);
    text = parts.join(' ');
  }}

  return {{ text, color, item }};
}}

function rebuildSegments() {{
  const filtered = activeMode === 'ALL'
    ? allItems
    : allItems.filter(it => {{
        const t = (it.type || it.sport || '').toUpperCase();
        return t === activeMode || t.startsWith(activeMode);
      }});

  segments = filtered.map(itemToSegment);

  // Compute total scroll width: each segment + '  ·  ' divider
  const DIV_W = measureText(' · ');
  totalLedWidth = 0;
  for (let i = 0; i < segments.length; i++) {{
    totalLedWidth += measureText(segments[i].text);
    if (i < segments.length - 1) totalLedWidth += DIV_W;
  }}
  totalLedWidth += DIV_W; // trailing gap before loop
}}

async function fetchData() {{
  try {{
    const resp = await fetch(buildApiUrl());
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    allItems = parseSports(data);
    rebuildSegments();
    const ts = new Date().toLocaleTimeString();
    fetchStatus.textContent = 'Last fetch: ' + ts + '  ·  ' + allItems.length + ' items';
    updateDetailPanel();
  }} catch(e) {{
    fetchStatus.textContent = 'Fetch error: ' + e.message;
  }}
}}

// ─── LED Canvas rendering ─────────────────────────────────────────────────────
function drawOffGrid() {{
  ctx.fillStyle = '#111116';
  for (let ly = 0; ly < LED_H; ly++) {{
    for (let lx = 0; lx < LED_W; lx++) {{
      // 1×1 dot centered in each 2×2 LED cell
      ctx.fillRect(lx * SCALE, ly * SCALE, 1, 1);
    }}
  }}
}}

function renderFrame() {{
  // Background
  ctx.fillStyle = '#060608';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Off-LED grid
  drawOffGrid();

  if (!segments.length) {{
    // No data: draw placeholder
    ctx.shadowBlur = 0;
    drawText(ctx, 'NO DATA', 2, 13, '#333333');
    return;
  }}

  // Build absolute-position item rects for this frame
  const newRects = [];
  const DIV_W = measureText(' · ');
  const DIV_COLOR = '#333333';
  const TEXT_Y = 13; // LED row to center 5-tall text in 32-tall display

  // scrollLedX is how many LED pixels we've scrolled
  // content starts at LED x=192 (center-right of 384-wide) and scrolls left
  // visible LED range: 0..383
  // "world" x of segment start = 192 - scrollLedX + offset_into_segments
  // We need to iterate segments and wrap

  // Calculate starting world-x for each segment
  let segStarts = [];
  let cur = 0;
  for (let i = 0; i < segments.length; i++) {{
    segStarts.push(cur);
    cur += measureText(segments[i].text);
    if (i < segments.length - 1) cur += DIV_W;
  }}
  cur += DIV_W; // trailing gap

  // Origin on canvas: content starts scrolling in from right (LED x=192 at scroll=0)
  // canvasLedX = 192 - scrollLedX + worldX
  // We render 2 copies to cover wrap
  for (let copy = 0; copy < 3; copy++) {{
    const worldOffset = copy * totalLedWidth;

    for (let i = 0; i < segments.length; i++) {{
      const seg = segments[i];
      const worldX = segStarts[i] + worldOffset;
      const ledX   = Math.round(192 - scrollLedX + worldX);

      // Cull: skip if entirely off-canvas
      const segW = measureText(seg.text);
      if (ledX + segW < -5 || ledX > LED_W + 5) {{
        // Still track rect for hit-test
        const cxStart = (ledX) * SCALE;
        const cxEnd   = (ledX + segW) * SCALE;
        newRects.push({{ item: seg.item, canvasStartX: cxStart, canvasEndX: cxEnd }});
        continue;
      }}

      // Draw text
      drawText(ctx, seg.text, ledX, TEXT_Y, seg.color);

      const cxStart = ledX * SCALE;
      const cxEnd   = (ledX + segW) * SCALE;
      newRects.push({{ item: seg.item, canvasStartX: cxStart, canvasEndX: cxEnd }});

      // Divider
      if (i < segments.length - 1) {{
        const divX = ledX + segW + 1;
        drawText(ctx, '·', divX, TEXT_Y, DIV_COLOR);
      }}
    }}
  }}

  itemRects = newRects;
}}

// ─── Animation loop ───────────────────────────────────────────────────────────
function tick() {{
  if (!paused && totalLedWidth > 0) {{
    scrollLedX += FPS_SCROLL;
    if (scrollLedX >= totalLedWidth) scrollLedX -= totalLedWidth;
  }}
  renderFrame();
  rafId = requestAnimationFrame(tick);
}}

// ─── Detail Panel ─────────────────────────────────────────────────────────────
function itemSportKey(item) {{
  return (item.type || item.sport || '').toUpperCase();
}}

function makeDetailCard(item, idx) {{
  const sport  = itemSportKey(item);
  const color  = sportColor(sport);
  const bgC    = color + '22';
  const type   = (item.type || item.sport || '').toUpperCase();

  let teamsHtml = '', scoreHtml = '', statusHtml = '', detailHtml = '';

  if (type === 'WEATHER') {{
    const city  = item.city || item.location || 'N/A';
    const temp  = item.temp != null ? Math.round(item.temp) + '°F' : '';
    const cond  = item.condition || item.description || '';
    teamsHtml  = `<div class="dc-teams">${{city}}</div>`;
    scoreHtml  = temp ? `<div class="dc-score">${{temp}}</div>` : '';
    statusHtml = `<div class="dc-status">${{cond}}</div>`;
    detailHtml = `<div class="row"><span>Humidity</span><span>${{item.humidity != null ? item.humidity + '%' : '—'}}</span></div>
                  <div class="row"><span>Wind</span><span>${{item.wind || '—'}}</span></div>`;
  }} else if (type === 'STOCKS' || type === 'STOCK') {{
    const sym  = item.symbol || '';
    const price = item.price != null ? '$' + (+item.price).toFixed(2) : '';
    const pct   = item.change_pct != null ? (+item.change_pct).toFixed(2) + '%' : '';
    const pctColor = (item.change_pct || 0) >= 0 ? '#44dd88' : '#ff4444';
    teamsHtml  = `<div class="dc-teams">${{sym}}</div>`;
    scoreHtml  = price ? `<div class="dc-score">${{price}}</div>` : '';
    statusHtml = pct ? `<div class="dc-status" style="color:${{pctColor}}">${{pct}}</div>` : '';
    detailHtml = `<div class="row"><span>Change</span><span style="color:${{pctColor}}">${{item.change || pct}}</span></div>
                  <div class="row"><span>Volume</span><span>${{item.volume || '—'}}</span></div>`;
  }} else if (type === 'FLIGHT') {{
    const flt  = item.flight || item.id || '';
    const orig = item.origin || '';
    const dest = item.dest || item.destination || '';
    const stat = item.status || '';
    teamsHtml  = `<div class="dc-teams">${{flt}}</div>`;
    scoreHtml  = (orig && dest) ? `<div class="dc-score" style="font-size:16px">${{orig}} → ${{dest}}</div>` : '';
    statusHtml = `<div class="dc-status">${{stat}}</div>`;
    detailHtml = `<div class="row"><span>Departure</span><span>${{item.depart || '—'}}</span></div>
                  <div class="row"><span>Arrival</span><span>${{item.arrive || '—'}}</span></div>`;
  }} else {{
    // Game
    const away   = item.away   || item.away_name   || '';
    const home   = item.home   || item.home_name   || '';
    const aScore = item.away_score != null ? item.away_score : '';
    const hScore = item.home_score != null ? item.home_score : '';
    const status = item.status || item.clock || '';
    const isFinal = /final|ft|full/i.test(status);
    const isLive  = !isFinal && (item.period || item.clock);
    const statusColor = isLive ? color : isFinal ? '#555' : '#888';
    teamsHtml  = `<div class="dc-teams">${{away}} vs ${{home}}</div>`;
    scoreHtml  = (aScore !== '' && hScore !== '')
      ? `<div class="dc-score">${{aScore}} – ${{hScore}}</div>` : '';
    statusHtml = `<div class="dc-status" style="color:${{statusColor}}">${{status}}</div>`;
    detailHtml = `<div class="row"><span>League</span><span>${{item.league || sport}}</span></div>
                  <div class="row"><span>Venue</span><span>${{item.venue || '—'}}</span></div>`;
  }}

  return `<div class="dc" data-idx="${{idx}}" onclick="toggleCard(this,${{idx}})">
    <div class="dc-badge" style="background:${{bgC}};color:${{color}};border:1px solid ${{color}}40">${{sport}}</div>
    ${{teamsHtml}}
    ${{scoreHtml}}
    ${{statusHtml}}
    <div class="dc-detail">${{detailHtml}}</div>
  </div>`;
}}

function updateDetailPanel() {{
  const grid = document.getElementById('detail-grid');
  const title = document.getElementById('detail-title');
  const filtered = activeMode === 'ALL'
    ? allItems
    : allItems.filter(it => {{
        const t = itemSportKey(it);
        return t === activeMode || t.startsWith(activeMode);
      }});

  title.textContent = (activeMode === 'ALL' ? 'All Items' : activeMode) + ' — ' + filtered.length + ' items';

  if (!filtered.length) {{
    grid.innerHTML = '<p style="color:#333;font-size:12px">No items for this filter.</p>';
    return;
  }}
  grid.innerHTML = filtered.map((item, idx) => makeDetailCard(item, idx)).join('');
}}

// ─── Card toggle ──────────────────────────────────────────────────────────────
window.toggleCard = function(el, idx) {{
  const wasActive = el.classList.contains('active');
  document.querySelectorAll('.dc.active').forEach(c => c.classList.remove('active'));
  if (!wasActive) el.classList.add('active');
}};

// ─── Canvas click — pause + item selection ────────────────────────────────────
document.getElementById('canvas-wrap').addEventListener('click', function(e) {{
  const rect   = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const clickX = (e.clientX - rect.left) * scaleX; // canvas pixel x

  // Find hit item
  let hit = null;
  for (const r of itemRects) {{
    if (clickX >= r.canvasStartX && clickX <= r.canvasEndX) {{
      hit = r.item;
      break;
    }}
  }}

  if (hit) {{
    // Highlight matching card in detail panel
    const idx = allItems.indexOf(hit);
    if (idx !== -1) {{
      const card = document.querySelector('.dc[data-idx="' + idx + '"]');
      if (card) {{
        document.querySelectorAll('.dc.active').forEach(c => c.classList.remove('active'));
        card.classList.add('active');
        card.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
      }}
    }}
  }} else {{
    // Toggle pause
    paused = !paused;
    pauseBadge.classList.toggle('visible', paused);
  }}
}});

// ─── Mode filter buttons ──────────────────────────────────────────────────────
document.getElementById('mode-filters').addEventListener('click', function(e) {{
  const btn = e.target.closest('.mf-btn');
  if (!btn) return;
  document.querySelectorAll('.mf-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  activeMode = btn.dataset.mode;
  rebuildSegments();
  scrollLedX = 0;
  updateDetailPanel();
}});

// ─── Boot ─────────────────────────────────────────────────────────────────────
fetchData();
setInterval(fetchData, FETCH_EVERY);
tick();

}})();
</script>
</body>
</html>"""
    return make_response(html, 200, {'Content-Type': 'text/html'})


