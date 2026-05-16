(function () {
'use strict';

const CFG = window._CFG || {};
const TICKER_ID = CFG.tickerId || '';
const BROWSER_RT = window.__tickerBrowserRuntime || null;

const LED_W = 384;
const LED_H = 32;
const SCALE = 2;
const SCROLL_SPD = 0.3;
const FETCH_EVERY = 20000;
const STATIC_MODES = new Set(['music', 'weather', 'clock', 'flights', 'flight_tracker', 'golf', 'masters']);

const canvas = document.getElementById('ticker-canvas');
const ctx = canvas.getContext('2d');
const pauseBadge = document.getElementById('pause-badge');
const fetchStatus = document.getElementById('fetch-status');

ctx.imageSmoothingEnabled = false;

let stripBitmap = null;
let stripSrcW = 0;
let scrollSrcX = 0;
let paused = false;
let currentApiMode = CFG.defaultMode || 'sports';
let allItems = [];
let pinnedId = null;
let lastFetchAt = 0;
let nowPlayingStart = 0;
let nowPlayingDuration = 210;

window._scrollSpd = SCROLL_SPD;

function isStaticMode(mode) {
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

function renderFrame() {
  ctx.fillStyle = '#040406';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  if (!stripBitmap || stripSrcW === 0) {
    ctx.fillStyle = '#1a1a22';
    for (let sy = 0; sy < LED_H * SCALE; sy += SCALE) {
      for (let sx = 0; sx < LED_W * SCALE; sx += SCALE) {
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
  renderFrame();
  requestAnimationFrame(tick);
}

async function fetchStrip() {
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
    const url = '/api/preview/strip.png?mode=' + encodeURIComponent(currentApiMode);
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
    const serverPin = data && (data.pinned_game || (Array.isArray(data.pinned_games) ? data.pinned_games[0] : ''));
    pinnedId = serverPin ? String(serverPin) : null;
    document.getElementById('unpin-btn').style.display = pinnedId ? '' : 'none';
    updateDetailPanel();
  } catch (e) {
    console.warn('Items fetch error:', e.message);
  }
}

async function fetchAll() {
  await Promise.all([fetchStrip(), fetchItems()]);
}

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
    document.getElementById('unpin-btn').style.display = 'none';
  } else {
    pinnedId = gameId;
    el.classList.add('pinned');
    document.getElementById('unpin-btn').style.display = '';
  }

  try {
    const payload = { game_ids: pinnedId ? [pinnedId] : [] };
    if (TICKER_ID) payload.ticker_id = TICKER_ID;
    await fetch('/api/pin_games', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    fetchAll();
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
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    fetchAll();
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
setInterval(() => {
  if (currentApiMode === 'music') fetchAll();
}, 1000);
tick();

})();
