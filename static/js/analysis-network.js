(function () {
  "use strict";

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

function _ruSessionsWord(nAbs) {
  const n = Math.abs(Number(nAbs) || 0);
  const t = n % 10;
  const h = n % 100;
  if (t === 1 && h !== 11) return "сеанс";
  if (t >= 2 && t <= 4 && (h < 10 || h >= 20)) return "сеанса";
  return "сеансов";
}

function _ruCorrWord(nAbs) {
  const n = Math.abs(Number(nAbs) || 0);
  const t = n % 10;
  const h = n % 100;
  if (t === 1 && h !== 11) return "корреспондент";
  if (t >= 2 && t <= 4 && (h < 10 || h >= 20)) return "корреспондента";
  return "корреспондентов";
}

function netVizDeltaAbsLabel(delta, field) {
  const sign = delta > 0 ? "+" : "";
  const w = field === "sessions" ? _ruSessionsWord(delta) : _ruCorrWord(delta);
  return `${sign}${delta} ${w}`;
}

/** Текст про процент к прошлому; при «было 0» — пояснение без деления на ноль. */
function netVizDeltaPctLabel(c, p, delta) {
  if (delta === 0) return "";
  if (p > 0) {
    const pct = ((c - p) / p) * 100;
    const absPct = Math.abs(Math.round(pct * 10) / 10);
    const numStr = Number.isInteger(absPct) ? String(absPct) : absPct.toFixed(1);
    return delta > 0
      ? `увеличение на ${numStr}% к прошлому`
      : `уменьшение на ${numStr}% к прошлому`;
  }
  if (p === 0 && c > 0) return "в прошлом периоде — 0 (процент не считается)";
  return "";
}

function fmtPrevRange(startIso, endIso) {
  if (!startIso || !endIso) return "—";
  try {
    const s = new Date(startIso);
    const e = new Date(endIso);
    if (Number.isNaN(s.getTime()) || Number.isNaN(e.getTime())) return "—";
    const pad = (n) => String(n).padStart(2, "0");
    const fmt = (d) =>
      `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(
        d.getMinutes()
      )}`;
    return `${fmt(s)} — ${fmt(e)}`;
  } catch (_e) {
    return "—";
  }
}

function _networkExportUnitName() {
  const el = $("net-unit-export");
  return el ? String(el.value || "").trim() : "";
}

function _networkToIsoMin(d) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(
    d.getMinutes()
  )}`;
}

function _updateNetworkExportUnitBtn() {
  const btn = $("net-export-unit-btn");
  if (!btn) return;
  const startEl = $("net-start");
  const endEl = $("net-end");
  const start = startEl ? String(startEl.value || "").trim() : "";
  const end = endEl ? String(endEl.value || "").trim() : "";
  const hasTable = !!(window.__NET_LAST_PAYLOAD__ && Array.isArray(window.__NET_LAST_PAYLOAD__.clusters));
  btn.disabled = !start || !end || !_networkExportUnitName() || !hasTable;
}

function applyNetworkDatePreset(range) {
  const netStart = $("net-start");
  const netEnd = $("net-end");
  if (!netStart || !netEnd) return;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  let start = new Date(today.getTime());
  let end = new Date(today.getTime() + 24 * 60 * 60 * 1000 - 60 * 1000);
  if (range === "week") {
    start = new Date(today.getTime() - 6 * 24 * 60 * 60 * 1000);
  } else if (range === "month") {
    start = new Date(today.getTime() - 29 * 24 * 60 * 60 * 1000);
  }
  netStart.value = _networkToIsoMin(start);
  netEnd.value = _networkToIsoMin(end);
  const netPrev = $("net-prev");
  if (netPrev) {
    const pr = computePrevPeriod(netStart.value, netEnd.value);
    netPrev.textContent = pr ? fmtPrevRange(pr.prevStart, pr.prevEnd) : "—";
  }
  _updateNetworkExportUnitBtn();
}

function computePrevPeriod(startIso, endIso) {
  try {
    const s = new Date(startIso);
    const e = new Date(endIso);
    if (Number.isNaN(s.getTime()) || Number.isNaN(e.getTime())) return null;
    const delta = e.getTime() - s.getTime();
    if (delta <= 0) return null;
    const prevEnd = new Date(s.getTime());
    const prevStart = new Date(s.getTime() - delta);
    const toIsoMin = (d) => {
      const pad = (n) => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(
        d.getMinutes()
      )}`;
    };
    return { prevStart: toIsoMin(prevStart), prevEnd: toIsoMin(prevEnd) };
  } catch (_e) {
    return null;
  }
}

function renderNetworkTable(payload) {
  const headRow = $("net-head-row");
  const body = $("net-body");
  if (!headRow || !body) return;
  const clusters = Array.isArray(payload.clusters) ? payload.clusters : [];

  // header
  headRow.innerHTML = `<th style="min-width:200px;">Сеть</th>` + clusters.map((c) => `<th>${escapeHtml(c)}</th>`).join("");

  const mkRow = (label, map, field) => {
    let tds = `<td class="fw-semibold">${escapeHtml(label)}</td>`;
    for (const c of clusters) {
      const v = map && map[c] ? Number(map[c][field] || 0) : 0;
      tds += `<td class="text-center">${escapeHtml(String(v))}</td>`;
    }
    return `<tr>${tds}</tr>`;
  };

  const prevLabel = fmtPrevRange(payload.prev_start, payload.prev_end);
  const curLabel = fmtPrevRange(payload.start, payload.end);

  body.innerHTML =
    mkRow(prevLabel || "Предыдущий период", payload.previous || {}, "sessions") +
    mkRow("Кол-во корреспондентов", payload.previous || {}, "correspondents") +
    `<tr class="table-light"><td colspan="${clusters.length + 1}"></td></tr>` +
    mkRow(curLabel || "Текущий период", payload.current || {}, "sessions") +
    mkRow("Кол-во корреспондентов", payload.current || {}, "correspondents");
}

function ensureNetVizBandContainers(section) {
  if (!section) return { unitsEl: null, corrEl: null, capEl: null };
  let unitsEl = $("net-blocks-units");
  let corrEl = $("net-blocks-corr");
  if (unitsEl && corrEl) {
    return { unitsEl, corrEl, capEl: $("net-viz-caption") };
  }
  if (!section.querySelector(".net-viz-head")) {
    section.insertAdjacentHTML(
      "afterbegin",
      `<div class="net-viz-head">
        <div>
          <h3 class="net-viz-title">Активность по сетям</h3>
          <p class="net-viz-caption small text-muted mb-0" id="net-viz-caption"></p>
        </div>
        <ul class="net-viz-legend list-unstyled small mb-0">
          <li><span class="net-viz-legend-prev" aria-hidden="true"></span> прошлый период</li>
          <li><span class="net-viz-legend-up"></span> рост к прошлому</li>
          <li><span class="net-viz-legend-down"></span> спад к прошлому</li>
        </ul>
      </div>`
    );
  }
  section.insertAdjacentHTML(
    "beforeend",
    `<div class="net-viz-band">
      <div class="net-viz-band-label">
        Подразделения
        <span class="net-viz-band-hint">сеансы связи</span>
      </div>
      <div class="net-viz-band-scale" id="net-viz-scale-units" aria-live="polite"></div>
      <div class="net-viz-scroll" id="net-blocks-units"></div>
    </div>
    <div class="net-viz-band net-viz-band--corr">
      <div class="net-viz-band-label">
        Корреспонденты
        <span class="net-viz-band-hint">уникальные ID за период</span>
      </div>
      <div class="net-viz-band-scale" id="net-viz-scale-corr" aria-live="polite"></div>
      <div class="net-viz-scroll" id="net-blocks-corr"></div>
    </div>`
  );
  unitsEl = $("net-blocks-units");
  corrEl = $("net-blocks-corr");
  return { unitsEl, corrEl, capEl: $("net-viz-caption") };
}

