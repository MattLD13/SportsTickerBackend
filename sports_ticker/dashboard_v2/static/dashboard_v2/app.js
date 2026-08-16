(() => {
  "use strict";

  const state = {
    tickers: [],
    selectedId: null,
    selected: null,
    snapshot: null,
    controllerToken: sessionStorage.getItem("sportsTicker.controllerToken") || "",
  };
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  const escapeHtml = value => String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const display = value => value === null || value === undefined || value === "" ? "—" : String(value);
  const modeName = value => display(value).replaceAll("_", " ");

  function setFeedback(message, error = false) {
    const target = $("[data-global-feedback]");
    target.textContent = message;
    target.className = `global-feedback ${error ? "is-error" : "is-ok"}`;
    window.setTimeout(() => { if (target.textContent === message) target.textContent = ""; }, 5000);
  }

  function controllerHeaders() {
    const token = state.controllerToken.trim();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  async function api(path, options = {}) {
    const headers = {
      Accept: "application/json",
      ...controllerHeaders(),
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    };
    const response = await fetch(path, { ...options, headers });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(body.error?.message || `Request failed (${response.status})`);
      error.status = response.status;
      throw error;
    }
    return body;
  }

  function setHealth(health) {
    const providers = Object.values(health.scheduler?.providers || {});
    const healthy = health.status === "ok";
    $$('[data-health-dot]').forEach(dot => dot.className = `status-dot ${healthy ? "is-ok" : "is-bad"}`);
    $$('[data-health-label]').forEach(node => node.textContent = healthy ? "Healthy" : "Degraded");
    $("[data-health-summary]").textContent = healthy ? "Backend health is nominal" : "Backend reports degraded providers";
    $$('[data-provider-count]').forEach(node => node.textContent = providers.length ? `${providers.filter(item => item.healthy).length}/${providers.length}` : "none");
  }

  function renderTickers() {
    const list = $("[data-ticker-list]");
    $$('[data-ticker-count]').forEach(node => node.textContent = state.tickers.length);
    if (!state.tickers.length) {
      list.innerHTML = '<div class="empty-state">No v2 tickers configured.</div>';
      return;
    }
    list.innerHTML = state.tickers.map(ticker => {
      const active = ticker.ticker_id === state.selectedId;
      const seen = ticker.device?.last_seen_at ? ago(ticker.device.last_seen_at) : "never seen";
      const mode = ticker.pairing?.paired ? ticker.display_settings?.mode : "pairing";
      return `<button class="ticker-row ${active ? "is-selected" : ""}" type="button" data-ticker-id="${escapeHtml(ticker.ticker_id)}">
        <span class="ticker-avatar">${escapeHtml((ticker.name || ticker.ticker_id).slice(0, 2).toUpperCase())}</span>
        <span class="ticker-row-copy"><strong>${escapeHtml(ticker.name)}</strong><small class="mono">${escapeHtml(ticker.ticker_id)}</small></span>
        <span class="ticker-row-meta"><b>${escapeHtml(modeName(mode))}</b><small>${escapeHtml(seen)}</small></span>
      </button>`;
    }).join("");
    $$('[data-ticker-id]').forEach(button => button.addEventListener("click", () => selectTicker(button.dataset.tickerId)));
  }

  function ago(value) {
    const timestamp = typeof value === "number" ? value * 1000 : Date.parse(value);
    if (!Number.isFinite(timestamp)) return "unknown age";
    const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  }

  function renderSettings() {
    const settings = state.selected?.display_settings || {};
    $$('[data-setting]').forEach(field => {
      const value = settings[field.dataset.setting];
      if (field.type === "checkbox") field.checked = Boolean(value);
      else field.value = value ?? "";
    });
    syncSportsControls();
  }

  function syncSportsControls() {
    const mode = $('[data-setting="mode"]');
    const presentation = $('[data-setting="sports_presentation"]');
    const pinnedId = $('[data-setting="pinned_content_id"]');
    if (!mode || !presentation || !pinnedId) return;
    const sports = mode.value === "sports";
    presentation.disabled = !sports;
    pinnedId.disabled = !sports || presentation.value !== "pinned";
  }

  function renderSnapshot() {
    const ticker = state.selected;
    const data = state.snapshot;
    $("[data-selected-name]").textContent = ticker?.name || "—";
    $("[data-selected-id]").textContent = ticker?.ticker_id || "—";
    $("[data-selected-device]").textContent = ticker?.device?.last_seen_at ? `Device seen ${ago(ticker.device.last_seen_at)}` : "Device not seen";
    const effectiveMode = data?.settings?.mode || (ticker?.pairing?.paired ? ticker?.display_settings?.mode : "pairing");
    $("[data-selected-mode]").textContent = modeName(effectiveMode);
    $("[data-snapshot-revision]").textContent = display(data?.snapshot?.revision);
    $("[data-snapshot-age]").textContent = data?.snapshot?.observed_at ? ago(data.snapshot.observed_at) : "no snapshot";
    const health = data?.health;
    const healthPill = $("[data-snapshot-health]");
    healthPill.textContent = data ? (health?.healthy ? "PROVIDER OK" : "PROVIDER ERROR") : "NO SNAPSHOT";
    healthPill.className = `pill ${data && health?.healthy ? "is-ok" : "is-bad"}`;
    const summary = $("[data-content-summary]");
    const items = Object.values(data?.content || {}).flat();
    const visible = items.filter(item => item.is_shown !== false);
    summary.textContent = data ? `${visible.length} visible item${visible.length === 1 ? "" : "s"} · ${items.length} total · ${data.events?.alerts?.length || 0} alerts · ${data.events?.news?.length || 0} news` : "Waiting for a snapshot.";
    renderContent(visible);
    $("[data-json-view]").textContent = data ? JSON.stringify(data, null, 2) : "—";
  }

  function renderContent(items) {
    const grid = $("[data-content-grid]");
    if (!items.length) { grid.innerHTML = '<div class="empty-state">No visible content in this snapshot.</div>'; return; }
    grid.innerHTML = items.slice(0, 12).map(item => {
      const data = item.data || {};
      const summary = contentSummary(item, data);
      return `<article class="content-card"><div class="content-card-top"><span class="family-tag">${escapeHtml(item.family)}</span><span class="mono">${escapeHtml(summary.schema)}</span></div><strong>${escapeHtml(summary.title)}</strong><b>${escapeHtml(summary.value)}</b><small>${escapeHtml(summary.detail || item.id)}</small></article>`;
    }).join("");
  }

  function contentSummary(item, data) {
    const displayData = data.display || data.scoreboard || data.canonical || {};
    const home = displayData.home || {};
    const away = displayData.away || {};
    const homeLabel = home.label || home.abbreviation || home.abbr || data.home_abbr;
    const awayLabel = away.label || away.abbreviation || away.abbr || data.away_abbr;
    const scoreboard = homeLabel || awayLabel;
    const title = scoreboard
      ? `${display(awayLabel)} @ ${display(homeLabel)}`
      : firstValue(data, "title", "headline", "name", "city", "symbol", "artist", "driver", "flight_number") || item.kind || item.family;
    const value = scoreboard
      ? `${display(away.score ?? data.away_score)} — ${display(home.score ?? data.home_score)}`
      : firstValue(data, "value", "score", "temperature", "temp", "price", "condition", "status", "headline", "text") || item.kind || item.family;
    const detail = firstValue(data, "clock", "game_clock", "round", "session", "state", "status", "detail", "id");
    return { schema: data.schema || data.sport || data.league || data.series || "custom", title, value, detail };
  }

  function firstValue(data, ...keys) {
    for (const key of keys) {
      if (data[key] !== null && data[key] !== undefined && data[key] !== "") return data[key];
    }
    return "";
  }

  async function selectTicker(id) {
    state.selectedId = id;
    state.selected = state.tickers.find(ticker => ticker.ticker_id === id) || null;
    state.snapshot = null;
    renderTickers(); renderSettings(); renderSnapshot();
    try { state.snapshot = await fetchSnapshot(id); renderSnapshot(); }
    catch (error) { setFeedback(error.message, true); }
  }

  async function fetchSnapshot(tickerId) {
    try {
      return await api(`/api/v2/tickers/${encodeURIComponent(tickerId)}/data`);
    } catch (error) {
      if (error.status === 404) return null;
      throw error;
    }
  }

  async function refresh() {
    try {
      const [health, tickerData] = await Promise.all([api("/api/v2/health"), api("/api/v2/tickers")]);
      setHealth(health); state.tickers = tickerData.tickers || [];
      if (!state.selectedId || !state.tickers.some(item => item.ticker_id === state.selectedId)) state.selectedId = state.tickers[0]?.ticker_id || null;
      state.selected = state.tickers.find(item => item.ticker_id === state.selectedId) || null;
      renderTickers(); renderSettings();
      if (state.selectedId) state.snapshot = await fetchSnapshot(state.selectedId);
      renderSnapshot();
      $("[data-updated]").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch (error) { setFeedback(error.message, true); $$('[data-health-label]').forEach(node => node.textContent = "Unavailable"); }
  }

  function formSettings() {
    const current = { ...(state.selected?.display_settings || {}) };
    $$('[data-setting]').forEach(field => {
      const value = field.type === "checkbox" ? field.checked : field.value;
      current[field.dataset.setting] = field.type === "number" ? Number(value) : value;
    });
    return current;
  }

  async function saveSettings(event) {
    event.preventDefault();
    if (!state.selectedId) return;
    const stateLabel = $("[data-settings-state]"); stateLabel.textContent = "Saving…";
    try {
      const settings = formSettings();
      if (settings.mode !== "sports") {
        settings.sports_presentation = "rotation";
        settings.pinned_content_id = "";
      }
      settings.pinned_content_id = String(settings.pinned_content_id || "").trim();
      if (settings.mode === "sports" && settings.sports_presentation === "pinned" && !settings.pinned_content_id) {
        stateLabel.textContent = "Pinned ID required";
        setFeedback("Sports pinned presentation requires a pinned content ID.", true);
        return;
      }
      const updated = await api(`/api/v2/tickers/${encodeURIComponent(state.selectedId)}`, { method: "PATCH", body: JSON.stringify({ display_settings: settings }) });
      state.selected = updated; state.tickers = state.tickers.map(item => item.ticker_id === updated.ticker_id ? updated : item);
      if (state.snapshot) state.snapshot.settings = { ...state.snapshot.settings, ...updated.display_settings };
      stateLabel.textContent = "Saved"; renderTickers(); renderSettings(); renderSnapshot();
    } catch (error) { stateLabel.textContent = "Save failed"; setFeedback(error.message, true); }
  }

  async function saveControllerToken(event) {
    event.preventDefault();
    const input = $("[data-controller-token]");
    state.controllerToken = String(input?.value || "").trim();
    if (state.controllerToken) sessionStorage.setItem("sportsTicker.controllerToken", state.controllerToken);
    else sessionStorage.removeItem("sportsTicker.controllerToken");
    state.selectedId = null;
    state.selected = null;
    state.snapshot = null;
    renderTickers(); renderSettings(); renderSnapshot();
    await refresh();
  }

  function overlayPayload(form, type) {
    const values = Object.fromEntries(new FormData(form).entries());
    const ttl = Number(values.ttl_seconds || 60);
    delete values.ttl_seconds;
    if (type === "alert") return { kind: "score_alert", payload: values, target_ticker_ids: [state.selectedId], ttl_seconds: ttl };
    return { kind: values.kind || "news", payload: values, target_ticker_ids: [state.selectedId], ttl_seconds: ttl };
  }

  async function sendOverlay(event) {
    event.preventDefault();
    if (!state.selectedId) return;
    const form = event.currentTarget; const type = form.dataset.overlayForm;
    const feedback = $("[data-overlay-feedback]"); feedback.textContent = "Sending…";
    try {
      await api(`/api/v2/events/${type === "alert" ? "alerts" : "news"}`, { method: "POST", body: JSON.stringify(overlayPayload(form, type)) });
      feedback.textContent = `${type === "alert" ? "Score alert" : "News overlay"} sent.`; form.reset();
      state.snapshot = await api(`/api/v2/tickers/${encodeURIComponent(state.selectedId)}/data`); renderSnapshot();
    } catch (error) { feedback.textContent = error.message; }
  }

  function bind() {
    $("[data-refresh]").addEventListener("click", refresh);
    $("[data-controller-token-form]").addEventListener("submit", event => {
      saveControllerToken(event).catch(error => setFeedback(error.message, true));
    });
    $("[data-settings-form]").addEventListener("submit", saveSettings);
    $$('[data-setting="mode"], [data-setting="sports_presentation"]').forEach(field => field.addEventListener("change", syncSportsControls));
    $$('[data-overlay-form]').forEach(form => form.addEventListener("submit", sendOverlay));
    $$('[data-overlay-tab]').forEach(tab => tab.addEventListener("click", () => {
      $$('[data-overlay-tab]').forEach(item => item.classList.toggle("is-active", item === tab));
      $$('[data-overlay-form]').forEach(form => form.classList.toggle("is-hidden", form.dataset.overlayForm !== tab.dataset.overlayTab));
    }));
    $("[data-copy-json]").addEventListener("click", async event => {
      if (!state.snapshot) return;
      await navigator.clipboard.writeText(JSON.stringify(state.snapshot, null, 2));
      event.currentTarget.textContent = "Copied"; window.setTimeout(() => { event.currentTarget.textContent = "Copy JSON"; }, 1500);
    });
  }

  const tokenInput = $("[data-controller-token]");
  if (tokenInput) tokenInput.value = state.controllerToken;
  bind(); refresh();
  window.setInterval(refresh, 30000);
  window.setInterval(() => { if (state.snapshot) renderSnapshot(); }, 1000);
})();
