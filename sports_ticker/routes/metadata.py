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
      <button class="mf-btn active" data-mode="sports"         style="--c:#FF8C00">ALL SPORTS</button>
      <button class="mf-btn"        data-mode="live"           style="--c:#FF4444">LIVE</button>
      <button class="mf-btn"        data-mode="stocks"         style="--c:#44DD88">STOCKS</button>
      <button class="mf-btn"        data-mode="music"          style="--c:#CC44FF">MUSIC</button>
      <button class="mf-btn"        data-mode="flights"        style="--c:#00DDCC">FLIGHTS</button>
      <button class="mf-btn"        data-mode="flight_tracker" style="--c:#00AACC">TRACKER</button>
      <button class="mf-btn"        data-mode="weather"        style="--c:#44AAFF">WEATHER</button>
      <button class="mf-btn"        data-mode="clock"          style="--c:#888888">CLOCK</button>
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
function tick() {{
  if (!paused && stripBitmap && stripSrcW > LED_W) {{
    scrollSrcX += SCROLL_SPD;
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
    teams  = away + ' vs ' + home;
    score  = (aScore !== '' && hScore !== '') ? aScore + ' – ' + hScore : '';
    status = `<span style="color:${{isLive ? color : isFinal ? '#555' : '#888'}}">${{item.status||item.clock||''}}</span>`;
    detail = `<div class="row"><span>League</span><span>${{item.league||sport}}</span></div>
              <div class="row"><span>Venue</span><span>${{item.venue||'—'}}</span></div>`;
    // Logos
    const awayLogo = item.away_logo ? `<img src="${{item.away_logo}}" style="width:16px;height:16px;object-fit:contain;vertical-align:middle;margin-right:4px" onerror="this.style.display='none'">` : '';
    const homeLogo = item.home_logo ? `<img src="${{item.home_logo}}" style="width:16px;height:16px;object-fit:contain;vertical-align:middle;margin-left:4px"  onerror="this.style.display='none'">` : '';
    teams = awayLogo + away + ' vs ' + home + homeLogo;
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
  fetchAll();
}});

// ─── Boot ─────────────────────────────────────────────────────────────────────
fetchAll();
setInterval(fetchAll, FETCH_EVERY);
tick();

}})();
</script>
</body>
</html>"""
    return make_response(html, 200, {'Content-Type': 'text/html'})