function renderNetworkActivityBlocks(payload) {
  const section = $("net-viz-section");
  const { unitsEl, corrEl, capEl } = ensureNetVizBandContainers(section);
  if (!section || !unitsEl || !corrEl) return;
  const clusters = Array.isArray(payload.clusters) ? payload.clusters : [];
  if (!clusters.length) {
    section.style.display = "none";
    section.hidden = true;
    return;
  }
  section.style.display = "";
  section.hidden = false;
  const curL = fmtPrevRange(payload.start, payload.end);
  const prevL = fmtPrevRange(payload.prev_start, payload.prev_end);
  if (capEl) {
    capEl.textContent =
      `У прошлого периода (${prevL}): пунктир от оси вправо и жирная точка слева с числом. Крупная метка — текущий период (${curL}). Рост: зелёный столбец до «сейчас». Спад: синий столбец — объём сейчас, красная зона — падение к уровню прошлого. Одна шкала на весь ряд.`;
  }

  const rowPeak = (field) => {
    let m = 1;
    for (const n of clusters) {
      const p = Number((payload.previous && payload.previous[n] && payload.previous[n][field]) || 0);
      const c = Number((payload.current && payload.current[n] && payload.current[n][field]) || 0);
      m = Math.max(m, p, c);
    }
    return m;
  };
  const scaleSessions = rowPeak("sessions");
  const scaleCorr = rowPeak("correspondents");
  const su = $("net-viz-scale-units");
  const sc = $("net-viz-scale-corr");
  if (su) {
    su.textContent = `Общая шкала ряда: 100% высоты = ${scaleSessions} сеансов (максимум из «текущий / прошлый» по любой сетке в этом ряду).`;
  }
  if (sc) {
    sc.textContent = `Общая шкала ряда: 100% высоты = ${scaleCorr} корреспондентов (то же правило).`;
  }

  const mkCard = (name, field, scaleMax, metricTitle) => {
    const p = Number((payload.previous && payload.previous[name] && payload.previous[name][field]) || 0);
    const c = Number((payload.current && payload.current[name] && payload.current[name][field]) || 0);
    const maxV = Math.max(Number(scaleMax) || 1, 1);
    const pct = (v) => Math.min(100, Math.max(0, Math.round((v / maxV) * 10000) / 100));
    const prevPct = pct(p);
    const curPct = pct(c);
    /* Должно совпадать с --net-viz-bar-h у .net-viz-card__bar в CSS. */
    const netVizBarH = 168;
    const barH = (v) => {
      if (v <= 0) return "0px";
      const pc = pct(v);
      if (pc >= 99.98) return `${netVizBarH}px`;
      const px = Math.max(3, Math.round((pc / 100) * netVizBarH));
      return `${px}px`;
    };
    const trend = c > p ? "up" : c < p ? "down" : "same";
    const delta = c - p;
    const trendClass = trend === "up" ? "net-viz-card--up" : trend === "down" ? "net-viz-card--down" : "net-viz-card--same";
    const deltaCls =
      trend === "up" ? "net-viz-card__delta--up" : trend === "down" ? "net-viz-card__delta--down" : "net-viz-card__delta--same";

    const midTickVal = maxV < 3 ? null : Math.round(maxV / 2);

    let layers = "";
    layers += `<div class="net-viz-card__axis" aria-hidden="true">
      <span class="net-viz-card__axis-tick net-viz-card__axis-tick--max">${maxV}</span>
      ${
        midTickVal != null
          ? `<span class="net-viz-card__axis-tick net-viz-card__axis-tick--mid">${midTickVal}</span>`
          : `<span class="net-viz-card__axis-tick net-viz-card__axis-tick--mid" style="opacity:0">·</span>`
      }
      <span class="net-viz-card__axis-tick net-viz-card__axis-tick--zero">0</span>
    </div>`;

    if (p === 0 && c === 0) {
      layers += `<div class="net-viz-card__fill-same" style="height:10%"></div>`;
    } else if (trend === "up") {
      layers += `<div class="net-viz-card__fill-up" style="height:${barH(c)}"></div>`;
    } else if (trend === "down") {
      if (c > 0) {
        layers += `<div class="net-viz-card__fill-cur" style="height:${barH(c)}"></div>`;
      }
      const dropH = Math.max(0, prevPct - curPct);
      if (dropH > 0.05) {
        const dropFull = dropH >= 99.98 && curPct <= 0.02;
        const dropHStyle = dropFull ? "height:100%;bottom:0" : `height:${dropH}%;bottom:${curPct}%`;
        const dropCls = dropFull ? "net-viz-card__fill-drop net-viz-card__fill-drop--full" : "net-viz-card__fill-drop";
        layers += `<div class="${dropCls}" style="${dropHStyle}"></div>`;
      }
    } else {
      layers += `<div class="net-viz-card__fill-same" style="height:${barH(c)}"></div>`;
    }
    if (!(p === 0 && c === 0)) {
      const prevMarkEdgeClass =
        prevPct >= 86 ? " net-viz-card__prev-mark--nudge-down" : prevPct <= 10 ? " net-viz-card__prev-mark--nudge-up" : "";
      layers += `<div class="net-viz-card__prev-mark${prevMarkEdgeClass}" style="bottom:${prevPct}%" title="Прошлый период: ${p}">
      <span class="net-viz-card__prev-anchor">
        <span class="net-viz-card__prev-knob" aria-hidden="true"></span>
        <span class="net-viz-card__prev-num">${p}</span>
      </span>
      <span class="net-viz-card__prev-dash" aria-hidden="true"></span>
    </div>`;
    }

    const netVizTagH = 58;
    const netVizTagGap = 7;
    const netVizTagTopPad = 6;
    let tagBottomPx;
    if (p === 0 && c === 0) {
      tagBottomPx = 22;
    } else if (c === 0) {
      tagBottomPx = Math.min(netVizBarH * 0.32, 36);
    } else {
      const fillTopPx = (curPct / 100) * netVizBarH;
      tagBottomPx = fillTopPx + netVizTagGap;
      const cap = netVizBarH - netVizTagH - netVizTagTopPad;
      tagBottomPx = Math.min(tagBottomPx, cap);
      tagBottomPx = Math.max(tagBottomPx, 14);
      /* Уровни близко — чуть поднимаем «сейчас», чтобы не перекрывать маркер «было». */
      if (p > 0 && Math.abs(curPct - prevPct) < 13) {
        tagBottomPx = Math.min(tagBottomPx + 12, cap);
      }
    }
    layers += `<div class="net-viz-card__current-tag" style="bottom:${tagBottomPx}px;top:auto">
      <span class="net-viz-card__current-value">${c}</span>
      <span class="net-viz-card__current-label">сейчас</span>
    </div>`;

    const labelShort = field === "sessions" ? "сеансов" : "корр.";
    const deltaPctText = netVizDeltaPctLabel(c, p, delta);
    const deltaBlock =
      delta === 0
        ? "без изм."
        : `<span class="net-viz-card__delta-abs">${escapeHtml(netVizDeltaAbsLabel(delta, field))}</span>${
            deltaPctText
              ? `<span class="net-viz-card__delta-pct">${escapeHtml(deltaPctText)}</span>`
              : ""
          }`;
    const tipPct = deltaPctText ? `. ${escapeHtml(deltaPctText)}` : "";
    return `<div class="net-viz-card ${trendClass}" title="${escapeHtml(name)}: ${escapeHtml(metricTitle)}, сейчас ${c}, было ${p}${tipPct}">
      <span class="net-viz-card__metric">${escapeHtml(metricTitle)}</span>
      <div class="net-viz-card__bar" role="img" aria-label="${escapeHtml(name)}: ${c} из ${p} ${labelShort}">${layers}</div>
      <div class="net-viz-card__meta">
        <div class="net-viz-card__name">${escapeHtml(name)}</div>
        <div class="net-viz-card__counts"><span class="net-viz-card__num-cur">${c}</span><span class="net-viz-card__slash">/</span><span class="net-viz-card__num-prev">${p}</span></div>
        <div class="net-viz-card__delta ${deltaCls}">${deltaBlock}</div>
      </div>
    </div>`;
  };

  try {
    unitsEl.innerHTML = clusters
      .map((n) => mkCard(n, "sessions", scaleSessions, "Сеансы"))
      .join("");
    corrEl.innerHTML = clusters
      .map((n) => mkCard(n, "correspondents", scaleCorr, "Корреспонденты"))
      .join("");
  } catch (err) {
    console.error("renderNetworkActivityBlocks", err);
    unitsEl.innerHTML = "";
    corrEl.innerHTML = "";
  }
}

