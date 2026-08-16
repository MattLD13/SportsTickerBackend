/* ══════════════════════════════════════════════════════════════════════════
   ticker-demo.js — browser emulation of the 384×32 HUB75 panel.

   Scroll / static modes pull a rendered strip from /api/preview/strip.png.
   Music and clock are drawn client-side so they animate at full frame rate,
   mirroring ticker_controller/modes/music.py and modes/misc.py.

   Mount by putting  data-ticker-demo  on a container that holds a
   [data-demo-vp] viewport and a [data-demo-controls] button row.
   ══════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const W = 384, H = 32;          // real panel dimensions
  const FALLBACK_SCROLL = 33;     // px/sec, if the server didn't say
  const FADE_MS       = 260;
  const ROTATE_MS     = 18000;    // dwell per mode when auto-rotating

  const REDUCED_MOTION = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const DEFAULT_MODES = [
    { id: 'sports',  label: 'Sports',  kind: 'scroll' },
    { id: 'live',    label: 'Live',    kind: 'scroll' },
    { id: 'stocks',  label: 'Stocks',  kind: 'scroll' },
    { id: 'weather', label: 'Weather', kind: 'static' },
    { id: 'music',   label: 'Music',   kind: 'canvas' },
    { id: 'clock',   label: 'Clock',   kind: 'canvas' },
  ];

  // Served from the backend itself → same origin. Opened from disk → fall back
  // to the public host so the file keeps working standalone.
  const FALLBACK_BASE = 'https://ticker.mattdicks.org';

  function resolveBase(el) {
    const explicit = el.getAttribute('data-base');
    if (explicit) return explicit.replace(/\/$/, '');
    return location.protocol === 'file:' ? FALLBACK_BASE : '';
  }

  // ════════════════════════════════════════════════════════════════════════
  // MUSIC — matches draw_music_card() in ticker_controller/modes/music.py
  // ════════════════════════════════════════════════════════════════════════

  function initMusicState() {
    return {
      albumImg:     null,
      artUrl:       '',
      domColor:     [29, 185, 84],   // Spotify green default
      spindleColor: 'white',
      vinylRot:     0,               // degrees
      scrollPos:    0,               // pixels
      lastFrame:    performance.now(),
      progress:     112,             // seconds
      duration:     303,             // seconds
      fetchTs:      Date.now() / 1000,
      isPlaying:    true,
      title:        'MR. BLUE SKY',
      artist:       'ELECTRIC LIGHT ORCHESTRA',
      vizH:         Array(16).fill(2),
      vizPhase:     Array.from({ length: 16 }, () => Math.random() * 10),
    };
  }

  async function fetchSpotify(base, ms) {
    try {
      const r = await fetch(`${base}/api/spotify/now`);
      if (!r.ok) return;
      const d = await r.json();
      ms.isPlaying = !!d.is_playing;
      ms.progress  = d.progress || 0;     // already seconds (server pre-interpolates)
      ms.duration  = d.duration || 240;   // already seconds
      ms.fetchTs   = Date.now() / 1000;   // snapshot when we received the data
      ms.title     = d.name   || 'NOT PLAYING';
      ms.artist    = d.artist || '';
      const cover = d.cover || '';
      if (cover && cover !== ms.artUrl) {
        ms.artUrl = cover;
        loadArt(ms, cover);
      }
    } catch (_) { /* keep last frame */ }
  }

  function loadArt(ms, url) {
    // Try CORS load first (needed for pixel sampling)
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      ms.albumImg = img;
      try {
        const tmp = document.createElement('canvas');
        tmp.width = tmp.height = 8;
        const t = tmp.getContext('2d');
        t.drawImage(img, 0, 0, 8, 8);
        const px = t.getImageData(0, 0, 8, 8).data;
        let r = 0, g = 0, b = 0;
        for (let i = 0; i < 64; i++) { r += px[i * 4]; g += px[i * 4 + 1]; b += px[i * 4 + 2]; }
        r /= 64; g /= 64; b /= 64;
        const lum = 0.299 * r + 0.587 * g + 0.114 * b;
        ms.spindleColor = lum < 140 ? 'white' : '#111';
        // Mirror extract_colors_and_spindle: HSV boost for saturation + brightness
        const rf = r / 255, gf = g / 255, bf = b / 255;
        const mx = Math.max(rf, gf, bf), mn = Math.min(rf, gf, bf), d = mx - mn;
        let h = 0, s = mx ? d / mx : 0, v = mx;
        if (d) {
          if (mx === rf)      h = ((gf - bf) / d + 6) % 6;
          else if (mx === gf) h = (bf - rf) / d + 2;
          else                h = (rf - gf) / d + 4;
          h /= 6;
        }
        if      (s < 0.2) s = 0.0;
        else if (s < 0.5) s = Math.min(1.0, s * 1.5);
        if      (v < 0.3) v = 0.5;          // dark art → boost to mid brightness
        else if (v < 0.8) v = Math.min(1.0, v * 1.3);
        const i6 = Math.floor(h * 6), f = h * 6 - i6;
        const p = v * (1 - s), q = v * (1 - f * s), tt = v * (1 - (1 - f) * s);
        let nr, ng, nb;
        switch (i6 % 6) {
          case 0: nr = v;  ng = tt; nb = p;  break;
          case 1: nr = q;  ng = v;  nb = p;  break;
          case 2: nr = p;  ng = v;  nb = tt; break;
          case 3: nr = p;  ng = q;  nb = v;  break;
          case 4: nr = tt; ng = p;  nb = v;  break;
          case 5: nr = v;  ng = p;  nb = q;  break;
        }
        ms.domColor = [nr * 255 | 0, ng * 255 | 0, nb * 255 | 0];
      } catch (_) {
        ms.domColor = [29, 185, 84]; // fallback if CORS blocked
      }
    };
    img.onerror = () => {
      // Fallback: load without CORS for display only, no color sample
      const img2 = new Image();
      img2.onload = () => { ms.albumImg = img2; };
      img2.src = url;
    };
    img.src = url;
  }

  function drawScrollText(ctx, text, x, y, maxW, scrollPos) {
    const tw = ctx.measureText(text).width;
    if (tw <= maxW - 2) { ctx.fillText(text, x, y); return; }
    const GAP = 40, loop = tw + GAP;
    const off = scrollPos % loop;
    ctx.save();
    ctx.beginPath();
    ctx.rect(x, 0, maxW, H);
    ctx.clip();
    ctx.fillText(text, x - off, y);
    if (x - off + tw < x + maxW) ctx.fillText(text, x - off + loop, y);
    ctx.restore();
  }

  function drawMusicFrame(canvas, ms) {
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, W, H);

    const now = performance.now();
    const dt  = Math.min((now - ms.lastFrame) / 1000, 0.1);
    ms.lastFrame = now;

    // Interpolate progress (fetchTs is Date.now()/1000 at last fetch)
    let localProg = ms.progress;
    if (ms.isPlaying) {
      localProg = ms.progress + (Date.now() / 1000 - ms.fetchTs);
      ms.vinylRot   = (ms.vinylRot - 100 * dt) % 360;
      ms.scrollPos += 15 * dt;
    }
    localProg = Math.min(localProg, ms.duration);

    const [dr, dg, db] = ms.domColor;
    const domRgb = `rgb(${dr},${dg},${db})`;

    // ── Vinyl disc ──────────────────────────────────────────────────────
    // Real: VINYL_SIZE=51, COVER_SIZE=42, pasted at (4,-9)
    // → center at (4+25.5, -9+25.5) = (29.5, 16.5)
    const VCX = 29.5, VCY = 16.5, VR = 25.5, CR = 21;

    ctx.fillStyle = '#141414';
    ctx.beginPath(); ctx.arc(VCX, VCY, VR, 0, Math.PI * 2); ctx.fill();

    // Groove rings
    ctx.lineWidth = 0.5;
    for (let r = 5; r < VR; r += 3) {
      ctx.strokeStyle = 'rgba(55,55,55,0.9)';
      ctx.beginPath(); ctx.arc(VCX, VCY, r, 0, Math.PI * 2); ctx.stroke();
    }

    // Album art — circular clipped, rotated
    ctx.save();
    ctx.beginPath(); ctx.arc(VCX, VCY, CR, 0, Math.PI * 2); ctx.clip();
    ctx.translate(VCX, VCY);
    ctx.rotate(ms.vinylRot * Math.PI / 180);
    if (ms.albumImg) {
      ctx.drawImage(ms.albumImg, -CR, -CR, CR * 2, CR * 2);
    } else {
      ctx.fillStyle = domRgb;
      ctx.fillRect(-CR, -CR, CR * 2, CR * 2);
    }
    ctx.restore();

    // Spindle (real: ellipse (22,22,28,28) outer, (23,23,27,27) inner on 51×51)
    ctx.fillStyle = '#222';
    ctx.beginPath(); ctx.arc(VCX, VCY, 3, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = ms.spindleColor;
    ctx.beginPath(); ctx.arc(VCX, VCY, 2, 0, Math.PI * 2); ctx.fill();

    // ── Song title (scrolling) real: TEXT_X=60, y=0, medium_font ────────
    const TX = 60;
    ctx.textBaseline = 'top';
    ctx.font = 'bold 11px "Courier New", monospace';
    ctx.fillStyle = 'white';
    drawScrollText(ctx, ms.title, TX, 0, 188, ms.scrollPos);

    // ── Spotify-style icon real: ellipse(60,15,72,27) + 3 arcs ──────────
    const ICX = TX + 6, ICY = 21;
    ctx.fillStyle = domRgb;
    ctx.beginPath(); ctx.arc(ICX, ICY, 6, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = 'rgba(0,0,0,0.75)';
    ctx.lineWidth = 0.7;
    for (let i = 0; i < 3; i++) {
      // PIL arc 190°→350° clockwise from 3-o'clock (y-down), shifted down per row
      const r = 4.5 - i * 1.2;
      ctx.beginPath();
      ctx.arc(ICX, ICY + i, r, 190 * Math.PI / 180, 350 * Math.PI / 180);
      ctx.stroke();
    }

    // ── Artist (scrolling) real: TEXT_X+16=76, y=17, tiny ───────────────
    ctx.font = '8px "Courier New", monospace';
    ctx.fillStyle = 'rgb(180,180,180)';
    drawScrollText(ctx, ms.artist, TX + 16, 19, 172, ms.scrollPos);

    // ── Visualizer real: x=248, y=6, w=80, h=20, 16 bars (w=2,gap=3) ────
    const VX = 248, VY = 6, VH = 20, BARS = 16, BW = 2, BG = 3;
    const t  = now / 1000;
    const CY = VY + VH / 2;
    for (let i = 0; i < BARS; i++) {
      let tgt;
      if (ms.isPlaying) {
        const base  = Math.sin(t * 4 + ms.vizPhase[i]);
        const noise = Math.sin(t * 12 + i * 0.5) * (0.5 + Math.random() * 0.7);
        const amp   = i < 5 ? 8 + Math.sin(t * 2) * 2 : i < 11 ? 6 : 4 + noise * 2;
        tgt = Math.max(2, Math.min(VH, Math.abs(base + noise) * amp));
      } else {
        tgt = 2;
      }
      ms.vizH[i] += (tgt - ms.vizH[i]) * 0.25;
      const h = ms.vizH[i] | 0;

      // Gradient: dominant → lighter (matches render_visualizer)
      const f  = (i / (BARS - 1)) * 0.6;
      const cr = Math.min(255, dr + (255 - dr) * f) | 0;
      const cg = Math.min(255, dg + (255 - dg) * f) | 0;
      const cb = Math.min(255, db + (255 - db) * f) | 0;
      ctx.fillStyle = `rgb(${cr},${cg},${cb})`;
      ctx.fillRect(VX + i * (BW + BG), CY - h / 2, BW, h);
    }

    // ── Progress bar real: y=31, 1px, colored ───────────────────────────
    const pct = Math.max(0, Math.min(1, localProg / ms.duration));
    ctx.fillStyle = '#222';
    ctx.fillRect(0, 31, W, 1);
    ctx.fillStyle = domRgb;
    ctx.fillRect(0, 31, W * pct | 0, 1);

    // ── Time remaining real: right-aligned, y=10, tiny ──────────────────
    const remS   = Math.max(0, ms.duration - localProg) | 0;
    const remStr = `-${remS / 60 | 0}:${String(remS % 60).padStart(2, '0')}`;
    ctx.font = '8px "Courier New", monospace';
    ctx.fillStyle = 'white';
    ctx.textBaseline = 'top';
    const tw = ctx.measureText(remStr).width;
    ctx.fillText(remStr, W - tw - 5, 12);
  }

  // ════════════════════════════════════════════════════════════════════════
  // CLOCK — matches draw_clock_modern() in ticker_controller/modes/misc.py
  // Uses the viewer's local timezone; the panel uses the server's.
  // ════════════════════════════════════════════════════════════════════════

  const DAYS   = ['SUNDAY', 'MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY'];
  const MONTHS = ['JANUARY', 'FEBRUARY', 'MARCH', 'APRIL', 'MAY', 'JUNE',
                  'JULY', 'AUGUST', 'SEPTEMBER', 'OCTOBER', 'NOVEMBER', 'DECEMBER'];

  function drawClockFrame(canvas) {
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, W, H);

    const now = new Date();
    const dateStr = `${DAYS[now.getDay()]} ${MONTHS[now.getMonth()]} ${now.getDate()}`;

    // Date row — real: y=-1, tiny font, centered, gray
    ctx.font = '8px "Courier New", monospace';
    ctx.fillStyle = 'rgb(200,200,200)';
    ctx.textBaseline = 'top';
    const dw = ctx.measureText(dateStr).width;
    ctx.fillText(dateStr, (W - dw) / 2, 0);

    // Time — real: clock_giant (28px bold), y=4, centered, white
    const h12 = now.getHours() % 12 || 12;
    const timeStr = `${h12}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;
    ctx.font = 'bold 22px "Courier New", monospace';
    ctx.fillStyle = 'white';
    const tw = ctx.measureText(timeStr).width;
    ctx.fillText(timeStr, (W - tw) / 2, 6);

    // Second progress bar — real: y=31, dark bg + cyan fill
    const totalSec = now.getSeconds() + now.getMilliseconds() / 1000;
    const barW = (totalSec / 60) * W | 0;
    ctx.fillStyle = 'rgb(30,30,30)';
    ctx.fillRect(0, 31, W, 1);
    ctx.fillStyle = 'rgb(0,200,255)';
    ctx.fillRect(0, 31, barW, 1);
  }

  // ════════════════════════════════════════════════════════════════════════
  // DEMO INSTANCE
  // ════════════════════════════════════════════════════════════════════════

  function mount(root) {
    const vp       = root.querySelector('[data-demo-vp]');
    const controls = root.querySelector('[data-demo-controls]');
    const sampleMusic = root.getAttribute('data-demo-music') === 'sample';
    if (!vp) return;

    const base = resolveBase(root);

    let modes = DEFAULT_MODES;
    const raw = root.getAttribute('data-modes');
    if (raw) {
      try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed.length) modes = parsed;
      } catch (_) { /* keep defaults */ }
    }

    const canRotate = root.getAttribute('data-autorotate') === 'true' && !REDUCED_MOTION;

    // The controller steps the strip one pixel per scroll_speed seconds; the
    // server hands us the resulting rate so the emulation matches the board.
    const scrollPxS = parseFloat(root.getAttribute('data-scroll-rate')) || FALLBACK_SCROLL;

    let curIdx    = 0;
    let rafId     = null;
    let frameFn   = null;      // current per-frame callback, or null
    let poller    = null;      // music polling interval
    let pollFn    = null;
    let rotateId  = null;
    let rotating  = canRotate;
    let visible   = true;
    let switching = false;

    // Scroll state
    let offset = 0, lastTs = null, stripW = 0, track = null;

    // ── Animation plumbing ────────────────────────────────────────────────
    function tick(ts) {
      if (frameFn) frameFn(ts);
      rafId = requestAnimationFrame(tick);
    }
    function startLoop() {
      if (rafId === null && frameFn) rafId = requestAnimationFrame(tick);
    }
    function stopLoop() {
      if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null; }
      lastTs = null;
    }
    function startPoll() {
      if (!poller && pollFn) { pollFn(); poller = setInterval(pollFn, 5000); }
    }
    function stopPoll() {
      if (poller) { clearInterval(poller); poller = null; }
    }
    function teardown() {
      stopLoop(); stopPoll();
      frameFn = null; pollFn = null; track = null;
    }

    // ── Mode builders ─────────────────────────────────────────────────────
    function showStatus(text) {
      vp.innerHTML = '';
      const s = document.createElement('div');
      s.className = 'demo-status';
      s.textContent = text;
      vp.appendChild(s);
    }

    function buildScroll(url) {
      track = document.createElement('div');
      track.className = 'demo-track';
      let loaded = 0;
      const onLoad = (img) => {
        if (++loaded !== 2) return;
        stripW = img.naturalWidth * (vp.clientHeight / H);
        if (!stripW) { showStatus('NO DATA FOR THIS MODE'); return; }
        offset = 0; lastTs = null;
        frameFn = (ts) => {
          if (!lastTs) lastTs = ts;
          const dt = Math.min((ts - lastTs) / 1000, 0.1);
          lastTs = ts;
          const scale = vp.clientHeight / H;
          offset = (offset + scrollPxS * scale * dt) % stripW;
          track.style.transform = `translateX(${-offset}px)`;
        };
        if (visible) startLoop();
      };
      const onErr = () => showStatus('NO DATA FOR THIS MODE');
      for (let i = 0; i < 2; i++) {
        const img = document.createElement('img');
        img.className = 'demo-strip';
        img.alt = '';
        img.onload  = () => onLoad(img);
        img.onerror = onErr;
        img.src = url;
        track.appendChild(img);
      }
      vp.appendChild(track);
    }

    function buildStatic(url) {
      const img = document.createElement('img');
      img.className = 'demo-frame';
      img.alt = '';
      img.onerror = () => showStatus('NO DATA FOR THIS MODE');
      img.src = url;
      vp.appendChild(img);
    }

    function newCanvas() {
      const canvas = document.createElement('canvas');
      canvas.width  = W;
      canvas.height = H;
      canvas.className = 'demo-canvas';
      vp.appendChild(canvas);
      return canvas;
    }

    function buildMusic() {
      const canvas = newCanvas();
      const ms = initMusicState();
      if (!sampleMusic) pollFn = () => fetchSpotify(base, ms);
      frameFn = () => drawMusicFrame(canvas, ms);
      drawMusicFrame(canvas, ms);
      if (visible) { startPoll(); startLoop(); }
    }

    function buildClock() {
      const canvas = newCanvas();
      frameFn = () => drawClockFrame(canvas);
      drawClockFrame(canvas);
      if (visible) startLoop();
    }

    // ── Mode switching ────────────────────────────────────────────────────
    function goTo(idx, userInitiated) {
      if (userInitiated) stopRotate();
      if (switching) return;

      curIdx = ((idx % modes.length) + modes.length) % modes.length;
      const mode = modes[curIdx];

      // Mode buttons only — the Auto chip shares the .demo-btn class but tracks
      // whether rotation is on, not which mode is showing. Including it here
      // switched it off on every mode change, the first paint included.
      if (controls) {
        controls.querySelectorAll('.demo-btn:not(.demo-btn-auto)').forEach((b, i) => {
          const on = i === curIdx;
          b.classList.toggle('is-active', on);
          b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
      }
      root.setAttribute('data-mode', mode.id);

      teardown();
      switching = true;
      vp.classList.add('is-fading');

      setTimeout(() => {
        vp.innerHTML = '';
        const url = `${base}/api/preview/strip.png?mode=${encodeURIComponent(mode.id)}&_t=${Date.now()}`;

        if (mode.kind === 'canvas' || mode.canvas) {
          if (mode.id === 'music')      buildMusic();
          else if (mode.id === 'clock') buildClock();
          else                          buildStatic(url);
        } else if (mode.kind === 'static' || mode.scroll === false) {
          buildStatic(url);
        } else {
          buildScroll(url);
        }

        vp.classList.remove('is-fading');
        switching = false;
        if (rotating) queueRotate();
      }, FADE_MS);
    }

    // ── Auto-rotate ───────────────────────────────────────────────────────
    function queueRotate() {
      clearTimeout(rotateId);
      rotateId = setTimeout(() => {
        if (rotating && visible) goTo(curIdx + 1, false);
        else if (rotating) queueRotate();
      }, ROTATE_MS);
    }
    function stopRotate() {
      rotating = false;
      clearTimeout(rotateId);
      if (autoBtn) {
        autoBtn.classList.remove('is-active');
        autoBtn.setAttribute('aria-pressed', 'false');
      }
    }
    function startRotate() {
      rotating = true;
      if (autoBtn) {
        autoBtn.classList.add('is-active');
        autoBtn.setAttribute('aria-pressed', 'true');
      }
      queueRotate();
    }

    // ── Controls ──────────────────────────────────────────────────────────
    let autoBtn = null;
    if (controls) {
      controls.innerHTML = '';
      modes.forEach((m, i) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'demo-btn' + (i === 0 ? ' is-active' : '');
        b.textContent = m.label || m.id;
        b.setAttribute('aria-pressed', i === 0 ? 'true' : 'false');
        b.addEventListener('click', () => goTo(i, true));
        controls.appendChild(b);
      });

      if (canRotate) {
        autoBtn = document.createElement('button');
        autoBtn.type = 'button';
        autoBtn.className = 'demo-btn demo-btn-auto is-active';
        autoBtn.innerHTML = '<span class="demo-btn-dot"></span>Auto';
        autoBtn.title = 'Cycle through modes automatically';
        autoBtn.setAttribute('aria-pressed', 'true');
        autoBtn.addEventListener('click', () => {
          if (rotating) stopRotate();
          else          startRotate();
        });
        controls.appendChild(autoBtn);
      }
    }

    // ── Pause when off-screen or backgrounded ─────────────────────────────
    function setVisible(v) {
      if (v === visible) return;
      visible = v;
      if (v) { startLoop(); startPoll(); if (rotating) queueRotate(); }
      else   { stopLoop();  stopPoll();  clearTimeout(rotateId); }
    }

    if ('IntersectionObserver' in window) {
      new IntersectionObserver((entries) => {
        setVisible(entries[0].isIntersecting && !document.hidden);
      }, { threshold: 0.01 }).observe(root);
    }
    document.addEventListener('visibilitychange', () => {
      setVisible(!document.hidden && root.getBoundingClientRect().bottom > 0);
    });

    // Re-measure the strip when the panel is resized.
    let resizeId = null;
    window.addEventListener('resize', () => {
      clearTimeout(resizeId);
      resizeId = setTimeout(() => {
        const img = track && track.querySelector('img');
        if (img && img.naturalWidth) stripW = img.naturalWidth * (vp.clientHeight / H);
      }, 200);
    });

    goTo(0, false);
    if (rotating) queueRotate();
  }

  function boot() {
    document.querySelectorAll('[data-ticker-demo]').forEach(mount);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
