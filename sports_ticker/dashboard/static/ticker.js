(function () {
'use strict';

// ─── Config injected by server ────────────────────────────────────────────────
const CFG        = window._CFG || {};
const TICKER_ID  = CFG.tickerId || '';
const BROWSER_RT = window.__tickerBrowserRuntime || null;

// ─── Constants ────────────────────────────────────────────────────────────────
const LED_W       = 384;
const LED_H       = 32;
const SCALE       = 2;          // screen pixels per LED pixel
const SCROLL_SPD  = 0.5;        // default: speed slider 5 → 5 * 0.1
const FETCH_EVERY = 20000;

// ─── Canvas + state ───────────────────────────────────────────────────────────
const canvas      = document.getElementById('ticker-canvas');
const ctx         = canvas.getContext('2d');
const pauseBadge  = document.getElementById('pause-badge');
const fetchStatus = document.getElementById('fetch-status');

ctx.imageSmoothingEnabled = false; // nearest-neighbour pixel-perfect upscale

let stripBitmap    = null;   // ImageBitmap from server-rendered PNG strip
let stripSrcW      = 0;      // source pixels wide
let scrollSrcX     = 0;      // fractional source-pixel scroll offset
let paused         = false;
let currentApiMode = CFG.defaultMode || 'sports';
let allItems       = [];
let pinnedId       = null;
window._scrollSpd  = SCROLL_SPD;

// ─── LED grid overlay ─────────────────────────────────────────────────────────
function drawLedGrid() {
  ctx.fillStyle = 'rgba(0,0,0,0.45)';
  for (let sy = 0; sy < LED_H * SCALE; sy += SCALE) {
    for (let sx = 0; sx < LED_W * SCALE; sx += SCALE) {
      ctx.fillRect(sx, sy, 1, 1);
    }
  }
}

// ─── Render frame (proper tiling for strips shorter than LED_W) ───────────────
function renderFrame() {
  ctx.fillStyle = '#040406';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  if (!stripBitmap || stripSrcW === 0) {
    ctx.fillStyle = '#1a1a22';
    for (let sy = 0; sy < LED_H * SCALE; sy += SCALE)
      for (let sx = 0; sx < LED_W * SCALE; sx += SCALE)
        ctx.fillRect(sx + 1, sy + 1, SCALE - 1, SCALE - 1);
    drawLedGrid();
    return;
  }

  const canvasH = LED_H * SCALE;
  let dstX = 0;
  let srcX = Math.floor(scrollSrcX) % stripSrcW;

  while (dstX < LED_W * SCALE) {
    const availSrc  = stripSrcW - srcX;
    const remainDst = LED_W * SCALE - dstX;
    const drawSrcW  = Math.min(availSrc, Math.ceil(remainDst / SCALE));
    if (drawSrcW <= 0) break;
    ctx.drawImage(stripBitmap, srcX, 0, drawSrcW, LED_H, dstX, 0, drawSrcW * SCALE, canvasH);
    dstX += drawSrcW * SCALE;
    srcX  = 0;  // wrap: next tile starts from beginning of strip
  }

  drawLedGrid();
}

// ─── Animation loop ───────────────────────────────────────────────────────────
function tick() {
  if (!paused && stripBitmap && stripSrcW > 0) {
    scrollSrcX = (scrollSrcX + (window._scrollSpd || SCROLL_SPD)) % stripSrcW;
  }
  renderFrame();
  requestAnimationFrame(tick);
}

// ─── Strip fetching ───────────────────────────────────────────────────────────
(function () {
'use strict';

const CFG = window._CFG || {};
const TICKER_ID = CFG.tickerId || '';
const BROWSER_RT = window.__tickerBrowserRuntime || null;

const LED_W = 384;
const LED_H = 32;
const MODE_OPTIONS = [
  'sports',
  'live',
  'my_teams',
  'sports_full',
  'soccer_full',
  'golf',
  'stocks',
  'weather',
  'music',
  'clock',
  'flights',
  'flight_tracker',
];
const SCALE_OPTIONS = [2, 3, 4, 5, 6, 8];
const FETCH_EVERY = 20000;
const SPEED_MULT = 0.1;

const MODE_LABELS = {
  sports: 'ALL SPORTS',
  live: 'LIVE',
  my_teams: 'MY TEAMS',
  sports_full: 'SPORTS FULL',
  soccer_full: 'SOCCER FULL',
  golf: 'GOLF',
  stocks: 'STOCKS',
  weather: 'WEATHER',
  music: 'MUSIC',
  clock: 'CLOCK',
  flights: 'FLIGHTS',
  flight_tracker: 'TRACKER',
};

const canvas = document.getElementById('ticker-canvas');
const ctx = canvas.getContext('2d');
const canvasWrap = document.getElementById('canvas-wrap');
const gridOverlay = document.getElementById('grid-overlay');
const pauseBadge = document.getElementById('pause-badge');
const fetchStatus = document.getElementById('fetch-status');
const statusText = document.getElementById('status-text');
const frameInfo = document.getElementById('frame-info');
const modeSelect = document.getElementById('mode-select');
const speedRange = document.getElementById('speed-range');
const speedVal = document.getElementById('speed-val');
const zoomVal = document.getElementById('zoom-val');
const pauseBtn = document.getElementById('pause-btn');
const gridBtn = document.getElementById('grid-btn');
const shotBtn = document.getElementById('shot-btn');
const zoomInBtn = document.getElementById('zoom-in');
const zoomOutBtn = document.getElementById('zoom-out');

ctx.imageSmoothingEnabled = false;

let stripBitmap = null;
let stripSrcW = 0;
let scrollSrcX = 0;
let paused = false;
let showGrid = false;
let currentMode = MODE_OPTIONS.includes(String(CFG.defaultMode || 'sports')) ? String(CFG.defaultMode || 'sports') : 'sports';
let currentScale = 4;
let scrollSpeed = 0.5;
let lastFetchAt = 0;
let lastRenderAt = 0;
let refreshPending = null;

function formatMode(mode) {
  return MODE_LABELS[mode] || String(mode || '').toUpperCase().replace(/_/g, ' ');
}

function updateCanvasSize() {
  const width = LED_W * currentScale;
  const height = LED_H * currentScale;
  canvasWrap.style.width = width + 'px';
  canvasWrap.style.height = height + 'px';
  canvas.style.width = width + 'px';
  canvas.style.height = height + 'px';
  zoomVal.textContent = currentScale + 'x';
  frameInfo.textContent = LED_W + '×' + LED_H + ' panel · ' + currentScale + 'x zoom';
  gridOverlay.style.display = showGrid && currentScale >= 4 ? 'block' : 'none';
  gridOverlay.style.backgroundSize = currentScale + 'px ' + currentScale + 'px';
}

function updateModeSelect() {
  if (!modeSelect.options.length) {
    for (const mode of MODE_OPTIONS) {
      const opt = document.createElement('option');
      opt.value = mode;
      opt.textContent = formatMode(mode);
      modeSelect.appendChild(opt);
    }
  }
  modeSelect.value = currentMode;
}

function updateStatusLine(message) {
  const ageMs = lastFetchAt ? (Date.now() - lastFetchAt) : Infinity;
  let connection = 'connecting…';
  if (lastFetchAt) {
    connection = ageMs > 3000 ? 'stale ' + Math.round(ageMs / 1000) + 's ago' : 'live';
  }

  const parts = [
    'mode=' + currentMode,
    'speed=' + scrollSpeed.toFixed(1),
    'scale=' + currentScale + 'x',
    'source=' + (stripSrcW || '?') + 'px',
    connection,
  ];

  if (paused) parts.push('paused');
  statusText.textContent = parts.join('  ·  ');
  fetchStatus.textContent = message || fetchStatus.textContent;
  document.title = 'Ticker Emulator - ' + currentMode + ' - ' + connection;
}

function renderFallback() {
  ctx.fillStyle = '#040406';
  ctx.fillRect(0, 0, LED_W, LED_H);
  ctx.fillStyle = '#15161d';
  for (let y = 0; y < LED_H; y++) {
    for (let x = 0; x < LED_W; x++) {
      if (((x + y) % 4) === 0) {
        ctx.fillRect(x, y, 1, 1);
      }
    }
  }
}

function renderFrame() {
  ctx.fillStyle = '#040406';
  ctx.fillRect(0, 0, LED_W, LED_H);

  if (!stripBitmap || !stripSrcW) {
    renderFallback();
    return;
  }

  let dstX = 0;
  let srcX = Math.floor(scrollSrcX) % stripSrcW;
  while (dstX < LED_W) {
    const remainSrc = stripSrcW - srcX;
    const remainDst = LED_W - dstX;
    const drawSrcW = Math.min(remainSrc, remainDst);
    if (drawSrcW <= 0) break;
    ctx.drawImage(stripBitmap, srcX, 0, drawSrcW, LED_H, dstX, 0, drawSrcW, LED_H);
    dstX += drawSrcW;
    srcX = 0;
  }
}

async function fetchStrip() {
  if (refreshPending) return refreshPending;

  refreshPending = (async function () {
    try {
      if (!BROWSER_RT || typeof BROWSER_RT.renderStrip !== 'function') {
        throw new Error('browser runtime unavailable');
      }

      const strip = await BROWSER_RT.renderStrip(currentMode, TICKER_ID);
      if (!strip || !strip.dataUrl) {
        throw new Error('browser runtime returned no strip');
      }

      const blob = await (await fetch(strip.dataUrl)).blob();
      const bmp = await createImageBitmap(blob);
      stripBitmap = bmp;
      stripSrcW = strip.width || bmp.width || 0;
      scrollSrcX = 0;
      lastFetchAt = Date.now();
      fetchStatus.textContent = 'Updated ' + new Date().toLocaleTimeString() + ' · strip ' + stripSrcW + 'px';
      updateStatusLine(fetchStatus.textContent);
      renderFrame();
    } catch (err) {
      console.warn('Browser ticker render failed; trying server preview.', err);
      try {
        const url = '/api/preview/strip.png?mode=' + encodeURIComponent(currentMode);
        const resp = await fetch(url, { cache: 'no-store' });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const bmp = await createImageBitmap(await resp.blob());
        stripBitmap = bmp;
        stripSrcW = bmp.width || 0;
        scrollSrcX = 0;
        lastFetchAt = Date.now();
        fetchStatus.textContent = 'Server preview ' + new Date().toLocaleTimeString() + ' · strip ' + stripSrcW + 'px';
      } catch (fallbackErr) {
        fetchStatus.textContent = 'Render error: ' + err.message;
        lastFetchAt = 0;
        stripBitmap = null;
        stripSrcW = 0;
        console.warn('Server preview fallback failed:', fallbackErr);
      }
      renderFrame();
      updateStatusLine(fetchStatus.textContent);
    } finally {
      refreshPending = null;
    }
  })();

  return refreshPending;
}

function saveScreenshot() {
  const link = document.createElement('a');
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  link.download = 'ticker_screenshot_' + stamp + '.png';
  link.href = canvas.toDataURL('image/png');
  link.click();
}

function applyScale(nextScale) {
  const clamped = Math.max(SCALE_OPTIONS[0], Math.min(SCALE_OPTIONS[SCALE_OPTIONS.length - 1], nextScale));
  currentScale = SCALE_OPTIONS.reduce(function (best, value) {
    return Math.abs(value - clamped) < Math.abs(best - clamped) ? value : best;
  }, SCALE_OPTIONS[0]);
  updateCanvasSize();
  renderFrame();
  updateStatusLine();
}

function stepMode(delta) {
  let index = MODE_OPTIONS.indexOf(currentMode);
  if (index < 0) index = 0;
  index = (index + delta + MODE_OPTIONS.length) % MODE_OPTIONS.length;
  currentMode = MODE_OPTIONS[index];
  updateModeSelect();
  scrollSrcX = 0;
  fetchStrip();
}

function togglePause() {
  paused = !paused;
  pauseBadge.classList.toggle('visible', paused);
  pauseBtn.textContent = paused ? 'Resume' : 'Pause';
  updateStatusLine();
}

function toggleGrid() {
  showGrid = !showGrid;
  gridBtn.textContent = showGrid ? 'Grid On' : 'Grid';
  updateCanvasSize();
}

canvasWrap.addEventListener('click', function () {
  togglePause();
});

modeSelect.addEventListener('change', function () {
  currentMode = this.value;
  scrollSrcX = 0;
  fetchStrip();
});

speedRange.addEventListener('input', function () {
  const value = parseInt(this.value, 10) || 5;
  speedVal.textContent = String(value);
  scrollSpeed = value * SPEED_MULT;
  updateStatusLine();
});

pauseBtn.addEventListener('click', togglePause);
gridBtn.addEventListener('click', toggleGrid);
shotBtn.addEventListener('click', saveScreenshot);
zoomInBtn.addEventListener('click', function () {
  const index = SCALE_OPTIONS.indexOf(currentScale);
  applyScale(SCALE_OPTIONS[Math.min(SCALE_OPTIONS.length - 1, index + 1)] || currentScale);
});
zoomOutBtn.addEventListener('click', function () {
  const index = SCALE_OPTIONS.indexOf(currentScale);
  applyScale(SCALE_OPTIONS[Math.max(0, index - 1)] || currentScale);
});

window.addEventListener('keydown', function (event) {
  if (event.target && /input|select|textarea/i.test(event.target.tagName || '')) return;
  if (event.key === ' ' || event.key === 'Spacebar') {
    event.preventDefault();
    togglePause();
    return;
  }
  if (event.key === 'g' || event.key === 'G') {
    toggleGrid();
    return;
  }
  if (event.key === 's' || event.key === 'S') {
    saveScreenshot();
    return;
  }
  if (event.key === 'm') {
    stepMode(1);
    return;
  }
  if (event.key === 'M' || (event.shiftKey && event.key === 'm')) {
    stepMode(-1);
    return;
  }
  if (event.key === '+' || event.key === '=' || event.key === 'Add') {
    zoomInBtn.click();
    return;
  }
  if (event.key === '-' || event.key === '_' || event.key === 'Subtract') {
    zoomOutBtn.click();
    return;
  }
});

function tick() {
  if (!paused && stripBitmap && stripSrcW > 0) {
    scrollSrcX = (scrollSrcX + scrollSpeed) % stripSrcW;
    renderFrame();
    lastRenderAt = performance.now();
  }
  requestAnimationFrame(tick);
}

function refreshStatusLoop() {
  updateStatusLine();
  window.setTimeout(refreshStatusLoop, 1000);
}

modeSelect.innerHTML = '';
updateModeSelect();
speedVal.textContent = speedRange.value;
scrollSpeed = parseInt(speedRange.value, 10) * SPEED_MULT;
updateCanvasSize();
updateStatusLine('fetching…');
renderFrame();
fetchStrip();
setInterval(fetchStrip, FETCH_EVERY);
tick();
refreshStatusLoop();

})();
};