/* Редизайн: таблица и сводка показывают только подразделения, без технических
 * сущностей (частоты, рабочие группы и т.п.). */
function _netMetric(payload, name, field) {
  return Number((payload.current && payload.current[name] && payload.current[name][field]) || 0);
}

function _netPreviousMetric(payload, name, field) {
  return Number((payload.previous && payload.previous[name] && payload.previous[name][field]) || 0);
}

function _netFilteredClusters(payload) {
  const clusters = Array.isArray(payload.clusters) ? payload.clusters : [];
  const query = String($("net-unit-search")?.value || "").trim().toLocaleLowerCase();
  if (!query) return clusters;
  return clusters.filter((name) => String(name).toLocaleLowerCase().includes(query));
}

function _netInitials(name) {
  const words = String(name || "").trim().split(/\s+/).filter(Boolean);
  return (words.slice(0, 2).map((word) => word[0]).join("") || "П").toUpperCase();
}

function renderNetworkTable(payload) {
  const headRow = $("net-head-row");
  const body = $("net-body");
  if (!headRow || !body) return;
  const clusters = _netFilteredClusters(payload);
  const allClusters = Array.isArray(payload.clusters) ? payload.clusters : [];
  const maxSessions = Math.max(1, ...allClusters.map((name) => _netMetric(payload, name, "sessions")));
  const optionList = $("net-unit-options");
  if (optionList) optionList.innerHTML = allClusters.map((name) => `<option value="${escapeHtml(name)}"></option>`).join("");

  headRow.innerHTML = "<th>Подразделение</th><th>Сеансы</th><th>Предыдущий период</th><th>Изменение</th><th>Корреспонденты</th><th>Интенсивность</th><th aria-label=\"Избранное\"></th>";
  if (!clusters.length) {
    body.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4">Подразделения по заданному фильтру не найдены.</td></tr>`;
    return;
  }
  body.innerHTML = clusters.map((name, index) => {
    const current = _netMetric(payload, name, "sessions");
    const previous = _netPreviousMetric(payload, name, "sessions");
    const correspondents = _netMetric(payload, name, "correspondents");
    const delta = current - previous;
    const deltaClass = delta > 0 ? "up" : delta < 0 ? "down" : "same";
    const deltaText = `${delta > 0 ? "+" : ""}${delta}`;
    const intensity = Math.round((current / maxSessions) * 100);
    const avatar = String((payload.avatars && payload.avatars[name]) || "").trim();
    const avatarMarkup = avatar
      ? `<img class="net-unit-avatar" src="${escapeHtml(avatar)}" alt="">`
      : `<span class="net-unit-avatar net-unit-avatar--fallback">${escapeHtml(_netInitials(name))}</span>`;
    const favorites = window.__NET_FAVORITES__ instanceof Set ? window.__NET_FAVORITES__ : new Set();
    const isFavorite = favorites.has(name);
    return `<tr>
      <td><div class="net-unit-cell">${avatarMarkup}<div><div class="net-unit-name">${escapeHtml(name)}</div><div class="net-unit-sub">Подразделение</div></div></div></td>
      <td class="fw-semibold">${current}</td>
      <td>${previous}</td>
      <td><span class="net-delta net-delta--${deltaClass}">${deltaText}</span></td>
      <td>${correspondents}</td>
      <td><div class="net-intensity"><span class="net-intensity__bar"><b style="width:${intensity}%"></b></span><span class="net-intensity__value">${intensity}%</span></div></td>
      <td><button type="button" class="net-fav-btn ${isFavorite ? "net-fav-btn--active" : ""}" data-net-fav-index="${index}" title="Избранное"><i class="bi bi-star${isFavorite ? "-fill" : ""}"></i></button></td>
    </tr>`;
  }).join("");
  body.querySelectorAll("[data-net-fav-index]").forEach((button) => {
    button.addEventListener("click", () => {
      const name = clusters[Number(button.dataset.netFavIndex)];
      if (!name) return;
      const favorites = window.__NET_FAVORITES__ instanceof Set ? window.__NET_FAVORITES__ : new Set();
      if (favorites.has(name)) favorites.delete(name); else favorites.add(name);
      window.__NET_FAVORITES__ = favorites;
      saveNetworkFavorites(window.__NET_POS__ || "__all__", favorites);
      renderNetworkTable(payload);
      renderNetworkActivityBlocks(payload);
    });
  });
}

