(function () {
  "use strict";

  const MODES = ["sports", "weather", "music", "flights", "airports", "stock", "clock"];
  const state = {
    document: null,
    controllerToken: sessionStorage.getItem("sportsTicker.controllerToken") || "",
    selectedMode: "sports",
    draggingBlock: false,
  };
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  const escapeHtml = value => String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
  const modeName = mode => String(mode || "").replaceAll("_", " ");

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

  function setFeedback(message, error = false) {
    const target = $("[data-schedule-feedback]");
    target.textContent = message;
    target.className = `global-feedback ${error ? "is-error" : "is-ok"}`;
  }

  function fmtMinute(value) {
    const minute = Math.max(0, Math.min(1440, Number(value) || 0));
    if (minute === 1440) return "24:00";
    return `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
  }

  function snapMinute(value) {
    return Math.max(0, Math.min(1440, Math.round(value / 15) * 15));
  }

  function selectMode(mode) {
    if (!MODES.includes(mode)) return;
    state.selectedMode = mode;
    $$("[data-mode]").forEach(button => button.classList.toggle("is-selected", button.dataset.mode === mode));
  }

  function renderAxis() {
    const axis = $("[data-time-axis]");
    axis.innerHTML = Array.from({ length: 13 }, (_, index) => {
      const minute = index * 120;
      return `<span style="left:${(minute / 1440) * 100}%">${fmtMinute(minute)}</span>`;
    }).join("");
  }

  function renderBlocks() {
    const blocks = state.document?.blocks || {};
    $$("[data-day-group]").forEach(lane => {
      const group = lane.dataset.dayGroup;
      const track = $("[data-lane-track]", lane);
      const items = Array.isArray(blocks[group]) ? blocks[group] : [];
      track.innerHTML = items.map(block => {
        const start = Number(block.start_minute);
        const end = Number(block.end_minute);
        const width = Math.max(1, end - start);
        return `<article class="schedule-block mode-${escapeHtml(block.mode)}" data-block-id="${escapeHtml(block.id)}" data-start="${start}" data-end="${end}" style="left:${(start / 1440) * 100}%;width:${(width / 1440) * 100}%" title="${escapeHtml(modeName(block.mode))} ${fmtMinute(start)}–${fmtMinute(end)}">
          <button class="block-delete" type="button" data-delete-block aria-label="Delete ${escapeHtml(modeName(block.mode))} block">×</button>
          <strong>${escapeHtml(modeName(block.mode))}</strong>
          <small>${fmtMinute(start)} — ${fmtMinute(end)}</small>
        </article>`;
      }).join("");
      items.forEach(block => bindBlock($("[data-block-id=\"${CSS.escape(block.id)}\"]", track), block));
      track.ondragover = event => event.preventDefault();
      track.ondrop = event => {
        event.preventDefault();
        const mode = event.dataTransfer?.getData("text/mode") || state.selectedMode;
        createBlockAt(group, minuteFromEvent(event, track), mode);
      };
      track.onclick = event => {
        if (event.target.closest(".schedule-block")) return;
        createBlockAt(group, minuteFromEvent(event, track), state.selectedMode);
      };
    });
  }

  function bindBlock(block, source) {
    if (!block) return;
    $("[data-delete-block]", block).addEventListener("click", async event => {
      event.stopPropagation();
      if (!window.confirm(`Delete the ${modeName(source.mode)} block?`)) return;
      try {
        await api(`/api/v2/schedule/blocks/${encodeURIComponent(source.id)}`, { method: "DELETE" });
        setFeedback("Schedule block deleted.");
        await load();
      } catch (error) { setFeedback(error.message, true); }
    });
    block.addEventListener("pointerdown", event => {
      if (event.target.closest("button")) return;
      event.preventDefault();
      const track = block.closest(".lane-track");
      const rect = track.getBoundingClientRect();
      const start = Number(source.start_minute);
      const duration = Number(source.end_minute) - start;
      state.draggingBlock = true;
      block.setPointerCapture(event.pointerId);
      const move = moveEvent => {
        const rawDelta = ((moveEvent.clientX - event.clientX) / rect.width) * 1440;
        const delta = Math.round(rawDelta / 15) * 15;
        const nextStart = Math.max(0, Math.min(1440 - duration, start + delta));
        block.dataset.previewStart = String(nextStart);
        block.style.left = `${(nextStart / 1440) * 100}%`;
        block.title = `${modeName(source.mode)} ${fmtMinute(nextStart)}–${fmtMinute(nextStart + duration)}`;
        $("small", block).textContent = `${fmtMinute(nextStart)} — ${fmtMinute(nextStart + duration)}`;
      };
      const finish = async finishEvent => {
        block.removeEventListener("pointermove", move);
        block.removeEventListener("pointerup", finish);
        block.removeEventListener("pointercancel", finish);
        state.draggingBlock = false;
        const nextStart = Number(block.dataset.previewStart ?? start);
        if (nextStart === start) return;
        try {
          await api(`/api/v2/schedule/blocks/${encodeURIComponent(source.id)}`, {
            method: "PATCH",
            body: JSON.stringify({ start_minute: nextStart, end_minute: nextStart + duration }),
          });
          setFeedback("Schedule block moved.");
          await load();
        } catch (error) { setFeedback(error.message, true); await load(); }
        if (block.hasPointerCapture(finishEvent.pointerId)) block.releasePointerCapture(finishEvent.pointerId);
      };
      block.addEventListener("pointermove", move);
      block.addEventListener("pointerup", finish);
      block.addEventListener("pointercancel", finish);
    });
  }

  function minuteFromEvent(event, track) {
    const rect = track.getBoundingClientRect();
    const fraction = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    return snapMinute(fraction * 1440);
  }

  async function createBlockAt(dayGroup, startMinute, mode) {
    if (!MODES.includes(mode)) return;
    const start = Math.min(1380, snapMinute(startMinute));
    try {
      await api("/api/v2/schedule/blocks", {
        method: "POST",
        body: JSON.stringify({ day_group: dayGroup, start_minute: start, end_minute: Math.min(1440, start + 60), mode, enabled: true }),
      });
      setFeedback(`${modeName(mode)} block added to ${dayGroup}.`);
      await load();
    } catch (error) { setFeedback(error.message, true); }
  }

  function renderConditions() {
    const list = $("[data-condition-list]");
    const conditions = state.document?.conditions || [];
    if (!conditions.length) {
      list.innerHTML = '<div class="empty-state">No live-game conditions configured.</div>';
      return;
    }
    list.innerHTML = conditions.map(condition => `<div class="condition-row" data-condition-id="${escapeHtml(condition.id)}">
      <div><strong>${Number(condition.threshold)}+ live game${Number(condition.threshold) === 1 ? "" : "s"}</strong><small>Condition ${condition.enabled ? "enabled" : "paused"}</small></div>
      <label>Force mode<select data-condition-mode>${MODES.map(mode => `<option value="${mode}" ${mode === condition.mode ? "selected" : ""}>${modeName(mode)}</option>`).join("")}</select></label>
      <label class="check-label"><input type="checkbox" data-condition-enabled ${condition.enabled ? "checked" : ""}> Enabled</label>
      <button class="delete-condition" type="button" data-delete-condition>Delete</button>
    </div>`).join("");
    conditions.forEach(condition => {
      const row = $(`[data-condition-id="${CSS.escape(condition.id)}"]`, list);
      $("[data-condition-mode]", row).addEventListener("change", event => updateCondition(condition, { mode: event.target.value }));
      $("[data-condition-enabled]", row).addEventListener("change", event => updateCondition(condition, { enabled: event.target.checked }));
      $("[data-delete-condition]", row).addEventListener("click", async () => {
        if (!window.confirm("Delete this live-game condition?")) return;
        try {
          await api(`/api/v2/schedule/conditions/${encodeURIComponent(condition.id)}`, { method: "DELETE" });
          setFeedback("Live-game condition deleted.");
          await load();
        } catch (error) { setFeedback(error.message, true); }
      });
    });
  }

  async function updateCondition(condition, changes) {
    try {
      await api(`/api/v2/schedule/conditions/${encodeURIComponent(condition.id)}`, {
        method: "PATCH",
        body: JSON.stringify(changes),
      });
      setFeedback("Live-game condition updated.");
      await load();
    } catch (error) { setFeedback(error.message, true); }
  }

  function render() {
    renderAxis();
    renderBlocks();
    renderConditions();
    const liveGames = Number(state.document?.live_games || 0);
    const blocks = Object.values(state.document?.blocks || {}).flat().length;
    const conditions = state.document?.conditions?.length || 0;
    $("[data-live-games]").textContent = liveGames;
    $("[data-rule-count]").textContent = blocks + conditions;
    $("[data-schedule-summary]").textContent = `${blocks} time block${blocks === 1 ? "" : "s"} · ${conditions} live condition${conditions === 1 ? "" : "s"} · ${liveGames} live game${liveGames === 1 ? "" : "s"}`;
    $("[data-timeline-status]").textContent = "READY";
  }

  async function load() {
    if (!state.controllerToken.trim() || state.draggingBlock) return;
    try {
      state.document = await api("/api/v2/schedule");
      render();
    } catch (error) {
      $("[data-schedule-summary]").textContent = error.status === 401 ? "Enter a controller token to load the schedule" : error.message;
      $("[data-timeline-status]").textContent = "LOCKED";
      setFeedback(error.message, true);
    }
  }

  function bindModePalette() {
    $$('[data-mode]').forEach(button => {
      button.addEventListener("click", () => selectMode(button.dataset.mode));
      button.addEventListener("dragstart", event => {
        selectMode(button.dataset.mode);
        event.dataTransfer.setData("text/mode", button.dataset.mode);
        event.dataTransfer.effectAllowed = "copy";
      });
    });
    selectMode(state.selectedMode);
  }

  function bindAuth() {
    $("[data-controller-token-form]").addEventListener("submit", event => {
      event.preventDefault();
      state.controllerToken = $("[data-controller-token]").value.trim();
      sessionStorage.setItem("sportsTicker.controllerToken", state.controllerToken);
      setFeedback(state.controllerToken ? "Controller token saved." : "Controller token cleared.");
      load();
    });
    $("[data-controller-token]").value = state.controllerToken;
  }

  $("[data-condition-form]").addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const threshold = Number(form.elements.threshold.value);
    const mode = form.elements.mode.value;
    try {
      await api("/api/v2/schedule/conditions", {
        method: "POST",
        body: JSON.stringify({ kind: "live_games", threshold, mode, enabled: true }),
      });
      setFeedback("Live-game condition added.");
      await load();
    } catch (error) { setFeedback(error.message, true); }
  });

  bindAuth();
  bindModePalette();
  renderAxis();
  load();
  window.setInterval(load, 30000);
}());
