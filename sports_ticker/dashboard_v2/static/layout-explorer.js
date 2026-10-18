/* Browse exact sample frames without controlling a connected ticker. */
(function () {
  'use strict';
  const root = document.querySelector('[data-layout-explorer]');
  if (!root) return;
  const $ = id => document.getElementById(id);
  const png = data => `data:image/png;base64,${data}`;
  function mainUrl(row, presentation = 'pinned') {
    if (!row.main.full) presentation = 'rotation';
    const url = new URL(root.dataset.frameUrl, location.href);
    url.searchParams.set('case', row.name); url.searchParams.set('presentation', presentation);
    return url.href;
  }
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const images = new Map();
  const sources = new Map();
  let cases = [], filtered = [], current = null, generation = 0;
  let playing = false, timer = null, animating = !reducedMotion, animation = null;
  let strip = null, offset = 0, lastTime = null;
  let miniAtlas = null, motionMs = 0, lastMiniFrame = -1;
  let zoomSource = null;

  function status(message) { $('status').textContent = message; }
  function image(data) {
    return loadImage(png(data));
  }
  function loadImage(url) {
    if (!images.has(url)) {
      images.set(url, new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error('A sample frame failed to load.'));
        img.src = url;
      }));
    }
    return images.get(url);
  }

  function canvasFrom(source) {
    const canvas = document.createElement('canvas');
    canvas.width = source.naturalWidth || source.width;
    canvas.height = source.naturalHeight || source.height;
    canvas.getContext('2d').drawImage(source, 0, 0);
    return canvas;
  }

  function paint(target, source, enlarged = false) {
    const dots = $('pixels').value === 'led';
    const pitch = dots ? (enlarged ? 8 : 4) : 1;
    target.width = source.width * pitch;
    target.height = source.height * pitch;
    const ctx = target.getContext('2d');
    ctx.imageSmoothingEnabled = false;
    if (!dots) { ctx.drawImage(source, 0, 0); return; }
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, target.width, target.height);
    const pixels = source.getContext('2d').getImageData(0, 0, source.width, source.height).data;
    for (let y = 0; y < source.height; y++) {
      for (let x = 0; x < source.width; x++) {
        const i = (y * source.width + x) * 4;
        ctx.fillStyle = `rgb(${pixels[i]},${pixels[i + 1]},${pixels[i + 2]})`;
        ctx.beginPath();
        ctx.arc((x + 0.5) * pitch, (y + 0.5) * pitch, pitch * 0.37, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }

  function setBoard(device, source) {
    sources.set(device, source);
    paint($(`${device}-frame`), source);
    root.querySelector(`[data-board="${device}"]`).classList.remove('unavailable');
    $(`${device}-screen`).disabled = false;
  }

  function writeUrl() {
    if (!current) return;
    const params = new URLSearchParams();
    params.set('case', current.name);
    for (const id of ['category', 'device', 'layout', 'pixels', 'brightness']) params.set(id, $(id).value);
    if ($('search').value) params.set('q', $('search').value);
    history.replaceState(null, '', `${location.pathname}?${params}`);
  }

  function stopAnimation() {
    if (animation !== null) cancelAnimationFrame(animation);
    animation = null;
    lastTime = null;
  }

  function drawStrip() {
    if (!strip) return;
    const frame = document.createElement('canvas');
    frame.width = 384; frame.height = 32;
    const ctx = frame.getContext('2d');
    ctx.fillStyle = '#000'; ctx.fillRect(0, 0, 384, 32);
    const left = Math.floor(offset);
    for (let x = -left; x < 384; x += strip.width) ctx.drawImage(strip, x, 0);
    setBoard('main', frame);
  }

  function animate(time) {
    animation = null;
    if (!animating || document.hidden) return;
    const elapsed = lastTime === null ? 0 : Math.min(time - lastTime, 100);
    motionMs += elapsed;
    if (strip && $('layout').value === 'pane' && $('device').value !== 'mini') {
      const previousPixel = Math.floor(offset);
      offset = (offset + elapsed / 1000 * 33) % strip.width;
      if (Math.floor(offset) !== previousPixel) drawStrip();
    }
    if (miniAtlas && $('device').value !== 'main') {
      const index = Math.floor(motionMs / miniAtlas.frameMs) % miniAtlas.frames;
      if (index !== lastMiniFrame) {
        const frame = document.createElement('canvas'); frame.width = 64; frame.height = 32;
        frame.getContext('2d').drawImage(miniAtlas.source, 0, index * 32, 64, 32, 0, 0, 64, 32);
        setBoard('mini', frame); lastMiniFrame = index;
      }
    }
    lastTime = time;
    animation = requestAnimationFrame(animate);
  }

  function startAnimation() {
    stopAnimation();
    const activeMini = miniAtlas && $('device').value !== 'main';
    const activeMain = strip && $('device').value !== 'mini' && $('layout').value === 'pane';
    if (animating && !document.hidden && !$('zoom').open && (activeMini || activeMain)) animation = requestAnimationFrame(animate);
  }

  async function drawCurrent() {
    if (!current) return;
    const token = ++generation;
    const row = current;
    stopAnimation(); strip = null; miniAtlas = null; offset = 0; motionMs = 0; lastMiniFrame = -1;
    $('layout').disabled = !row.main.pane || !row.main.full;
    if (!row.main.full) $('layout').value = 'pane';
    else if (!row.main.pane) $('layout').value = 'pinned';
    $('motion').hidden = !(row.mini_animation && $('device').value !== 'main') &&
      !($('layout').value === 'pane' && row.main.pane && $('device').value !== 'mini');
    $('motion').setAttribute('aria-pressed', String(animating));
    $('motion').textContent = animating ? 'Pause animation' : 'Animate views';
    try {
      const [mini, atlas] = await Promise.all([image(row.mini), row.mini_animation ? image(row.mini_animation.image) : null]);
      if (token !== generation) return;
      setBoard('mini', canvasFrom(mini));
      if (atlas) miniAtlas = {source: atlas, frames: row.mini_animation.frames, frameMs: row.mini_animation.frame_ms};
      $('mini-note').textContent = atlas ? 'Current Mini layout · repeating example' : 'Current Mini layout · sample data';
      startAnimation();
      if (!row.main.available) {
        sources.delete('main');
        root.querySelector('[data-board="main"]').classList.add('unavailable');
        $('main-screen').disabled = true;
        $('main-note').textContent = row.main.note;
        return;
      }
      if ($('layout').value === 'pane' && row.main.pane) {
        const rendered = await loadImage(mainUrl(row, 'rotation'));
        if (token !== generation) return;
        strip = canvasFrom(rendered);
        drawStrip(); startAnimation();
        $('main-note').textContent = 'Production scrolling panes · neighboring examples share the board';
      } else {
        const main = await loadImage(mainUrl(row));
        if (token !== generation) return;
        setBoard('main', canvasFrom(main));
        $('main-note').textContent = 'Production Pi renderer · sample data';
      }
    } catch (error) { if (token === generation) status(error.message); }
  }

  function schedule() {
    clearTimeout(timer);
    if (playing && !document.hidden && filtered.length > 1) timer = setTimeout(() => step(1, false), Number($('dwell').value) * 1000);
  }

  function pause() {
    playing = false; clearTimeout(timer);
    $('play').textContent = 'Play examples'; $('play').setAttribute('aria-pressed', 'false');
  }

  function select(row, manual = true) {
    if (!row) return;
    if (manual) pause();
    current = row;
    $('case-title').textContent = row.title;
    $('case-category').textContent = `${row.group.toUpperCase()} / ${row.name}`;
    $('case-note').textContent = row.note || '';
    $('case-note').hidden = !row.note;
    $('position').textContent = `${filtered.indexOf(row) + 1} / ${filtered.length}`;
    for (const card of $('cases').children) card.setAttribute('aria-pressed', String(card.dataset.case === row.name));
    $('previous').disabled = $('next').disabled = filtered.length < 2;
    drawCurrent(); writeUrl(); schedule();
  }

  function step(direction, manual = true) {
    if (!filtered.length) return;
    select(filtered[(filtered.indexOf(current) + direction + filtered.length) % filtered.length], manual);
  }

  function makeCards() {
    const fragment = document.createDocumentFragment();
    for (const row of filtered) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'case-card'; button.dataset.case = row.name;
      button.setAttribute('aria-pressed', String(row === current));
      const label = document.createElement('span'); label.className = 'case-label';
      const id = document.createElement('span'); id.className = 'case-id'; id.textContent = row.name;
      const title = document.createElement('span'); title.textContent = row.title;
      label.append(id, title);
      const screens = document.createElement('span'); screens.className = 'case-screens';
      for (const device of ['main', 'mini']) {
        const data = device === 'main' ? row.main.available : row.mini;
        if (!data) continue;
        const img = document.createElement('img');
        img.className = `thumb-${device}`; img.loading = 'lazy'; img.alt = device === 'main' ? 'Ticker Six' : 'Mini ticker'; img.src = device === 'main' ? mainUrl(row) : png(data);
        img.width = device === 'main' ? 384 : 64; img.height = 32;
        screens.append(img);
      }
      const group = document.createElement('span'); group.className = 'case-group'; group.textContent = row.group;
      button.append(label, screens, group);
      button.addEventListener('click', () => { select(row); $('case-title').scrollIntoView({block:'start', behavior: reducedMotion ? 'instant' : 'smooth'}); });
      fragment.append(button);
    }
    $('cases').replaceChildren(fragment);
  }

  function filter(preferred = null) {
    const query = $('search').value.trim().toLowerCase();
    filtered = cases.filter(row => ($('category').value === 'all' || row.group === $('category').value) && `${row.name} ${row.title} ${row.group} ${row.mode} ${JSON.stringify(row.game)}`.toLowerCase().includes(query));
    $('result-count').textContent = `${filtered.length} of ${cases.length} examples`;
    $('empty').hidden = filtered.length !== 0;
    for (const chip of $('category-chips').children) chip.setAttribute('aria-pressed', String(chip.dataset.category === $('category').value));
    makeCards();
    const selected = filtered.find(row => row.name === preferred) || (filtered.includes(current) ? current : filtered[0]);
    if (selected) select(selected);
    else {
      pause(); $('position').textContent = '0 / 0'; $('previous').disabled = $('next').disabled = true;
      writeUrl();
    }
  }

  function showZoom(device) {
    const source = sources.get(device);
    if (!source) return;
    zoomSource = canvasFrom(source);
    pause(); stopAnimation();
    $('zoom-title').textContent = `${device === 'main' ? 'Big' : 'Mini'} ticker · ${current.name} · ${current.title}`;
    paint($('zoom-frame'), zoomSource, true);
    $('zoom-frame').style.width = `${zoomSource.width * (device === 'mini' ? 12 : 6)}px`;
    $('pixel-readout').textContent = 'Move over the image to inspect a source pixel. Colors use full brightness.';
    $('zoom').showModal();
  }

  function restore(params, id) {
    const value = params.get(id);
    if (value !== null && [...$(id).options].some(option => option.value === value)) $(id).value = value;
  }

  async function boot() {
    try {
      const response = await fetch(root.dataset.galleryUrl, {credentials:'omit'});
      if (!response.ok) throw new Error('The layout library is unavailable. Reload to try again.');
      const data = await response.json();
      if (data.schema_version !== 3 || !Array.isArray(data.cases) || !data.cases.length) throw new Error('The layout library is invalid.');
      cases = data.cases;
      for (const group of [...new Set(cases.map(row => row.group))]) $('category').add(new Option(group, group));
      for (const option of $('category').options) {
        const button = document.createElement('button'); button.type = 'button'; button.textContent = option.text;
        button.dataset.category = option.value; button.setAttribute('aria-pressed', 'false');
        button.onclick = () => { $('category').value = option.value; filter(); };
        $('category-chips').append(button);
      }
      const params = new URLSearchParams(location.search);
      for (const id of ['category', 'device', 'layout', 'pixels']) restore(params, id);
      if (params.has('brightness')) $('brightness').value = String(Math.max(20, Math.min(100, Number(params.get('brightness')) || 100)));
      $('search').value = params.get('q') || '';
      setDevice(); setBrightness(); filter(params.get('case'));
      status(`${cases.length} examples ready. Choose a layout to compare both tickers.`);
    } catch (error) { status(error.message); $('case-title').textContent = 'Examples unavailable'; }
  }

  function setDevice() {
    const device = $('device').value;
    root.querySelector('.boards').dataset.device = device;
    for (const board of root.querySelectorAll('[data-board]')) board.hidden = device !== 'both' && device !== board.dataset.board;
    writeUrl();
  }

  function setBrightness() {
    root.style.setProperty('--brightness', Number($('brightness').value) / 100);
    $('brightness-value').textContent = `${$('brightness').value}%`; writeUrl();
  }

  $('previous').onclick = () => step(-1);
  $('next').onclick = () => step(1);
  $('category').onchange = () => filter();
  $('search').oninput = () => filter();
  $('clear').onclick = () => { $('category').value = 'all'; $('search').value = ''; filter(); };
  $('device').onchange = () => { setDevice(); drawCurrent(); };
  $('layout').onchange = () => { drawCurrent(); writeUrl(); };
  $('pixels').onchange = () => { drawCurrent(); writeUrl(); };
  $('brightness').oninput = setBrightness;
  $('dwell').onchange = schedule;
  $('play').onclick = () => {
    if (playing) { pause(); return; }
    if (filtered.length < 2) { status('Choose at least two matching examples to play.'); return; }
    playing = true; $('play').textContent = 'Pause examples'; $('play').setAttribute('aria-pressed', 'true'); schedule();
  };
  $('motion').onclick = () => {
    animating = !animating; $('motion').setAttribute('aria-pressed', String(animating));
    $('motion').textContent = animating ? 'Pause animation' : 'Animate views'; startAnimation();
  };
  $('share').onclick = async () => {
    writeUrl();
    try { await navigator.clipboard.writeText(location.href); status('Link copied. It opens this example with your preview settings.'); }
    catch (_) { status(`Copy this address: ${location.href}`); }
  };
  $('main-screen').onclick = () => showZoom('main');
  $('mini-screen').onclick = () => showZoom('mini');
  $('close-zoom').onclick = () => $('zoom').close();
  $('zoom').addEventListener('close', startAnimation);
  $('zoom').addEventListener('click', event => { if (event.target === $('zoom')) $('zoom').close(); });
  $('zoom-frame').addEventListener('pointermove', event => {
    if (!zoomSource) return;
    const bounds = event.target.getBoundingClientRect();
    const x = Math.min(zoomSource.width - 1, Math.max(0, Math.floor((event.clientX - bounds.left) / bounds.width * zoomSource.width)));
    const y = Math.min(zoomSource.height - 1, Math.max(0, Math.floor((event.clientY - bounds.top) / bounds.height * zoomSource.height)));
    const rgb = zoomSource.getContext('2d').getImageData(x, y, 1, 1).data;
    $('pixel-readout').textContent = `x ${x} · y ${y} · RGB ${rgb[0]}, ${rgb[1]}, ${rgb[2]}`;
  });
  document.addEventListener('keydown', event => {
    if ($('zoom').open || event.target.matches('input,select,textarea,[contenteditable=true]') || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); step(event.key === 'ArrowRight' ? 1 : -1); }
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { clearTimeout(timer); stopAnimation(); }
    else { schedule(); startAnimation(); }
  });
  boot();
})();