function renderNetworkActivityBlocks(payload) {
  const clusters = Array.isArray(payload.clusters) ? payload.clusters : [];
  const totalCurrent = clusters.reduce((sum, name) => sum + _netMetric(payload, name, "sessions"), 0);
  const totalPrevious = clusters.reduce((sum, name) => sum + _netPreviousMetric(payload, name, "sessions"), 0);
  const totalCorrespondents = clusters.reduce((sum, name) => sum + _netMetric(payload, name, "correspondents"), 0);
  const kpis = $("net-kpis");
  const totalDelta = totalCurrent - totalPrevious;
  if (kpis) {
    kpis.innerHTML = [
      ["bi-broadcast", "Сеансы связи", totalCurrent, `изменение ${totalDelta > 0 ? "+" : ""}${totalDelta} к прошлому`, "aqua"],
      ["bi-person-lines-fill", "Корреспонденты", totalCorrespondents, "уникальные за период", ""],
      ["bi-diagram-3", "Активные подразделения", clusters.filter((name) => _netMetric(payload, name, "sessions") > 0).length, `из ${clusters.length} в отчёте`, "violet"],
      ["bi-calendar3", "Период", clusters.length, "подразделений в анализе", ""],
    ].map(([icon, label, value, hint, cls]) => `<article class="net-kpi net-kpi--${cls}"><div class="net-kpi__icon"><i class="bi ${icon}"></i></div><div><div class="net-kpi__label">${label}</div><div class="net-kpi__value">${value}</div><div class="net-kpi__hint">${hint}</div></div></article>`).join("");
  }
  const chart = $("net-activity-chart");
  const chartNames = clusters.slice(0, 9);
  if (chart) {
    if (!chartNames.length) {
      chart.innerHTML = '<div class="net-empty">Нет данных за этот период.</div>';
    } else {
      const values = chartNames.flatMap((name) => [_netMetric(payload, name, "sessions"), _netPreviousMetric(payload, name, "sessions")]);
      const maxValue = Math.max(1, ...values);
      const width = 720; const height = 230; const left = 20; const right = 18; const top = 14; const bottom = 35;
      const x = (index) => left + (chartNames.length === 1 ? (width - left - right) / 2 : index * (width - left - right) / (chartNames.length - 1));
      const y = (value) => top + (height - top - bottom) * (1 - value / maxValue);
      const points = (field, previous) => chartNames.map((name, index) => `${x(index)},${y(previous ? _netPreviousMetric(payload, name, field) : _netMetric(payload, name, field))}`).join(" ");
      const currentPoints = points("sessions", false);
      const prevPoints = points("sessions", true);
      const area = `${left},${height - bottom} ${currentPoints} ${x(chartNames.length - 1)},${height - bottom}`;
      const labels = chartNames.map((name, index) => `<text class="net-chart-label" x="${x(index)}" y="${height - 11}" text-anchor="middle">${escapeHtml(String(name).slice(0, 10))}</text>`).join("");
      const grid = [0, 1, 2, 3].map((n) => `<line class="net-chart-grid" x1="${left}" x2="${width - right}" y1="${top + n * (height - top - bottom) / 3}" y2="${top + n * (height - top - bottom) / 3}"></line>`).join("");
      const dots = chartNames.map((name, index) => `<circle class="net-chart-dot" cx="${x(index)}" cy="${y(_netMetric(payload, name, "sessions"))}" r="4"><title>${escapeHtml(name)}: ${_netMetric(payload, name, "sessions")} сеансов</title></circle>`).join("");
      chart.innerHTML = `<svg class="net-chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="Сравнение сеансов по подразделениям">${grid}<polygon class="net-chart-area" points="${area}"></polygon><polyline class="net-chart-line-prev" points="${prevPoints}"></polyline><polyline class="net-chart-line-now" points="${currentPoints}"></polyline>${dots}${labels}</svg>`;
    }
  }
  const changes = $("net-changes-list");
  if (changes) {
    const sorted = clusters.map((name) => ({ name, current: _netMetric(payload, name, "sessions"), delta: _netMetric(payload, name, "sessions") - _netPreviousMetric(payload, name, "sessions") })).sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)).slice(0, 5);
    changes.innerHTML = sorted.length ? sorted.map((item) => `<div class="net-change"><div><div class="net-change__name">${escapeHtml(item.name)}</div><div class="net-change__meta">${item.current} сеансов за период</div></div><div class="net-change__value net-change__value--${item.delta > 0 ? "up" : item.delta < 0 ? "down" : "same"}">${item.delta > 0 ? "+" : ""}${item.delta}</div></div>`).join("") : '<div class="net-empty">Нет данных.</div>';
  }
}

