(function () {
  "use strict";
  const ML_UI_ENABLED = false;

  function $(id) {
    return document.getElementById(id);
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  async function apiGet(url) {
    const r = await fetch(url, { credentials: "same-origin" });
    let data = null;
    try {
      data = await r.json();
    } catch (_e) {
      data = null;
    }
    if (!r.ok || (data && data.ok === false)) {
      throw new Error((data && (data.error || data.message)) || `HTTP ${r.status}`);
    }
    return data || {};
  }

  async function apiPost(url, body) {
    const r = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    let data = null;
    try {
      data = await r.json();
    } catch (_e) {
      data = null;
    }
    if (!r.ok || (data && data.ok === false)) {
      throw new Error((data && (data.error || data.message)) || `HTTP ${r.status}`);
    }
    return data || {};
  }

  let resizeObserver = null;

  const state = {
    enabled: false,
    active: false,
    initialized: false,
    cy: null,
    timer: null,
    loading: false,
    timelineBuckets: [],
    timelineRange: null,
    timelineIdx: 0,
    timelineManual: false,
    graphData: null,
    compareData: null,
    searchDebounce: null,
    refreshDebounce: null,
    destroyed: false,
    contextTarget: null,
    selectedBucketRange: null,
    mlRisk: null,
    mlPredictionId: 0,
    mlSettings: null,
    mlModels: [],
    graphMode: "static",
    liveEnabled: true,
    livePollMs: 5000,
    playbackSpeed: 1,
    playbackActive: false,
    playbackTimer: null,
    timelineVisualIdx: 0,
    timelineAnimFrame: null,
    compAnimFrame: null,
    compValues: null,
    dynamicCursorTs: "",
    dynamicSinceTs: "",
    forecast: null,
    dynamicErrorStreak: 0,
    focusedElementId: "",
    hoveredNodeId: "",
  };

  const ui = {};

  function getGraphMode() {
    return ui.mode ? String(ui.mode.value || "static") : "static";
  }

  function isDynamicMode() {
    return getGraphMode() === "dynamic";
  }

  function updateLiveBadge() {
    if (!ui.liveState) return;
    const dynamic = isDynamicMode();
    const liveOn = dynamic && !!(ui.live && ui.live.checked);
    ui.liveState.textContent = liveOn ? "LIVE" : dynamic ? "DYNAMIC" : "STATIC";
    ui.liveState.classList.toggle("live-on", liveOn);
    ui.liveState.classList.toggle("live-off", !liveOn);
  }

  function setPeriodTransition(active) {
    const on = !!active;
    if (ui.dashboard) ui.dashboard.classList.toggle("rg-period-switching", on);
    if (ui.stage) ui.stage.classList.toggle("rg-period-switching", on);
  }

  function syncFullscreenPanels() {
    if (!ui.stage || !ui.fsPanels) return;
    const inFullscreen = document.fullscreenElement === ui.stage;
    ui.fsPanels.setAttribute("aria-hidden", inFullscreen ? "false" : "true");
    if (!inFullscreen) return;

    if (ui.fsSelection && ui.selection) ui.fsSelection.innerHTML = ui.selection.innerHTML || "—";
    if (ui.fsTopHubs && ui.topHubs) ui.fsTopHubs.textContent = ui.topHubs.textContent || "—";
    if (ui.fsTopBridges && ui.topBridges) ui.fsTopBridges.textContent = ui.topBridges.textContent || "—";
    if (ui.fsMlPrediction && ui.mlPrediction) ui.fsMlPrediction.textContent = ui.mlPrediction.textContent || "—";
    if (ui.fsMlReasons && ui.mlReasons) ui.fsMlReasons.textContent = ui.mlReasons.textContent || "—";
    if (ui.fsMlHotspots && ui.mlHotspots) ui.fsMlHotspots.textContent = ui.mlHotspots.textContent || "—";
    if (ui.fsMlModelActive && ui.mlModelActive) ui.fsMlModelActive.textContent = ui.mlModelActive.textContent || "Активная модель: —";
    if (ui.fsMlModelMetrics && ui.mlModelMetrics) ui.fsMlModelMetrics.textContent = ui.mlModelMetrics.textContent || "Метрики: —";
    if (ui.fsMlModelDiagnostics && ui.mlModelDiagnostics) ui.fsMlModelDiagnostics.textContent = ui.mlModelDiagnostics.textContent || "Диагностика: —";
    if (ui.fsMlModelRuns && ui.mlModelRuns) ui.fsMlModelRuns.textContent = ui.mlModelRuns.textContent || "Последние модели: —";
    if (ui.fsStatus && ui.statusMsg) ui.fsStatus.textContent = ui.statusMsg.textContent || "—";

    if (ui.fsStart && ui.start) ui.fsStart.value = ui.start.value;
    if (ui.fsEnd && ui.end) ui.fsEnd.value = ui.end.value;
    if (ui.fsMode && ui.mode) ui.fsMode.value = ui.mode.value;
    if (ui.fsLive && ui.live) ui.fsLive.checked = !!ui.live.checked;
    if (ui.fsPlaySpeed && ui.playSpeed) ui.fsPlaySpeed.value = ui.playSpeed.value;
    if (ui.fsPlayToggle && ui.playToggle) ui.fsPlayToggle.textContent = ui.playToggle.textContent || "Play";
    if (ui.fsTimeSlider && ui.timeSlider) {
      ui.fsTimeSlider.max = ui.timeSlider.max || "0";
      ui.fsTimeSlider.value = ui.timeSlider.value || "0";
    }
    if (ui.fsTimeLabel && ui.timeLabel) ui.fsTimeLabel.textContent = ui.timeLabel.textContent || "—";
    if (ui.fsComposition && ui.composition) ui.fsComposition.textContent = ui.composition.textContent || "—";
    if (ui.fsPeriod) {
      const mainActive = ui.period ? ui.period.querySelector(".active[data-days]") : null;
      const days = mainActive ? String(mainActive.getAttribute("data-days") || "1") : "1";
      ui.fsPeriod.querySelectorAll("[data-days]").forEach((b) => {
        b.classList.toggle("active", String(b.getAttribute("data-days") || "") === days);
      });
    }
    if (ui.fsForecastSummary && ui.forecastSummary) ui.fsForecastSummary.textContent = ui.forecastSummary.textContent || "—";
    if (ui.fsForecastReliability && ui.forecastReliability) ui.fsForecastReliability.textContent = ui.forecastReliability.textContent || "Надёжность: —";
    if (ui.fsForecastH30 && ui.forecastH30) ui.fsForecastH30.textContent = ui.forecastH30.textContent || "H30: —";
    if (ui.fsForecastH60 && ui.forecastH60) ui.fsForecastH60.textContent = ui.forecastH60.textContent || "H60: —";
    if (ui.fsForecastH120 && ui.forecastH120) ui.fsForecastH120.textContent = ui.forecastH120.textContent || "H120: —";
  }

  function isEnabled() {
    return !!$("rg-dashboard");
  }

  function getCtx() {
    const c = window.__AN_GRAPH_CONTEXT || {};
    return {
      selectedUnit: String(c.selectedUnit || ""),
      selectedPair: c.selectedPair || null,
    };
  }

  function fmtDateTime(v) {
    if (!v) return "—";
    const d = new Date(v);
    if (Number.isNaN(d.getTime())) return String(v);
    return d.toLocaleString("ru-RU", { hour12: false });
  }

  function formatGroupLabel(rawGroup) {
    const g = String(rawGroup || "").trim();
    if (!g) return "G —";
    const normalized = g.replace(/^g\s*/i, "").trim();
    if (!normalized) return "G —";
    return `G ${normalized}`;
  }

  function hashCode(s) {
    let h = 2166136261;
    const str = String(s || "");
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return Math.abs(h >>> 0);
  }

  function pickThemeNodeColor(data) {
    const mode = ui.theme ? String(ui.theme.value || "unit") : "unit";
    if (mode === "mono") return "#4f7cf1";
    if (mode === "contrast") {
      const contrast = ["#ef6c5b", "#4f7cf1", "#8f6be8", "#2ea3a0", "#f2a93b", "#4e8d5f", "#aa6f54", "#5b88cc"];
      return contrast[hashCode(data.cluster || data.unit || data.id) % contrast.length];
    }
    const unitPalette = ["#5b88cc", "#4e8d5f", "#8f6be8", "#f2a93b", "#d97777", "#2ea3a0", "#6f94d9", "#aa6f54"];
    return unitPalette[hashCode(data.cluster || data.unit || data.id) % unitPalette.length];
  }

  function syncInspector(open) {
    if (!ui.dashboard) return;
    const show = !!open;
    ui.dashboard.classList.toggle("rg2-inspector-open", show);
    if (ui.inspectorBackdrop) {
      ui.inspectorBackdrop.hidden = !show;
      ui.inspectorBackdrop.setAttribute("aria-hidden", show ? "false" : "true");
    }
    if (state.cy) {
      window.requestAnimationFrame(() => {
        try {
          state.cy.resize();
        } catch (_e) {
          /* ignore */
        }
      });
    }
  }

  function openInspector() {
    syncInspector(true);
  }

  function closeInspector() {
    syncInspector(false);
  }

  function toggleFilterDrawer() {
    if (!ui.dashboard || !ui.filterDrawer) return;
    const open = ui.filterDrawer.hidden;
    ui.filterDrawer.hidden = !open;
    ui.dashboard.classList.toggle("rg2-filters-open", open);
    if (ui.toggleFiltersBtn) {
      ui.toggleFiltersBtn.setAttribute("aria-expanded", open ? "true" : "false");
      ui.toggleFiltersBtn.classList.toggle("active", open);
    }
  }

  function closeFilterDrawer() {
    if (!ui.dashboard || !ui.filterDrawer) return;
    ui.filterDrawer.hidden = true;
    ui.dashboard.classList.remove("rg2-filters-open");
    if (ui.toggleFiltersBtn) {
      ui.toggleFiltersBtn.setAttribute("aria-expanded", "false");
      ui.toggleFiltersBtn.classList.remove("active");
    }
  }

  function hideContextMenu() {
    if (ui.contextMenu) ui.contextMenu.style.display = "none";
    state.contextTarget = null;
  }

  function showContextMenu(ev, items, target) {
    if (!ui.contextMenu || !ui.stage || !Array.isArray(items) || !items.length) return;
    ui.contextMenu.innerHTML = "";
    state.contextTarget = target || null;
    for (const item of items) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = item.label;
      btn.addEventListener("click", () => {
        hideContextMenu();
        item.action();
      });
      ui.contextMenu.appendChild(btn);
    }
    const stageRect = ui.stage.getBoundingClientRect();
    const x = Math.max(8, Math.min(stageRect.width - 188, Number(ev.renderedPosition ? ev.renderedPosition.x : 12)));
    const y = Math.max(8, Math.min(stageRect.height - 180, Number(ev.renderedPosition ? ev.renderedPosition.y : 12)));
    ui.contextMenu.style.left = `${x}px`;
    ui.contextMenu.style.top = `${y}px`;
    ui.contextMenu.style.display = "";
  }

  function readRange() {
    const start = ui.start ? String(ui.start.value || "").trim() : "";
    const end = ui.end ? String(ui.end.value || "").trim() : "";
    if (!start || !end) return null;
    const s = new Date(start);
    const e = new Date(end);
    if (Number.isNaN(s.getTime()) || Number.isNaN(e.getTime()) || e <= s) return null;
    return { start, end };
  }

  function buildScope(params) {
    const scope = ui.scope ? String(ui.scope.value || "pair") : "pair";
    const ctx = getCtx();
    if (scope === "pair" && ctx.selectedPair) {
      params.set("frequency", String(ctx.selectedPair.frequency || ""));
      params.set("group", String(ctx.selectedPair.group || ""));
      return "pair";
    }
    if (scope === "unit" && ctx.selectedUnit) {
      params.set("unit_name", ctx.selectedUnit);
      return "unit";
    }
    return "all";
  }

  function getTimelineDays() {
    const btn = ui.period ? ui.period.querySelector(".active[data-days]") : null;
    const d = btn ? parseInt(btn.getAttribute("data-days") || "1", 10) : 1;
    if (!Number.isFinite(d)) return 1;
    return Math.max(1, Math.min(30, d));
  }

  function buildGraphParams() {
    const params = new URLSearchParams();
    const range = readRange();
    if (range) {
      params.set("start", range.start);
      params.set("end", range.end);
    } else {
      params.set("days", String(getTimelineDays()));
    }
    buildScope(params);
    params.set("include_other", ui.includeOther && ui.includeOther.checked ? "1" : "0");
    if (ui.unitQuery && ui.unitQuery.value.trim()) params.set("unit_query", ui.unitQuery.value.trim());
    if (ui.groupQuery && ui.groupQuery.value.trim()) params.set("group_query", ui.groupQuery.value.trim());
    params.set("min_weight", String(Math.max(1, Number(ui.minWeight ? ui.minWeight.value : 1) || 1)));
    params.set("cluster_by", ui.clusterBy ? String(ui.clusterBy.value || "unit") : "unit");
    params.set("max_nodes_mode", ui.maxNodesMode ? String(ui.maxNodesMode.value || "balanced") : "balanced");
    params.set("layout_hint", ui.layout ? String(ui.layout.value || "cose") : "cose");
    if (ui.focusId && ui.focusId.value.trim()) params.set("focus_id", ui.focusId.value.trim());
    if (ui.maxNodes && String(ui.maxNodes.value || "").trim()) {
      const n = parseInt(ui.maxNodes.value, 10);
      if (Number.isFinite(n)) params.set("max_nodes", String(n));
    }
    if (ui.maxEdges && String(ui.maxEdges.value || "").trim()) {
      const n = parseInt(ui.maxEdges.value, 10);
      if (Number.isFinite(n)) params.set("max_edges", String(n));
    }
    return params;
  }

  function syncRangeLabel() {
    if (!ui.statusRange) return;
    if (state.timelineManual && state.selectedBucketRange && state.selectedBucketRange.start && state.selectedBucketRange.end) {
      ui.statusRange.textContent = `${fmtDateTime(state.selectedBucketRange.start)} — ${fmtDateTime(
        state.selectedBucketRange.end
      )}`;
      return;
    }
    const range = readRange();
    if (range) {
      ui.statusRange.textContent = `${fmtDateTime(range.start)} — ${fmtDateTime(range.end)}`;
    } else {
      const labels = { 1: "Сутки", 3: "3 дня", 7: "Неделя", 30: "Месяц" };
      ui.statusRange.textContent = labels[getTimelineDays()] || "Сутки";
    }
  }

  function showStatus(text, isError) {
    if (!ui.statusMsg) return;
    ui.statusMsg.textContent = text || "—";
    ui.statusMsg.classList.toggle("text-danger", !!isError);
    syncFullscreenPanels();
  }

  function updateMetrics(data) {
    const metrics = data && data.metrics ? data.metrics : {};
    if (ui.mNodes) ui.mNodes.textContent = String((data && data.nodes && data.nodes.length) || 0);
    if (ui.mEdges) ui.mEdges.textContent = String((data && data.edges && data.edges.length) || 0);
    if (ui.mDensity) ui.mDensity.textContent = Number(metrics.density || 0).toFixed(3);
    if (ui.mComponents) ui.mComponents.textContent = String(metrics.components || 0);
    if (ui.mRisk) {
      const risk = metrics.risk || {};
      const score = Number(risk.score || 0);
      const level = String(risk.level || "low").toLowerCase();
      const levelText = level === "high" ? "HIGH" : level === "medium" ? "MEDIUM" : "LOW";
      ui.mRisk.textContent = `${score} (${levelText})`;
      ui.mRisk.classList.remove("risk-low", "risk-medium", "risk-high");
      ui.mRisk.classList.add(level === "high" ? "risk-high" : level === "medium" ? "risk-medium" : "risk-low");
      const reasons = Array.isArray(risk.reasons) ? risk.reasons : [];
      ui.mRisk.title = reasons.length ? reasons.join("; ") : "Сигналы риска в норме";
    }
    if (ui.mMlRisk) {
      const ml = metrics.ml_risk || state.mlRisk || {};
      const p = Number(ml.probability || 0);
      const pct = Math.max(0, Math.min(100, Math.round(p * 100)));
      const lbl = String(ml.top_label || "none").toUpperCase();
      ui.mMlRisk.textContent = `${pct}% (${lbl})`;
    }
    if (ui.topHubs) {
      const hubs = Array.isArray(metrics.top_hubs) ? metrics.top_hubs : [];
      ui.topHubs.textContent = hubs.length
        ? hubs.slice(0, 6).map((h) => `${h.id} (${h.weighted_degree})`).join(", ")
        : "—";
    }
    if (ui.topBridges) {
      const bridges = Array.isArray(metrics.top_bridges) ? metrics.top_bridges : [];
      ui.topBridges.textContent = bridges.length
        ? bridges.slice(0, 6).map((h) => `${h.id} (${Number(h.betweenness_approx || 0).toFixed(2)})`).join(", ")
        : "—";
    }
    syncFullscreenPanels();
  }

  function makeCyElements(data) {
    const nodes = Array.isArray(data.nodes) ? data.nodes : [];
    const edges = Array.isArray(data.edges) ? data.edges : [];
    const out = [];
    const units = new Map();
    const nodeIds = new Set();
    const nodeAvatars = new Map();
    for (const n of nodes) {
      const unitName = String(n.unit_name || "").trim();
      const id = String(n.id || "");
      if (!id) continue;
      nodeIds.add(id);
      nodeAvatars.set(id, String(n.avatar_url || ""));
      out.push({
        data: {
          id,
          label: id,
          displayLabel: String(id),
          renderLabel: String(id),
          unit: unitName,
          group: String(n.group || ""),
          count: Number(n.count || 0),
          degree: Number(n.degree || 0),
          weighted_degree: Number(n.weighted_degree || 0),
          betweenness: Number(n.betweenness_approx || 0),
          cluster: String(n.cluster_key || n.unit_name || ""),
          avatar: String(n.avatar_url || ""),
          kind: "id",
          nodeColor: "#5b88cc",
        },
      });
      if (unitName) {
        const unitId = `unit::${unitName}`;
        if (!units.has(unitId)) {
          units.set(unitId, {
            data: {
              id: unitId,
              label: unitName,
              displayLabel: unitName,
              renderLabel: unitName,
              unit: unitName,
              avatar: String(n.avatar_url || ""),
              kind: "unit",
              nodeColor: "#f2a93b",
            },
            classes: "rg-unit-hub",
          });
        }
        out.push({
          data: {
            id: `${unitId}__${id}`,
            source: unitId,
            target: id,
            weight: 1,
            norm: 0.1,
            unit: unitName,
            kind: "unit-link",
            avatar: String(n.avatar_url || ""),
            edgeColor: "#9bb3e8",
          },
          classes: "rg-unit-link",
        });
      }
    }
    units.forEach((u) => out.push(u));
    units.forEach((u) => nodeIds.add(String(u.data.id || "")));
    for (const e of edges) {
      const s = String(e.source || "");
      const t = String(e.target || "");
      if (!s || !t || !nodeIds.has(s) || !nodeIds.has(t)) continue;
      out.push({
        data: {
          id: `${s}__${t}`,
          source: s,
          target: t,
          weight: Number(e.weight || 0),
          norm: Number(e.normalized_weight || 0),
          unit: String(e.unit_name || ""),
          recent: String(e.recent_activity || ""),
          avatar: String(e.avatar_url || ""),
          sourceAvatar: String(nodeAvatars.get(s) || ""),
          targetAvatar: String(nodeAvatars.get(t) || ""),
          kind: "edge",
          edgeColor: "#6f94d9",
        },
      });
    }
    return out;
  }

  function packDisconnectedComponents() {
    if (!state.cy) return;
    const components = state.cy.elements().components()
      .map((component) => component.nodes())
      .filter((nodes) => nodes.length > 0);
    if (components.length < 2) return;

    const gap = 54;
    const items = components.map((nodes) => {
      const bb = nodes.boundingBox({ includeLabels: true, includeOverlays: false });
      return {
        nodes,
        bb,
        width: Math.max(44, bb.w) + gap,
        height: Math.max(44, bb.h) + gap,
      };
    }).sort((a, b) => (b.width * b.height) - (a.width * a.height));
    const totalArea = items.reduce((sum, item) => sum + item.width * item.height, 0);
    const canvasRatio = Math.max(1.2, (ui.canvas?.clientWidth || 1200) / Math.max(1, ui.canvas?.clientHeight || 700));
    const targetWidth = Math.max(items[0].width, Math.sqrt(totalArea * canvasRatio) * 1.12);
    let cursorX = 0;
    let cursorY = 0;
    let rowHeight = 0;

    state.cy.batch(() => {
      for (const item of items) {
        if (cursorX > 0 && cursorX + item.width > targetWidth) {
          cursorX = 0;
          cursorY += rowHeight;
          rowHeight = 0;
        }
        const dx = cursorX + gap / 2 - item.bb.x1;
        const dy = cursorY + gap / 2 - item.bb.y1;
        item.nodes.forEach((node) => {
          if (node.locked()) return;
          const pos = node.position();
          node.position({ x: pos.x + dx, y: pos.y + dy });
        });
        cursorX += item.width;
        rowHeight = Math.max(rowHeight, item.height);
      }
    });
  }

  function updateNodeLabels() {
    if (!state.cy) return;
    const showAll = !!(ui.showLabels && ui.showLabels.checked);
    const zoom = Number(state.cy.zoom() || 1);
    state.cy.nodes().style("font-size", Math.min(26, Math.max(13, 11 / zoom)));
    const weighted = state.cy.nodes("[kind = 'id']").map((node) => Number(node.data("weighted_degree") || 0)).sort((a, b) => b - a);
    const hubCutoff = weighted.length ? weighted[Math.min(weighted.length - 1, Math.floor(weighted.length * 0.16))] : 0;
    state.cy.batch(() => {
      state.cy.nodes("[kind = 'id']").forEach((node) => {
        const isFocused = node.selected() || node.id() === state.focusedElementId || node.id() === state.hoveredNodeId || node.hasClass("rg-related");
        const isHub = Number(node.data("weighted_degree") || 0) >= hubCutoff && Number(node.data("weighted_degree") || 0) > 0;
        const visible = isFocused || showAll || (zoom >= 0.4 && isHub) || (weighted.length <= 45 && zoom >= 0.4) || zoom >= 1.35;
        if (!visible) {
          node.data("renderLabel", "");
          return;
        }
        const idLabel = String(node.data("displayLabel") || "");
        const groupLabel = zoom >= 0.82 || isFocused ? formatGroupLabel(String(node.data("group") || "").trim()) : "";
        node.data("renderLabel", groupLabel ? `${idLabel}\n${groupLabel}` : idLabel);
      });
      state.cy.nodes("[kind = 'unit']").forEach((node) => {
        node.data("renderLabel", String(node.data("label") || ""));
      });
    });
    state.cy.style().update();
  }

  function clearGraphFocus(shouldFit = false) {
    if (!state.cy) return;
    state.focusedElementId = "";
    state.cy.elements().removeClass("rg-dimmed rg-related rg-focused");
    state.cy.elements().unselect();
    updateNodeLabels();
    if (shouldFit) state.cy.animate({ fit: { eles: state.cy.elements(), padding: 42 }, duration: 260 });
  }

  function focusGraphElement(target, shouldFit = true) {
    if (!state.cy || !target) return;
    state.cy.elements().removeClass("rg-dimmed rg-related rg-focused");
    let keep = target;
    if (typeof target.isNode === "function" && target.isNode()) {
      const nodes = target.closedNeighborhood().nodes();
      const edges = state.cy.edges().filter((edge) => nodes.contains(edge.source()) && nodes.contains(edge.target()));
      keep = nodes.union(edges);
    } else if (typeof target.isEdge === "function" && target.isEdge()) {
      keep = target.union(target.connectedNodes());
    }
    state.cy.elements().difference(keep).addClass("rg-dimmed");
    keep.addClass("rg-related");
    target.addClass("rg-focused");
    state.focusedElementId = String(target.id() || "");
    updateNodeLabels();
    if (shouldFit) state.cy.animate({ fit: { eles: keep, padding: 92 }, duration: 320 });
  }

  function runLayout() {
    if (!state.cy) return;
    const name = ui.layout ? String(ui.layout.value || "cose") : "cose";
    const nodeCount = state.cy.nodes().length;
    const edgeCount = state.cy.edges().length;
    const dense = nodeCount > 120 || edgeCount > 420;
    const pad = Math.min(72, Math.max(24, Math.round(nodeCount * 0.26)));
    const cfg = {
      name,
      animate: "end",
      animationDuration: dense ? 260 : 340,
      fit: true,
      padding: pad,
      nodeDimensionsIncludeLabels: true,
      avoidOverlap: true,
    };
    if (name === "cose") {
      cfg.randomize = false;
      cfg.numIter = dense ? 1200 : 1800;
      cfg.idealEdgeLength = dense ? 82 : nodeCount > 60 ? 96 : 112;
      cfg.nodeRepulsion = dense ? 9200 : 12800;
      cfg.gravity = dense ? 0.3 : 0.22;
      cfg.componentSpacing = dense ? 74 : 96;
      cfg.nestingFactor = 0.95;
      cfg.edgeElasticity = dense ? 68 : 90;
    } else if (name === "concentric") {
      cfg.minNodeSpacing = dense ? 14 : 20;
      cfg.spacingFactor = dense ? 0.85 : 1.0;
      cfg.startAngle = -Math.PI / 2;
      cfg.sweep = Math.PI * 2;
      cfg.clockwise = true;
      cfg.avoidOverlap = true;
      cfg.concentric = (n) => {
        const d = n.data() || {};
        return Number(d.weighted_degree || d.degree || d.count || 0);
      };
      cfg.levelWidth = () => 5;
    } else if (name === "circle") {
      cfg.clockwise = true;
      cfg.sort = (a, b) => {
        const aw = Number(a.data("weighted_degree") || 0);
        const bw = Number(b.data("weighted_degree") || 0);
        return bw - aw;
      };
      cfg.spacingFactor = dense ? 0.78 : 0.92;
    } else if (name === "grid") {
      cfg.condense = true;
      cfg.avoidOverlap = true;
      cfg.avoidOverlapPadding = dense ? 5 : 8;
      cfg.spacingFactor = dense ? 0.75 : 0.9;
    }
    const layout = state.cy.layout(cfg);
    layout.one("layoutstop", () => {
      packDisconnectedComponents();
      clearGraphFocus(false);
      state.cy.fit(undefined, 42);
    });
    layout.run();
  }

  function applySearchFilter() {
    if (!state.cy || !ui.search) return;
    const q = String(ui.search.value || "").trim().toLowerCase();
    state.cy.elements().removeClass("rg-dimmed");
    state.focusedElementId = "";
    if (!q) {
      updateNodeLabels();
      return;
    }
    const matches = state.cy.nodes().filter((n) => {
      const d = n.data();
      return (
        String(d.id || "").toLowerCase().includes(q) ||
        String(d.unit || "").toLowerCase().includes(q) ||
        String(d.group || "").toLowerCase().includes(q)
      );
    });
    const keep = matches.union(matches.neighborhood());
    state.cy.elements().difference(keep).addClass("rg-dimmed");
    keep.addClass("rg-related");
    updateNodeLabels();
    if (matches.length) state.cy.animate({ fit: { eles: keep, padding: 92 }, duration: 260 });
  }

  function renderSelection(target) {
    if (!ui.selection) return;
    if (!target) {
      ui.selection.textContent = "—";
      return;
    }
    if (document.fullscreenElement !== ui.stage) {
      openInspector();
    }
    if (typeof target.isEdge === "function" && target.isEdge()) {
      const d = target.data();
      const edgeAvatar = String(d.avatar || "");
      const sourceAvatar = String(d.sourceAvatar || edgeAvatar);
      const targetAvatar = String(d.targetAvatar || edgeAvatar);
      const avatar = (src, fallbackIcon) => src
        ? `<img class="rg-edge-card__avatar" src="${escapeHtml(src)}" alt="" />`
        : `<span class="rg-edge-card__avatar rg-edge-card__avatar--empty"><i class="bi ${fallbackIcon}"></i></span>`;
      ui.selection.innerHTML = [
        `<div class="rg-edge-card__avatars">${avatar(sourceAvatar, "bi-person") }<span class="rg-edge-card__link"><i class="bi bi-arrow-left-right"></i></span>${avatar(targetAvatar, "bi-person")}</div>`,
        `<div><strong>Связь:</strong> ${escapeHtml(d.source || "—")} ↔ ${escapeHtml(d.target || "—")}</div>`,
        `<div><strong>Подразделение:</strong> ${escapeHtml(d.unit || "—")}</div>`,
        `<div><strong>Вес:</strong> ${Number(d.weight || 0)}</div>`,
        `<div><strong>Норм.вес:</strong> ${Number(d.norm || 0).toFixed(3)}</div>`,
        `<div><strong>Последняя активность:</strong> ${escapeHtml(d.recent || "—")}</div>`,
      ].join("");
      syncFullscreenPanels();
      return;
    }
    const d = target.data();
    if (String(d.kind || "") === "unit") {
      const avatar = String(d.avatar || "");
      ui.selection.innerHTML = [
        avatar ? `<img class="rg-unit-card__avatar" src="${escapeHtml(avatar)}" alt="" />` : `<div class="rg-unit-card__avatar rg-unit-card__avatar--empty"><i class="bi bi-building"></i></div>`,
        `<div><strong>Подразделение:</strong> ${escapeHtml(d.unit || d.label || "—")}</div>`,
        `<div class="small wp-subtle mt-1">Изображение загружается в разделе «Поиск онлайн».</div>`,
        `<div class="mt-2 d-flex gap-2">
          <button class="btn btn-outline-secondary btn-sm" id="rg-focus-neigh">Соседи</button>
          <button class="btn btn-outline-secondary btn-sm" id="rg-reset-filter">Сброс</button>
        </div>`,
      ].join("");
      const btnFocusUnit = $("rg-focus-neigh");
      const btnResetUnit = $("rg-reset-filter");
      if (btnFocusUnit) {
        btnFocusUnit.onclick = () => {
          const keep = target.closedNeighborhood();
          state.cy.elements().addClass("rg-dimmed");
          keep.removeClass("rg-dimmed");
        };
      }
      if (btnResetUnit) {
        btnResetUnit.onclick = () => state.cy.elements().removeClass("rg-dimmed");
      }
      syncFullscreenPanels();
      return;
    }
    const num = (v) => (Number.isFinite(Number(v)) ? String(Number(v)) : "—");
    ui.selection.innerHTML = [
      `<div><strong>ID:</strong> ${escapeHtml(d.id)}</div>`,
      `<div><strong>Подразделение:</strong> ${escapeHtml(d.unit || "—")}</div>`,
      `<div><strong>Группа:</strong> ${escapeHtml(d.group || "—")}</div>`,
      `<div><strong>Активность:</strong> ${num(d.count)}</div>`,
      `<div><strong>Degree:</strong> ${num(d.degree)}</div>`,
      `<div><strong>Weighted degree:</strong> ${num(d.weighted_degree)}</div>`,
      `<div><strong>Betweenness:</strong> ${Number(d.betweenness || 0).toFixed(3)}</div>`,
      `<div class="mt-2 d-flex gap-2">
        <button class="btn btn-outline-secondary btn-sm" id="rg-focus-neigh">Соседи</button>
        <button class="btn btn-outline-secondary btn-sm" id="rg-isolate-node">Изолировать</button>
        <button class="btn btn-outline-secondary btn-sm" id="rg-reset-filter">Сброс</button>
      </div>`,
    ].join("");
    const btnFocus = $("rg-focus-neigh");
    const btnIso = $("rg-isolate-node");
    const btnReset = $("rg-reset-filter");
    if (btnFocus) {
      btnFocus.onclick = () => {
        const keep = target.closedNeighborhood();
        state.cy.elements().addClass("rg-dimmed");
        keep.removeClass("rg-dimmed");
      };
    }
    if (btnIso) {
      btnIso.onclick = () => {
        state.cy.elements().addClass("rg-dimmed");
        target.removeClass("rg-dimmed");
      };
    }
    if (btnReset) {
      btnReset.onclick = () => state.cy.elements().removeClass("rg-dimmed");
    }
    syncFullscreenPanels();
  }

  function applyTheme() {
    if (!state.cy) return;
    state.cy.batch(() => {
      state.cy.nodes().forEach((n) => {
        const c = pickThemeNodeColor(n.data());
        n.data("nodeColor", c);
      });
      state.cy.edges().forEach((e) => {
        if (e.hasClass("rg-unit-link")) {
          e.data("edgeColor", "#9bb3e8");
          return;
        }
        const sourceData = e.source() ? e.source().data() : {};
        e.data("edgeColor", pickThemeNodeColor(sourceData));
      });
    });
    state.cy.style().update();
  }

  function ensureCyLibrary() {
    return typeof window.cytoscape === "function";
  }

  function scheduleCyResize() {
    if (!state.cy) return;
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        try {
          state.cy.resize();
          state.cy.fit(undefined, 28);
        } catch (_e) {
          /* ignore */
        }
      });
    });
  }

  function bindCanvasResizeObserver() {
    if (!ui.canvas || typeof ResizeObserver !== "function") return;
    if (resizeObserver) {
      try {
        resizeObserver.disconnect();
      } catch (_e) {
        /* ignore */
      }
    }
    resizeObserver = new ResizeObserver(() => {
      if (!state.active || !state.cy) return;
      scheduleCyResize();
    });
    resizeObserver.observe(ui.canvas);
  }

  function buildCy(data) {
    if (!ui.canvas) {
      showStatus("Контейнер графа не найден", true);
      return;
    }
    if (!ensureCyLibrary()) {
      showStatus("Cytoscape не подключён — обновите страницу (Ctrl+F5)", true);
      return;
    }
    const elements = makeCyElements(data);
    if (state.cy) {
      state.cy.elements().remove();
      state.cy.add(elements);
      runLayout();
      applyTheme();
      applySearchFilter();
      scheduleCyResize();
      return;
    }
    const dark = document.documentElement.getAttribute("data-wp-theme") === "dark";
    const labelColor = dark ? "#e2e8f0" : "#334155";
    const labelBg = dark ? "#182336" : "#ffffff";
    state.cy = window.cytoscape({
      container: ui.canvas,
      elements,
      minZoom: 0.3,
      maxZoom: 2.5,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(nodeColor)",
            label: "data(renderLabel)",
            "font-size": 13,
            "font-weight": 600,
            color: labelColor,
            "text-background-color": labelBg,
            "text-background-opacity": 0.92,
            "text-background-shape": "roundrectangle",
            "text-background-padding": 4,
            "text-outline-width": 0,
            "text-wrap": "wrap",
            "text-max-width": 116,
            "text-justification": "center",
            "text-valign": "bottom",
            "text-margin-y": 9,
            "line-height": 1.05,
            width: "mapData(weighted_degree, 0, 60, 18, 38)",
            height: "mapData(weighted_degree, 0, 60, 18, 38)",
            "border-width": 2.2,
            "border-color": dark ? "#233249" : "#ffffff",
          },
        },
        {
          selector: "node.rg-unit-hub",
          style: {
            "background-color": "data(nodeColor)",
            label: "data(label)",
            color: labelColor,
            "font-size": 12,
            "font-weight": 700,
            width: 52,
            height: 52,
            "border-width": 3,
            "border-color": "#ffffff",
            "border-opacity": 0.92,
            "text-wrap": "wrap",
            "text-max-width": 180,
            "text-background-color": labelBg,
            "text-background-opacity": 1,
            "text-background-shape": "roundrectangle",
            "text-background-padding": 5,
            "text-outline-width": 0,
          },
        },
        {
          selector: "node.rg-unit-hub[avatar != '']",
          style: {
            "background-image": "data(avatar)",
            "background-fit": "cover",
            "background-clip": "node",
            "background-opacity": 1,
          },
        },
        {
          selector: "node[kind = 'id'][avatar != '']",
          style: {
            "background-image": "data(avatar)",
            "background-fit": "cover",
            "background-clip": "node",
            "background-opacity": 1,
          },
        },
        {
          selector: "edge",
          style: {
            width: "mapData(weight, 1, 25, 0.8, 3.2)",
            "line-color": "data(edgeColor)",
            "curve-style": "bezier",
            "line-cap": "round",
            "line-opacity": "mapData(weight, 1, 25, 0.22, 0.68)",
            opacity: 0.92,
          },
        },
        {
          selector: "edge.rg-unit-link",
          style: {
            width: 1,
            opacity: 0.18,
            "line-style": "dashed",
            "line-color": "data(edgeColor)",
            "curve-style": "straight",
          },
        },
        {
          selector: ".rg-dimmed",
          style: {
            opacity: 0.035,
          },
        },
        {
          selector: "node.rg-related",
          style: {
            "border-width": 3,
            "border-color": "#dbeafe",
            "underlay-color": "#60a5fa",
            "underlay-opacity": 0.12,
            "underlay-padding": 7,
          },
        },
        {
          selector: "edge.rg-related",
          style: {
            opacity: 1,
            "line-opacity": 0.95,
            "z-index": 999,
          },
        },
        {
          selector: "node.rg-focused",
          style: {
            "border-width": 4,
            "border-color": "#f8fafc",
            "underlay-color": "#f59e0b",
            "underlay-opacity": 0.34,
            "underlay-padding": 11,
          },
        },
        {
          selector: ":selected",
          style: {
            "border-color": "#f59e0b",
            "line-color": "#f59e0b",
            "target-arrow-color": "#f59e0b",
          },
        },
      ],
    });
    runLayout();
    applyTheme();
    scheduleCyResize();
    state.cy.on("tap", "node, edge", (ev) => {
      renderSelection(ev.target);
      focusGraphElement(ev.target, true);
    });
    state.cy.on("tap", (ev) => {
      hideContextMenu();
      if (ev.target === state.cy) {
        renderSelection(null);
        clearGraphFocus(true);
      }
    });
    state.cy.on("mouseover", "node", (ev) => {
      state.hoveredNodeId = String(ev.target.id() || "");
      updateNodeLabels();
    });
    state.cy.on("mouseout", "node", () => {
      state.hoveredNodeId = "";
      updateNodeLabels();
    });
    state.cy.on("zoom", () => {
      clearTimeout(state.labelZoomTimer);
      state.labelZoomTimer = setTimeout(updateNodeLabels, 90);
    });
    state.cy.on("cxttap", "node", (ev) => {
      const target = ev.target;
      renderSelection(target);
      const nodeId = String(target.data("id") || "");
      showContextMenu(
        ev,
        [
          {
            label: "Показать соседей",
            action: () => {
              const keep = target.closedNeighborhood();
              state.cy.elements().addClass("rg-dimmed");
              keep.removeClass("rg-dimmed");
            },
          },
          {
            label: "Изолировать узел",
            action: () => {
              state.cy.elements().addClass("rg-dimmed");
              target.removeClass("rg-dimmed");
            },
          },
          {
            label: target.locked() ? "Снять фиксацию узла" : "Зафиксировать узел",
            action: () => {
              if (target.locked()) target.unlock();
              else target.lock();
            },
          },
          {
            label: "Скопировать ID",
            action: async () => {
              try {
                await navigator.clipboard.writeText(nodeId);
              } catch (_e) {
                // ignore
              }
            },
          },
          {
            label: "Сбросить фильтрацию",
            action: () => state.cy.elements().removeClass("rg-dimmed"),
          },
        ],
        target
      );
    });
    state.cy.on("cxttap", "edge", (ev) => {
      const target = ev.target;
      renderSelection(target);
      showContextMenu(
        ev,
        [
          {
            label: "Выделить концы связи",
            action: () => {
              state.cy.elements().addClass("rg-dimmed");
              target.connectedNodes().removeClass("rg-dimmed");
              target.removeClass("rg-dimmed");
            },
          },
          {
            label: "Сбросить фильтрацию",
            action: () => state.cy.elements().removeClass("rg-dimmed"),
          },
        ],
        target
      );
    });
  }

  function drawTimelineCanvas(canvas) {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const rect = canvas.getBoundingClientRect();
    const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    const w = Math.max(320, Math.round(rect.width));
    const h = Math.max(100, Math.round(rect.height));
    const bw = Math.round(w * dpr);
    const bh = Math.round(h * dpr);
    if (canvas.width !== bw) canvas.width = bw;
    if (canvas.height !== bh) canvas.height = bh;
    if (canvas.style.width !== `${w}px`) canvas.style.width = `${w}px`;
    if (canvas.style.height !== `${h}px`) canvas.style.height = `${h}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const buckets = state.timelineBuckets || [];
    if (!buckets.length) return;
    const vals = buckets.map((b) => Number(b.active_ids || 0));
    const max = Math.max(1, ...vals);
    ctx.strokeStyle = "rgba(59,130,246,0.95)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    vals.forEach((v, i) => {
      const x = 8 + (i * (w - 16)) / Math.max(1, vals.length - 1);
      const y = h - 8 - (v / max) * (h - 16);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    const visRaw =
      Number.isFinite(Number(state.timelineVisualIdx)) && vals.length
        ? Number(state.timelineVisualIdx)
        : Number(state.timelineIdx || 0);
    const vis = Math.max(0, Math.min(visRaw, vals.length - 1));
    const idx0 = Math.floor(vis);
    const idx1 = Math.min(vals.length - 1, idx0 + 1);
    const t = vis - idx0;
    const x0 = 8 + (idx0 * (w - 16)) / Math.max(1, vals.length - 1);
    const x1 = 8 + (idx1 * (w - 16)) / Math.max(1, vals.length - 1);
    const y0 = h - 8 - (vals[idx0] / max) * (h - 16);
    const y1 = h - 8 - (vals[idx1] / max) * (h - 16);
    const mx = x0 + (x1 - x0) * t;
    const my = y0 + (y1 - y0) * t;
    ctx.fillStyle = "#f59e0b";
    ctx.beginPath();
    ctx.arc(mx, my, 4, 0, Math.PI * 2);
    ctx.fill();
  }

  function drawTimeline() {
    drawTimelineCanvas(ui.timeline);
    drawTimelineCanvas(ui.fsTimeline);
  }

  function _animateTimelineCursor(targetIdx) {
    const to = Number(targetIdx || 0);
    const from = Number.isFinite(Number(state.timelineVisualIdx))
      ? Number(state.timelineVisualIdx)
      : Number(state.timelineIdx || 0);
    if (!Number.isFinite(to) || Math.abs(to - from) < 0.001) {
      state.timelineVisualIdx = to;
      drawTimeline();
      return;
    }
    if (state.timelineAnimFrame) {
      cancelAnimationFrame(state.timelineAnimFrame);
      state.timelineAnimFrame = null;
    }
    const start = performance.now();
    const dur = 260;
    const ease = (k) => 1 - Math.pow(1 - k, 3);
    const tick = (now) => {
      const p = Math.max(0, Math.min(1, (now - start) / dur));
      state.timelineVisualIdx = from + (to - from) * ease(p);
      drawTimeline();
      if (p < 1) {
        state.timelineAnimFrame = requestAnimationFrame(tick);
      } else {
        state.timelineVisualIdx = to;
        state.timelineAnimFrame = null;
      }
    };
    state.timelineAnimFrame = requestAnimationFrame(tick);
  }

  function updateCompareText(data) {
    if (!ui.compareLabel || !ui.compareStats) return;
    const cur = Array.isArray(data.current) ? data.current : [];
    const prev = Array.isArray(data.previous) ? data.previous : [];
    ui.compareLabel.textContent = `${fmtDateTime(data.prev_start)} — ${fmtDateTime(data.prev_end)} vs ${fmtDateTime(
      data.start
    )} — ${fmtDateTime(data.end)}`;
    const avg = (arr, key) => {
      if (!arr.length) return 0;
      return arr.reduce((s, x) => s + Number(x[key] || 0), 0) / arr.length;
    };
    const curActive = avg(cur, "active_ids");
    const prevActive = avg(prev, "active_ids");
    const curSess = avg(cur, "sessions");
    const prevSess = avg(prev, "sessions");
    ui.compareStats.textContent =
      `Средние активные ID: ${curActive.toFixed(1)} (${(curActive - prevActive).toFixed(1)} к прошлому), ` +
      `средние сеансы: ${curSess.toFixed(1)} (${(curSess - prevSess).toFixed(1)} к прошлому)`;
  }

  function updateCompositionMetrics(bucket) {
    const activeEl = $("rg-comp-active");
    const sessionsEl = $("rg-comp-sessions");
    const newEl = $("rg-comp-new");
    const goneEl = $("rg-comp-gone");
    const fsActiveEl = $("rg-fs-comp-active");
    const fsSessionsEl = $("rg-fs-comp-sessions");
    const fsNewEl = $("rg-fs-comp-new");
    const fsGoneEl = $("rg-fs-comp-gone");
    const setVals = (a, s, n, g, vals) => {
      if (!a || !s || !n || !g) return;
      a.textContent = vals.active;
      s.textContent = vals.sessions;
      n.textContent = vals.newv;
      g.textContent = vals.gone;
    };
    const setNumericVals = (vals) => {
      const str = {
        active: String(Math.round(vals.active || 0)),
        sessions: String(Math.round(vals.sessions || 0)),
        newv: String(Math.round(vals.newv || 0)),
        gone: String(Math.round(vals.gone || 0)),
      };
      setVals(activeEl, sessionsEl, newEl, goneEl, str);
      setVals(fsActiveEl, fsSessionsEl, fsNewEl, fsGoneEl, str);
    };
    if (!bucket) {
      if (state.compAnimFrame) {
        cancelAnimationFrame(state.compAnimFrame);
        state.compAnimFrame = null;
      }
      state.compValues = null;
      setVals(activeEl, sessionsEl, newEl, goneEl, { active: "—", sessions: "—", newv: "—", gone: "—" });
      setVals(fsActiveEl, fsSessionsEl, fsNewEl, fsGoneEl, { active: "—", sessions: "—", newv: "—", gone: "—" });
      return;
    }
    const to = {
      active: Number(bucket.active_ids || 0),
      sessions: Number(bucket.sessions || 0),
      newv: Number(bucket.new_ids || 0),
      gone: Number(bucket.gone_ids || 0),
    };
    const from = state.compValues
      ? {
          active: Number(state.compValues.active || 0),
          sessions: Number(state.compValues.sessions || 0),
          newv: Number(state.compValues.newv || 0),
          gone: Number(state.compValues.gone || 0),
        }
      : to;
    if (state.compAnimFrame) {
      cancelAnimationFrame(state.compAnimFrame);
      state.compAnimFrame = null;
    }
    const start = performance.now();
    const dur = 260;
    const ease = (k) => 1 - Math.pow(1 - k, 3);
    const tick = (now) => {
      const p = Math.max(0, Math.min(1, (now - start) / dur));
      const e = ease(p);
      const vals = {
        active: from.active + (to.active - from.active) * e,
        sessions: from.sessions + (to.sessions - from.sessions) * e,
        newv: from.newv + (to.newv - from.newv) * e,
        gone: from.gone + (to.gone - from.gone) * e,
      };
      setNumericVals(vals);
      if (p < 1) {
        state.compAnimFrame = requestAnimationFrame(tick);
      } else {
        state.compAnimFrame = null;
        setNumericVals(to);
      }
    };
    state.compValues = { ...to };
    setNumericVals(from);
    state.compAnimFrame = requestAnimationFrame(tick);
  }

  function bucketHasData(bucket) {
    if (!bucket) return false;
    return Number(bucket.sessions || 0) > 0 || Number(bucket.active_ids || 0) > 0;
  }

  function findLastActiveBucketIdx(buckets) {
    if (!Array.isArray(buckets) || !buckets.length) return 0;
    for (let i = buckets.length - 1; i >= 0; i -= 1) {
      if (bucketHasData(buckets[i])) return i;
    }
    return buckets.length - 1;
  }

  function findBestBucketIdx(buckets) {
    if (!Array.isArray(buckets) || !buckets.length) return 0;
    let bestIdx = 0;
    let bestScore = -1;
    buckets.forEach((bucket, idx) => {
      const score = Number(bucket.sessions || 0) * 10 + Number(bucket.active_ids || 0);
      if (score > bestScore) {
        bestScore = score;
        bestIdx = idx;
      }
    });
    return bestIdx;
  }

  function applyGraphTimeRange(params) {
    params.delete("minutes");
    if (state.timelineManual && state.selectedBucketRange) {
      params.set("start", String(state.selectedBucketRange.start));
      params.set("end", String(state.selectedBucketRange.end));
      params.delete("minutes");
      params.delete("days");
      return "bucket";
    }
    const range = readRange();
    if (range) {
      params.set("start", range.start);
      params.set("end", range.end);
      params.delete("days");
      return "custom";
    }
    params.delete("start");
    params.delete("end");
    params.set("days", String(getTimelineDays()));
    return "days";
  }

  function applyBucketSelectionByIdx(idx, manual) {
    const i = Math.max(0, Math.min(Number(idx || 0), Math.max(0, state.timelineBuckets.length - 1)));
    state.timelineIdx = i;
    if (manual) state.timelineManual = true;
    if (ui.timeSlider) ui.timeSlider.value = String(i);
    if (ui.fsTimeSlider) ui.fsTimeSlider.value = String(i);
    _animateTimelineCursor(i);
    const b = state.timelineBuckets[i] || null;
    state.selectedBucketRange = b ? { start: b.start, end: b.end } : null;
    if (b && b.end) state.dynamicCursorTs = String(b.end);
    if (ui.timeLabel) ui.timeLabel.textContent = b ? `${b.start} — ${b.end}` : "—";
    if (ui.fsTimeLabel) ui.fsTimeLabel.textContent = b ? `${b.start} — ${b.end}` : "—";
    if (ui.composition) {
      ui.composition.textContent = b
        ? `Активных ID: ${b.active_ids}, сеансов: ${b.sessions}, новые: ${b.new_ids}, ушли: ${b.gone_ids}`
        : "—";
    }
    if (ui.fsComposition) {
      ui.fsComposition.textContent = b
        ? `Активных ID: ${b.active_ids}, сеансов: ${b.sessions}, новые: ${b.new_ids}, ушли: ${b.gone_ids}`
        : "—";
    }
    if (ui.compMetrics) {
      ui.compMetrics.classList.remove("rg-comp-anim");
      requestAnimationFrame(() => ui.compMetrics && ui.compMetrics.classList.add("rg-comp-anim"));
    }
    if (ui.fsCompMetrics) {
      ui.fsCompMetrics.classList.remove("rg-comp-anim");
      requestAnimationFrame(() => ui.fsCompMetrics && ui.fsCompMetrics.classList.add("rg-comp-anim"));
    }
    if (ui.composition) {
      ui.composition.classList.remove("rg-comp-text-anim");
      requestAnimationFrame(() => ui.composition && ui.composition.classList.add("rg-comp-text-anim"));
    }
    if (ui.fsComposition) {
      ui.fsComposition.classList.remove("rg-comp-text-anim");
      requestAnimationFrame(() => ui.fsComposition && ui.fsComposition.classList.add("rg-comp-text-anim"));
    }
    updateCompositionMetrics(b);
    syncRangeLabel();
  }

  function stopPlayback() {
    if (state.playbackTimer) clearInterval(state.playbackTimer);
    state.playbackTimer = null;
    state.playbackActive = false;
    if (ui.playToggle) ui.playToggle.textContent = "Play";
    if (ui.fsPlayToggle) ui.fsPlayToggle.textContent = "Play";
  }

  function stepTimeline(delta) {
    const n = state.timelineBuckets.length;
    if (!n) return;
    const next = Math.max(0, Math.min(n - 1, state.timelineIdx + delta));
    if (next === state.timelineIdx) return;
    applyBucketSelectionByIdx(next, true);
    if (isDynamicMode()) {
      loadDynamicWindow().catch((e) => showStatus(`Dynamic window: ${e.message || e}`, true));
      loadMlRisk().catch(() => {});
    } else {
      loadGraph().catch((e) => showStatus(`Graph: ${e.message || e}`, true));
      loadMlRisk().catch(() => {});
    }
  }

  function startPlayback() {
    stopPlayback();
    state.playbackActive = true;
    if (ui.playToggle) ui.playToggle.textContent = "Pause";
    if (ui.fsPlayToggle) ui.fsPlayToggle.textContent = "Pause";
    const speed = Math.max(0.25, Number(state.playbackSpeed || 1));
    const intervalMs = Math.max(350, Math.round(1300 / speed));
    state.playbackTimer = setInterval(() => {
      if (document.hidden) return;
      const n = state.timelineBuckets.length;
      if (!n) return;
      if (state.timelineIdx >= n - 1) {
        stopPlayback();
        return;
      }
      stepTimeline(1);
    }, intervalMs);
  }

  async function loadGraph() {
    const params = buildGraphParams();
    const rangeMode = applyGraphTimeRange(params);
    const data = await apiGet(`/api/analysis/graph?${params.toString()}`);
    state.graphData = data;
    if (ui.empty) ui.empty.style.display = data.nodes && data.nodes.length ? "none" : "";
    updateMetrics(data);
    buildCy(data);
    updateNodeLabels();
    applySearchFilter();
    if (ui.statusRange && data.start && data.end) {
      ui.statusRange.textContent = `${data.start} — ${data.end}`;
    }
    if (!(data.nodes && data.nodes.length) && rangeMode === "bucket") {
      showStatus("В выбранном интервале нет данных. Сдвиньте ползунок таймлайна или выберите больший период.", true);
    } else {
      showStatus(`Узлов: ${(data.nodes || []).length}, связей: ${(data.edges || []).length}`);
    }
  }

  async function loadTimeline() {
    const params = buildGraphParams();
    params.delete("minutes");
    params.set("days", String(getTimelineDays()));
    const timelineUrl = isDynamicMode()
      ? `/api/analysis/graph-dynamic/timeline?${params.toString()}`
      : `/api/analysis/graph-timeline?${params.toString()}`;
    const data = await apiGet(timelineUrl);
    const buckets = Array.isArray(data.buckets) ? data.buckets : [];
    state.timelineBuckets = buckets;
    state.timelineRange =
      data && data.start && data.end ? { start: String(data.start), end: String(data.end) } : null;
    if (data && data.server_ts) state.dynamicSinceTs = String(data.server_ts || "");
    if (!buckets.length) {
      state.timelineIdx = 0;
    } else if (!state.timelineManual) {
      state.timelineIdx = findLastActiveBucketIdx(buckets);
      if (!bucketHasData(buckets[state.timelineIdx])) {
        state.timelineIdx = findBestBucketIdx(buckets);
      }
    } else {
      state.timelineIdx = Math.min(state.timelineIdx, buckets.length - 1);
    }
    if (ui.timeSlider) {
      ui.timeSlider.max = String(Math.max(0, buckets.length - 1));
      ui.timeSlider.value = String(state.timelineIdx);
    }
    if (ui.fsTimeSlider) {
      ui.fsTimeSlider.max = String(Math.max(0, buckets.length - 1));
      ui.fsTimeSlider.value = String(state.timelineIdx);
    }
    if (!Number.isFinite(Number(state.timelineVisualIdx)) || !state.timelineManual) {
      state.timelineVisualIdx = state.timelineIdx;
    } else {
      state.timelineVisualIdx = Math.max(0, Math.min(Number(state.timelineVisualIdx), Math.max(0, buckets.length - 1)));
    }
    applyBucketSelectionByIdx(state.timelineIdx, false);
  }

  async function loadDynamicWindow() {
    const params = buildGraphParams();
    applyGraphTimeRange(params);
    const b = state.timelineBuckets[state.timelineIdx] || null;
    const cursorTs = (b && b.end) || state.dynamicCursorTs;
    const manual = state.timelineManual && state.selectedBucketRange;
    if (manual && cursorTs) {
      params.set("cursor_ts", String(cursorTs));
      const start = new Date(String(manual.start).replace(" ", "T"));
      const end = new Date(String(manual.end).replace(" ", "T"));
      params.set("window_minutes", String(Math.max(5, Math.round((end - start) / 60000) || 5)));
    }
    const endpoint = manual ? "graph-dynamic/window" : "graph";
    const data = await apiGet(`/api/analysis/${endpoint}?${params.toString()}`);
    state.graphData = data;
    if (ui.empty) ui.empty.style.display = data.nodes && data.nodes.length ? "none" : "";
    updateMetrics(data);
    buildCy(data);
    applySearchFilter();
    if (ui.statusRange && data.start && data.end) {
      ui.statusRange.textContent = `${data.start} — ${data.end}`;
    }
    showStatus(`Узлов: ${(data.nodes || []).length}, связей: ${(data.edges || []).length} · динамика`);
  }

  async function loadDynamicLiveIncremental() {
    if (!isDynamicMode()) return;
    if (!(ui.live && ui.live.checked)) return;
    const params = buildGraphParams();
    params.delete("minutes");
    params.set("days", String(getTimelineDays()));
    if (state.dynamicSinceTs) params.set("since_ts", state.dynamicSinceTs);
    const data = await apiGet(`/api/analysis/graph-dynamic/live?${params.toString()}`);
    if (data && data.server_ts) state.dynamicSinceTs = String(data.server_ts || "");
    const hasUpdates = !!(data && Array.isArray(data.new_buckets) && data.new_buckets.length);
    if (!hasUpdates) return;
    await loadTimeline();
    if (!state.timelineManual) {
      applyBucketSelectionByIdx(Math.max(0, state.timelineBuckets.length - 1), false);
      await loadDynamicWindow();
      await loadMlRisk();
    }
  }

  async function loadCompare() {
    const params = buildGraphParams();
    params.delete("minutes");
    params.set("days", String(getTimelineDays()));
    const data = await apiGet(`/api/analysis/graph-compare?${params.toString()}`);
    state.compareData = data;
    updateCompareText(data);
  }

  function buildMlPayload() {
    const params = buildGraphParams();
    const out = {};
    for (const [k, v] of params.entries()) out[k] = v;
    const b = state.selectedBucketRange;
    if (b && b.start && b.end) {
      out.start = b.start;
      out.end = b.end;
    }
    const cfgWindow = Number(ui.mlCfgWindow ? ui.mlCfgWindow.value : 0) || 0;
    const fallbackWindow = Number(ui.minutes ? ui.minutes.value : 60) || 60;
    out.window_minutes = Math.max(5, cfgWindow || fallbackWindow);
    return out;
  }

  function pad2(n) {
    return String(n).padStart(2, "0");
  }

  function toSqlDateTime(dt) {
    return `${dt.getFullYear()}-${pad2(dt.getMonth() + 1)}-${pad2(dt.getDate())} ${pad2(dt.getHours())}:${pad2(
      dt.getMinutes()
    )}:${pad2(dt.getSeconds())}`;
  }

  function parseSqlDateTime(value) {
    const raw = String(value || "").trim().replace("T", " ");
    if (!raw) return null;
    const dt = new Date(raw);
    return Number.isNaN(dt.getTime()) ? null : dt;
  }

  function getFullReportMonthRange() {
    const buckets = state.timelineBuckets || [];
    let ref = null;
    for (let i = buckets.length - 1; i >= 0; i -= 1) {
      ref =
        parseSqlDateTime(buckets[i].end) ||
        parseSqlDateTime(buckets[i].start);
      if (ref) break;
    }
    const range = readRange();
    const bucket = state.selectedBucketRange;
    if (!ref) {
      ref =
        parseSqlDateTime(bucket && bucket.end) ||
        parseSqlDateTime(range && range.end) ||
        parseSqlDateTime(range && range.start) ||
        new Date();
    }
    const year = ref.getFullYear();
    const month = ref.getMonth();
    const start = new Date(year, month, 1, 0, 0, 0);
    const end = new Date(year, month + 1, 0, 23, 59, 59);
    return {
      start: toSqlDateTime(start),
      end: toSqlDateTime(end),
      report_month: `${year}-${pad2(month + 1)}`,
    };
  }

  function buildFullReportPayload() {
    const monthRange = getFullReportMonthRange();
    return {
      start: monthRange.start,
      end: monthRange.end,
      report_month: monthRange.report_month,
    };
  }

  function safeReportNamePart(value, fallback) {
    const cleaned = String(value || "")
      .replace(/[^\w\u0400-\u04FF-]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 80);
    return cleaned || fallback;
  }

  function buildFullReportFilename(payload) {
    const month = safeReportNamePart(String(payload.report_month || payload.start || "month").slice(0, 7), "month");
    return `full_radio_report_${month}.docx`;
  }

  async function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const res = String(reader.result || "");
        resolve(res.includes(",") ? res.split(",", 1)[1] : res);
      };
      reader.onerror = () => reject(new Error("Не удалось прочитать PNG графа"));
      reader.readAsDataURL(blob);
    });
  }

  async function captureGraphPngBase64() {
    if (!state.cy) return "";
    try {
      const png = state.cy.png({ output: "blob-promise", full: true, scale: 2, bg: "#0b1220" });
      const blob = await Promise.resolve(png);
      if (!blob) return "";
      return await blobToBase64(blob);
    } catch (_e) {
      return "";
    }
  }

  async function exportFullReport() {
    if (!ui.fullReportBtn) return;
    const payload = buildFullReportPayload();
    const oldHtml = ui.fullReportBtn.innerHTML;
    ui.fullReportBtn.disabled = true;
    ui.fullReportBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Отчёт';
    showStatus("Подготовка снимка графа…");
    try {
      const graphPng = await captureGraphPngBase64();
      if (graphPng) payload.graph_png_base64 = graphPng;
      showStatus("Полный отчёт поставлен в очередь…");
      const queued = await apiPost("/api/analysis/full-report/export-job", payload);
      if (!queued || !queued.job_id) throw new Error("Сервер не вернул job_id");
      await waitExportJob(queued.job_id, (msg) => showStatus(msg));
      await downloadExportJob(queued.job_id, buildFullReportFilename(payload));
      showStatus("Полный DOCX отчёт готов.");
    } catch (e) {
      showStatus(`Ошибка полного отчёта: ${e.message || e}`, true);
    } finally {
      ui.fullReportBtn.disabled = false;
      ui.fullReportBtn.innerHTML = oldHtml;
    }
  }

  function readMlSettingsFromUi() {
    const window_minutes = Math.max(5, Math.min(720, Number(ui.mlCfgWindow ? ui.mlCfgWindow.value : 60) || 60));
    const train_epochs = Math.max(5, Math.min(1000, Number(ui.mlCfgEpochs ? ui.mlCfgEpochs.value : 60) || 60));
    const train_lr = Math.max(0.00001, Math.min(0.1, Number(ui.mlCfgLr ? ui.mlCfgLr.value : 0.001) || 0.001));
    const retrain_min_samples = Math.max(10, Math.min(10000, Number(ui.mlCfgRetrainMin ? ui.mlCfgRetrainMin.value : 30) || 30));
    const retrain_step = Math.max(1, Math.min(1000, Number(ui.mlCfgRetrainStep ? ui.mlCfgRetrainStep.value : 10) || 10));
    const auto_activate = !!(ui.mlCfgAutoActivate && ui.mlCfgAutoActivate.checked);
    return { window_minutes, train_epochs, train_lr, retrain_min_samples, retrain_step, auto_activate };
  }

  function applyMlSettingsToUi(settings) {
    const s = settings || {};
    if (ui.mlCfgWindow) ui.mlCfgWindow.value = String(Number(s.window_minutes || 60));
    if (ui.mlCfgEpochs) ui.mlCfgEpochs.value = String(Number(s.train_epochs || 60));
    if (ui.mlCfgLr) ui.mlCfgLr.value = String(Number(s.train_lr || 0.001));
    if (ui.mlCfgRetrainMin) ui.mlCfgRetrainMin.value = String(Number(s.retrain_min_samples || 30));
    if (ui.mlCfgRetrainStep) ui.mlCfgRetrainStep.value = String(Number(s.retrain_step || 10));
    if (ui.mlCfgAutoActivate) ui.mlCfgAutoActivate.checked = !!s.auto_activate;
  }

  function renderMlRisk(data) {
    const ml = data && data.ml_risk ? data.ml_risk : null;
    state.mlRisk = ml;
    state.mlPredictionId = Number(data && data.prediction_id ? data.prediction_id : 0);
    if (!ml) {
      if (ui.mlPrediction) ui.mlPrediction.textContent = "—";
      if (ui.mlReasons) ui.mlReasons.textContent = "—";
      if (ui.mlHotspots) ui.mlHotspots.textContent = "—";
      if (ui.mMlRisk) ui.mMlRisk.textContent = "0% (NONE)";
      syncFullscreenPanels();
      return;
    }
    const scorePct = Math.max(0, Math.min(100, Math.round(Number(ml.probability || 0) * 100)));
    const label = String(ml.top_label || "none");
    const modelVersion = String(ml.model_version || "");
    if (ui.mlPrediction) {
      ui.mlPrediction.textContent = `${scorePct}% • ${label}${modelVersion ? ` • ${modelVersion}` : ""}`;
    }
    const reasons = Array.isArray(ml.reasons) ? ml.reasons : [];
    if (ui.mlReasons) {
      const msg = reasons
        .slice(0, 5)
        .map((r) => String(r.reason || r.label || r.feature || ""))
        .filter(Boolean)
        .join("; ");
      ui.mlReasons.textContent = msg || "Причины не определены";
    }
    const hotspots = Array.isArray(ml.hotspots) ? ml.hotspots : [];
    if (ui.mlHotspots) {
      ui.mlHotspots.textContent = hotspots.length
        ? hotspots
            .slice(0, 6)
            .map((h) => `${h.kind}:${h.name} (${Number(h.contribution || 0).toFixed(1)}%)`)
            .join(", ")
        : "Hotspots не выявлены";
    }
    if (ui.mMlRisk) {
      ui.mMlRisk.textContent = `${scorePct}% (${label.toUpperCase()})`;
    }
    syncFullscreenPanels();
  }

  function renderForecast(data) {
    const forecast = data && data.forecast ? data.forecast : null;
    state.forecast = forecast;
    const setText = (el, txt) => {
      if (el) el.textContent = txt;
    };
    if (!forecast) {
      setText(ui.forecastSummary, "—");
      setText(ui.forecastReliability, "Надёжность: —");
      setText(ui.forecastH30, "H30: —");
      setText(ui.forecastH60, "H60: —");
      setText(ui.forecastH120, "H120: —");
      syncFullscreenPanels();
      return;
    }
    const h = forecast.horizons || {};
    const fmt = (x) => {
      const top = x && x.top1 ? x.top1 : null;
      if (!top) return "—";
      const pct = Math.round(Math.max(0, Math.min(1, Number(top.probability || 0))) * 100);
      return `${String(top.label || "none")} (${pct}%)`;
    };
    const reliability = String(forecast.reliability || "low");
    const source = String(forecast.source || "forecast_models");
    const sourceTxt = source === "fallback_nowcast" ? " (fallback from current ML)" : "";
    setText(ui.forecastSummary, `Top-1: H30 ${fmt(h["30"])} | H60 ${fmt(h["60"])} | H120 ${fmt(h["120"])}`);
    setText(ui.forecastReliability, `Надёжность: ${reliability}${sourceTxt}`);
    setText(ui.forecastH30, `H30: ${fmt(h["30"])}`);
    setText(ui.forecastH60, `H60: ${fmt(h["60"])}`);
    setText(ui.forecastH120, `H120: ${fmt(h["120"])}`);
    syncFullscreenPanels();
  }

  async function loadMlRisk() {
    if (!ML_UI_ENABLED) return;
    const payload = buildMlPayload();
    const data = await apiPost("/api/analysis/ml/predict", payload);
    renderMlRisk(data || {});
    try {
      const forecastData = await apiPost("/api/analysis/ml/predict-forecast", payload);
      renderForecast(forecastData || {});
    } catch (_e) {
      renderForecast(null);
    }
  }

  async function submitMlTag() {
    const label = window.prompt("Введите тег события (класс):", "");
    if (!label) return;
    const description = window.prompt("Описание события (опционально):", "") || "";
    const b = state.selectedBucketRange;
    if (!b || !b.start || !b.end) {
      showStatus("Для тега выбери окно на динамике (ползунок).", true);
      return;
    }
    await apiPost("/api/analysis/ml/event-tag", {
      start_ts: b.start,
      end_ts: b.end,
      label: String(label).trim(),
      tag: String(label).trim(),
      description: String(description).trim(),
      status: "validated",
    });
    showStatus("Тег события сохранён.", false);
  }

  async function submitMlMinuteTag() {
    const label = window.prompt("Введите тег события для текущей минуты:", "");
    if (!label) return;
    const description = window.prompt("Описание события (опционально):", "") || "";
    const b = state.selectedBucketRange;
    if (!b || !b.end) {
      showStatus("Выбери метку времени на динамике.", true);
      return;
    }
    const endDt = new Date(String(b.end).replace(" ", "T"));
    const startDt = Number.isNaN(endDt.getTime()) ? new Date() : new Date(endDt.getTime() - 60 * 1000);
    const toSql = (d) => {
      const pad = (n) => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(
        d.getSeconds()
      )}`;
    };
    await apiPost("/api/analysis/ml/event-tag", {
      start_ts: toSql(startDt),
      end_ts: toSql(endDt),
      label: String(label).trim(),
      tag: String(label).trim(),
      description: String(description).trim(),
      status: "validated",
      granularity: "minute",
    });
    showStatus("Минутный тег сохранён.", false);
  }

  async function submitMlFeedback(isPositive) {
    if (!state.mlPredictionId) {
      showStatus("Сначала получи ML-прогноз для текущего окна.", true);
      return;
    }
    let corrected = "";
    if (!isPositive) {
      corrected = window.prompt("Укажи корректный класс события:", "") || "";
    }
    await apiPost("/api/analysis/ml/feedback", {
      prediction_id: state.mlPredictionId,
      feedback_label: isPositive ? "confirmed" : "false_positive",
      corrected_label: corrected.trim(),
    });
    showStatus(isPositive ? "Feedback: прогноз подтверждён." : "Feedback: ложный прогноз сохранён.", false);
  }

  async function runMlDatasetBuild() {
    const payload = buildMlPayload();
    let data = null;
    try {
      data = await apiPost("/api/analysis/ml/dataset-build-forecast", payload);
    } catch (_e) {
      data = await apiPost("/api/analysis/ml/dataset-build", payload);
    }
    const inserted = Number(data && data.inserted ? data.inserted : 0);
    const manual = Number(data && data.manual_labeled ? data.manual_labeled : 0);
    const auto = Number(data && data.auto_labeled ? data.auto_labeled : 0);
    const expanded = Boolean(data && data.expanded_range);
    const periodNote =
      expanded && data && data.start && data.end
        ? ` Диапазон авто-расширен: ${String(data.start)} - ${String(data.end)}.`
        : "";
    showStatus(
      `ML-датасет собран: окон=${inserted}, ручных меток=${manual}, auto=${auto}.${periodNote}`,
      false
    );
  }

  async function runMlTrain() {
    const s = readMlSettingsFromUi();
    let data = null;
    try {
      data = await apiPost("/api/analysis/ml/train-forecast", {
        epochs: s.train_epochs,
        lr: s.train_lr,
        activate: s.auto_activate,
      });
    } catch (_e) {
      data = await apiPost("/api/analysis/ml/train", {
        epochs: s.train_epochs,
        lr: s.train_lr,
        activate: s.auto_activate,
      });
    }
    const modelVersion = String((data && data.model_version) || "").trim();
    const isActive = Boolean(data && data.active);
    showStatus(
      isActive
        ? `ML-модель обучена и активирована: ${modelVersion || "—"}.`
        : `ML-модель обучена: ${modelVersion || "—"}. Активируй её вручную в панели.`,
      false
    );
    await loadMlRisk();
    await loadMlModelStatus();
  }

  async function saveMlSettings() {
    const s = readMlSettingsFromUi();
    const data = await apiPost("/api/analysis/ml/settings", s);
    state.mlSettings = data && data.settings ? data.settings : s;
    applyMlSettingsToUi(state.mlSettings);
    showStatus("Настройки ML сохранены.", false);
  }

  async function loadMlSettings() {
    if (!ML_UI_ENABLED) return;
    const data = await apiGet("/api/analysis/ml/settings");
    state.mlSettings = data && data.settings ? data.settings : null;
    applyMlSettingsToUi(state.mlSettings || {});
  }

  async function activateMlModelFromSelect() {
    if (!ui.mlModelSelect) return;
    const modelVersion = String(ui.mlModelSelect.value || "").trim();
    if (!modelVersion) {
      showStatus("Выбери модель для активации.", true);
      return;
    }
    await apiPost("/api/analysis/ml/model-activate", { model_version: modelVersion });
    showStatus(`Активирована модель: ${modelVersion}`, false);
    await loadMlModelStatus();
    await loadMlRisk();
  }

  function renderMlModelStatus(data) {
    const active = data && data.active_model ? data.active_model : null;
    const diagnostics = data && data.diagnostics ? data.diagnostics : {};
    const models = Array.isArray(data && data.models ? data.models : []) ? data.models : [];
    const settings = data && data.settings ? data.settings : null;
    state.mlModels = models;
    if (settings) {
      state.mlSettings = settings;
      applyMlSettingsToUi(settings);
    }
    if (ui.mlModelActive) {
      ui.mlModelActive.textContent = active
        ? `Активная модель: ${String(active.model_version || "—")}`
        : "Активная модель: отсутствует";
    }
    if (ui.mlModelMetrics) {
      const m = (active && active.metrics) || {};
      const acc = Number(m.val_accuracy || 0);
      const f1 = Number(m.val_f1_macro || 0);
      ui.mlModelMetrics.textContent = active
        ? `Метрики: acc=${acc.toFixed(3)}, f1=${f1.toFixed(3)}`
        : "Метрики: —";
    }
    if (ui.mlModelDiagnostics) {
      const samples = Number(diagnostics.pending_validated_samples || 0);
      const retrain = diagnostics.retrain_recommended ? "да" : "нет";
      ui.mlModelDiagnostics.textContent = `Диагностика: валидных=${samples}, retrain=${retrain}`;
    }
    if (ui.mlModelRuns) {
      ui.mlModelRuns.textContent = models.length
        ? `Последние модели: ${models.slice(0, 4).map((m) => String(m.model_version || "—")).join(", ")}`
        : "Последние модели: —";
    }
    if (ui.mlModelSelect) {
      const prev = String(ui.mlModelSelect.value || "");
      ui.mlModelSelect.innerHTML = "";
      if (!models.length) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "Нет обученных моделей";
        ui.mlModelSelect.appendChild(opt);
      } else {
        models.forEach((m) => {
          const mv = String(m.model_version || "");
          const opt = document.createElement("option");
          opt.value = mv;
          opt.textContent = `${mv}${m.is_active ? " (active)" : ""}`;
          ui.mlModelSelect.appendChild(opt);
        });
      }
      if (prev && models.some((m) => String(m.model_version || "") === prev)) {
        ui.mlModelSelect.value = prev;
      } else if (active && active.model_version) {
        ui.mlModelSelect.value = String(active.model_version);
      }
    }
    syncFullscreenPanels();
  }

  async function loadMlModelStatus() {
    if (!ML_UI_ENABLED) return;
    const data = await apiGet("/api/analysis/ml/model-status");
    renderMlModelStatus(data || {});
  }

  async function refresh(opts = {}) {
    if (!state.active) return;
    if (state.loading) {
      state.queuedRefresh = opts;
      return;
    }
    const animatePeriod = !!opts.animatePeriod;
    state.loading = true;
    if (animatePeriod) {
      setPeriodTransition(true);
      await new Promise((resolve) => setTimeout(resolve, 90));
    }
    if (ui.loading) ui.loading.style.display = "";
    syncRangeLabel();
    try {
      if (ML_UI_ENABLED) {
        await loadMlSettings();
      }
      await loadTimeline();
      if (isDynamicMode()) {
        await Promise.all([loadDynamicWindow(), loadCompare()]);
      } else {
        await Promise.all([loadGraph(), loadCompare()]);
      }
      await loadMlRisk();
      await loadMlModelStatus();
      updateLiveBadge();
    } catch (e) {
      console.error("Radio graph refresh failed", e);
      showStatus(`Ошибка: ${e.message || e}`, true);
    } finally {
      if (ui.loading) ui.loading.style.display = "none";
      if (animatePeriod) {
        requestAnimationFrame(() => setPeriodTransition(false));
      }
      state.loading = false;
      if (state.queuedRefresh) {
        const queued = state.queuedRefresh;
        state.queuedRefresh = null;
        refresh(queued);
      }
    }
  }

  function scheduleRefresh(delayMs) {
    clearTimeout(state.refreshDebounce);
    state.refreshDebounce = setTimeout(() => {
      refresh();
    }, Math.max(0, delayMs || 0));
  }

  function startPolling() {
    stopPolling();
    state.timer = setInterval(() => {
      if (!state.active) return;
      if (document.hidden) return;
      if (!ui.auto || !ui.auto.checked) return;
      if (isDynamicMode()) {
        loadDynamicLiveIncremental()
          .then(() => {
            state.dynamicErrorStreak = 0;
          })
          .catch((e) => {
            state.dynamicErrorStreak += 1;
            showStatus(`LIVE: ${e.message || e}`, true);
            if (state.dynamicErrorStreak >= 3 && ui.mode) {
              ui.mode.value = "static";
              if (ui.fsMode) ui.fsMode.value = "static";
              updateLiveBadge();
              showStatus("Dynamic API недоступен, выполнен авто-фолбэк в статический режим.", true);
              state.dynamicErrorStreak = 0;
              startPolling();
              refresh();
            }
          });
      } else {
        refresh();
      }
    }, isDynamicMode() ? state.livePollMs : 120000);
  }

  function stopPolling() {
    if (state.timer) clearInterval(state.timer);
    state.timer = null;
  }

  function selectPeriod(value) {
    const days = String(value || "1");
    [ui.period, ui.fsPeriod].forEach((group) => {
      if (!group) return;
      group.querySelectorAll("[data-days]").forEach((button) => {
        const active = button.getAttribute("data-days") === days;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", String(active));
      });
    });
    [ui.start, ui.end, ui.fsStart, ui.fsEnd].forEach((input) => { if (input) input.value = ""; });
    stopPlayback();
    state.timelineManual = false;
    state.selectedBucketRange = null;
    refresh({ animatePeriod: true });
  }

  function bindControls() {
    const onRefreshInput = () => scheduleRefresh(250);
    [ui.scope, ui.unitQuery, ui.groupQuery, ui.start, ui.end, ui.minWeight, ui.clusterBy, ui.maxNodesMode, ui.mode]
      .forEach((el) => {
        if (el) el.addEventListener("change", onRefreshInput);
      });
    if (ui.includeOther) ui.includeOther.addEventListener("change", onRefreshInput);
    if (ui.live) {
      ui.live.addEventListener("change", () => {
        updateLiveBadge();
        if (ui.fsLive) ui.fsLive.checked = !!ui.live.checked;
      });
    }
    if (ui.fsMode) {
      ui.fsMode.addEventListener("change", () => {
        if (ui.mode) ui.mode.value = ui.fsMode.value;
        state.timelineManual = false;
        updateLiveBadge();
        startPolling();
        refresh();
      });
    }
    if (ui.fsLive) {
      ui.fsLive.addEventListener("change", () => {
        if (ui.live) ui.live.checked = !!ui.fsLive.checked;
        updateLiveBadge();
      });
    }
    if (ui.mode) {
      ui.mode.addEventListener("change", () => {
        if (ui.fsMode) ui.fsMode.value = ui.mode.value;
        state.timelineManual = false;
        updateLiveBadge();
        startPolling();
      });
    }
    if (ui.layout) {
      ui.layout.addEventListener("change", () => {
        if (state.cy) runLayout();
      });
    }
    if (ui.theme) {
      ui.theme.addEventListener("change", () => applyTheme());
    }
    if (ui.refreshBtn) ui.refreshBtn.addEventListener("click", () => refresh());
    if (ui.mlSettingsSaveBtn) ui.mlSettingsSaveBtn.addEventListener("click", () => saveMlSettings().catch((e) => showStatus(`ML settings: ${e.message || e}`, true)));
    if (ui.mlStatusRefreshBtn) ui.mlStatusRefreshBtn.addEventListener("click", () => loadMlModelStatus().catch((e) => showStatus(`ML status: ${e.message || e}`, true)));
    if (ui.mlModelActivateBtn) ui.mlModelActivateBtn.addEventListener("click", () => activateMlModelFromSelect().catch((e) => showStatus(`ML activate: ${e.message || e}`, true)));
    if (ui.mlDatasetBtn) ui.mlDatasetBtn.addEventListener("click", () => runMlDatasetBuild().catch((e) => showStatus(`ML dataset: ${e.message || e}`, true)));
    if (ui.mlTrainBtn) ui.mlTrainBtn.addEventListener("click", () => runMlTrain().catch((e) => showStatus(`ML train: ${e.message || e}`, true)));
    if (ui.fullReportBtn) ui.fullReportBtn.addEventListener("click", () => exportFullReport());
    if (ui.mlTagBtn) ui.mlTagBtn.addEventListener("click", () => submitMlTag().catch((e) => showStatus(`ML tag: ${e.message || e}`, true)));
    if (ui.fsMlTagBtn) ui.fsMlTagBtn.addEventListener("click", () => submitMlTag().catch((e) => showStatus(`ML tag: ${e.message || e}`, true)));
    if (ui.mlMinuteTagBtn) ui.mlMinuteTagBtn.addEventListener("click", () => submitMlMinuteTag().catch((e) => showStatus(`ML minute tag: ${e.message || e}`, true)));
    if (ui.fsMlMinuteTagBtn) ui.fsMlMinuteTagBtn.addEventListener("click", () => submitMlMinuteTag().catch((e) => showStatus(`ML minute tag: ${e.message || e}`, true)));
    if (ui.mlFeedbackOkBtn) ui.mlFeedbackOkBtn.addEventListener("click", () => submitMlFeedback(true).catch((e) => showStatus(`ML feedback: ${e.message || e}`, true)));
    if (ui.mlFeedbackFalseBtn) ui.mlFeedbackFalseBtn.addEventListener("click", () => submitMlFeedback(false).catch((e) => showStatus(`ML feedback: ${e.message || e}`, true)));
    if (ui.fsMlFeedbackOkBtn) ui.fsMlFeedbackOkBtn.addEventListener("click", () => submitMlFeedback(true).catch((e) => showStatus(`ML feedback: ${e.message || e}`, true)));
    if (ui.fsMlFeedbackFalseBtn) ui.fsMlFeedbackFalseBtn.addEventListener("click", () => submitMlFeedback(false).catch((e) => showStatus(`ML feedback: ${e.message || e}`, true)));
    if (ui.exportBtn) {
      ui.exportBtn.addEventListener("click", () => {
        if (!state.cy) return;
        const png = state.cy.png({ output: "blob-promise", full: true, scale: 2, bg: "#0b1220" });
        Promise.resolve(png).then((blob) => {
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `radio-graph-${Date.now()}.png`;
          document.body.appendChild(a);
          a.click();
          a.remove();
          setTimeout(() => URL.revokeObjectURL(url), 1500);
        });
      });
    }
    if (ui.rangeClear) {
      ui.rangeClear.addEventListener("click", () => {
        stopPlayback();
        if (ui.start) ui.start.value = "";
        if (ui.end) ui.end.value = "";
        state.selectedBucketRange = null;
        state.timelineManual = false;
        refresh();
      });
    }
    if (ui.fullscreen) {
      ui.fullscreen.addEventListener("click", async () => {
        const root = ui.stage;
        if (!root) return;
        try {
          if (document.fullscreenElement === root) await document.exitFullscreen();
          else await root.requestFullscreen();
        } catch (_e) {
          // ignore
        }
      });
    }
    if (ui.openInspectorBtn) ui.openInspectorBtn.addEventListener("click", openInspector);
    if (ui.closeInspectorBtn) ui.closeInspectorBtn.addEventListener("click", closeInspector);
    if (ui.inspectorBackdrop) ui.inspectorBackdrop.addEventListener("click", closeInspector);
    if (ui.toggleFiltersBtn) ui.toggleFiltersBtn.addEventListener("click", toggleFilterDrawer);
    document.addEventListener("fullscreenchange", () => {
      syncFullscreenPanels();
      if (document.fullscreenElement === ui.stage) {
        closeInspector();
      }
      if (state.cy && document.fullscreenElement === ui.stage) {
        state.cy.resize();
        state.cy.fit(undefined, 20);
      }
    });
    if (ui.search) {
      ui.search.addEventListener("input", () => {
        clearTimeout(state.searchDebounce);
        state.searchDebounce = setTimeout(() => applySearchFilter(), 120);
      });
    }
    document.addEventListener("click", (ev) => {
      if (!ui.contextMenu || !ui.stage) return;
      if (ui.contextMenu.contains(ev.target)) return;
      hideContextMenu();
    });
    if (ui.zoomIn) ui.zoomIn.addEventListener("click", () => state.cy && state.cy.zoom(state.cy.zoom() * 1.14));
    if (ui.zoomOut) ui.zoomOut.addEventListener("click", () => state.cy && state.cy.zoom(state.cy.zoom() / 1.14));
    if (ui.fit) ui.fit.addEventListener("click", () => clearGraphFocus(true));
    if (ui.playSpeed) {
      ui.playSpeed.addEventListener("change", () => {
        state.playbackSpeed = Math.max(0.25, Number(ui.playSpeed.value || 1));
        if (ui.fsPlaySpeed) ui.fsPlaySpeed.value = ui.playSpeed.value;
        if (state.playbackActive) startPlayback();
      });
    }
    if (ui.fsPlaySpeed) {
      ui.fsPlaySpeed.addEventListener("change", () => {
        if (ui.playSpeed) ui.playSpeed.value = ui.fsPlaySpeed.value;
        state.playbackSpeed = Math.max(0.25, Number(ui.fsPlaySpeed.value || 1));
        if (state.playbackActive) startPlayback();
      });
    }
    if (ui.playToggle) {
      ui.playToggle.addEventListener("click", () => {
        if (state.playbackActive) stopPlayback();
        else startPlayback();
      });
    }
    if (ui.fsPlayToggle) {
      ui.fsPlayToggle.addEventListener("click", () => {
        if (state.playbackActive) stopPlayback();
        else startPlayback();
      });
    }
    if (ui.playPrev) ui.playPrev.addEventListener("click", () => stepTimeline(-1));
    if (ui.playNext) ui.playNext.addEventListener("click", () => stepTimeline(1));
    if (ui.fsPlayPrev) ui.fsPlayPrev.addEventListener("click", () => stepTimeline(-1));
    if (ui.fsPlayNext) ui.fsPlayNext.addEventListener("click", () => stepTimeline(1));
    if (ui.showLabels) {
      ui.showLabels.addEventListener("change", () => {
        updateNodeLabels();
      });
    }
    if (ui.timeSlider) {
      ui.timeSlider.addEventListener("input", () => {
        stopPlayback();
        applyBucketSelectionByIdx(Number(ui.timeSlider.value || 0), true);
        if (isDynamicMode()) loadDynamicWindow();
        else loadGraph();
        loadMlRisk();
      });
    }
    if (ui.fsTimeSlider) {
      ui.fsTimeSlider.addEventListener("input", () => {
        stopPlayback();
        const idx = Number(ui.fsTimeSlider.value || 0);
        applyBucketSelectionByIdx(idx, true);
        if (isDynamicMode()) loadDynamicWindow();
        else loadGraph();
        loadMlRisk();
      });
    }
    if (ui.period) {
      ui.period.querySelectorAll("[data-days]").forEach((btn) => {
        btn.addEventListener("click", () => {
          selectPeriod(btn.getAttribute("data-days"));
        });
      });
    }
    if (ui.applyFilters) {
      ui.applyFilters.addEventListener("click", () => {
        state.timelineManual = false;
        state.selectedBucketRange = null;
        closeFilterDrawer();
        refresh();
      });
    }
    if (ui.fsApply) {
      ui.fsApply.addEventListener("click", () => {
        if (ui.start && ui.fsStart) ui.start.value = ui.fsStart.value;
        if (ui.end && ui.fsEnd) ui.end.value = ui.fsEnd.value;
        if (ui.mode && ui.fsMode) ui.mode.value = ui.fsMode.value;
        if (ui.live && ui.fsLive) ui.live.checked = !!ui.fsLive.checked;
        if (ui.fsPeriod && ui.period) {
          const active = ui.fsPeriod.querySelector(".active[data-days]");
          const days = active ? String(active.getAttribute("data-days") || "1") : "1";
          ui.period.querySelectorAll("[data-days]").forEach((b) => {
            b.classList.toggle("active", String(b.getAttribute("data-days") || "") === days);
          });
        }
        state.timelineManual = false;
        state.selectedBucketRange = null;
        updateLiveBadge();
        startPolling();
        refresh({ animatePeriod: true });
      });
    }
    if (ui.fsReset) {
      ui.fsReset.addEventListener("click", () => {
        if (ui.fsStart) ui.fsStart.value = "";
        if (ui.fsEnd) ui.fsEnd.value = "";
        if (ui.start) ui.start.value = "";
        if (ui.end) ui.end.value = "";
        state.timelineManual = false;
        state.selectedBucketRange = null;
        refresh();
      });
    }
    if (ui.fsPeriod) {
      ui.fsPeriod.querySelectorAll("[data-days]").forEach((btn) => {
        btn.addEventListener("click", () => {
          selectPeriod(btn.getAttribute("data-days"));
        });
      });
    }
    if (ui.quickChips) {
      ui.quickChips.querySelectorAll("[data-preset]").forEach((btn) => {
        btn.addEventListener("click", () => {
          if (!state.graphData || !state.cy) return;
          const preset = btn.getAttribute("data-preset");
          if (preset === "hubs" && state.graphData.metrics && state.graphData.metrics.top_hubs) {
            const id = state.graphData.metrics.top_hubs[0] && state.graphData.metrics.top_hubs[0].id;
            if (id) {
              const n = state.cy.$id(String(id));
              state.cy.elements().addClass("rg-dimmed");
              n.closedNeighborhood().removeClass("rg-dimmed");
              state.cy.center(n);
              renderSelection(n);
            }
          } else if (preset === "bridges" && state.graphData.metrics && state.graphData.metrics.top_bridges) {
            const id = state.graphData.metrics.top_bridges[0] && state.graphData.metrics.top_bridges[0].id;
            if (id) {
              const n = state.cy.$id(String(id));
              state.cy.elements().addClass("rg-dimmed");
              n.closedNeighborhood().removeClass("rg-dimmed");
              state.cy.center(n);
              renderSelection(n);
            }
          } else if (preset === "cross-unit") {
            state.cy.elements().removeClass("rg-dimmed");
            state.cy.edges().forEach((e) => {
              const s = e.source().data("unit");
              const t = e.target().data("unit");
              if (!s || !t || s === t) e.addClass("rg-dimmed");
            });
          }
        });
      });
    }
  }

  function cacheUiRefs() {
    ui.dashboard = $("rg-dashboard");
    ui.stage = document.querySelector(".rg-stage");
    ui.canvas = $("rg-canvas");
    ui.contextMenu = $("rg-context-menu");
    ui.empty = $("rg-empty");
    ui.loading = $("rg-loading");
    ui.statusMsg = $("rg-status-msg");
    ui.statusRange = $("rg-status-range");
    ui.scope = $("rg-scope");
    ui.focusId = $("rg-focus-id");
    ui.maxNodes = $("rg-max-nodes");
    ui.maxEdges = $("rg-max-edges");
    ui.applyFilters = $("rg-apply-filters");
    ui.unitQuery = $("rg-unit-query");
    ui.groupQuery = $("rg-group-query");
    ui.start = $("rg-start");
    ui.end = $("rg-end");
    ui.minWeight = $("rg-min-weight");
    ui.clusterBy = $("rg-cluster-by");
    ui.maxNodesMode = $("rg-max-nodes-mode");
    ui.mode = $("rg-mode");
    ui.includeOther = $("rg-include-other");
    ui.auto = $("rg-auto");
    ui.live = $("rg-live");
    ui.liveState = $("rg-live-state");
    ui.layout = $("rg-layout");
    ui.theme = $("rg-theme");
    ui.showLabels = $("rg-show-labels");
    ui.refreshBtn = $("rg-refresh");
    ui.mlDatasetBtn = $("rg-ml-dataset");
    ui.mlTrainBtn = $("rg-ml-train");
    ui.fullReportBtn = $("rg-full-report");
    ui.exportBtn = $("rg-export-png");
    ui.rangeClear = $("rg-range-clear");
    ui.fullscreen = $("rg-fullscreen");
    ui.search = $("rg-search");
    ui.zoomIn = $("rg-zoom-in");
    ui.zoomOut = $("rg-zoom-out");
    ui.fit = $("rg-fit");
    ui.selection = $("rg-selection");
    ui.period = $("rg-period");
    ui.quickChips = $("rg-quick-chips");
    ui.timeline = $("rg-timeline");
    ui.timeSlider = $("rg-time-slider");
    ui.timeLabel = $("rg-time-label");
    ui.composition = $("rg-composition");
    ui.compMetrics = $("rg-comp-metrics");
    ui.compareLabel = $("rg-compare-label");
    ui.compareStats = $("rg-compare-stats");
    ui.topHubs = $("rg-top-hubs");
    ui.topBridges = $("rg-top-bridges");
    ui.mlPrediction = $("rg-ml-prediction");
    ui.mlReasons = $("rg-ml-reasons");
    ui.mlHotspots = $("rg-ml-hotspots");
    ui.mlModelActive = $("rg-ml-model-active");
    ui.mlModelMetrics = $("rg-ml-model-metrics");
    ui.mlModelDiagnostics = $("rg-ml-model-diagnostics");
    ui.mlModelRuns = $("rg-ml-model-runs");
    ui.mlModelSelect = $("rg-ml-model-select");
    ui.mlModelActivateBtn = $("rg-ml-model-activate");
    ui.mlCfgWindow = $("rg-ml-cfg-window");
    ui.mlCfgEpochs = $("rg-ml-cfg-epochs");
    ui.mlCfgLr = $("rg-ml-cfg-lr");
    ui.mlCfgRetrainMin = $("rg-ml-cfg-retrain-min");
    ui.mlCfgRetrainStep = $("rg-ml-cfg-retrain-step");
    ui.mlCfgAutoActivate = $("rg-ml-cfg-auto-activate");
    ui.mlSettingsSaveBtn = $("rg-ml-settings-save");
    ui.mlStatusRefreshBtn = $("rg-ml-status-refresh");
    ui.mlTagBtn = $("rg-ml-tag");
    ui.mlMinuteTagBtn = $("rg-ml-minute-tag");
    ui.mlFeedbackOkBtn = $("rg-ml-feedback-ok");
    ui.mlFeedbackFalseBtn = $("rg-ml-feedback-false");
    ui.forecastSummary = $("rg-forecast-summary");
    ui.forecastReliability = $("rg-forecast-reliability");
    ui.forecastH30 = $("rg-forecast-h30");
    ui.forecastH60 = $("rg-forecast-h60");
    ui.forecastH120 = $("rg-forecast-h120");
    ui.mNodes = $("rg-m-nodes");
    ui.mEdges = $("rg-m-edges");
    ui.mDensity = $("rg-m-density");
    ui.mComponents = $("rg-m-components");
    ui.mRisk = $("rg-m-risk");
    ui.mMlRisk = $("rg-m-ml-risk");
    ui.fsPanels = $("rg-fs-panels");
    ui.fsSelection = $("rg-fs-selection");
    ui.fsTopHubs = $("rg-fs-top-hubs");
    ui.fsTopBridges = $("rg-fs-top-bridges");
    ui.fsMlPrediction = $("rg-fs-ml-prediction");
    ui.fsMlReasons = $("rg-fs-ml-reasons");
    ui.fsMlHotspots = $("rg-fs-ml-hotspots");
    ui.fsMlModelActive = $("rg-fs-ml-model-active");
    ui.fsMlModelMetrics = $("rg-fs-ml-model-metrics");
    ui.fsMlModelDiagnostics = $("rg-fs-ml-model-diagnostics");
    ui.fsMlModelRuns = $("rg-fs-ml-model-runs");
    ui.fsStatus = $("rg-fs-status");
    ui.fsPeriod = $("rg-fs-period");
    ui.fsStart = $("rg-fs-start");
    ui.fsEnd = $("rg-fs-end");
    ui.fsMode = $("rg-fs-mode");
    ui.fsLive = $("rg-fs-live");
    ui.fsApply = $("rg-fs-apply");
    ui.fsReset = $("rg-fs-reset");
    ui.fsMlTagBtn = $("rg-fs-ml-tag");
    ui.fsMlMinuteTagBtn = $("rg-fs-ml-minute-tag");
    ui.fsMlFeedbackOkBtn = $("rg-fs-ml-feedback-ok");
    ui.fsMlFeedbackFalseBtn = $("rg-fs-ml-feedback-false");
    ui.fsTimeline = $("rg-fs-timeline");
    ui.fsTimeSlider = $("rg-fs-time-slider");
    ui.fsTimeLabel = $("rg-fs-time-label");
    ui.fsComposition = $("rg-fs-composition");
    ui.fsCompMetrics = $("rg-fs-comp-metrics");
    ui.playPrev = $("rg-play-prev");
    ui.playToggle = $("rg-play-toggle");
    ui.playNext = $("rg-play-next");
    ui.playSpeed = $("rg-play-speed");
    ui.fsPlayPrev = $("rg-fs-play-prev");
    ui.fsPlayToggle = $("rg-fs-play-toggle");
    ui.fsPlayNext = $("rg-fs-play-next");
    ui.fsPlaySpeed = $("rg-fs-play-speed");
    ui.fsForecastSummary = $("rg-fs-forecast-summary");
    ui.fsForecastReliability = $("rg-fs-forecast-reliability");
    ui.fsForecastH30 = $("rg-fs-forecast-h30");
    ui.fsForecastH60 = $("rg-fs-forecast-h60");
    ui.fsForecastH120 = $("rg-fs-forecast-h120");
    ui.inspectorBackdrop = $("rg-inspector-backdrop");
    ui.openInspectorBtn = $("rg-open-inspector");
    ui.closeInspectorBtn = $("rg-close-inspector");
    ui.sidePanel = $("rg-side-panel");
    ui.filterDrawer = $("rg-filter-drawer");
    ui.toggleFiltersBtn = $("rg-toggle-filters");
  }

  function activate() {
    if (!isEnabled()) return;
    state.enabled = true;
    state.active = true;
    if (!state.initialized) {
      cacheUiRefs();
      bindControls();
      bindCanvasResizeObserver();
      state.initialized = true;
    }
    state.playbackSpeed = Math.max(0.25, Number(ui.playSpeed ? ui.playSpeed.value : 1) || 1);
    updateLiveBadge();
    syncFullscreenPanels();
    scheduleCyResize();
    startPolling();
    refresh();
  }

  function deactivate() {
    state.active = false;
    stopPlayback();
    stopPolling();
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopPlayback();
      stopPolling();
      return;
    }
    if (state.active) {
      startPolling();
    }
  });

  window.AnalysisGraphV2 = {
    isEnabled,
    activate,
    deactivate,
    refresh,
  };
})();
