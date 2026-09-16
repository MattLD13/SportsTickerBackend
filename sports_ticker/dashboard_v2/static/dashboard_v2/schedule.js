(function () {
  "use strict";

  const MODES = ["sports", "weather", "music", "flights", "airports", "stock", "clock"];
  const MODE_MARKS = { sports: "S", weather: "W", music: "M", flights: "F", airports: "A", stock: "$", clock: "C" };
  const MIN_BLOCK_MINUTES = 15;
  const state = {
    document: null,
    selectedMode: "sports",
    dragging: null,
  };
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  const escapeHtml = value => String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
  const modeName = mode => String(mode || "").replaceAll("_", " ");
  const modeMark = mode => MODE_MARKS[mode] || "?";

  async function api(path, options = {}) {
    const headers = {
      Accept: "application/json",
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

  function fmtDuration(value) {
    const duration = Math.max(MIN_BLOCK_MINUTES, Math.round(Number(value) || MIN_BLOCK_MINUTES));
    const hours = Math.floor(duration / 60);
    const minutes = duration % 60;
    return hours ? `${hours}h${minutes ? ` ${minutes}m` : ""}` : `${minutes}m`;
  }

  function snapMinute(value) {
    return Math.max(0, Math.min(1440, Math.round(value / 15) * 15));
  }

  function selectMode(mode) {
    if (!MODES.includes(mode)) return;
    state.selectedMode = mode;
    $$("[data-mode]").forEach(button => button.classList.toggle("is-selected", button.dataset.mode === mode));
  }

  function isPrimaryPointer(event) {
    return event.isPrimary !== false && (event.pointerType !== "mouse" || event.button === 0);
  }

  function laneAtPoint(clientX, clientY) {
    const target = document.elementFromPoint(clientX, clientY);
    return target?.closest?.("[data-lane-track]") || null;
  }

  function clearDropTarget() {
    $$('[data-lane-track].is-drop-target').forEach(track => track.classList.remove("is-drop-target"));
  }

  function markDropTarget(track) {
    clearDropTarget();
    track?.classList.add("is-drop-target");
  }

  function releasePointer(target, pointerId) {
    if (target?.hasPointerCapture?.(pointerId)) target.releasePointerCapture(pointerId);
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
        const density = width < 120 ? "compact" : "full";
        return `<article class="schedule-block mode-${escapeHtml(block.mode)}" data-block-id="${escapeHtml(block.id)}" data-start="${start}" data-end="${end}" data-block-mode="${escapeHtml(block.mode)}" data-density="${density}" style="left:${(start / 1440) * 100}%;width:${(width / 1440) * 100}%" title="${escapeHtml(modeName(block.mode))} ${fmtMinute(start)}–${fmtMinute(end)}">
          <span class="block-resize-handle block-resize-start" data-resize="start" role="separator" aria-label="Resize ${escapeHtml(modeName(block.mode))} start time"></span>
          <div class="block-main"><span class="block-mark" aria-hidden="true">${escapeHtml(modeMark(block.mode))}</span><div class="block-copy"><strong>${escapeHtml(modeName(block.mode))}</strong><small data-block-time>${fmtMinute(start)} — ${fmtMinute(end)}</small></div><span class="block-compact-time" data-block-duration>${fmtDuration(width)}</span></div>
          <button class="block-delete" type="button" data-delete-block aria-label="Delete ${escapeHtml(modeName(block.mode))} block">×</button>
          <span class="block-resize-handle block-resize-end" data-resize="end" role="separator" aria-label="Resize ${escapeHtml(modeName(block.mode))} end time"></span>
        </article>`;
      }).join("");
      items.forEach(block => bindBlock($(`[data-block-id="${CSS.escape(block.id)}"]`, track), block));
      track.onclick = event => {
        if (event.target.closest(".schedule-block")) return;
        createBlockAt(group, minuteFromEvent(event, track), state.selectedMode);
      };
    });
  }

  function updateBlockPreview(block, start, end) {
    const width = Math.max(1, end - start);
    block.dataset.previewStart = String(start);
    block.dataset.previewEnd = String(end);
    block.style.left = `${(start / 1440) * 100}%`;
    block.style.width = `${(width / 1440) * 100}%`;
    block.dataset.density = width < 120 ? "compact" : "full";
    block.title = `${modeName(block.dataset.blockMode)} ${fmtMinute(start)}–${fmtMinute(end)}`;
    const time = $("[data-block-time]", block);
    if (time) time.textContent = `${fmtMinute(start)} — ${fmtMinute(end)}`;
    const duration = $("[data-block-duration]", block);
    if (duration) duration.textContent = fmtDuration(width);
  }

  function beginBlockResize(event, block, source, edge) {
    if (!["start", "end"].includes(edge) || !isPrimaryPointer(event)) return;
    event.preventDefault();
    event.stopPropagation();
    const track = block.closest(".lane-track");
    const handle = event.target.closest("[data-resize]");
    if (!track || !handle) return;
    const pointerId = event.pointerId;
    const originalStart = Number(source.start_minute);
    const originalEnd = Number(source.end_minute);
    let currentStart = originalStart;
    let currentEnd = originalEnd;
    let moved = false;
    state.dragging = { kind: "resize", pointerId };
    block.classList.add("is-resizing");
    handle.setPointerCapture?.(pointerId);
    const move = moveEvent => {
      if (moveEvent.pointerId !== pointerId) return;
      moveEvent.preventDefault();
      const minute = minuteFromEvent(moveEvent, track);
      if (edge === "start") {
        currentStart = Math.max(0, Math.min(originalEnd - MIN_BLOCK_MINUTES, minute));
      } else {
        currentEnd = Math.min(1440, Math.max(originalStart + MIN_BLOCK_MINUTES, minute));
      }
      moved = currentStart !== originalStart || currentEnd !== originalEnd;
      updateBlockPreview(block, currentStart, currentEnd);
    };
    const finish = async finishEvent => {
      if (finishEvent.pointerId !== pointerId) return;
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", finish);
      handle.removeEventListener("pointercancel", finish);
      state.dragging = null;
      block.classList.remove("is-resizing");
      releasePointer(handle, pointerId);
      if (!moved || finishEvent.type === "pointercancel") {
        if (moved) await load();
        return;
      }
      try {
        await api(`/api/v2/schedule/blocks/${encodeURIComponent(source.id)}`, {
          method: "PATCH",
          body: JSON.stringify({ start_minute: currentStart, end_minute: currentEnd }),
        });
        setFeedback(`Schedule block resized to ${fmtMinute(currentStart)} — ${fmtMinute(currentEnd)}.`);
        await load();
      } catch (error) { setFeedback(error.message, true); await load(); }
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
  }

  function beginBlockMove(event, block, source) {
    event.preventDefault();
    const track = block.closest(".lane-track");
    if (!track) return;
    const blockRect = block.getBoundingClientRect();
    const start = Number(source.start_minute);
    const duration = Number(source.end_minute) - start;
    const pointerId = event.pointerId;
    const grabOffset = event.clientX - blockRect.left;
    let currentTrack = track;
    let currentGroup = source.day_group;
    let currentStart = start;
    let moved = false;
    state.dragging = { kind: "block", pointerId };
    block.classList.add("is-dragging");
    block.setPointerCapture?.(pointerId);
    const move = moveEvent => {
      if (moveEvent.pointerId !== pointerId) return;
      const distance = Math.hypot(moveEvent.clientX - event.clientX, moveEvent.clientY - event.clientY);
      if (!moved) {
        if (distance < 5) return;
        moved = true;
      }
      moveEvent.preventDefault();
      const targetTrack = laneAtPoint(moveEvent.clientX, moveEvent.clientY) || currentTrack;
      if (!targetTrack) return;
      if (targetTrack !== currentTrack) {
        targetTrack.appendChild(block);
        currentTrack = targetTrack;
        currentGroup = targetTrack.closest("[data-day-group]")?.dataset.dayGroup || currentGroup;
      }
      markDropTarget(currentTrack);
      const rect = currentTrack.getBoundingClientRect();
      const rawStart = ((moveEvent.clientX - rect.left - grabOffset) / rect.width) * 1440;
      const nextStart = Math.max(0, Math.min(1440 - duration, snapMinute(rawStart)));
      currentStart = nextStart;
      updateBlockPreview(block, nextStart, nextStart + duration);
    };
    const finish = async finishEvent => {
      if (finishEvent.pointerId !== pointerId) return;
      block.removeEventListener("pointermove", move);
      block.removeEventListener("pointerup", finish);
      block.removeEventListener("pointercancel", finish);
      state.dragging = null;
      block.classList.remove("is-dragging");
      clearDropTarget();
      releasePointer(block, pointerId);
      if (!moved || finishEvent.type === "pointercancel") {
        if (moved) await load();
        return;
      }
      try {
        await api(`/api/v2/schedule/blocks/${encodeURIComponent(source.id)}`, {
          method: "PATCH",
          body: JSON.stringify({
            day_group: currentGroup,
            start_minute: currentStart,
            end_minute: currentStart + duration,
          }),
        });
        setFeedback("Schedule block moved.");
        await load();
      } catch (error) { setFeedback(error.message, true); await load(); }
    };
    block.addEventListener("pointermove", move);
    block.addEventListener("pointerup", finish);
    block.addEventListener("pointercancel", finish);
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
      const resizeHandle = event.target.closest?.("[data-resize]");
      if (resizeHandle) {
        beginBlockResize(event, block, source, resizeHandle.dataset.resize);
        return;
      }
      if (event.target.closest?.("button") || !isPrimaryPointer(event)) return;
      beginBlockMove(event, block, source);
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
    const tickers = Array.isArray(state.document?.tickers) ? state.document.tickers : [];
    const liveGames = Number(state.document?.live_games || 0);
    const blocks = Object.values(state.document?.blocks || {}).flat().length;
    const conditions = state.document?.conditions?.length || 0;
    $("[data-ticker-count]").textContent = tickers.length;
    $("[data-ticker-list]").innerHTML = tickers.length
      ? tickers.map(ticker => `<div class="server-ticker"><strong>${escapeHtml(ticker.name || "Ticker")}</strong><small class="mono">${escapeHtml(ticker.id)}</small></div>`).join("")
      : '<div class="empty-state">No server tickers are registered.</div>';
    $("[data-live-games]").textContent = liveGames;
    $("[data-rule-count]").textContent = blocks + conditions;
    $("[data-schedule-summary]").textContent = `${blocks} time block${blocks === 1 ? "" : "s"} · ${conditions} live condition${conditions === 1 ? "" : "s"} · ${liveGames} live game${liveGames === 1 ? "" : "s"}`;
    $("[data-timeline-status]").textContent = "READY";
  }

  async function load() {
    if (state.dragging) return;
    try {
      state.document = await api("/api/v2/schedule");
      render();
    } catch (error) {
      $("[data-schedule-summary]").textContent = error.message;
      $("[data-timeline-status]").textContent = "LOCKED";
      setFeedback(error.message, true);
    }
  }

  function bindModePalette() {
    $$('[data-mode]').forEach(button => {
      button.addEventListener("click", () => selectMode(button.dataset.mode));
      button.addEventListener("pointerdown", event => {
        if (!isPrimaryPointer(event)) return;
        const pointerId = event.pointerId;
        const originX = event.clientX;
        const originY = event.clientY;
        let moved = false;
        state.dragging = { kind: "palette", pointerId };
        button.classList.add("is-dragging");
        button.setPointerCapture?.(pointerId);
        const move = moveEvent => {
          if (moveEvent.pointerId !== pointerId) return;
          const distance = Math.hypot(moveEvent.clientX - originX, moveEvent.clientY - originY);
          if (!moved) {
            if (distance < 5) return;
            moved = true;
          }
          moveEvent.preventDefault();
          markDropTarget(laneAtPoint(moveEvent.clientX, moveEvent.clientY));
        };
        const finish = async finishEvent => {
          if (finishEvent.pointerId !== pointerId) return;
          button.removeEventListener("pointermove", move);
          button.removeEventListener("pointerup", finish);
          button.removeEventListener("pointercancel", finish);
          state.dragging = null;
          button.classList.remove("is-dragging");
          const targetTrack = laneAtPoint(finishEvent.clientX, finishEvent.clientY);
          clearDropTarget();
          releasePointer(button, pointerId);
          if (!moved || finishEvent.type === "pointercancel") return;
          if (!targetTrack) {
            setFeedback("Drop the mode on a weekday or weekend lane.", true);
            return;
          }
          const lane = targetTrack.closest("[data-day-group]");
          const group = lane?.dataset.dayGroup;
          if (group) await createBlockAt(group, minuteFromEvent(finishEvent, targetTrack), button.dataset.mode);
        };
        button.addEventListener("pointermove", move);
        button.addEventListener("pointerup", finish);
        button.addEventListener("pointercancel", finish);
      });
    });
    selectMode(state.selectedMode);
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

  bindModePalette();
  renderAxis();
  load();
  window.setInterval(load, 30000);
}());