async function buildNetworkSummary() {
  const startEl = $("net-start");
  const endEl = $("net-end");
  const status = $("net-status");
  const exportBtn = $("net-export-btn");
  const orderBtn = $("net-order-toggle");
  if (!startEl || !endEl) return;
  const start = (startEl.value || "").trim();
  const end = (endEl.value || "").trim();
  if (!start || !end) {
    if (status) status.textContent = "Укажи начало и конец периода.";
    return;
  }
  if (status) status.textContent = "Загрузка…";
  if (exportBtn) exportBtn.disabled = true;
  if (orderBtn) orderBtn.disabled = true;
  const exportUnitBtn = $("net-export-unit-btn");
  if (exportUnitBtn) exportUnitBtn.disabled = true;
  const sessionsFavoritesPromise = apiGet("/api/sessions/favorites?with_unit_names=1").catch(() => null);
  try {
    let url = `/api/analysis/network-summary?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
    const data = await apiGet(url);
    const posKey = data.all_positions ? "__all__" : (data.position || "__all__");
    window.__NET_POS__ = posKey;
    const columnOrder = Array.isArray(data.column_order) ? data.column_order.map(String) : [];
    const sharedOrder = Array.isArray(data.shared_order) ? data.shared_order.map(String) : [];
    const saved = loadNetworkOrder(posKey);
    const hidden = loadNetworkHidden(posKey);
    const favorites = loadNetworkFavorites(posKey);
    const favData = await sessionsFavoritesPromise;
    if (favData && Array.isArray(favData.favorites)) {
      favData.favorites.forEach((f) => {
        const u = f && f.unit_name != null ? String(f.unit_name).trim() : "";
        if (u) favorites.add(u);
      });
    }
    const favoritesOnly = loadNetworkFavoritesOnly(posKey);
    const customUnits = loadNetworkCustom(posKey);
    const baseClusters = mergeNetworkCustom(
      Array.isArray(data.clusters) ? data.clusters : [],
      customUnits
    );

    if (!data.current) data.current = {};
    if (!data.previous) data.previous = {};
    baseClusters.forEach((name) => {
      if (!data.current[name]) data.current[name] = { sessions: 0, correspondents: 0 };
      if (!data.previous[name]) data.previous[name] = { sessions: 0, correspondents: 0 };
    });
    const effectiveHidden = resolveNetworkHiddenForMode(
      baseClusters,
      hidden,
      favorites,
      favoritesOnly
    );
    const orderSource =
      columnOrder.length > 0
        ? columnOrder
        : sharedOrder.length > 0
          ? sharedOrder
          : saved;
    const ordered = applyOrder(orderSource, baseClusters, effectiveHidden);
    data.all_clusters = baseClusters.slice();
    data.clusters = ordered;
    window.__NET_LAST_PAYLOAD__ = data;
    window.__NET_ORDER__ = ordered.slice();
    window.__NET_COLUMN_ORDER__ = columnOrder.slice();
    window.__NET_SHARED_ORDER__ = sharedOrder.slice();
    window.__NET_HIDDEN__ = hidden;
    window.__NET_FAVORITES__ = favorites;
    window.__NET_FAVORITES_ONLY__ = favoritesOnly;
    window.__NET_CUSTOM__ = customUnits.slice();
    window.__NET_POS__ = posKey;
    renderNetworkTable(data);
    if (status) status.textContent = "Таблица готова…";
    requestAnimationFrame(() => {
      renderNetworkActivityBlocks(data);
      initNetworkOrderUI(posKey, baseClusters, hidden, favorites);
      if (status) status.textContent = "Готово.";
      if (exportBtn) exportBtn.disabled = false;
      if (orderBtn) orderBtn.disabled = false;
      _updateNetworkExportUnitBtn();
    });
  } catch (e) {
    if (status) status.textContent = `Ошибка: ${e.message || e}`;
  }
}
async function exportNetworkSummary(unitsOnly) {
  const startEl = $("net-start");
  const endEl = $("net-end");
  const status = $("net-status");
  if (!startEl || !endEl) return;
  const start = (startEl.value || "").trim();
  const end = (endEl.value || "").trim();
  if (!start || !end) return;
  const unitFilter =
    unitsOnly != null && String(unitsOnly).trim()
      ? String(unitsOnly).trim()
      : _networkExportUnitName();
  try {
    if (status) status.textContent = "Формирование Excel…";
    const posKey = window.__NET_POS__ || "__all__";
    const hidden = window.__NET_HIDDEN__ || loadNetworkHidden(posKey);
    const favorites = await loadMergedNetworkFavorites(posKey);
    const favoritesOnly = window.__NET_FAVORITES_ONLY__ === true || loadNetworkFavoritesOnly(posKey);
    const customUnits = Array.isArray(window.__NET_CUSTOM__)
      ? window.__NET_CUSTOM__
      : loadNetworkCustom(posKey);
    const allClusters = Array.isArray(window.__NET_LAST_PAYLOAD__?.all_clusters)
      ? window.__NET_LAST_PAYLOAD__.all_clusters
      : (Array.isArray(window.__NET_LAST_PAYLOAD__?.clusters) ? window.__NET_LAST_PAYLOAD__.clusters : []);
    const effectiveHidden = resolveNetworkHiddenForMode(
      allClusters,
      hidden,
      favorites,
      favoritesOnly
    );
    const order = Array.isArray(window.__NET_ORDER__) ? window.__NET_ORDER__ : [];
    const filteredOrder = order.filter(name => !effectiveHidden.has(String(name)));
    const payload = {
      start,
      end,
      cluster_order: filteredOrder.length > 0 ? filteredOrder : undefined,
      custom_units: customUnits,
      favorites_only: favoritesOnly,
      favorite_units: Array.from(favorites || []),
    };
    if (unitFilter) payload.units_only = unitFilter;
    const queued = await apiPost("/api/analysis/network-summary/export-job", payload);
    if (!queued || !queued.job_id) throw new Error("Сервер не вернул job_id");
    if (status) status.textContent = "Экспорт в очереди…";
    await waitExportJob(queued.job_id, (msg) => {
      if (status) status.textContent = msg;
    });
    await downloadExportJob(
      queued.job_id,
      unitFilter
        ? `Ucet_intensivnosti_${unitFilter.replace(/[^\w\u0400-\u04FF]+/gi, "_").slice(0, 40)}_${start.replace(/[:]/g, "-")}_${end.replace(/[:]/g, "-")}.xlsx`
        : `Ucet_intensivnosti_${start.replace(/[:]/g, "-")}_${end.replace(/[:]/g, "-")}.xlsx`
    );
    if (status) status.textContent = "Excel готов.";
  } catch (e) {
    if (status) status.textContent = `Ошибка: ${e.message || e}`;
  }
}

async function exportNetworkUnitSummary() {
  const unit = _networkExportUnitName();
  if (!unit) {
    alert("Укажите подразделение для выборочной выгрузки");
    return;
  }
  await exportNetworkSummary(unit);
}

async function mergeIntensity2hTo6h() {
  const status = $("net-merge-status");
  const inputs = ["net-merge-file-1", "net-merge-file-2", "net-merge-file-3"].map((id) => $(id));
  if (inputs.some((el) => !el)) return;

  const selected = inputs
    .map((el) => (el.files && el.files.length ? el.files[0] : null))
    .filter(Boolean);
  if (!selected.length) {
    if (status) status.textContent = "Выберите хотя бы одну двухчасовую таблицу.";
    return;
  }

  const fd = new FormData();
  selected.forEach((file, idx) => fd.append(`file${idx + 1}`, file));
  const tplInput = $("net-merge-template-6h");
  if (tplInput && tplInput.files && tplInput.files.length) {
    fd.append("template_6h", tplInput.files[0]);
  }

  try {
    if (status) status.textContent = "Сборка 6-часовой таблицы…";
    const res = await fetch("/api/analysis/intensity/merge-2h-to-6h", { method: "POST", body: fd });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    let filename = "Ucet_intensivnosti_6h_merged.xlsx";
    const cd = res.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename\*?=(?:UTF-8''|")?([^";]+)/i);
    if (m && m[1]) {
      try {
        filename = decodeURIComponent(m[1].replace(/"/g, "").trim());
      } catch (_e) {
        filename = m[1].replace(/"/g, "").trim();
      }
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    if (status) status.textContent = "6-часовая таблица готова — файл скачан.";
    const metaHdr = res.headers.get("X-Intensity-Merge-Meta");
    if (metaHdr && status) {
      try {
        const meta = JSON.parse(metaHdr);
        const n = meta.files_count || selected.length;
        status.textContent = `Готово: объединено ${n} файл(ов), интервалов: ${(meta.slots_updated || []).join(", ") || "—"}.`;
        const dup = Array.isArray(meta.duplicate_slots) ? meta.duplicate_slots : [];
        if (dup.length) {
          status.textContent += " Один интервал в нескольких файлах — значения сложены.";
        }
      } catch (_e) {
        // ignore
      }
    }
  } catch (e) {
    if (status) status.textContent = `Ошибка: ${e.message || e}`;
  }
}
function networkOrderStorageKey(positionKey) {
  return `wp_network_cluster_order::${String(positionKey || "__all__")}`;
}

function networkHiddenStorageKey(positionKey) {
  return `wp_network_cluster_hidden::${String(positionKey || "__all__")}`;
}

function networkCustomStorageKey(positionKey) {
  return `wp_network_cluster_custom::${String(positionKey || "__all__")}`;
}

function networkFavoritesStorageKey(positionKey) {
  return `wp_network_cluster_favorites::${String(positionKey || "__all__")}`;
}

function networkFavoritesOnlyStorageKey(positionKey) {
  return `wp_network_cluster_favorites_only::${String(positionKey || "__all__")}`;
}

function loadNetworkOrder(positionKey) {
  try {
    const raw = localStorage.getItem(networkOrderStorageKey(positionKey));
    const arr = JSON.parse(raw || "[]");
    return Array.isArray(arr) ? arr.map(String) : [];
  } catch (_e) {
    return [];
  }
}

function saveNetworkOrder(positionKey, order) {
  try {
    localStorage.setItem(networkOrderStorageKey(positionKey), JSON.stringify(order || []));
  } catch (_e) {
    // ignore
  }
}

function loadNetworkHidden(positionKey) {
  try {
    const raw = localStorage.getItem(networkHiddenStorageKey(positionKey));
    const arr = JSON.parse(raw || "[]");
    return new Set(Array.isArray(arr) ? arr.map(String) : []);
  } catch (_e) {
    return new Set();
  }
}

function saveNetworkHidden(positionKey, hidden) {
  try {
    const arr = Array.from(hidden || []);
    localStorage.setItem(networkHiddenStorageKey(positionKey), JSON.stringify(arr));
  } catch (_e) {
    // ignore
  }
}

function loadNetworkCustom(positionKey) {
  try {
    const raw = localStorage.getItem(networkCustomStorageKey(positionKey));
    const arr = JSON.parse(raw || "[]");
    return Array.isArray(arr) ? arr.map(String).filter(Boolean) : [];
  } catch (_e) {
    return [];
  }
}

function saveNetworkCustom(positionKey, list) {
  try {
    const arr = Array.isArray(list) ? list.map(String).filter(Boolean) : [];
    localStorage.setItem(networkCustomStorageKey(positionKey), JSON.stringify(arr));
  } catch (_e) {
    // ignore
  }
}

function loadNetworkFavorites(positionKey) {
  try {
    const raw = localStorage.getItem(networkFavoritesStorageKey(positionKey));
    const arr = JSON.parse(raw || "[]");
    return new Set(Array.isArray(arr) ? arr.map(String) : []);
  } catch (_e) {
    return new Set();
  }
}

/**
 * Избранное для режима «только избранное» в учёте интенсивности:
 * локальное (настройки таблицы) + то же избранное, что на вкладке «Сеансы» (БД).
 * Раньше учитывался только localStorage — подразделения из сеансов не попадали в список.
 */
async function loadMergedNetworkFavorites(positionKey) {
  const merged = new Set(loadNetworkFavorites(positionKey));
  try {
    const favData = await apiGet("/api/sessions/favorites?with_unit_names=1");
    const rows = Array.isArray(favData.favorites) ? favData.favorites : [];
    rows.forEach((f) => {
      const u = f && f.unit_name != null ? String(f.unit_name).trim() : "";
      if (u) merged.add(u);
    });
  } catch (_e) {
    // без сессий / прав — остаётся только localStorage
  }
  return merged;
}

function saveNetworkFavorites(positionKey, favorites) {
  try {
    const arr = Array.from(favorites || []);
    localStorage.setItem(networkFavoritesStorageKey(positionKey), JSON.stringify(arr));
  } catch (_e) {
    // ignore
  }
}

function loadNetworkFavoritesOnly(positionKey) {
  try {
    const raw = localStorage.getItem(networkFavoritesOnlyStorageKey(positionKey));
    return raw === "1";
  } catch (_e) {
    return false;
  }
}

function saveNetworkFavoritesOnly(positionKey, value) {
  try {
    localStorage.setItem(networkFavoritesOnlyStorageKey(positionKey), value ? "1" : "0");
  } catch (_e) {
    // ignore
  }
}

function mergeNetworkCustom(clusters, custom) {
  const src = Array.isArray(clusters) ? clusters.map(String) : [];
  const customList = Array.isArray(custom) ? custom.map(String) : [];
  const lowerMap = new Map(src.map((n) => [n.toLowerCase(), n]));
  const out = src.slice();
  for (const c of customList) {
    const name = String(c || "").trim();
    if (!name) continue;
    const key = name.toLowerCase();
    if (lowerMap.has(key)) continue;
    out.push(name);
    lowerMap.set(key, name);
  }
  return out;
}

function resolveNetworkHidden(clusters, hidden, favorites) {
  const hiddenSet = hidden instanceof Set ? new Set(hidden) : new Set();
  const favSet = favorites instanceof Set ? favorites : new Set();
  if (favSet.size > 0) {
    const eff = new Set();
    const list = Array.isArray(clusters) ? clusters : [];
    const favLower = new Set(
      [...favSet].map((s) => String(s || "").trim().toLowerCase())
    );
    list.forEach((n) => {
      const ns = String(n);
      if (!favLower.has(ns.trim().toLowerCase())) eff.add(ns);
    });
    hiddenSet.forEach((n) => eff.add(String(n)));
    return eff;
  }
  return hiddenSet;
}

function resolveNetworkHiddenForMode(clusters, hidden, favorites, favoritesOnly) {
  const hiddenPlain = hidden instanceof Set ? hidden : new Set(hidden || []);
  if (favoritesOnly) {
    const fav = favorites instanceof Set ? favorites : new Set();
    // «Только избранное» без ни одного избранного раньше скрывало все колонки — выглядело как пропажа данных.
    if (!fav.size) {
      return hiddenPlain;
    }
    return resolveNetworkHidden(clusters, hiddenPlain, fav);
  }
  return hiddenPlain;
}

function applyOrder(order, clusters, hidden) {
  const src = Array.isArray(clusters) ? clusters.map(String) : [];
  const hiddenSet = hidden instanceof Set ? hidden : new Set();
  const out = [];
  const seen = new Set();
  for (const x of Array.isArray(order) ? order : []) {
    const n = String(x || "");
    if (!n || seen.has(n)) continue;
    if (src.includes(n) && !hiddenSet.has(n)) {
      out.push(n);
      seen.add(n);
    }
  }
  for (const n of src) {
    if (!seen.has(n) && !hiddenSet.has(n)) out.push(n);
  }
  return out;
}

function initNetworkOrderUI(positionKey, clusters, hidden, favorites) {
  window.__NET_POS__ = positionKey;
  if (!Array.isArray(window.__NET_ORDER__)) {
    window.__NET_ORDER__ = Array.isArray(clusters) ? clusters.slice() : [];
  }
  if (!(window.__NET_HIDDEN__ instanceof Set)) {
    window.__NET_HIDDEN__ = hidden instanceof Set ? new Set(hidden) : new Set();
  }
  if (!(window.__NET_FAVORITES__ instanceof Set)) {
    window.__NET_FAVORITES__ = favorites instanceof Set ? new Set(favorites) : new Set();
  }
  if (!Array.isArray(window.__NET_CUSTOM__)) {
    window.__NET_CUSTOM__ = Array.isArray(loadNetworkCustom(positionKey))
      ? loadNetworkCustom(positionKey)
      : [];
  }

  const toggleBtn = $("net-order-toggle");
  const card = $("net-order-card");
  const list = $("net-order-list");
  const saveBtn = $("net-order-save");
  const shareBtn = $("net-order-share");
  const resetBtn = $("net-order-reset");
  const customInput = $("net-custom-input");
  const customAddBtn = $("net-custom-add");
  const orderSearch = $("net-order-search");
  const favoritesOnlyToggle = $("net-favorites-only");

  const getPersistedOrder = () => {
    const col = Array.isArray(window.__NET_COLUMN_ORDER__) ? window.__NET_COLUMN_ORDER__ : [];
    if (col.length) return col.slice();
    const shared = Array.isArray(window.__NET_SHARED_ORDER__) ? window.__NET_SHARED_ORDER__ : [];
    if (shared.length) return shared.slice();
    return loadNetworkOrder(positionKey);
  };

  const getWorkingOrder = () => {
    const order = Array.isArray(window.__NET_ORDER__) ? window.__NET_ORDER__ : [];
    if (order.length) return order.slice();
    return getPersistedOrder();
  };

  if (favoritesOnlyToggle) {
    const stored = loadNetworkFavoritesOnly(positionKey);
    favoritesOnlyToggle.checked = stored;
    window.__NET_FAVORITES_ONLY__ = stored;
    favoritesOnlyToggle.onchange = () => {
      const val = !!favoritesOnlyToggle.checked;
      window.__NET_FAVORITES_ONLY__ = val;
      saveNetworkFavoritesOnly(positionKey, val);
      render();
      updateTable();
    };
  }

  if (orderSearch) {
    orderSearch.oninput = () => {
      render();
    };
  }

  const updateTable = () => {
    const hiddenSet = window.__NET_HIDDEN__ || new Set();
    const favoritesSet = window.__NET_FAVORITES__ || new Set();
    const favoritesOnly = !!window.__NET_FAVORITES_ONLY__;
    const allClusters = Array.isArray(clusters) ? clusters : [];
    const effectiveHidden = resolveNetworkHiddenForMode(
      allClusters,
      hiddenSet,
      favoritesSet,
      favoritesOnly
    );
    const visibleClusters = allClusters.filter(c => !effectiveHidden.has(String(c)));
    const ordered = applyOrder(getWorkingOrder(), visibleClusters, effectiveHidden);

    const payload = window.__NET_LAST_PAYLOAD__;
    if (payload) {
      payload.clusters = ordered;
      window.__NET_ORDER__ = ordered.slice();
      renderNetworkTable(payload);
      renderNetworkActivityBlocks(payload);
    }
  };

  const render = () => {
    if (!list) return;
    list.innerHTML = "";
    const allClusters = Array.isArray(clusters) ? clusters : [];
    const hiddenSet = window.__NET_HIDDEN__ || new Set();
    const favoritesSet = window.__NET_FAVORITES__ || new Set();
    const favoritesOnly = !!window.__NET_FAVORITES_ONLY__;
    const effectiveHidden = resolveNetworkHiddenForMode(
      allClusters,
      hiddenSet,
      favoritesSet,
      favoritesOnly
    );
    const query = orderSearch ? String(orderSearch.value || "").trim().toLowerCase() : "";
    const visibleClusters = allClusters.filter(c => !effectiveHidden.has(String(c)));
    const orderedVisible = applyOrder(getWorkingOrder(), visibleClusters, effectiveHidden);
    const hiddenClusters = allClusters.filter(c => effectiveHidden.has(String(c)));
    const orderedAll = orderedVisible.concat(hiddenClusters);
    const listClusters = orderedAll.filter((n) => {
      if (!query) return true;
      return String(n || "").toLowerCase().includes(query);
    });

    listClusters.forEach((name, idx) => {
      const nameStr = String(name || "");
      const isHidden = effectiveHidden.has(nameStr);
      const item = document.createElement("div");
      item.className = `list-group-item d-flex align-items-center justify-content-between gap-2 ${isHidden ? "opacity-50" : ""}`;

      // Находим позицию в отсортированном списке (только для видимых)
      const ordered = orderedVisible;
      const visibleIdx = isHidden ? -1 : ordered.indexOf(nameStr);

      item.innerHTML = `
        <div class="d-flex align-items-center gap-2 flex-grow-1">
          <input type="checkbox" class="form-check-input" id="net-hidden-${idx}" ${isHidden ? "" : "checked"} 
                 style="cursor: pointer;" />
          <input type="number" class="form-control form-control-sm net-order-input" min="1"
                 value="${visibleIdx >= 0 ? visibleIdx + 1 : ""}" ${isHidden ? "disabled" : ""} style="width:64px;" />
          <label class="form-check-label fw-semibold ${isHidden ? "text-muted" : ""}" for="net-hidden-${idx}" style="cursor: pointer; flex-grow: 1;">
            ${escapeHtml(nameStr)}
          </label>
        </div>
        <div class="btn-group btn-group-sm" role="group">
          <button class="btn btn-outline-secondary" data-move="up" ${visibleIdx <= 0 ? "disabled" : ""} ${isHidden ? "disabled" : ""}>↑</button>
          <button class="btn btn-outline-secondary" data-move="down" ${visibleIdx < 0 || visibleIdx >= ordered.length - 1 ? "disabled" : ""} ${isHidden ? "disabled" : ""}>↓</button>
        </div>
      `;

      // Обработчик чекбокса
      const checkbox = item.querySelector(`#net-hidden-${idx}`);
      if (checkbox) {
        checkbox.addEventListener("change", (ev) => {
          const hidden = window.__NET_HIDDEN__ || new Set();
          if (ev.target.checked) {
            hidden.delete(nameStr);
          } else {
            hidden.add(nameStr);
          }
          window.__NET_HIDDEN__ = hidden;
          saveNetworkHidden(positionKey, hidden);
          render();
          updateTable();
        });
      }

      const orderInput = item.querySelector(".net-order-input");
      if (orderInput) {
        orderInput.addEventListener("change", () => {
          if (isHidden) return;
          const raw = Number(orderInput.value || 0);
          if (!Number.isFinite(raw) || raw <= 0) return;
          const allClusters = Array.isArray(clusters) ? clusters : [];
          const hiddenSet = window.__NET_HIDDEN__ || new Set();
          const visibleClusters = allClusters.filter(c => !hiddenSet.has(String(c)));
          const ordered = applyOrder(getWorkingOrder(), visibleClusters, hiddenSet);
          if (!ordered.length) return;
          const currentIdx = ordered.indexOf(nameStr);
          if (currentIdx < 0) return;
          const desired = Math.max(1, Math.min(ordered.length, Math.round(raw)));
          if (desired - 1 === currentIdx) return;
          const copy = ordered.slice();
          copy.splice(currentIdx, 1);
          copy.splice(desired - 1, 0, nameStr);
          window.__NET_ORDER__ = copy;
          saveNetworkOrder(positionKey, copy);
          render();
          updateTable();
        });
      }

      // Обработчики кнопок перемещения
      item.querySelectorAll("button[data-move]").forEach((btn) => {
        btn.addEventListener("click", () => {
          if (isHidden) return;
          const dir = btn.getAttribute("data-move");
          const o = Array.isArray(window.__NET_ORDER__) ? window.__NET_ORDER__ : [];
          const i = visibleIdx;
          const j = dir === "up" ? i - 1 : i + 1;
          if (j < 0 || j >= o.length) return;
          const copy = o.slice();
          const tmp = copy[i];
          copy[i] = copy[j];
          copy[j] = tmp;
          window.__NET_ORDER__ = copy;
          saveNetworkOrder(positionKey, copy);
          render();
          updateTable();
        });
      });
      list.appendChild(item);
    });
  };

  // when buildNetworkSummary calls renderNetworkTable we want last payload with maps
  // We'll update it here from the current DOM header if possible later.
  // The caller sets data and then calls initNetworkOrderUI; re-use that global.

  if (toggleBtn && card) {
    toggleBtn.onclick = () => {
      card.style.display = card.style.display === "none" ? "block" : "none";
      if (card.style.display !== "none") render();
    };
  }
  if (saveBtn) {
    saveBtn.onclick = async () => {
      const order = Array.isArray(window.__NET_ORDER__) ? window.__NET_ORDER__ : [];
      saveNetworkOrder(positionKey, order);
      const hidden = window.__NET_HIDDEN__ || new Set();
      saveNetworkHidden(positionKey, hidden);
      try {
        const res = await apiPost("/api/analysis/network-order/save", { order });
        const next = Array.isArray(res.order) ? res.order.map(String) : order;
        window.__NET_COLUMN_ORDER__ = next.slice();
        setText("net-status", "Порядок сохранён в базе для позиции.");
      } catch (e) {
        setText("net-status", `Локально сохранено. Сервер: ${e.message || e}`);
      }
    };
  }
  if (shareBtn) {
    shareBtn.onclick = async () => {
      const previousText = shareBtn.textContent;
      try {
        shareBtn.disabled = true;
        shareBtn.textContent = "Сохраняю…";
        const allClusters = Array.isArray(clusters) ? clusters : [];
        const orderToShare = applyOrder(getWorkingOrder(), allClusters, new Set());
        const res = await apiPost("/api/analysis/network-order/shared", { order: orderToShare });
        const nextOrder = Array.isArray(res.order) ? res.order.map(String) : orderToShare;
        window.__NET_SHARED_ORDER__ = nextOrder.slice();
        window.__NET_ORDER__ = nextOrder.slice();
        window.__NET_COLUMN_ORDER__ = [];
        setText("net-status", "Общий порядок сохранён для всех.");
        render();
        updateTable();
      } catch (e) {
        setText("net-status", `Ошибка общего порядка: ${e.message || e}`);
      } finally {
        shareBtn.disabled = false;
        shareBtn.textContent = previousText || "Сделать порядок для всех";
      }
    };
  }
  if (resetBtn) {
    resetBtn.onclick = async () => {
      const shared = Array.isArray(window.__NET_SHARED_ORDER__) ? window.__NET_SHARED_ORDER__ : [];
      window.__NET_ORDER__ = shared.length ? shared.slice() : (Array.isArray(clusters) ? clusters.slice() : []);
      window.__NET_HIDDEN__ = new Set();
      window.__NET_FAVORITES__ = new Set();
      window.__NET_CUSTOM__ = [];
      window.__NET_FAVORITES_ONLY__ = false;
      window.__NET_COLUMN_ORDER__ = [];
      saveNetworkOrder(positionKey, []); // reset stored
      saveNetworkHidden(positionKey, new Set());
      saveNetworkFavorites(positionKey, new Set());
      saveNetworkCustom(positionKey, []);
      saveNetworkFavoritesOnly(positionKey, false);
      if (favoritesOnlyToggle) favoritesOnlyToggle.checked = false;
      try {
        await apiPost("/api/analysis/network-order/save", { order: [] });
      } catch (_e) {
        // сброс только локальный (например режим «все позиции» без прав)
      }
      render();
      updateTable();
    };
  }
  if (customAddBtn && customInput) {
    customAddBtn.onclick = () => {
      const name = String(customInput.value || "").trim();
      if (!name) return;
      const current = loadNetworkCustom(positionKey);
      const merged = mergeNetworkCustom(current, [name]);
      saveNetworkCustom(positionKey, merged);
      window.__NET_CUSTOM__ = merged;
      clusters.splice(0, clusters.length, ...mergeNetworkCustom(clusters, [name]));
      const payload = window.__NET_LAST_PAYLOAD__;
      if (payload) {
        if (!payload.current) payload.current = {};
        if (!payload.previous) payload.previous = {};
        if (!payload.current[name]) payload.current[name] = { sessions: 0, correspondents: 0 };
        if (!payload.previous[name]) payload.previous[name] = { sessions: 0, correspondents: 0 };
      }
      customInput.value = "";
      render();
      updateTable();
    };
  }
  render();
}

  function boot() {
    if (!window.AnalysisRuntime?.isModule("network")) return;
    window.__ANALYSIS_ACTIVE_BUNDLE__ = "network";
    const netStart = $("net-start");
    const netEnd = $("net-end");
    const netPrev = $("net-prev");
    const netBuildBtn = $("net-build-btn");
    const netExportBtn = $("net-export-btn");
    const updatePrev = () => {
      if (!netStart || !netEnd || !netPrev) return;
      const pr = computePrevPeriod(netStart.value, netEnd.value);
      if (!pr) {
        netPrev.textContent = "—";
        return;
      }
      netPrev.textContent = fmtPrevRange(pr.prevStart, pr.prevEnd);
    };
    if (netStart && netEnd) {
      // По умолчанию — неделя: для общего анализа это информативнее старого 2-часового интервала.
      const now = new Date();
      const end = new Date(now.getTime());
      const start = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      const toIsoMin = (d) => {
        const pad = (n) => String(n).padStart(2, "0");
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(
          d.getMinutes()
        )}`;
      };
      if (!netEnd.value) netEnd.value = toIsoMin(end);
      if (!netStart.value) netStart.value = toIsoMin(start);
      updatePrev();
      netStart.addEventListener("change", updatePrev);
      netEnd.addEventListener("change", updatePrev);
    }
    if (netBuildBtn) netBuildBtn.addEventListener("click", buildNetworkSummary);
    if (netExportBtn) netExportBtn.addEventListener("click", () => exportNetworkSummary());
    if ($("net-export-unit-btn")) {
      $("net-export-unit-btn").addEventListener("click", exportNetworkUnitSummary);
    }
    if ($("net-preset-today")) {
      $("net-preset-today").addEventListener("click", () => applyNetworkDatePreset("today"));
    }
    if ($("net-preset-week")) {
      $("net-preset-week").addEventListener("click", () => applyNetworkDatePreset("week"));
    }
    if ($("net-preset-month")) {
      $("net-preset-month").addEventListener("click", () => applyNetworkDatePreset("month"));
    }
    const netUnitExport = $("net-unit-export");
    if (netUnitExport) {
      netUnitExport.addEventListener("input", _updateNetworkExportUnitBtn);
      netUnitExport.addEventListener("change", _updateNetworkExportUnitBtn);
    }
    const netUnitSearch = $("net-unit-search");
    if (netUnitSearch) {
      netUnitSearch.addEventListener("input", () => {
        const payload = window.__NET_LAST_PAYLOAD__;
        if (payload) renderNetworkTable(payload);
      });
    }
  }

  window.AnalysisRuntime?.onReady(boot);
})();
