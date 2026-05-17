(function () {
'use strict';

const CFG = window._CFG || {};
const TICKER_ID = CFG.tickerId || '';
const BROWSER_RT = null; // always use server preview — pyodide has no fonts available

const LED_W = 384;
const LED_H = 32;
const SCALE = 2;
const SCROLL_SPD = 0.3;
const FETCH_EVERY = 10000;
const STATIC_MODES = new Set(['music', 'weather', 'clock', 'flights', 'flight_tracker']);

const canvas = document.getElementById('ticker-canvas');
const ctx = canvas.getContext('2d');
const pauseBadge = document.getElementById('pause-badge');
const fetchStatus = document.getElementById('fetch-status');

ctx.imageSmoothingEnabled = false;

let stripBitmap = null;
let stripSrcW = 0;
let scrollSrcX = 0;
let loadingFrame = 0;
let paused = false;
let currentApiMode = CFG.defaultMode || 'sports';
let allItems = [];
let pinnedId = null;
let activeStockListId = 'stock_tech_ai';
let lastFetchAt = 0;

const STOCK_LISTS = [
  { id: 'stock_tech_ai',   label: 'Tech / AI'  },
  { id: 'stock_momentum',  label: 'Momentum'   },
  { id: 'stock_energy',    label: 'Energy'     },
  { id: 'stock_finance',   label: 'Financial'  },
  { id: 'stock_consumer',  label: 'Consumer'   },
];
let nowPlayingStart = 0;
let nowPlayingDuration = 210;
let musicVinylRot = 0;
let musicWavePhase = 0;
let musicArtImg = null;
let musicArtUrlLoaded = '';
let musicTrackTitle = '';
let musicTrackArtist = '';
let musicDominantColor = [29, 185, 84];
let musicSpindleLight = true;
let musicVizHeights = new Array(16).fill(2);
let musicTextScrollPos = 0;

window._scrollSpd = SCROLL_SPD;

function isStaticMode(mode) {
  if (pinnedId) return true;
  return STATIC_MODES.has(String(mode || '').toLowerCase());
}

function drawLedGrid() {
  ctx.fillStyle = 'rgba(0,0,0,0.45)';
  for (let sy = 0; sy < LED_H * SCALE; sy += SCALE) {
    for (let sx = 0; sx < LED_W * SCALE; sx += SCALE) {
      ctx.fillRect(sx, sy, 1, 1);
    }
  }
}

function renderClockOnCanvas() {
  const cw = LED_W * SCALE, ch = LED_H * SCALE;
  ctx.fillStyle = '#040406';
  ctx.fillRect(0, 0, cw, ch);

  const now = new Date();
  const hh = String((now.getHours() % 12) || 12);
  const mm = now.getMinutes().toString().padStart(2, '0');
  const ss = now.getSeconds().toString().padStart(2, '0');
  const timeStr = `${hh}:${mm}:${ss}`;

  const DAYS = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
  const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  const dateStr = (DAYS[now.getDay()] + ' ' + MONTHS[now.getMonth()] + ' ' + now.getDate()).toUpperCase();

  ctx.save();
  ctx.textAlign = 'center';

  // Date — small monospace at top, slightly cropped like the real ticker (y=-1 → y=-SCALE)
  ctx.textBaseline = 'top';
  ctx.font = `${SCALE * 9}px 'Courier New', 'DejaVu Sans Mono', monospace`;
  ctx.fillStyle = '#c8c8c8';
  ctx.fillText(dateStr, cw / 2, -SCALE);

  // Time — large bold display font centered (matches clock_giant = display_font 28 bold)
  ctx.textBaseline = 'top';
  ctx.font = `bold ${SCALE * 26}px Arial, 'Helvetica Neue', sans-serif`;
  ctx.fillStyle = '#ffffff';
  ctx.fillText(timeStr, cw / 2, SCALE * 5);

  ctx.restore();

  // Seconds progress bar — bottom 1 LED row (2px in SCALE=2)
  const totalSec = now.getSeconds() + now.getMilliseconds() / 1000;
  const barW = Math.round((totalSec / 60) * cw);
  ctx.fillStyle = '#1e1e1e';
  ctx.fillRect(0, ch - SCALE, cw, SCALE);
  ctx.fillStyle = '#00c8ff';
  if (barW > 0) ctx.fillRect(0, ch - SCALE, barW, SCALE);

  drawLedGrid();
}

function renderMusicOnCanvas() {
  // Faithful port of draw_music_card() from ticker_controller/modes/music.py
  // LED canvas: LED_W=384 x LED_H=32, scaled x2 to 768x64
  const S = SCALE;             // 2
  const cw = LED_W * S;        // 768
  const ch = LED_H * S;        // 64

  // Black background
  ctx.fillStyle = '#000000';
  ctx.fillRect(0, 0, cw, ch);

  // ── Vinyl disc ──────────────────────────────────────────────────────────
  // VINYL_SIZE=51, COVER_SIZE=42, pasted at LED(4, -9)
  // Vinyl center in LED coords: (4+25, -9+25) = (29, 16)
  // In canvas coords: (58, 32)
  const VINYL_R = 25.5 * S;    // half of 51 LED px
  const COVER_R = 21 * S;      // half of 42 LED px
  const vCx = (4 + 25.5) * S; // 59
  const vCy = (-9 + 25.5) * S; // 33

  ctx.save();
  ctx.translate(vCx, vCy);
  ctx.rotate(musicVinylRot * Math.PI / 180);

  // Scratch layer background disc: fill=(20,20,20), outline=(50,50,50)
  ctx.beginPath();
  ctx.arc(0, 0, VINYL_R, 0, Math.PI * 2);
  ctx.fillStyle = '#141414';
  ctx.fill();
  ctx.strokeStyle = '#323232';
  ctx.lineWidth = S * 0.5;
  ctx.stroke();

  // Album art clipped to COVER circle
  ctx.save();
  ctx.beginPath();
  ctx.arc(0, 0, COVER_R, 0, Math.PI * 2);
  ctx.clip();
  if (musicArtImg && musicArtImg.complete && musicArtImg.naturalWidth > 0) {
    ctx.drawImage(musicArtImg, -COVER_R, -COVER_R, COVER_R * 2, COVER_R * 2);
  } else {
    ctx.fillStyle = '#1a1a1a';
    ctx.fillRect(-COVER_R, -COVER_R, COVER_R * 2, COVER_R * 2);
  }
  ctx.restore();

  // Spindle: outer (22,22,28,28) → radius 3 at center; inner (23,23,27,27) → radius 2
  ctx.beginPath();
  ctx.arc(0, 0, 3 * S, 0, Math.PI * 2);
  ctx.fillStyle = '#222222';
  ctx.fill();
  ctx.beginPath();
  ctx.arc(0, 0, 2 * S, 0, Math.PI * 2);
  ctx.fillStyle = musicSpindleLight ? '#ffffff' : '#000000';
  ctx.fill();

  ctx.restore(); // end vinyl rotation

  // ── Text ─────────────────────────────────────────────────────────────────
  // TEXT_X = 60 LED px → 120 canvas px
  const TEXT_X = 60 * S;
  const [dr, dg, db] = musicDominantColor;

  // Song title: medium_font (12pt mono bold), y=0
  ctx.save();
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  ctx.font = `bold ${12 * S}px 'Courier New', 'Consolas', monospace`;
  ctx.fillStyle = '#ffffff';
  // Scrolling text: clip to text area width (188 LED px → 376 canvas px)
  const songArea = 188 * S;
  ctx.save();
  ctx.rect(TEXT_X, 0, songArea, 16 * S);
  ctx.clip();
  const songTxt = musicTrackTitle || 'Unknown';
  const songW = ctx.measureText(songTxt).width;
  if (songW <= songArea) {
    ctx.fillText(songTxt, TEXT_X, 0);
  } else {
    const GAP = 40 * S;
    const loop = songW + GAP;
    const off = musicTextScrollPos % loop;
    ctx.fillText(songTxt, TEXT_X - off, 0);
    if (TEXT_X - off + songW < TEXT_X + songArea) {
      ctx.fillText(songTxt, TEXT_X - off + loop, 0);
    }
  }
  ctx.restore();

  // Artist: tiny (9pt mono), y=17, x=TEXT_X+16
  ctx.font = `${9 * S}px 'Courier New', 'Consolas', monospace`;
  ctx.fillStyle = '#b4b4b4';
  const artistArea = 172 * S;
  ctx.save();
  ctx.rect(TEXT_X + 16 * S, 17 * S, artistArea, 12 * S);
  ctx.clip();
  const artistTxt = musicTrackArtist || 'Unknown';
  const artistW = ctx.measureText(artistTxt).width;
  if (artistW <= artistArea) {
    ctx.fillText(artistTxt, TEXT_X + 16 * S, 17 * S);
  } else {
    const GAP = 40 * S;
    const loop = artistW + GAP;
    const off = musicTextScrollPos % loop;
    ctx.fillText(artistTxt, TEXT_X + 16 * S - off, 17 * S);
    if (TEXT_X + 16 * S - off + artistW < TEXT_X + 16 * S + artistArea) {
      ctx.fillText(artistTxt, TEXT_X + 16 * S - off + loop, 17 * S);
    }
  }
  ctx.restore();
  ctx.restore();

  // ── Music note icon: ellipse (60,15)→(72,27) filled dominant color ───────
  const noteCx = (60 + 6) * S;  // 132
  const noteCy = (15 + 6) * S;  // 42
  const noteRx = 6 * S;
  const noteRy = 6 * S;
  ctx.beginPath();
  ctx.ellipse(noteCx, noteCy, noteRx, noteRy, 0, 0, Math.PI * 2);
  ctx.fillStyle = `rgb(${dr},${dg},${db})`;
  ctx.fill();
  // Arcs inside: draw_music_card draws 3 arcs (190°→350°) as grooves
  ctx.strokeStyle = 'rgba(0,0,0,0.7)';
  ctx.lineWidth = S * 0.5;
  for (let ai = 0; ai < 3; ai++) {
    const arcCy = noteCy - 3 * S + ai * 2 * S;
    ctx.beginPath();
    ctx.arc(noteCx, arcCy, 3 * S, 190 * Math.PI / 180, 350 * Math.PI / 180);
    ctx.stroke();
  }

  // ── Visualizer: x=248, y=6, width=80, height=20, 16 bars ──────────────
  // bar_w=2, gap=3 → spacing=5 per bar, all in LED px
  const VIZ_X = 248 * S;
  const VIZ_CY = (6 + 10) * S;  // center_y = y + height/2 = 6+10 = 16 → canvas 32
  const BAR_W = 2 * S;
  const BAR_STEP = 5 * S;        // bar_w + gap = 5 LED px
  const VIZ_MAX_H = 20 * S;

  const isPlaying = nowPlayingStart > 0 && nowPlayingDuration > 0;
  const t = musicWavePhase;

  for (let i = 0; i < 16; i++) {
    let targetH;
    if (isPlaying) {
      const base = Math.sin(t * 0.8 + musicVizHeights[i] * 0.01 + i);
      const noise = Math.sin(t * 2 + i * 0.5) * 0.8;
      let amp;
      if (i < 5) amp = (8.0 + Math.sin(t * 0.4) * 2) * S;
      else if (i < 11) amp = 6.0 * S;
      else amp = (4.0 + noise * 2) * S;
      targetH = Math.max(2 * S, Math.min(VIZ_MAX_H, Math.abs(base + noise) * amp));
    } else {
      targetH = 2 * S;
    }
    musicVizHeights[i] += (targetH - musicVizHeights[i]) * 0.25;
    const h = musicVizHeights[i];
    const by = VIZ_CY - h / 2;

    const factor = i / 15 * 0.6;
    const vr = Math.min(255, Math.round(dr + (255 - dr) * factor));
    const vg = Math.min(255, Math.round(dg + (255 - dg) * factor));
    const vb = Math.min(255, Math.round(db + (255 - db) * factor));
    ctx.fillStyle = `rgb(${vr},${vg},${vb})`;
    ctx.fillRect(VIZ_X + i * BAR_STEP, by, BAR_W, h);
  }

  // ── Progress bar: y=31, dominant color ───────────────────────────────────
  if (nowPlayingDuration > 0 && nowPlayingStart > 0) {
    const elapsed = Math.min(Date.now() / 1000 - nowPlayingStart, nowPlayingDuration);
    const pct = elapsed / nowPlayingDuration;
    const barY = ch - S;  // bottom LED row → canvas y=62
    ctx.fillStyle = `rgb(${dr},${dg},${db})`;
    ctx.fillRect(0, barY, Math.round(pct * cw), S);

    // Time remaining: tiny font, right side, y=10
    const rem = nowPlayingDuration - elapsed;
    const m = Math.floor(Math.max(0, rem) / 60);
    const sec = Math.floor(Math.max(0, rem) % 60).toString().padStart(2, '0');
    const remStr = `-${m}:${sec}`;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'top';
    ctx.font = `${9 * S}px 'Courier New', 'Consolas', monospace`;
    ctx.fillStyle = '#ffffff';
    ctx.fillText(remStr, cw - 5 * S, 10 * S);
  }

  drawLedGrid();
}

function renderFrame() {
  if (currentApiMode === 'clock') {
    renderClockOnCanvas();
    return;
  }
  if (currentApiMode === 'music') {
    renderMusicOnCanvas();
    return;
  }

  ctx.fillStyle = '#040406';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  if (!stripBitmap || stripSrcW === 0) {
    // Scrolling wave loading animation
    const off = loadingFrame % (LED_W * 3);
    for (let sy = 0; sy < LED_H * SCALE; sy += SCALE) {
      const row = sy / SCALE;
      for (let sx = 0; sx < LED_W * SCALE; sx += SCALE) {
        const col = sx / SCALE;
        const wave = Math.sin((col - off / 3 + row * 0.5) * 0.45) * 0.5 + 0.5;
        const bright = Math.round(10 + wave * 22);
        ctx.fillStyle = `rgb(${bright},${bright},${Math.round(bright * 1.4)})`;
        ctx.fillRect(sx + 1, sy + 1, SCALE - 1, SCALE - 1);
      }
    }
    drawLedGrid();
    return;
  }

  const canvasH = LED_H * SCALE;
  if (isStaticMode(currentApiMode)) {
    const drawSrcW = Math.min(stripSrcW, LED_W);
    ctx.drawImage(stripBitmap, 0, 0, drawSrcW, LED_H, 0, 0, drawSrcW * SCALE, canvasH);
    // For music: draw the progress bar client-side so we don't re-fetch every second
    if (currentApiMode === 'music' && nowPlayingDuration > 0 && nowPlayingStart > 0) {
      const elapsed = Math.min(Date.now() / 1000 - nowPlayingStart, nowPlayingDuration);
      const pct = elapsed / nowPlayingDuration;
      const barY = canvasH - SCALE;
      ctx.fillStyle = '#111';
      ctx.fillRect(0, barY, LED_W * SCALE, SCALE);
      ctx.fillStyle = '#1DB954';
      ctx.fillRect(0, barY, Math.round(pct * LED_W * SCALE), SCALE);
    }
    drawLedGrid();
    return;
  }

  let dstX = 0;
  let srcX = Math.floor(scrollSrcX) % stripSrcW;

  while (dstX < LED_W * SCALE) {
    const availSrc = stripSrcW - srcX;
    const remainDst = LED_W * SCALE - dstX;
    const drawSrcW = Math.min(availSrc, Math.ceil(remainDst / SCALE));
    if (drawSrcW <= 0) break;
    ctx.drawImage(stripBitmap, srcX, 0, drawSrcW, LED_H, dstX, 0, drawSrcW * SCALE, canvasH);
    dstX += drawSrcW * SCALE;
    srcX = 0;
  }

  drawLedGrid();
}

function tick() {
  if (!paused && stripBitmap && stripSrcW > 0 && !isStaticMode(currentApiMode)) {
    scrollSrcX = (scrollSrcX + (window._scrollSpd || SCROLL_SPD)) % stripSrcW;
  }
  if (!stripBitmap || stripSrcW === 0) loadingFrame++;
  if (currentApiMode === 'music' && !paused) {
    // vinyl_rotation decrements by 100°/s; at 60fps → ~1.67°/frame
    musicVinylRot = (musicVinylRot - 1.67 + 360) % 360;
    musicWavePhase += 0.07;       // drives visualizer animation
    musicTextScrollPos += 0.25;   // matches 15px/s at ~60fps
  }
  renderFrame();
  requestAnimationFrame(tick);
}

async function fetchStrip() {
  // Clock and music are rendered directly on canvas — no strip fetch needed
  if (currentApiMode === 'clock' || currentApiMode === 'music') {
    fetchStatus.textContent = currentApiMode === 'clock' ? 'Clock — live canvas render' : 'Music — live canvas render';
    return;
  }

  if (BROWSER_RT && typeof BROWSER_RT.renderStrip === 'function') {
    try {
      const strip = await BROWSER_RT.renderStrip(currentApiMode, TICKER_ID);
      if (!strip || !strip.dataUrl) throw new Error('no strip data');
      const bmp = await createImageBitmap(await (await fetch(strip.dataUrl)).blob());
      stripBitmap = bmp;
      stripSrcW = strip.width || bmp.width;
      scrollSrcX = 0;
      lastFetchAt = Date.now();
      fetchStatus.textContent = 'Updated ' + new Date().toLocaleTimeString() + ' · browser runtime ' + stripSrcW + 'px';
      return;
    } catch (e) {
      console.warn('Browser runtime failed, falling back to server preview:', e);
    }
  }

  try {
    let url;
    if (pinnedId) {
      url = '/api/preview/strip.png?mode=sports_full&pin_id=' + encodeURIComponent(pinnedId);
    } else {
      url = '/api/preview/strip.png?mode=' + encodeURIComponent(currentApiMode);
    }
    const resp = await fetch(url, { cache: 'no-store' });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const bmp = await createImageBitmap(await resp.blob());
    stripBitmap = bmp;
    stripSrcW = bmp.width;
    scrollSrcX = 0;
    lastFetchAt = Date.now();
    fetchStatus.textContent = 'Updated ' + new Date().toLocaleTimeString() + ' · strip ' + bmp.width + 'px';
  } catch (e) {
    fetchStatus.textContent = 'Strip error: ' + e.message;
    console.warn('Strip render failed:', e);
  }
}

async function fetchItems() {
  try {
    const params = [];
    if (TICKER_ID) params.push('id=' + encodeURIComponent(TICKER_ID));
    if (currentApiMode) params.push('mode=' + encodeURIComponent(currentApiMode));
    const resp = await fetch('/api/state' + (params.length ? '?' + params.join('&') : ''));
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    allItems = data && Array.isArray(data.games) ? data.games.filter(item => item && item.is_shown !== false) : [];

    // Sync pin: use server pin if it has one; otherwise keep a locally-set pin so
    // the periodic refresh doesn't clear what the user just pinned (server may not
    // have a paired ticker to persist to during local dev).
    const serverPin = data && (data.pinned_game || (Array.isArray(data.pinned_games) ? data.pinned_games[0] : ''));
    if (serverPin) {
      pinnedId = String(serverPin);
    } else if (!pinnedId) {
      pinnedId = null;
    }
    document.getElementById('unpin-btn').style.display = pinnedId ? '' : 'none';

    // Sync active stock list from server state
    const as = data && data.settings && data.settings.active_sports;
    if (as) {
      const activeList = STOCK_LISTS.find(l => as[l.id]);
      if (activeList) activeStockListId = activeList.id;
    }
    _syncStockListButtons();

    updateDetailPanel();
  } catch (e) {
    console.warn('Items fetch error:', e.message);
  }
}

async function fetchAll() {
  await Promise.all([fetchStrip(), fetchItems()]);
}

function _syncStockListButtons() {
  document.querySelectorAll('.sl-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.list === activeStockListId);
  });
}

window.setStockList = async function (listId) {
  activeStockListId = listId;
  _syncStockListButtons();
  updateDetailPanel();
  const activeSports = {};
  STOCK_LISTS.forEach(l => { activeSports[l.id] = (l.id === listId); });
  try {
    await fetch('/api/config', {
      method: 'POST',
      headers: _tickerHeaders(),
      body: _tickerBody({ active_sports: activeSports }),
    });
    fetchAll();
  } catch (e) {
    console.error('stock list switch error', e);
  }
};

const SPORT_COLORS = {
  NFL: '#FF6B35', NBA: '#C9082A', NHL: '#00B2E3', MLB: '#003DA5',
  NCF_FBS: '#FF8C00', NCF_FCS: '#FF8C00',
  SOCCER_EPL: '#3D195B', SOCCER_FA_CUP: '#3D195B', SOCCER_CHAMP: '#003DA5',
  SOCCER_CHAMPIONS_LEAGUE: '#003366', SOCCER_EUROPA_LEAGUE: '#FF6B00',
  SOCCER_MLS: '#C0392B', SOCCER_WC: '#C09A2A',
  GOLF: '#66BB44', MASTERS: '#FFDD00',
  WEATHER: '#44AAFF', STOCK_TICKER: '#44DD88',
  MUSIC: '#CC44FF', CLOCK: '#888888',
  FLIGHT: '#00DDCC', FLIGHT_VISITOR: '#00AACC',
  DEFAULT: '#FF8C00',
};

function sportColor(item) {
  const sp = (item.sport || '').toUpperCase();
  const ty = (item.type || '').toUpperCase();
  return SPORT_COLORS[sp] || SPORT_COLORS[ty] || (sp.startsWith('SOCCER') ? '#4CAF50' : SPORT_COLORS.DEFAULT);
}

function isSportsGame(item) {
  const itype = (item.type || '').toLowerCase();
  const sport = (item.sport || '').toLowerCase();
  if (['weather', 'stock_ticker', 'music', 'clock', 'flight_visitor', 'flight'].includes(itype)) return false;
  if (sport === 'flight') return false;
  return !!(item.home || item.away || item.home_name || item.away_name || item.id);
}

function updateDetailPanel() {
  const grid = document.getElementById('detail-grid');
  const title = document.getElementById('detail-title');
  const activeBtn = document.querySelector('.mf-btn.active');
  const label = activeBtn ? activeBtn.textContent : currentApiMode;

  // Stocks mode: show list selector cards instead of individual stocks
  if (currentApiMode === 'stocks') {
    title.textContent = 'Stock Lists';
    grid.innerHTML = STOCK_LISTS.map(list => {
      const isActive = list.id === activeStockListId;
      const color = '#22c55e';
      const border = isActive ? color : '';
      const activeStyle = isActive ? `border-color:${color};background:rgba(34,197,94,.07);box-shadow:0 0 14px rgba(34,197,94,.12)` : '';
      return `<div class="dc" style="cursor:pointer;${activeStyle}" onclick="setStockList('${list.id}')">
  <div class="dc-badge" style="background:rgba(34,197,94,.1);color:${color};border:1px solid rgba(34,197,94,.3)">STOCKS</div>
  <div class="dc-teams">${list.label}</div>
  <div class="dc-status" style="color:${isActive ? color : 'var(--text-mute)'}">${isActive ? '● Active' : '○ Inactive'}</div>
</div>`;
    }).join('');
    return;
  }

  title.textContent = label + ' — ' + allItems.length + ' item' + (allItems.length !== 1 ? 's' : '');

  if (!allItems.length) {
    grid.innerHTML = '<p style="color:var(--text-mute);font-size:13px">No data for this mode.</p>';
    return;
  }

  grid.innerHTML = allItems.map((item, idx) => makeDetailCard(item, idx)).join('');

  if (pinnedId) {
    document.querySelectorAll('.dc[data-game-id="' + pinnedId + '"]')
      .forEach(el => el.classList.add('pinned'));
  }
}

window.toggleCard = function (el) {
  const was = el.classList.contains('active');
  document.querySelectorAll('.dc.active').forEach(c => c.classList.remove('active'));
  if (!was) el.classList.add('active');
};

function makeDetailCard(item, idx) {
  const color = sportColor(item);
  const bgC = color + '1a';
  const itype = (item.type || '').toLowerCase();
  const sport = (item.sport || itype || 'game').toUpperCase();
  let badge = sport.slice(0, 10);
  let teams = '';
  let score = '';
  let status = '';
  let detail = '';

  const gameId = item.id || '';
  const isGame = isSportsGame(item);
  const sportKey = (item.sport || '').toLowerCase();
  const pinId = isGame && sportKey && gameId ? `${sportKey}:${gameId}` : gameId;
  const clickFn = isGame && gameId ? `pinCardGame(this, '${pinId}')` : 'toggleCard(this)';
  const gameAttr = pinId ? ` data-game-id="${pinId}"` : '';

  if (itype === 'weather') {
    badge = 'WEATHER';
    teams = item.city || item.location || 'Weather';
    score = item.temp != null ? Math.round(item.temp) + '°F' : '';
    status = item.condition || item.description || '';
    detail = `<div class="row"><span>Humidity</span><span>${item.humidity != null ? item.humidity + '%' : '—'}</span></div>` +
             `<div class="row"><span>Wind</span><span>${item.wind || '—'}</span></div>`;
  } else if (itype === 'stock_ticker') {
    badge = 'STOCK';
    const pct = item.change_pct != null ? (+item.change_pct).toFixed(2) + '%' : '';
    const pctColor = (item.change_pct || 0) >= 0 ? '#44dd88' : '#ff4444';
    const stockLogo = item.home_logo ? `<img src="${item.home_logo}" style="width:18px;height:18px;object-fit:contain;vertical-align:middle;margin-right:4px" onerror="this.style.display='none'">` : '';
    teams = stockLogo + (item.symbol || '');
    score = item.price != null ? '$' + (+item.price).toFixed(2) : '';
    status = `<span style="color:${pctColor}">${pct}</span>`;
    detail = `<div class="row"><span>Change</span><span style="color:${pctColor}">${item.change || pct}</span></div>`;
  } else if (itype === 'music') {
    badge = 'MUSIC';
    teams = item.artist || item.artist_name || item.home_abbr || 'Unknown Artist';
    score = item.title || item.song || item.away_abbr || '';
    status = item.album || item.status || '';
  } else if (itype === 'clock') {
    badge = 'CLOCK';
    teams = 'Clock';
    score = item.time || item.clock_str || '';
  } else if (itype === 'flight_visitor') {
    badge = 'FLIGHT';
    teams = item.flight || item.id || '';
    score = (item.origin && item.dest) ? item.origin + ' → ' + item.dest : '';
    status = item.status || '';
    detail = `<div class="row"><span>Arrival</span><span>${item.arrive || '—'}</span></div>`;
  } else if ((item.sport || '').toLowerCase() === 'flight' || itype === 'flight') {
    badge = 'FLIGHT';
    teams = (item.airline || '') + ' ' + (item.flight_number || item.flight || '');
    score = item.destination || item.dest || '';
    status = item.status || '';
    detail = `<div class="row"><span>Gate</span><span>${item.gate || '—'}</span></div>` +
             `<div class="row"><span>Time</span><span>${item.time || item.scheduled || '—'}</span></div>`;
  } else {
    const away = item.away || item.away_name || '';
    const home = item.home || item.home_name || '';
    const aScore = item.away_score != null ? item.away_score : '';
    const hScore = item.home_score != null ? item.home_score : '';
    const isFinal = /final|ft|full/i.test(item.status || '');
    const isLive = !isFinal && (item.period || item.clock);
    score = (aScore !== '' && hScore !== '') ? aScore + ' – ' + hScore : '';
    status = `<span style="color:${isLive ? color : isFinal ? '#555' : '#888'}">${item.status || item.clock || ''}</span>`;
    detail = `<div class="row"><span>League</span><span>${item.league || sport}</span></div>` +
             `<div class="row"><span>Venue</span><span>${item.venue || '—'}</span></div>`;
    const awayLogo = item.away_logo ? `<img src="${item.away_logo}" style="width:18px;height:18px;object-fit:contain;vertical-align:middle;margin-right:4px" onerror="this.style.display='none'">` : '';
    const homeLogo = item.home_logo ? `<img src="${item.home_logo}" style="width:18px;height:18px;object-fit:contain;vertical-align:middle;margin-left:4px" onerror="this.style.display='none'">` : '';
    teams = awayLogo + away + ' vs ' + home + homeLogo;
  }

  return `<div class="dc" data-idx="${idx}"${gameAttr} onclick="${clickFn}">
    <div class="dc-badge" style="background:${bgC};color:${color};border:1px solid ${color}30">${badge}</div>
    <div class="dc-teams">${teams}</div>
    ${score ? `<div class="dc-score">${score}</div>` : ''}
    ${status ? `<div class="dc-status">${status}</div>` : ''}
    ${detail ? `<div class="dc-detail">${detail}</div>` : ''}
  </div>`;
}

canvas.addEventListener('click', function () {
  paused = !paused;
  pauseBadge.classList.toggle('visible', paused);
});

document.getElementById('mode-filters').addEventListener('click', function (e) {
  const btn = e.target.closest('.mf-btn');
  if (!btn) return;
  document.querySelectorAll('.mf-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  currentApiMode = btn.dataset.mode;
  scrollSrcX = 0;
  showCtrlPanel(currentApiMode);
  if (currentApiMode === 'music') fetchNowPlaying();
  fetch('/api/config', {
    method: 'POST',
    headers: _tickerHeaders(),
    body: _tickerBody({ mode: currentApiMode }),
  }).catch(e => console.error('mode switch error', e));
  fetchAll();
});

const speedRange = document.getElementById('speed-range');
const speedVal = document.getElementById('speed-val');
speedRange.addEventListener('input', function () {
  const v = parseInt(this.value, 10);
  window._scrollSpd = v * 0.1;
  speedVal.textContent = v;
});

function showCtrlPanel(mode) {
  document.querySelectorAll('.ctrl-panel').forEach(p => p.classList.remove('active'));
  const map = {
    sports: 'ctrl-sports', live: 'ctrl-sports',
    weather: 'ctrl-weather',
    flights: 'ctrl-flights', flight_tracker: 'ctrl-flight_tracker',
    music: 'ctrl-music',
    stocks: 'ctrl-stocks',
    clock: 'ctrl-clock',
  };
  const id = map[mode];
  if (id) document.getElementById(id)?.classList.add('active');
}

window.pinCardGame = async function (el, gameId) {
  const wasPinned = pinnedId === gameId;
  document.querySelectorAll('.dc.pinned').forEach(c => c.classList.remove('pinned'));

  if (wasPinned) {
    pinnedId = null;
    stripBitmap = null; stripSrcW = 0;
    document.getElementById('unpin-btn').style.display = 'none';
  } else {
    pinnedId = gameId;
    stripBitmap = null; stripSrcW = 0;
    el.classList.add('pinned');
    document.getElementById('unpin-btn').style.display = '';

    if (currentApiMode !== 'sports') {
      document.querySelectorAll('.mf-btn').forEach(b => b.classList.remove('active'));
      document.querySelector('.mf-btn[data-mode="sports"]')?.classList.add('active');
      currentApiMode = 'sports';
      scrollSrcX = 0;
      showCtrlPanel('sports');
    }
  }

  try {
    const payload = { game_ids: pinnedId ? [pinnedId] : [] };
    if (TICKER_ID) payload.ticker_id = TICKER_ID;
    await fetch('/api/pin_games', {
      method: 'POST',
      headers: _tickerHeaders(),
      body: JSON.stringify(payload),
    });
    if (pinnedId) {
      fetch('/api/config', {
        method: 'POST',
        headers: _tickerHeaders(),
        body: _tickerBody({ mode: 'sports' }),
      }).catch(() => {});
    }
    // Only refresh the strip — do NOT call fetchItems() which would read
    // pinnedId back from server state and clear it (server may not have a
    // paired ticker to persist the pin to during local dev)
    fetchStrip();
  } catch (e) {
    console.error(e);
  }
};

window.unpinGame = async function () {
  pinnedId = null;
  document.querySelectorAll('.dc.pinned').forEach(c => c.classList.remove('pinned'));
  document.getElementById('unpin-btn').style.display = 'none';
  try {
    const payload = { game_ids: [] };
    if (TICKER_ID) payload.ticker_id = TICKER_ID;
    await fetch('/api/pin_games', {
      method: 'POST',
      headers: _tickerHeaders(),
      body: JSON.stringify(payload),
    });
    fetchStrip(); // strip only; pinnedId is already null so fetchItems would be safe too
  } catch (e) {
    console.error(e);
  }
};

function _tickerHeaders() {
  const h = { 'Content-Type': 'application/json' };
  if (TICKER_ID) h['X-Client-ID'] = TICKER_ID;
  return h;
}
function _tickerBody(extra) {
  const b = Object.assign({}, extra);
  if (TICKER_ID) b.ticker_id = TICKER_ID;
  return JSON.stringify(b);
}

window.setWeather = async function () {
  const city = document.getElementById('weather-city').value.trim();
  if (!city) return;
  try {
    await fetch('/api/config', {
      method: 'POST',
      headers: _tickerHeaders(),
      body: _tickerBody({ weather_city: city, mode: 'weather' }),
    });
    fetchAll();
  } catch (e) {
    console.error(e);
  }
};

window.setAirport = async function () {
  const code = document.getElementById('airport-code').value.trim().toUpperCase();
  if (!code) return;
  try {
    await fetch('/api/config', {
      method: 'POST',
      headers: _tickerHeaders(),
      body: _tickerBody({ airport_code_iata: code, mode: 'flights', flight_submode: 'airport' }),
    });
    fetchAll();
  } catch (e) {
    console.error(e);
  }
};

window.setFlightTracker = async function () {
  const flt = document.getElementById('flight-id').value.trim().toUpperCase();
  const guest = document.getElementById('guest-name').value.trim();
  if (!flt) return;
  try {
    await fetch('/api/config', {
      method: 'POST',
      headers: _tickerHeaders(),
      body: _tickerBody({ track_flight_id: flt, track_guest_name: guest, mode: 'flight_tracker', flight_submode: 'track' }),
    });
    fetchAll();
  } catch (e) {
    console.error(e);
  }
};

window.clearFlight = async function () {
  document.getElementById('flight-id').value = '';
  document.getElementById('guest-name').value = '';
  try {
    await fetch('/api/config', {
      method: 'POST',
      headers: _tickerHeaders(),
      body: _tickerBody({ track_flight_id: '', track_guest_name: '' }),
    });
  } catch (e) {
    console.error(e);
  }
};

window.musicSearch = async function () {
  const q = document.getElementById('music-search-input').value.trim();
  if (!q) return;
  const resultsEl = document.getElementById('music-results');
  resultsEl.innerHTML = '<span style="color:var(--text-mute);font-size:12px">Searching…</span>';
  try {
    const r = await fetch('/api/music/search?q=' + encodeURIComponent(q));
    const items = await r.json();
    if (!items.length) {
      resultsEl.innerHTML = '<span style="color:var(--text-mute);font-size:12px">No results</span>';
      return;
    }
    resultsEl.innerHTML = items.map((it, i) => `
      <div class="music-result-row" onclick="selectCustomTrack(${i})" data-idx="${i}">
        <img class="music-result-art" src="${it.art_url}" onerror="this.style.display='none'" alt="">
        <div class="music-result-info">
          <div class="music-result-title">${it.title}</div>
          <div class="music-result-artist">${it.artist}</div>
        </div>
      </div>`).join('');
    resultsEl._items = items;
  } catch (e) {
    resultsEl.innerHTML = '<span style="color:#f44">Error: ' + e.message + '</span>';
  }
};

window.selectCustomTrack = async function (idx) {
  const resultsEl = document.getElementById('music-results');
  const items = resultsEl._items || [];
  const it = items[idx];
  if (!it) return;
  try {
    await fetch('/api/music/custom', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(it),
    });
    resultsEl.innerHTML = '';
    document.getElementById('music-search-input').value = '';
    document.getElementById('music-clear-btn').style.display = '';
    nowPlayingStart = Date.now() / 1000;
    nowPlayingDuration = (it.duration_ms || 180000) / 1000;
    renderNowPlaying(it.title, it.artist, it.art_url, 0, nowPlayingDuration);
    fetchAll();
  } catch (e) {
    console.error(e);
  }
};

window.clearCustomMusic = async function () {
  try {
    await fetch('/api/music/custom', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    document.getElementById('music-clear-btn').style.display = 'none';
    document.getElementById('music-results').innerHTML = '';
    fetchAll();
  } catch (e) {
    console.error(e);
  }
};

async function fetchNowPlaying() {
  const customR = await fetch('/api/music/custom').catch(() => null);
  if (customR && customR.ok) {
    const custom = await customR.json();
    if (custom && custom.title) {
      const durationSec = (custom.duration_ms || 0) / 1000 || 180;
      const elapsed = (Date.now() / 1000) - (custom.set_at || 0);
      const progressSec = elapsed % durationSec;
      nowPlayingDuration = durationSec;
      nowPlayingStart = Date.now() / 1000 - progressSec;
      renderNowPlaying(custom.title, custom.artist || '', custom.art_url || '', progressSec, durationSec);
      document.getElementById('music-clear-btn').style.display = '';
      return;
    }
  }
  try {
    const r = await fetch('/api/spotify/now');
    if (r.ok) {
      const d = await r.json();
      const title = d && (d.title || d.name || d.song || d.away_abbr || '');
      if (title && title !== 'Waiting for Music...') {
        const artist = d.artist || d.artist_name || d.home_abbr || '';
        const art = d.album_art || d.cover || d.home_logo || '';
        const durationRaw = Number(d.duration_ms || d.duration || 210);
        const progressRaw = Number(d.progress_ms || d.progress || 0);
        const durationSec = durationRaw > 10000 ? durationRaw / 1000 : durationRaw;
        const progressSec = progressRaw > 10000 ? progressRaw / 1000 : progressRaw;
        nowPlayingDuration = durationSec || 210;
        nowPlayingStart = Date.now() / 1000 - (progressSec || 0);
        renderNowPlaying(title, artist, art, progressSec || 0, nowPlayingDuration);
        return;
      }
    }
  } catch (_) {
  }

  try {
    const r = await fetch('https://itunes.apple.com/us/rss/topsongs/limit=10/json');
    if (r.ok) {
      const d = await r.json();
      const entries = d?.feed?.entry || [];
      if (entries.length) {
        const song = entries[Math.floor(Math.random() * Math.min(5, entries.length))];
        const title = song['im:name']?.label || 'Unknown';
        const artist = song['im:artist']?.label || '';
        const art = song['im:image']?.[2]?.label || '';
        nowPlayingDuration = 200 + Math.floor(Math.random() * 60);
        nowPlayingStart = Date.now() / 1000 - Math.floor(Math.random() * nowPlayingDuration * 0.8);
        renderNowPlaying(title, artist, art, Date.now() / 1000 - nowPlayingStart, nowPlayingDuration);
        return;
      }
    }
  } catch (_) {
  }

  renderNowPlaying('No song data', '', '', 0, 1);
}

function renderNowPlaying(title, artist, art, progressSec, durationSec) {
  document.getElementById('np-title').textContent = title;
  document.getElementById('np-artist').textContent = artist;
  const artEl = document.getElementById('np-art');
  if (art) {
    artEl.src = art;
    artEl.style.display = '';
  } else {
    artEl.style.display = 'none';
  }
  updateNpProgress(progressSec, durationSec);

  // Update canvas music state
  musicTrackTitle = title;
  musicTrackArtist = artist;
  if (art && art !== musicArtUrlLoaded) {
    musicArtUrlLoaded = art;
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => { musicArtImg = img; };
    img.onerror = () => { musicArtImg = null; };
    img.src = art;
  } else if (!art) {
    musicArtImg = null;
    musicArtUrlLoaded = '';
  }
}

function updateNpProgress(progressSec, durationSec) {
  const pct = durationSec > 0 ? Math.min(100, progressSec / durationSec * 100) : 0;
  document.getElementById('np-fill').style.width = pct + '%';
  const fmt = s => Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0');
  document.getElementById('np-time').textContent = fmt(progressSec) + ' / ' + fmt(durationSec);
}

setInterval(() => {
  if (nowPlayingStart > 0 && document.getElementById('ctrl-music').classList.contains('active')) {
    const elapsed = Date.now() / 1000 - nowPlayingStart;
    updateNpProgress(Math.min(elapsed, nowPlayingDuration), nowPlayingDuration);
  }
}, 1000);

setInterval(() => {
  const el = document.getElementById('clock-display');
  if (el && document.getElementById('ctrl-clock').classList.contains('active')) {
    el.textContent = new Date().toLocaleTimeString();
  }
}, 1000);

document.querySelectorAll('.mf-btn').forEach(b => {
  b.classList.toggle('active', b.dataset.mode === currentApiMode);
});
if (!document.querySelector('.mf-btn.active')) {
  currentApiMode = 'sports';
  document.querySelector('.mf-btn[data-mode="sports"]')?.classList.add('active');
}
showCtrlPanel(currentApiMode);
fetchAll();
fetchNowPlaying();
setInterval(fetchAll, FETCH_EVERY);
setInterval(fetchNowPlaying, 30000);
tick();

})();
