/* ══════════════════════════════════════════════════════════════════════════
   led.js — renders text as a real LED dot matrix.

   Every small label on this site is drawn the same way the panel itself
   draws text: a 5×7 bitmap font lit on a field of dark LEDs. Mark an
   element with data-led and its text becomes a display.

     <span data-led data-led-scale="2" data-led-color="amber">UPTIME</span>

   Attributes
     data-led-scale   glyph pixel → n×n LEDs (default 1)
     data-led-pitch   LED pitch in CSS px (default 3, inherited via --led-pitch)
     data-led-color   amber | white | dim | blue | green | red (default white)
     data-led-align   left | center | right (block mode only)
     data-led-pad     extra dark LED rows below the glyphs (default 1)
     data-led-inline  size the canvas to the text instead of the container
     data-led-fit     shrink scale until the text fits the container width

   Blocks that share a pitch and a container width line up dot-for-dot, so a
   stack of them reads as one continuous panel.
   ══════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  // ── 5×7 font, ASCII 0x20–0x5F. Five column bytes per glyph, bit 0 = top row.
  const FIRST_CHAR = 0x20;
  const FONT = [
    [0x00,0x00,0x00,0x00,0x00], // (space)
    [0x00,0x00,0x5f,0x00,0x00], // !
    [0x00,0x07,0x00,0x07,0x00], // "
    [0x14,0x7f,0x14,0x7f,0x14], // #
    [0x24,0x2a,0x7f,0x2a,0x12], // $
    [0x23,0x13,0x08,0x64,0x62], // %
    [0x36,0x49,0x55,0x22,0x50], // &
    [0x00,0x05,0x03,0x00,0x00], // '
    [0x00,0x1c,0x22,0x41,0x00], // (
    [0x00,0x41,0x22,0x1c,0x00], // )
    [0x14,0x08,0x3e,0x08,0x14], // *
    [0x08,0x08,0x3e,0x08,0x08], // +
    [0x00,0x50,0x30,0x00,0x00], // ,
    [0x08,0x08,0x08,0x08,0x08], // -
    [0x00,0x60,0x60,0x00,0x00], // .
    [0x20,0x10,0x08,0x04,0x02], // /
    [0x3e,0x51,0x49,0x45,0x3e], // 0
    [0x00,0x42,0x7f,0x40,0x00], // 1
    [0x42,0x61,0x51,0x49,0x46], // 2
    [0x21,0x41,0x45,0x4b,0x31], // 3
    [0x18,0x14,0x12,0x7f,0x10], // 4
    [0x27,0x45,0x45,0x45,0x39], // 5
    [0x3c,0x4a,0x49,0x49,0x30], // 6
    [0x01,0x71,0x09,0x05,0x03], // 7
    [0x36,0x49,0x49,0x49,0x36], // 8
    [0x06,0x49,0x49,0x29,0x1e], // 9
    [0x00,0x36,0x36,0x00,0x00], // :
    [0x00,0x56,0x36,0x00,0x00], // ;
    [0x08,0x14,0x22,0x41,0x00], // <
    [0x14,0x14,0x14,0x14,0x14], // =
    [0x00,0x41,0x22,0x14,0x08], // >
    [0x02,0x01,0x51,0x09,0x06], // ?
    [0x32,0x49,0x79,0x41,0x3e], // @
    [0x7e,0x11,0x11,0x11,0x7e], // A
    [0x7f,0x49,0x49,0x49,0x36], // B
    [0x3e,0x41,0x41,0x41,0x22], // C
    [0x7f,0x41,0x41,0x22,0x1c], // D
    [0x7f,0x49,0x49,0x49,0x41], // E
    [0x7f,0x09,0x09,0x09,0x01], // F
    [0x3e,0x41,0x49,0x49,0x7a], // G
    [0x7f,0x08,0x08,0x08,0x7f], // H
    [0x00,0x41,0x7f,0x41,0x00], // I
    [0x20,0x40,0x41,0x3f,0x01], // J
    [0x7f,0x08,0x14,0x22,0x41], // K
    [0x7f,0x40,0x40,0x40,0x40], // L
    [0x7f,0x02,0x0c,0x02,0x7f], // M
    [0x7f,0x04,0x08,0x10,0x7f], // N
    [0x3e,0x41,0x41,0x41,0x3e], // O
    [0x7f,0x09,0x09,0x09,0x06], // P
    [0x3e,0x41,0x51,0x21,0x5e], // Q
    [0x7f,0x09,0x19,0x29,0x46], // R
    [0x46,0x49,0x49,0x49,0x31], // S
    [0x01,0x01,0x7f,0x01,0x01], // T
    [0x3f,0x40,0x40,0x40,0x3f], // U
    [0x1f,0x20,0x40,0x20,0x1f], // V
    [0x3f,0x40,0x38,0x40,0x3f], // W
    [0x63,0x14,0x08,0x14,0x63], // X
    [0x07,0x08,0x70,0x08,0x07], // Y
    [0x61,0x51,0x49,0x45,0x43], // Z
    [0x00,0x7f,0x41,0x41,0x00], // [
    [0x02,0x04,0x08,0x10,0x20], // backslash
    [0x00,0x41,0x41,0x7f,0x00], // ]
    [0x04,0x02,0x01,0x02,0x04], // ^
    [0x40,0x40,0x40,0x40,0x40], // _
  ];

  const GLYPH_W = 5, GLYPH_H = 7, GLYPH_GAP = 1;

  const REDUCED_MOTION = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const COLORS = {
    white: '#f2f2f2',
    dim:   '#7d7d7d',
    amber: '#ffb02e',
    blue:  '#5aacf0',
    green: '#3ddc9a',
    red:   '#eb595a',
  };
  const OFF = 'rgba(255,255,255,0.052)';

  function glyph(ch) {
    const code = ch.toUpperCase().charCodeAt(0);
    const g = FONT[code - FIRST_CHAR];
    return g || FONT[0];
  }

  function textCols(text, scale) {
    if (!text.length) return 0;
    return (text.length * (GLYPH_W + GLYPH_GAP) - GLYPH_GAP) * scale;
  }

  function specOf(el) {
    const cycle = (el.getAttribute('data-led-cycle') || '')
      .split('|').map((w) => w.trim()).filter(Boolean);
    return {
      cycle:  cycle,
      text:   (el.getAttribute('data-led-text') || '').replace(/\s+/g, ' ').trim(),
      pitch:  parseFloat(el.getAttribute('data-led-pitch')) ||
              parseFloat(getComputedStyle(el).getPropertyValue('--led-pitch')) || 3,
      pad:    parseInt(el.getAttribute('data-led-pad') || '1', 10),
      align:  el.getAttribute('data-led-align') || 'left',
      inline: el.hasAttribute('data-led-inline'),
      color:  COLORS[el.getAttribute('data-led-color')] || COLORS.white,
      scale:  parseInt(el.getAttribute('data-led-scale') || '1', 10),
    };
  }

  /** Widest state this element can ever show. A cycling element is sized to
      its longest word so swapping words never reflows the line around it. */
  function widestCols(spec, scale) {
    const words = spec.cycle.length ? spec.cycle : [spec.text];
    return words.reduce((m, w) => Math.max(m, textCols(w, scale)), 0);
  }

  /** Largest scale ≤ the requested one whose text still fits the container. */
  function fitScale(el) {
    const s = specOf(el);
    if (!el.hasAttribute('data-led-fit') || s.inline) return s.scale;
    const maxCols = Math.floor(el.clientWidth / s.pitch);
    let scale = s.scale;
    while (scale > 1 && widestCols(s, scale) > maxCols) scale--;
    return scale;
  }

  /** Members of a data-led-group all settle on the group's smallest fit, so a
      row of stat cells never ends up with mismatched glyph sizes. */
  function resolveGroups(els) {
    const groups = {};
    els.forEach((el) => {
      const g = el.getAttribute('data-led-group');
      if (!g) return;
      const s = fitScale(el);
      groups[g] = groups[g] === undefined ? s : Math.min(groups[g], s);
    });
    return groups;
  }

  // ── Draw one block ───────────────────────────────────────────────────────
  function draw(el, canvas, groupScales) {
    const spec = specOf(el);
    const { text, pitch, pad, align, inline, color } = spec;

    const boxW = inline ? Infinity : el.clientWidth;
    if (!inline && boxW < pitch * 4) return false;   // not laid out yet

    const group = el.getAttribute('data-led-group');
    let scale = (groupScales && group && groupScales[group] !== undefined)
      ? groupScales[group]
      : fitScale(el);

    const tCols = widestCols(spec, scale);
    const cols  = inline ? tCols + scale * 2 : Math.floor(boxW / pitch);
    const rows  = GLYPH_H * scale + pad;
    if (cols < 1) return false;

    const cssW = cols * pitch, cssH = rows * pitch;
    const dpr  = Math.min(window.devicePixelRatio || 1, 2);

    canvas.width  = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    canvas.style.width  = cssW + 'px';
    canvas.style.height = cssH + 'px';

    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    const r = Math.max(0.75, pitch * 0.34);
    const dot = (c, rw, fill) => {
      ctx.fillStyle = fill;
      ctx.beginPath();
      ctx.arc(c * pitch + pitch / 2, rw * pitch + pitch / 2, r, 0, Math.PI * 2);
      ctx.fill();
    };

    // Dark LED field
    for (let c = 0; c < cols; c++) {
      for (let rw = 0; rw < rows; rw++) dot(c, rw, OFF);
    }

    // Lit glyphs. `tCols` is the reserved slot — for a cycling element that's
    // the longest word, so every shorter word is centred inside it rather than
    // left in place with dead LEDs trailing off to one side.
    let slotCol = inline ? scale : 0;
    if (!inline) {
      if (align === 'center')     slotCol = Math.max(0, Math.floor((cols - tCols) / 2));
      else if (align === 'right') slotCol = Math.max(0, cols - tCols);
    }
    const startFor = (word) =>
      slotCol + Math.floor((tCols - textCols(word, scale)) / 2);

    ctx.shadowColor = color;
    ctx.shadowBlur  = pitch * 1.15;

    const litWord = (word, keep) => {
      const startCol = startFor(word);
      for (let i = 0; i < word.length; i++) {
        const g = glyph(word[i]);
        const base = startCol + i * (GLYPH_W + GLYPH_GAP) * scale;
        for (let gc = 0; gc < GLYPH_W; gc++) {
          const bits = g[gc];
          for (let gr = 0; gr < GLYPH_H; gr++) {
            if (!(bits >> gr & 1)) continue;
            for (let dx = 0; dx < scale; dx++) {
              const c = base + gc * scale + dx;
              if (c < 0 || c >= cols || (keep && !keep(c))) continue;
              for (let dy = 0; dy < scale; dy++) dot(c, gr * scale + dy, color);
            }
          }
        }
      }
    };

    // Mid-swap, the new word has lit up to `wipeCol` and the old word still
    // holds the columns to its right — the panel changing over left to right.
    const wipe = el.__ledWipe;
    if (wipe) {
      const edge = slotCol + wipe.p * (tCols + scale * 2);
      litWord(wipe.to,   (c) => c < edge);
      litWord(wipe.from, (c) => c >= edge);
    } else {
      litWord(text, null);
    }

    ctx.shadowBlur = 0;
    return true;
  }

  // ── Mount ────────────────────────────────────────────────────────────────
  const mounted = [];

  function prepare(el) {
    if (el.__ledCanvas) return;
    const text = el.textContent.replace(/\s+/g, ' ').trim();
    el.setAttribute('data-led-text', text);

    const sr = document.createElement('span');
    sr.className = 'sr-only';
    sr.textContent = text;

    const canvas = document.createElement('canvas');
    canvas.className = 'led-canvas';
    canvas.setAttribute('aria-hidden', 'true');

    el.textContent = '';
    el.appendChild(sr);
    el.appendChild(canvas);
    el.__ledCanvas = canvas;
    el.classList.add('is-led');
    mounted.push(el);
  }

  function mount(el) {
    prepare(el);
    redraw();
  }

  let retryId = null;

  function redraw() {
    // A page that hasn't been given a real width yet (a hidden pane, a tab
    // restored in the background) would measure every container at ~0 and bake
    // that in. Wait for a width worth measuring instead.
    if (document.documentElement.clientWidth < 200) {
      clearTimeout(retryId);
      retryId = setTimeout(redraw, 250);
      return;
    }

    // Every canvas is emptied first: their intrinsic widths would otherwise
    // hold grid tracks open and skew the container measurements below.
    mounted.forEach((el) => {
      const c = el.__ledCanvas;
      c.style.width = ''; c.style.height = '';
      c.width = 0; c.height = 0;
    });

    const groups = resolveGroups(mounted);
    let failed = 0;
    mounted.forEach((el) => {
      try {
        if (!draw(el, el.__ledCanvas, groups)) failed++;
      } catch (_) { failed++; }
    });

    // Anything that couldn't measure itself gets another go once layout settles.
    clearTimeout(retryId);
    if (failed) retryId = setTimeout(redraw, 250);
  }

  // ── Cycling words ────────────────────────────────────────────────────────
  const HOLD_MS = 2100;   // how long each word sits
  const WIPE_MS = 420;    // how long the changeover takes

  function startCycle(el) {
    const words = specOf(el).cycle;
    if (words.length < 2) return;

    let i = 0;
    el.setAttribute('data-led-text', words[0]);

    const swap = () => {
      if (document.hidden) { setTimeout(swap, HOLD_MS); return; }

      const from = words[i];
      const to   = words[i = (i + 1) % words.length];
      const t0   = performance.now();

      const step = (ts) => {
        const p = Math.min(1, (ts - t0) / WIPE_MS);
        el.__ledWipe = { from: from, to: to, p: p };
        draw(el, el.__ledCanvas);
        if (p < 1) { requestAnimationFrame(step); return; }
        el.__ledWipe = null;
        el.setAttribute('data-led-text', to);
        const sr = el.querySelector('.sr-only');
        if (sr) sr.textContent = to;
        draw(el, el.__ledCanvas);
        setTimeout(swap, HOLD_MS);
      };
      requestAnimationFrame(step);
    };

    setTimeout(swap, HOLD_MS);
  }

  function boot() {
    document.querySelectorAll('[data-led]').forEach(prepare);
    redraw();

    if (!REDUCED_MOTION) {
      document.querySelectorAll('[data-led-cycle]').forEach(startCycle);
    }

    // Web fonts and image loads can shift widths after first paint.
    requestAnimationFrame(redraw);
    window.addEventListener('load', redraw);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(redraw);

    let t = null;
    let lastW = document.documentElement.clientWidth;
    const schedule = () => { clearTimeout(t); t = setTimeout(redraw, 120); };

    window.addEventListener('resize', schedule);

    // Catches width changes that never fire a window resize — a pane being
    // revealed, a sidebar opening, a scrollbar appearing. Width only, so the
    // height change a redraw itself causes can't feed back into a loop.
    if ('ResizeObserver' in window) {
      new ResizeObserver(() => {
        const w = document.documentElement.clientWidth;
        if (w === lastW) return;
        lastW = w;
        schedule();
      }).observe(document.documentElement);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  window.LEDText = { redraw: redraw, mount: mount };
})();
