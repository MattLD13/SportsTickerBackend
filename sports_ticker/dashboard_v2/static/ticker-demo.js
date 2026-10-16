/* Display production server pixels and move scrolling panes one pixel at a time. */
(function () {
  'use strict';
  const HEIGHT = 32, WIDTH = 384;
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

  function mount(root) {
    const viewport = root.querySelector('[data-demo-vp]');
    const controls = root.querySelector('[data-demo-controls]');
    if (!viewport) return;
    const base = (root.dataset.base || '').replace(/\/$/, '');
    const modes = JSON.parse(root.dataset.modes || '[]');
    if (!modes.length) return;
    const speed = Number(root.dataset.scrollRate) || 33;
    let index = 0, generation = 0, visible = !document.hidden;
    let rotating = root.dataset.autorotate === 'true' && !reducedMotion;
    let timer = null, rotation = null, animation = null, request = null;
    let track = null, stripWidth = 0, offset = 0, previousTime = null, objectUrl = null;
    const buttons = [];
    let auto = null;

    function status(text) {
      const message = document.createElement('div');
      message.className = 'demo-status'; message.textContent = text;
      viewport.replaceChildren(message);
    }

    function stop() {
      clearTimeout(timer); clearTimeout(rotation);
      if (animation !== null) cancelAnimationFrame(animation);
      animation = null; previousTime = null;
      if (request) request.abort();
      request = null;
    }

    function tick(time) {
      animation = null;
      if (!visible || !track || !stripWidth || reducedMotion) return;
      if (previousTime !== null) offset = (offset + Math.min((time - previousTime) / 1000, .1) * speed) % stripWidth;
      previousTime = time;
      const scale = viewport.clientHeight / HEIGHT;
      track.style.transform = `translateX(${-Math.floor(offset) * scale}px)`;
      animation = requestAnimationFrame(tick);
    }

    function startAnimation() {
      if (visible && track && animation === null && !reducedMotion) animation = requestAnimationFrame(tick);
    }

    function showPixels(image, url, mode) {
      const oldUrl = objectUrl;
      if (mode.kind === 'scroll') {
        stripWidth = image.naturalWidth;
        offset %= stripWidth;
        const replacement = document.createElement('div'); replacement.className = 'demo-track';
        const copies = Math.max(2, Math.ceil(WIDTH / stripWidth) + 1);
        for (let i = 0; i < copies; i++) {
          const pane = image.cloneNode(); pane.className = 'demo-strip'; pane.alt = `${mode.label} ticker preview`;
          replacement.append(pane);
        }
        if (track) track.replaceWith(replacement);
        else viewport.replaceChildren(replacement);
        track = replacement;
        track.style.transform = `translateX(${-Math.floor(offset) * viewport.clientHeight / HEIGHT}px)`;
        startAnimation();
      } else {
        image.className = 'demo-frame'; image.alt = `${mode.label} ticker preview`;
        viewport.replaceChildren(image);
      }
      objectUrl = url;
      if (oldUrl) URL.revokeObjectURL(oldUrl);
    }

    async function refresh(token) {
      if (!visible || token !== generation) return;
      const mode = modes[index];
      const controller = new AbortController(); request = controller;
      let candidate = null;
      try {
        const response = await fetch(`${base}/api/v2/demo/frame.png?mode=${encodeURIComponent(mode.id)}&_t=${Date.now()}`, {signal:controller.signal});
        if (!response.ok) throw new Error('Preview unavailable');
        candidate = URL.createObjectURL(await response.blob());
        const image = new Image();
        await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = reject; image.src = candidate; });
        if (token !== generation || controller.signal.aborted) return;
        showPixels(image, candidate, mode); candidate = null;
      } catch (error) {
        if (error.name !== 'AbortError' && token === generation && !objectUrl) status('PREVIEW UNAVAILABLE — RETRYING...');
      } finally {
        if (candidate) URL.revokeObjectURL(candidate);
        if (request === controller) request = null;
        if (visible && token === generation && !controller.signal.aborted) {
          const period = mode.id === 'clock' ? 1000 : ['music', 'weather'].includes(mode.id) ? 250 : 15000;
          timer = setTimeout(() => refresh(token), period);
        }
      }
    }

    function queueRotation() {
      clearTimeout(rotation);
      if (rotating && visible) rotation = setTimeout(() => goTo(index + 1), 18000);
    }

    function setRotating(value) {
      rotating = value;
      if (auto) { auto.classList.toggle('is-active', value); auto.setAttribute('aria-pressed', String(value)); }
      queueRotation();
    }

    function goTo(next, manual = false) {
      stop(); generation++;
      if (manual) setRotating(false);
      index = (next + modes.length) % modes.length;
      track = null; stripWidth = 0; offset = 0;
      if (objectUrl) { URL.revokeObjectURL(objectUrl); objectUrl = null; }
      root.dataset.mode = modes[index].id;
      buttons.forEach((button, i) => { button.classList.toggle('is-active', i === index); button.setAttribute('aria-pressed', String(i === index)); });
      status('LOADING TICKER...'); refresh(generation); queueRotation();
    }

    if (controls) {
      controls.replaceChildren();
      modes.forEach((mode, i) => {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'demo-btn'; button.textContent = mode.label;
        button.onclick = () => goTo(i, true); controls.append(button); buttons.push(button);
      });
      if (root.dataset.autorotate === 'true' && !reducedMotion) {
        auto = document.createElement('button'); auto.type = 'button'; auto.className = 'demo-btn demo-btn-auto is-active'; auto.textContent = 'Auto'; auto.setAttribute('aria-pressed', 'true');
        auto.onclick = () => setRotating(!rotating); controls.append(auto);
      }
    }
    function setVisible(value) {
      if (value === visible) return;
      visible = value;
      if (!value) stop();
      else { refresh(generation); startAnimation(); queueRotation(); }
    }
    if ('IntersectionObserver' in window) new IntersectionObserver(entries => setVisible(entries[0].isIntersecting && !document.hidden), {threshold:.01}).observe(root);
    document.addEventListener('visibilitychange', () => setVisible(!document.hidden && root.getBoundingClientRect().bottom > 0 && root.getBoundingClientRect().top < innerHeight));
    goTo(0);
  }
  document.querySelectorAll('[data-ticker-demo]').forEach(mount);
})();
