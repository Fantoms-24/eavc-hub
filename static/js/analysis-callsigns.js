(function () {
  "use strict";

function toIsoLocalMin(d) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`;
}

function fmtLocalDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`;
}

let STATE = null;
let DAYS = 1;
/** "rolling" — последние N суток от текущего момента МСК; "calendar" — даты period_start … period_end inclusive. */
let PERIOD_MODE = "rolling";
let PERIOD_START_DATE = ""; // YYYY-MM-DD для запросов
let PERIOD_END_DATE = "";
let CALLSIGNS = [];
/** Сбрасывает кеш списка позывных при подмене массива или правке тега. */
let CALLSIGNS_FILTER_REV = 0;
let _filteredCallsignsCacheSig = "";
let _filteredCallsignsCached = null;
let UNITS = [];
let SELECTED_UNIT = "";
let SELECTED_PAIR = null; // {frequency, group}
let MODE = "pair"; // 'pair' | 'unit'
let CURRENT_DETAIL = null;
let LAST_STATS = {
  rows: [],
  frequency: "",
  group: "",
  allowAssign: false,
  unitName: "",
  statsDays: 1,
  periodKey: "",
  periodMode: "",
};
let LAST_STATS_SEQ = 0;
function callsignMatchesScope(c, scope) {
  if (!c) return false;
  const cf = String(c.frequency || "").trim();
  const cg = String(c.group_code || "").trim();
  const cu = String(c.unit_name || "").trim();
  if (scope.mode === "pair") {
    const u = String(scope.unit_name || "").trim();
    const f = String(scope.frequency || "").trim();
    const g = String(scope.group || "").trim();
    // ВАЖНО: фильтруем позывные по выбранному подразделению, иначе смешиваются (31 омбр + 425 и т.д.)
    if (u) {
      if (!cu) return false; // старые/общие без unit_name не показываем в конкретном подразделении
      if (cu !== u) return false;
    }
    if (cf && cg) return cf === f && cg === g;
    // "общие" (без пары) показываем везде
    return !cf && !cg && !cu;
  }
  if (scope.mode === "unit") {
    const u = String(scope.unit_name || "").trim();
    if (cu) return cu === u;
    // общие показываем
    return !cf && !cg;
  }
  return false;
}

function currentCallsignScope() {
  if (MODE === "unit") return { mode: "unit", unit_name: SELECTED_UNIT };
  if (SELECTED_PAIR) {
    return {
      mode: "pair",
      unit_name: SELECTED_UNIT,
      frequency: SELECTED_PAIR.frequency,
      group: SELECTED_PAIR.group,
    };
  }
  return { mode: "none" };
}

function periodQueryKey() {
  if (PERIOD_MODE === "calendar") {
    const a = String(PERIOD_START_DATE || "").trim();
    const b = String(PERIOD_END_DATE || "").trim() || a;
    if (!a) return "";
    return `c:${a}:${b}`;
  }
  const d = Number(DAYS);
  const pd = Number.isFinite(d) && [1, 3, 7].includes(d) ? d : 1;
  return `r:${pd}`;
}

function metricsDenominatorDays() {
  const ok = statsMatchCurrentScope();
  const n = ok ? Number(LAST_STATS.statsDays) || 1 : Number(DAYS) || 1;
  return Math.max(1, n);
}

function statsMatchCurrentScope() {
  const pk = periodQueryKey();
  if (!pk || String(LAST_STATS.periodKey || "") !== pk) return false;
  if (MODE === "unit") {
    return (
      !LAST_STATS.allowAssign &&
      String(LAST_STATS.unitName || "").trim() === String(SELECTED_UNIT || "").trim()
    );
  }
  if (MODE === "pair" && SELECTED_PAIR) {
    return (
      LAST_STATS.allowAssign &&
      String(LAST_STATS.frequency || "").trim() === String(SELECTED_PAIR.frequency || "").trim() &&
      String(LAST_STATS.group || "").trim() === String(SELECTED_PAIR.group || "").trim()
    );
  }
  return false;
}

/** Сбросить подсказку активности к классу пресета и календаря. */
function syncPresetPeriodUI() {
  $("p-1d")?.classList.toggle(
    "active",
    PERIOD_MODE === "rolling" && Number(DAYS) === 1
  );
  $("p-3d")?.classList.toggle(
    "active",
    PERIOD_MODE === "rolling" && Number(DAYS) === 3
  );
  $("p-7d")?.classList.toggle(
    "active",
    PERIOD_MODE === "rolling" && Number(DAYS) === 7
  );
}

function buildAnalysisStatsQueryBase(frequency, group) {
  let q = `frequency=${encodeURIComponent(frequency)}&group=${encodeURIComponent(group)}`;
  if (PERIOD_MODE === "calendar") {
    let a = String(PERIOD_START_DATE || "").trim();
    let b = String(PERIOD_END_DATE || "").trim() || a;
    if (!a) return null;
    if (a > b) {
      const t = a;
      a = b;
      b = t;
    }
    q += `&period_start=${encodeURIComponent(a)}&period_end=${encodeURIComponent(b)}`;
  } else {
    const pd = [1, 3, 7].includes(Number(DAYS)) ? Number(DAYS) : 1;
    q += `&days=${encodeURIComponent(pd)}`;
  }
  return q;
}

function buildUnitStatsQueryBase() {
  let q = `unit_name=${encodeURIComponent(SELECTED_UNIT)}`;
  if (PERIOD_MODE === "calendar") {
    let a = String(PERIOD_START_DATE || "").trim();
    let b = String(PERIOD_END_DATE || "").trim() || a;
    if (!a) return null;
    if (a > b) {
      const t = a;
      a = b;
      b = t;
    }
    q += `&period_start=${encodeURIComponent(a)}&period_end=${encodeURIComponent(b)}`;
  } else {
    const pd = [1, 3, 7].includes(Number(DAYS)) ? Number(DAYS) : 1;
    q += `&days=${encodeURIComponent(pd)}`;
  }
  return q;
}

/** null — статистика за период ещё не совпадает с контекстом; Set — множество кода (= ID корреспондента) с сеансами count > 0. */
function activeCorrespondentCodesForCurrentStats() {
  if (!statsMatchCurrentScope()) return null;
  const s = new Set();
  for (const r of LAST_STATS.rows || []) {
    if (Number(r.count || 0) > 0) s.add(String(r.code ?? "").trim());
  }
  return s;
}

/**
 * @param {{ skipActivePeriod?: boolean }} [opts]
 */
function filteredCallsignsForScope(opts) {
  const skipActive = !!(opts && opts.skipActivePeriod);
  const scope = currentCallsignScope();
  const q = ($("an-cs-filter")?.value || "").trim().toLowerCase();
  const tagMode = ($("an-cs-tag-filter")?.value || "all").trim();
  const activeOnly = !!$("an-cs-active-only")?.checked && !skipActive;
  let sig;
  const activeSig = `${activeOnly ? 1 : 0}|${skipActive ? 1 : 0}|${LAST_STATS_SEQ}|${periodQueryKey()}`;
  if (scope.mode === "pair") {
    sig = `p|${SELECTED_UNIT}|${SELECTED_PAIR?.frequency}|${SELECTED_PAIR?.group}|${q}|${tagMode}|${CALLSIGNS_FILTER_REV}|${activeSig}`;
  } else if (scope.mode === "unit") {
    sig = `u|${SELECTED_UNIT}|${q}|${tagMode}|${CALLSIGNS_FILTER_REV}|${activeSig}`;
  } else {
    sig = `n|${q}|${tagMode}|${CALLSIGNS_FILTER_REV}|${activeSig}`;
  }
  if (_filteredCallsignsCacheSig === sig && _filteredCallsignsCached) return _filteredCallsignsCached;

  let list = (CALLSIGNS || []).filter((c) => callsignMatchesScope(c, scope));
  if (tagMode === "tagged") {
    list = list.filter((c) => String(c.tag || "").trim());
  } else if (tagMode === "untagged") {
    list = list.filter((c) => !String(c.tag || "").trim());
  }
  if (q) {
    list = list.filter((c) => {
      const hay = `${c.label || ""} ${c.code || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }
  if (activeOnly) {
    const act = activeCorrespondentCodesForCurrentStats();
    if (act !== null) {
      list = list.filter((c) => act.has(String(c.code ?? "").trim()));
    }
  }
  list.sort((a, b) => {
    const ac = Number(a.code || 0);
    const bc = Number(b.code || 0);
    if (ac !== bc) return ac - bc;
    return String(a.label || "").localeCompare(String(b.label || ""), "ru");
  });
  _filteredCallsignsCacheSig = sig;
  _filteredCallsignsCached = list;
  return list;
}

function _analysisAfterCallsignTagSaved(cid, tag, desc, color) {
  const idx = (CALLSIGNS || []).findIndex((x) => Number(x.id) === Number(cid));
  if (idx >= 0) {
    CALLSIGNS[idx] = {
      ...CALLSIGNS[idx],
      tag: String(tag || "").trim(),
      tag_desc: String(desc || "").trim(),
      tag_color: String(color || "").trim(),
    };
    CALLSIGNS_FILTER_REV += 1;
  }
  renderCallsignPanel();
  if (MODE === "pair" && SELECTED_PAIR) {
    try {
      loadPairStats();
    } catch (_e) { }
  }
}

function editCallsignTag(callsign) {
  if (!callsign || !Number(callsign.id)) return;
  if (typeof openCallsignTagModal !== "function") {
    window.alert("Модал тега недоступен.");
    return;
  }
  openCallsignTagModal(callsign, () => {
    const tagEl = document.getElementById("cs-tag-input");
    const descEl = document.getElementById("cs-tag-desc");
    const useColorEl = document.getElementById("cs-tag-use-color");
    const colorEl = document.getElementById("cs-tag-color");
    const tag = tagEl ? String(tagEl.value || "").trim() : "";
    const desc = descEl ? String(descEl.value || "").trim() : "";
    const color = (useColorEl && useColorEl.checked && colorEl) ? String(colorEl.value || "").trim() : "";
    _analysisAfterCallsignTagSaved(callsign.id, tag, desc, color);
  });
}

function _tagTextColor(bgHex) {
  try {
    const h = String(bgHex || "").trim();
    if (!/^#[0-9a-fA-F]{6}$/.test(h)) return "";
    const r = parseInt(h.slice(1, 3), 16);
    const g = parseInt(h.slice(3, 5), 16);
    const b = parseInt(h.slice(5, 7), 16);
    // perceived luminance
    const yiq = (r * 299 + g * 587 + b * 114) / 1000;
    return yiq >= 140 ? "#111" : "#fff";
  } catch (_e) {
    return "";
  }
}

function tagBadgeHtml(tag, desc, color) {
  const t = String(tag || "").trim();
  if (!t) return "";
  const d = String(desc || "").trim();
  const c = String(color || "").trim();
  if (c && /^#[0-9a-fA-F]{6}$/.test(c)) {
    const tc = _tagTextColor(c) || "#111";
    return `<span class="badge border" title="${escapeHtml(d)}" style="background:${escapeHtml(
      c
    )}; color:${escapeHtml(tc)};">${escapeHtml(t)}</span>`;
  }
  return `<span class="badge text-bg-light border" title="${escapeHtml(d)}">${escapeHtml(t)}</span>`;
}

function _anHashInt(s) {
  const str = String(s || "");
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function _anTgAvatarHue(seed) {
  return _anHashInt(seed) % 360;
}

function _anTgInitials(label, code) {
  const l = String(label || "").trim();
  const c = String(code || "").trim();
  if (l.length >= 2) return l.slice(0, 2).toUpperCase();
  if (c.length >= 2) return c.slice(0, 2);
  return (l || c || "?").charAt(0).toUpperCase();
}

function _anProfileInfoRow(icon, label, valueHtml) {
  return `
    <div class="an2__info-row">
      <i class="bi bi-${icon}" aria-hidden="true"></i>
      <span>
        <div class="fw-semibold">${valueHtml}</div>
        <div class="small text-muted">${escapeHtml(label)}</div>
      </span>
    </div>
  `;
}

const AN_SCOPE_EXPANDED = new Set();

function updateAnSelection() {
  const el = $("an-selection");
  if (!el) return;
  if (!SELECTED_UNIT) {
    el.textContent = "—";
    return;
  }
  if (SELECTED_PAIR) {
    el.textContent = `${SELECTED_UNIT} · ${SELECTED_PAIR.frequency} ${SELECTED_PAIR.group}`;
  } else if (MODE === "unit") {
    el.textContent = `${SELECTED_UNIT} · все позывные`;
  } else {
    el.textContent = SELECTED_UNIT;
  }
}

function syncAnCsDrawer(open) {
  const root = document.getElementById("an-callsigns-root");
  const drawer = $("an-cs-drawer");
  const backdrop = $("an-cs-backdrop");
  const dutySection = $("an-duty-section");
  if (!root) return;
  const show = !!open && !!CURRENT_DETAIL;
  root.classList.toggle("an-cs-drawer-open", show);
  if (drawer) {
    drawer.hidden = !show;
    drawer.setAttribute("aria-hidden", show ? "false" : "true");
  }
  if (backdrop) {
    backdrop.hidden = !show;
    backdrop.setAttribute("aria-hidden", show ? "false" : "true");
  }
  if (dutySection) {
    dutySection.hidden = !SELECTED_PAIR;
  }
}

function closeAnCsDrawer() {
  CURRENT_DETAIL = null;
  syncAnCsDrawer(false);
  renderDetailPanel();
  renderCallsignPanel();
  if (LAST_STATS.rows && LAST_STATS.rows.length) {
    rerenderStats();
  }
  const root = document.querySelector(".md3-analysis-group");
  if (root && root.classList.contains("an-mobile-ui")) {
    setAnalysisMobileCallsignsSub("main");
  }
}

function setAnCallsignsMainTab(tab) {
  const root = document.getElementById("an-callsigns-root");
  if (!root) return;
  const t = tab === "corr" ? "corr" : "callsigns";
  root.querySelectorAll("[data-an-cs-main-tab]").forEach((btn) => {
    const on = btn.getAttribute("data-an-cs-main-tab") === t;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
  root.querySelectorAll("[data-an-cs-main-panel]").forEach((panel) => {
    const isList = panel.id === "an-cs-list" || panel.id === "an-corr-list";
    const on = panel.getAttribute("data-an-cs-main-panel") === t;
    if (isList) {
      panel.hidden = !on;
    } else {
      panel.hidden = !on;
    }
  });
}

function initAnCallsignsMessengerUi() {
  const root = document.getElementById("an-callsigns-root");
  if (!root) return;
  root.querySelectorAll("[data-an-cs-main-tab]").forEach((tab) => {
    tab.addEventListener("click", () =>
      setAnCallsignsMainTab(tab.getAttribute("data-an-cs-main-tab"))
    );
  });
  $("an-cs-close-detail-btn")?.addEventListener("click", closeAnCsDrawer);
  $("an-cs-backdrop")?.addEventListener("click", closeAnCsDrawer);
  setAnCallsignsMainTab("callsigns");
  syncAnCsDrawer(false);
}

function setDetail(detail) {
  CURRENT_DETAIL = detail || null;
  renderDetailPanel();
  syncAnCsDrawer(!!CURRENT_DETAIL);
  const rootMob = document.querySelector(".md3-analysis-group");
  if (rootMob && rootMob.classList.contains("an-mobile-ui") && CURRENT_DETAIL) {
    setAnalysisMobileCallsignsSub("main");
    syncAnCsDrawer(true);
  }
}

function detailMatchesCallsign(callsign) {
  if (!CURRENT_DETAIL || CURRENT_DETAIL.kind !== "callsign") return false;
  const id = Number(callsign && callsign.id ? callsign.id : 0);
  if (id && Number(CURRENT_DETAIL.callsign_id || 0) === id) return true;
  return String(callsign?.code || "") === String(CURRENT_DETAIL.code || "");
}

function detailMatchesCorrespondent(code, frequency, group) {
  if (!CURRENT_DETAIL || CURRENT_DETAIL.kind !== "correspondent") return false;
  return (
    String(code || "") === String(CURRENT_DETAIL.code || "") &&
    String(frequency || "") === String(CURRENT_DETAIL.frequency || "") &&
    String(group || "") === String(CURRENT_DETAIL.group || "")
  );
}

function renderDetailPanel() {
  const body = $("an-detail-body");
  const scope = $("an-detail-scope");
  const actions = $("an-detail-actions");
  const tagBtn = $("an-detail-tag-btn");
  const dutyBtn = $("an-detail-duty-btn");
  const hero = $("an-detail-hero");
  const avatar = $("an-detail-avatar");
  const nameEl = $("an-detail-name");
  if (!body || !scope || !actions || !tagBtn || !dutyBtn) return;

  if (!CURRENT_DETAIL) {
    scope.textContent = "—";
    if (hero) hero.hidden = true;
    body.innerHTML = `Выберите позывной или корреспондента в списке.`;
    actions.style.display = "none";
    syncAnCsDrawer(false);
    return;
  }

  let label = "";
  let code = "";
  let tag = "";
  let desc = "";
  let color = "";
  let count = null;
  let unitName = "";
  let frequency = "";
  let group = "";
  let callsignForActions = null;

  if (CURRENT_DETAIL.kind === "callsign") {
    const cs = CURRENT_DETAIL.callsign || {};
    label = String(cs.label || "—");
    code = String(cs.code || "");
    tag = String(cs.tag || "");
    desc = String(cs.tag_desc || "");
    color = String(cs.tag_color || "");
    unitName = String(cs.unit_name || "");
    frequency = String(cs.frequency || "");
    group = String(cs.group_code || "");
    callsignForActions = cs;
  } else if (CURRENT_DETAIL.kind === "correspondent") {
    code = String(CURRENT_DETAIL.code || "");
    count = Number(CURRENT_DETAIL.count || 0);
    frequency = String(CURRENT_DETAIL.frequency || "");
    group = String(CURRENT_DETAIL.group || "");
    const cs = callsignByCode(code, frequency, group);
    label = String((cs && cs.label) || code || "—");
    tag = String((cs && cs.tag) || "");
    desc = String((cs && cs.tag_desc) || "");
    color = String((cs && cs.tag_color) || "");
    unitName = String((cs && cs.unit_name) || "");
    callsignForActions = cs;
  }

  scope.textContent = `${SELECTED_UNIT || "—"}${frequency ? ` • ${frequency} ${group}` : ""}`;

  const hue = _anTgAvatarHue(code || label);
  const initials = _anTgInitials(label, code);
  if (hero) hero.hidden = false;
  if (avatar) {
    avatar.textContent = initials;
    avatar.style.setProperty("--an2-hue", String(hue));
  }
  if (nameEl) {
    nameEl.textContent = label || "—";
    if (code) {
      nameEl.innerHTML = `${escapeHtml(label || "—")} <span class="wp-mono text-muted">(${escapeHtml(code)})</span>`;
    }
  }

  const rows = [];
  if (code) rows.push(_anProfileInfoRow("hash", "Код / ID", `<span class="wp-mono">${escapeHtml(code)}</span>`));
  if (tag) {
    rows.push(
      _anProfileInfoRow(
        "tag",
        "Тег",
        `${tagBadgeHtml(tag, desc, color)}${desc ? `<div class="small mt-1">${escapeHtml(desc)}</div>` : ""}`
      )
    );
  }
  if (unitName) rows.push(_anProfileInfoRow("building", "Подразделение", escapeHtml(unitName)));
  if (frequency && group) {
    rows.push(
      _anProfileInfoRow("broadcast", "Частота / группа", `<span class="wp-mono">${escapeHtml(frequency)} ${escapeHtml(group)}</span>`)
    );
  }
  if (count !== null) {
    rows.push(_anProfileInfoRow("activity", "Сеансов за период", escapeHtml(String(count))));
  }
  body.innerHTML = rows.length
    ? rows.join("")
    : `<div class="an2__info-row"><span class="text-muted">Нет дополнительных данных</span></div>`;

  actions.style.display = "grid";
  tagBtn.disabled = !callsignForActions;
  tagBtn.onclick = async () => {
    if (!callsignForActions) return;
    await editCallsignTag(callsignForActions);
  };

  const canAssignDuty = !!SELECTED_PAIR && callsignForActions && String(callsignForActions.code || "");
  dutyBtn.disabled = !canAssignDuty;
  dutyBtn.onclick = async () => {
    if (!canAssignDuty) return;
    try {
      const assignments = getCurrentAssignments();
      const isDuty = getDutyCodes(assignments).includes(
        String(callsignForActions.code || "")
      );
      const payloadCode = String(callsignForActions.code || "");
      await apiPost("/api/analysis/assign", {
        frequency: SELECTED_PAIR.frequency,
        group: SELECTED_PAIR.group,
        role_type: "duty",
        code: payloadCode,
        mode: "toggle",
      });
      await loadPairStats();
    } catch (e) {
      $("an-status").textContent = `Ошибка: ${e.message || e}`;
    }
  };
}

const CALLSIGN_FILTER_DEBOUNCE_MS = 180;
let CALLSIGN_PANEL_FILTER_TIMER = null;

function flushCallsignPanelFilterTimer() {
  if (CALLSIGN_PANEL_FILTER_TIMER) {
    clearTimeout(CALLSIGN_PANEL_FILTER_TIMER);
    CALLSIGN_PANEL_FILTER_TIMER = null;
  }
}

function scheduleRenderCallsignPanelFromFilter() {
  flushCallsignPanelFilterTimer();
  CALLSIGN_PANEL_FILTER_TIMER = setTimeout(() => {
    CALLSIGN_PANEL_FILTER_TIMER = null;
    renderCallsignPanel();
  }, CALLSIGN_FILTER_DEBOUNCE_MS);
}

const UNIT_FILTER_DEBOUNCE_MS = 180;
let UNITS_FILTER_TIMER = null;

function flushUnitsFilterTimer() {
  if (UNITS_FILTER_TIMER) {
    clearTimeout(UNITS_FILTER_TIMER);
    UNITS_FILTER_TIMER = null;
  }
}

function scheduleRenderUnitsFromFilter() {
  flushUnitsFilterTimer();
  UNITS_FILTER_TIMER = setTimeout(() => {
    UNITS_FILTER_TIMER = null;
    renderUnits();
  }, UNIT_FILTER_DEBOUNCE_MS);
}

function flushAndRenderUnits() {
  flushUnitsFilterTimer();
  renderUnits();
}

function _an2EmptyHtml(title, hint) {
  return `<div class="an2-empty"><strong>${escapeHtml(title)}</strong>${hint ? escapeHtml(hint) : ""}</div>`;
}

function renderCallsignPanel() {
  flushCallsignPanelFilterTimer();
  const list = $("an-cs-list");
  if (!list) return;
  const scope = currentCallsignScope();
  if (scope.mode === "pair") {
    setText("an-cs-scope", `${scope.frequency} ${scope.group} · позывные`);
  } else if (scope.mode === "unit") {
    setText("an-cs-scope", `${SELECTED_UNIT || "—"} · все позывные подразделения`);
  } else if (SELECTED_UNIT) {
    setText("an-cs-scope", `${SELECTED_UNIT} · выберите частоту / группу или «Все позывные»`);
  } else {
    setText("an-cs-scope", "Выберите подразделение слева");
  }
  const items = filteredCallsignsForScope();
  list.innerHTML = "";
  if (!items.length) {
    const inactiveActiveFilter =
      !!$("an-cs-active-only")?.checked &&
      filteredCallsignsForScope({ skipActivePeriod: true }).length > 0;
    list.innerHTML = inactiveActiveFilter
      ? _an2EmptyHtml(
          "Нет активных позывных",
          "Снимите «активные» или откройте вкладку «Корреспонденты»."
        )
      : SELECTED_UNIT && !SELECTED_PAIR && MODE !== "unit"
        ? _an2EmptyHtml("Нет позывных", "Выберите пару частота/группа или «Все позывные подразделения».")
        : _an2EmptyHtml("Нет позывных", "Измените период или фильтры.");
    return;
  }
  const allowAssign = scope.mode === "pair" && !!SELECTED_PAIR;
  const frag = document.createDocumentFragment();
  for (const c of items) {
    const isSelected = detailMatchesCallsign(c);
    const label = String(c.label || "").trim() || "Без названия";
    const code = String(c.code || "").trim();
    const tag = String(c.tag || "").trim();
    const desc = String(c.tag_desc || "").trim();
    const color = String(c.tag_color || "").trim();
    const hue = _anTgAvatarHue(code || label);
    const initials = _anTgInitials(label, code);

    const row = document.createElement("button");
    row.type = "button";
    row.className = `an2-row${isSelected ? " an2-row--active" : ""}`;
    row.innerHTML = `
      <span class="an2-row__ava" style="--an2-hue:${hue}">${escapeHtml(initials)}</span>
      <span class="an2-row__body">
        <span class="an2-row__title">${escapeHtml(label)}${code ? ` <span class="wp-mono text-muted">(${escapeHtml(code)})</span>` : ""}</span>
        <span class="an2-row__sub">${tag ? escapeHtml(tag) + (desc ? " · " + escapeHtml(desc) : "") : "Без тега"}</span>
      </span>
      <span class="an2-row__side"></span>
    `;
    const meta = row.querySelector(".an2-row__side");
    if (meta) {
      const actions = document.createElement("span");
      actions.className = "d-flex gap-1";
      if (allowAssign) {
        actions.innerHTML = `
          <button type="button" class="btn btn-outline-primary btn-sm" data-assign="duty"><i class="bi bi-headset"></i></button>
          <button type="button" class="btn btn-outline-secondary btn-sm" data-action="tag"><i class="bi bi-tag"></i></button>
        `;
        actions.querySelectorAll("button[data-assign]").forEach((btn) => {
          btn.addEventListener("click", async (ev) => {
            ev.stopPropagation();
            try {
              await apiPost("/api/analysis/assign", {
                frequency: SELECTED_PAIR.frequency,
                group: SELECTED_PAIR.group,
                role_type: btn.dataset.assign,
                code: String(c.code || ""),
                mode: "toggle",
              });
              await loadPairStats();
            } catch (e) {
              $("an-status").textContent = `Ошибка: ${e.message || e}`;
            }
          });
        });
        actions.querySelector('button[data-action="tag"]')?.addEventListener("click", async (ev) => {
          ev.stopPropagation();
          try {
            await editCallsignTag(c);
          } catch (e) {
            $("an-status").textContent = `Ошибка: ${e.message || e}`;
          }
        });
      } else {
        actions.innerHTML = `<button type="button" class="btn btn-outline-secondary btn-sm" data-action="tag"><i class="bi bi-tag"></i></button>`;
        actions.querySelector('button[data-action="tag"]')?.addEventListener("click", async (ev) => {
          ev.stopPropagation();
          try {
            await editCallsignTag(c);
          } catch (e) {
            $("an-status").textContent = `Ошибка: ${e.message || e}`;
          }
        });
      }
      meta.appendChild(actions);
    }
    row.addEventListener("click", () => {
      setDetail({ kind: "callsign", callsign: c, callsign_id: c.id, code: c.code });
      renderCallsignPanel();
    });
    frag.appendChild(row);
  }
  list.appendChild(frag);
}

function renderUnits() {
  renderScopeTree();
}

function updateUnitAllButton() {
  const btn = $("unit-all-btn");
  if (!btn) return;
  btn.disabled = !SELECTED_UNIT;
  btn.classList.toggle("active", MODE === "unit" && !!SELECTED_UNIT);
}

function renderPairsForUnit() {
  renderScopeTree();
}

function renderScopeTree() {
  flushUnitsFilterTimer();
  const host = $("an-scope-tree");
  if (!host) {
    const wrapU = $("units-side");
    if (!wrapU) return;
    return;
  }
  host.innerHTML = "";
  const q = ($("unit-filter")?.value || "").trim().toLowerCase();
  const list = (UNITS || []).filter((u) => {
    const name = String(u.unit_name || "").toLowerCase();
    if (!q) return true;
    if (name.includes(q)) return true;
    const pairs = (u.pairs || []);
    return pairs.some((p) => `${p.frequency} ${p.group}`.toLowerCase().includes(q));
  });
  if (!list.length) {
    host.innerHTML = _an2EmptyHtml("Ничего не найдено", "Измените поиск.");
    return;
  }

  for (const u of list) {
    const name = String(u.unit_name || "");
    const pairs = (u.pairs || []);
    const isOpen = AN_SCOPE_EXPANDED.has(name);
    const isUnitActive = name === SELECTED_UNIT && !SELECTED_PAIR && MODE !== "unit";
    const isUnitMode = name === SELECTED_UNIT && MODE === "unit";

    const block = document.createElement("div");
    block.className = `an2-unit${isOpen ? " an2-unit--open" : ""}`;

    const head = document.createElement("button");
    head.type = "button";
    head.className = `an2-unit__head${isUnitActive || isUnitMode ? " an2-unit__head--active" : ""}`;
    head.innerHTML = `<i class="bi bi-chevron-right an2-unit__chev" aria-hidden="true"></i><span class="text-truncate">${escapeHtml(name)}</span>`;
    head.addEventListener("click", () => {
      if (AN_SCOPE_EXPANDED.has(name)) AN_SCOPE_EXPANDED.delete(name);
      else AN_SCOPE_EXPANDED.add(name);
      if (SELECTED_UNIT !== name) {
        SELECTED_UNIT = name;
        SELECTED_PAIR = null;
        MODE = "pair";
        syncGraphContext();
        updateAnSelection();
        updateUnitAllButton();
        clearMain();
        renderCallsignPanel();
        requestGraphRefresh();
      }
      renderScopeTree();
    });
    block.appendChild(head);

    const pairsWrap = document.createElement("div");
    pairsWrap.className = "an2-unit__pairs";

    if (isOpen && pairs.length) {
      const allBtn = document.createElement("button");
      allBtn.type = "button";
      allBtn.className = `an2-pair an2-pair--unit-wide${isUnitMode ? " an2-pair--active" : ""}`;
      allBtn.textContent = "Все позывные подразделения";
      allBtn.addEventListener("click", async () => {
        SELECTED_UNIT = name;
        SELECTED_PAIR = null;
        MODE = "unit";
        AN_SCOPE_EXPANDED.add(name);
        syncGraphContext();
        updateAnSelection();
        updateUnitAllButton();
        clearMain();
        renderScopeTree();
        renderCallsignPanel();
        await loadUnitStats();
        requestGraphRefresh();
      });
      pairsWrap.appendChild(allBtn);

      for (const p of pairs) {
        const key = `${p.frequency} ${p.group}`;
        const active =
          SELECTED_PAIR &&
          SELECTED_PAIR.frequency === p.frequency &&
          SELECTED_PAIR.group === p.group &&
          SELECTED_UNIT === name;
        const pairBtn = document.createElement("button");
        pairBtn.type = "button";
        pairBtn.className = `an2-pair${active ? " an2-pair--active" : ""}`;
        pairBtn.textContent = key;
        pairBtn.addEventListener("click", async (ev) => {
          ev.stopPropagation();
          SELECTED_UNIT = name;
          SELECTED_PAIR = { frequency: p.frequency, group: p.group };
          MODE = "pair";
          AN_SCOPE_EXPANDED.add(name);
          syncGraphContext();
          updateAnSelection();
          updateUnitAllButton();
          renderScopeTree();
          renderCallsignPanel();
          await loadPairStats();
          requestGraphRefresh();
        });
        pairsWrap.appendChild(pairBtn);
      }
    } else if (isOpen && !pairs.length) {
      pairsWrap.innerHTML = `<div class="small text-muted px-2 py-1">Нет пар</div>`;
    }

    block.appendChild(pairsWrap);
    host.appendChild(block);
  }
  setText("unit-selected-label", SELECTED_UNIT || "—");
}

function setPeriod(days) {
  DAYS = days;
  PERIOD_MODE = "rolling";
  PERIOD_START_DATE = "";
  PERIOD_END_DATE = "";
  const sEl = $("an-period-start");
  const eEl = $("an-period-end");
  if (sEl) sEl.value = "";
  if (eEl) eEl.value = "";
  syncPresetPeriodUI();
  syncGraphContext();
  if (MODE === "unit") loadUnitStats();
  else loadPairStats();
}

function applyCalendarPeriodFromInputs() {
  let s = String($("an-period-start")?.value || "").trim();
  let e = String($("an-period-end")?.value || "").trim() || s;
  if (!s) {
    if ($("an-status")) $("an-status").textContent = "Укажите дату «с» или переключитесь на сутки/трое/неделю.";
    return;
  }
  if (s > e) {
    const t = s;
    s = e;
    e = t;
  }
  if ($("an-period-start")) $("an-period-start").value = s;
  if ($("an-period-end")) $("an-period-end").value = e;
  PERIOD_START_DATE = s;
  PERIOD_END_DATE = e;
  PERIOD_MODE = "calendar";
  syncPresetPeriodUI();
  syncGraphContext();
  if (MODE === "unit") loadUnitStats();
  else loadPairStats();
}

function labelByCode(code, frequency, group) {
  const cc = String(code);
  const u = String(SELECTED_UNIT || "").trim();
  const f = String(frequency || "").trim();
  const g = String(group || "").trim();
  // 1) точное совпадение по паре
  if (f && g) {
    const exact = (CALLSIGNS || []).find(
      (x) =>
        String(x.code) === cc &&
        String(x.frequency || "").trim() === f &&
        String(x.group_code || "").trim() === g &&
        // и по подразделению (если выбрано)
        (!u ? true : String(x.unit_name || "").trim() === u)
    );
    if (exact) return String(exact.label || "");
  }
  // 2) общий (без пары)
  const global = (CALLSIGNS || []).find(
    (x) =>
      String(x.code) === cc &&
      !String(x.frequency || "").trim() &&
      !String(x.group_code || "").trim() &&
      // не подмешиваем "общие" в конкретное подразделение, чтобы не было путаницы
      (!u ? true : !String(x.unit_name || "").trim())
  );
  if (global) return String(global.label || "");
  // 3) любой
  const any = (CALLSIGNS || []).find(
    (x) => String(x.code) === cc && (!u ? true : String(x.unit_name || "").trim() === u)
  );
  return any ? String(any.label || "") : "";
}

function callsignByCode(code, frequency, group) {
  const cc = String(code);
  const u = String(SELECTED_UNIT || "").trim();
  const f = String(frequency || "").trim();
  const g = String(group || "").trim();
  // 1) точное совпадение по паре
  if (f && g) {
    const exact = (CALLSIGNS || []).find(
      (x) =>
        String(x.code) === cc &&
        String(x.frequency || "").trim() === f &&
        String(x.group_code || "").trim() === g &&
        (!u ? true : String(x.unit_name || "").trim() === u)
    );
    if (exact) return exact;
  }
  // 2) общий (без пары)
  const global = (CALLSIGNS || []).find(
    (x) =>
      String(x.code) === cc &&
      !String(x.frequency || "").trim() &&
      !String(x.group_code || "").trim() &&
      (!u ? true : !String(x.unit_name || "").trim())
  );
  if (global) return global;
  // 3) любой
  const any = (CALLSIGNS || []).find(
    (x) => String(x.code) === cc && (!u ? true : String(x.unit_name || "").trim() === u)
  );
  return any || null;
}

function getDutyCodes(assignments) {
  const raw = assignments && assignments.duty ? assignments.duty : [];
  if (Array.isArray(raw)) {
    return raw.map((x) => String(x || "").trim()).filter((x) => x);
  }
  if (typeof raw === "string") {
    return raw
      .split(",")
      .map((x) => String(x || "").trim())
      .filter((x) => x);
  }
  return [];
}

function renderAssignments(assignments, correspondentsCount) {
  CURRENT_ASSIGNMENTS = assignments || {};
  const dutyCodes = getDutyCodes(assignments);
  const f = SELECTED_PAIR ? SELECTED_PAIR.frequency : "";
  const g = SELECTED_PAIR ? SELECTED_PAIR.group : "";

  // Отображаем количество корреспондентов
  const countEl = $("duty-correspondents-count");
  if (countEl) {
    if (correspondentsCount !== undefined && correspondentsCount !== null) {
      const count = Number(correspondentsCount || 0);
      countEl.textContent = `${count} ID`;
    } else {
      countEl.textContent = "—";
    }
  }

  if (!dutyCodes.length) {
    $("duty-box").innerHTML = '<span class="text-muted small">Не назначен</span>';
    return;
  }
  const itemsHtml = dutyCodes
    .map((code) => {
      const cs = callsignByCode(code, f, g);
      const label = (cs && cs.label) || labelByCode(code, f, g) || "—";
      const hue = _anTgAvatarHue(code || label);
      const initials = _anTgInitials(label, code);
      const tagHtml =
        cs && (cs.tag || cs.tag_desc)
          ? `<div class="small mt-1">${tagBadgeHtml(
            cs.tag || "тег",
            cs.tag_desc || "",
            cs.tag_color || ""
          )}</div>`
          : "";
      return `
        <div class="d-flex align-items-center gap-2 mb-2">
          <span class="an2-row__ava" style="--an2-hue:${hue};width:2rem;height:2rem;font-size:0.65rem;">${escapeHtml(initials)}</span>
          <span>
            <div class="fw-semibold small">${escapeHtml(label)}</div>
            <div class="wp-mono small text-muted">${escapeHtml(`(${code})`)}</div>
            ${tagHtml}
          </span>
        </div>
      `;
    })
    .join("");
  $("duty-box").innerHTML = itemsHtml;
}

function cacheStats(rows, frequency, group, allowAssign, unitName, periodPayload) {
  const pp = periodPayload && typeof periodPayload === "object" ? periodPayload : {};
  LAST_STATS_SEQ += 1;
  let sd =
    pp.days != null && !Number.isNaN(Number(pp.days))
      ? Number(pp.days)
      : Number(DAYS) || 1;
  sd = Math.max(1, sd);
  LAST_STATS = {
    rows: Array.isArray(rows) ? rows.slice() : [],
    frequency: String(frequency || ""),
    group: String(group || ""),
    allowAssign: !!allowAssign,
    unitName: String(unitName || ""),
    statsDays: sd,
    periodKey: String(pp.period_key || ""),
    periodMode: String(pp.period_mode || ""),
  };
}

function applyCorrFilters(rows, frequency, group) {
  const q = ($("an-corr-filter")?.value || "").trim().toLowerCase();
  const minRaw = ($("an-corr-min")?.value || "").trim();
  const minCount = minRaw === "" ? null : Number(minRaw);
  const sortMode = ($("an-corr-sort")?.value || "count_desc").trim();

  let list = Array.isArray(rows) ? rows.slice() : [];
  if (q) {
    list = list.filter((r) => {
      const label = labelByCode(r.code, frequency, group) || r.label || "";
      const hay = `${label} ${r.code || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }
  if (!Number.isNaN(minCount) && minCount !== null) {
    list = list.filter((r) => Number(r.count || 0) >= minCount);
  }

  if (sortMode === "count_asc") {
    list.sort((a, b) => Number(a.count || 0) - Number(b.count || 0));
  } else if (sortMode === "code") {
    list.sort((a, b) => String(a.code || "").localeCompare(String(b.code || ""), "ru"));
  } else if (sortMode === "label") {
    list.sort((a, b) => {
      const al = labelByCode(a.code, frequency, group) || a.label || "";
      const bl = labelByCode(b.code, frequency, group) || b.label || "";
      return String(al).localeCompare(String(bl), "ru");
    });
  } else {
    list.sort((a, b) => Number(b.count || 0) - Number(a.count || 0));
  }
  return list;
}

function updateCorrCount(total, filtered) {
  const el = $("an-corr-count");
  if (!el) return;
  el.textContent = `${filtered} из ${total}`;
}

function rerenderStats() {
  renderStatsTable(LAST_STATS.rows, LAST_STATS.frequency, LAST_STATS.group, LAST_STATS.allowAssign);
}

function renderStatsTable(rows, frequency, group, allowAssign) {
  const list = $("an-corr-list");
  if (!list) return;
  list.innerHTML = "";

  const sorted = (rows || [])
    .slice()
    .sort((a, b) => Number(b.count || 0) - Number(a.count || 0));

  // Вычисляем максимум для прогресс-баров
  const maxCount =
    sorted.length > 0
      ? Math.max(...sorted.map((r) => Number(r.count || 0)))
      : 1;
  let totalSessions = 0;
  sorted.forEach((r) => (totalSessions += Number(r.count || 0)));

  // Обновляем метрики
  updateMetrics(sorted, totalSessions);

  const filtered = applyCorrFilters(sorted, frequency, group);
  updateCorrCount(sorted.length, filtered.length);
  if (!filtered.length) {
    list.innerHTML = _an2EmptyHtml("Нет корреспондентов", "За выбранный период и фильтры.");
    return;
  }

  for (let i = 0; i < filtered.length; i++) {
    const r = filtered[i];
    const isSelected = detailMatchesCorrespondent(r.code, frequency, group);
    const label = labelByCode(r.code, frequency, group) || r.label || "";
    const code = String(r.code || "");
    const count = Number(r.count || 0);
    const percentage = maxCount > 0 ? Math.round((count / maxCount) * 100) : 0;
    const widthPercent = Math.max(8, percentage);
    const assignments = getCurrentAssignments();
    const isDuty = getDutyCodes(assignments).includes(code);
    const hue = _anTgAvatarHue(code || label);
    const initials = _anTgInitials(label, code);

    const item = document.createElement("button");
    item.type = "button";
    item.className = `an2-row${isSelected ? " an2-row--active" : ""}`;
    item.innerHTML = `
      <span class="an2-row__ava" style="--an2-hue:${hue}">${escapeHtml(initials)}</span>
      <span class="an2-row__body">
        <span class="an2-row__title">
          ${escapeHtml(label || "—")} <span class="wp-mono text-muted">(${escapeHtml(code)})</span>
          ${isDuty ? '<span class="assignment-badge duty ms-1"><i class="bi bi-headset"></i></span>' : ""}
        </span>
        <span class="an2-row__sub"><strong>${escapeHtml(String(count))}</strong> сеансов</span>
      </span>
      <span class="an2-row__side">
        <span class="an2-row__bar" style="width:${widthPercent}%;opacity:${0.35 + (percentage / 100) * 0.65}"></span>
      </span>
    `;
    const meta = item.querySelector(".an2-row__side");
    if (meta && allowAssign) {
      const bar = meta.querySelector(".an2-row__bar");
      meta.innerHTML = "";
      if (bar) meta.appendChild(bar);
      const actions = document.createElement("span");
      actions.className = "d-flex gap-1 mt-1";
      actions.innerHTML = `
          <button type="button" class="btn btn-outline-primary btn-sm ${isDuty ? "active" : ""}" data-assign="duty">
            <i class="bi bi-headset"></i>
          </button>
      `;
      meta.appendChild(actions);
      meta.querySelectorAll("button[data-assign]").forEach((btn) => {
        btn.addEventListener("click", async (ev) => {
          ev.stopPropagation();
          try {
            await apiPost("/api/analysis/assign", {
              frequency,
              group,
              role_type: btn.dataset.assign,
              code,
              mode: "toggle",
            });
            await loadPairStats();
          } catch (e) {
            $("an-status").textContent = `Ошибка: ${e.message || e}`;
          }
        });
      });
    }
    item.addEventListener("click", () => {
      setDetail({ kind: "correspondent", code: r.code, count: r.count, frequency, group });
      renderStatsTable(rows, frequency, group, allowAssign);
    });
    list.appendChild(item);
  }
}

let CURRENT_ASSIGNMENTS = {};

function getCurrentAssignments() {
  return CURRENT_ASSIGNMENTS;
}

function updateMetrics(rows, totalSessions) {
  const metricsRow = $("an-metrics-row");
  if (!metricsRow || rows.length === 0) {
    if (metricsRow) metricsRow.style.display = "none";
    return;
  }
  metricsRow.style.display = "flex";

  const activeCount = rows.length;
  const topCorrespondent = rows.length > 0 ? rows[0] : null;
  const avgPerDay = metricsDenominatorDays() > 0
    ? Math.round(totalSessions / metricsDenominatorDays())
    : 0;

  setText("metric-total", String(totalSessions));
  setText("metric-active", String(activeCount));
  setText("metric-top", topCorrespondent
    ? `${labelByCode(topCorrespondent.code, SELECTED_PAIR?.frequency || "", SELECTED_PAIR?.group || "") || "—"} (${topCorrespondent.count})`
    : "—");
  setText("metric-avg", String(avgPerDay));
}

async function loadState() {
  const data = await apiGet("/api/analysis/state");
  STATE = data;
  CALLSIGNS = data.callsigns || [];
  CALLSIGNS_FILTER_REV += 1;
  UNITS = data.units || [];
  if (!SELECTED_UNIT && UNITS.length) SELECTED_UNIT = UNITS[0].unit_name;
  if (SELECTED_UNIT) AN_SCOPE_EXPANDED.add(SELECTED_UNIT);
  syncGraphContext();
  updateAnSelection();
  renderScopeTree();
  updateUnitAllButton();
  renderCallsignPanel();
}

function clearMain() {
  if ($("duty-box")) $("duty-box").innerHTML = "—";
  if ($("duty-correspondents-count")) $("duty-correspondents-count").textContent = "—";
  if ($("duty-correspondents-count")) $("duty-correspondents-count").textContent = "—";
  if ($("an-corr-list")) $("an-corr-list").innerHTML = "";
  if ($("an-corr-count")) $("an-corr-count").textContent = "—";
  $("an-status").textContent = "";
  CURRENT_DETAIL = null;
  syncAnCsDrawer(false);
  LAST_STATS_SEQ += 1;
  LAST_STATS = {
    rows: [],
    frequency: "",
    group: "",
    allowAssign: false,
    unitName: "",
    statsDays: DAYS,
    periodKey: "",
    periodMode: "",
  };
  renderDetailPanel();
  renderCallsignPanel();
}

async function loadPairStats() {
  if (!SELECTED_PAIR) return;
  const frequency = SELECTED_PAIR.frequency;
  const group = SELECTED_PAIR.group;
  if (PERIOD_MODE === "calendar" && !String(PERIOD_START_DATE || "").trim()) return;
  $("an-status").textContent = "Загрузка…";
  try {
    const qb = buildAnalysisStatsQueryBase(frequency, group);
    if (!qb) return;
    const data = await apiGet(`/api/analysis/stats?${qb}`);
    const rows = data.rows || [];
    const correspondentsCount = rows.length;
    renderAssignments(data.assignments || {}, correspondentsCount);
    renderStatsTable(rows, frequency, group, true);
    cacheStats(rows, frequency, group, true, "", data);
    $("an-status").textContent = `Период: ${data.start} — ${data.end} МСК`;
    renderCallsignPanel();
  } catch (e) {
    $("an-status").textContent = `Ошибка: ${e.message || e}`;
  }
}

async function loadUnitStats() {
  if (!SELECTED_UNIT) return;
  MODE = "unit";
  if (PERIOD_MODE === "calendar" && !String(PERIOD_START_DATE || "").trim()) return;
  syncGraphContext();
  updateAnSelection();
  renderScopeTree();
  updateUnitAllButton();
  $("an-status").textContent = "Загрузка…";
  if ($("duty-box")) $("duty-box").innerHTML = "—";
  if ($("duty-correspondents-count")) $("duty-correspondents-count").textContent = "—";
  try {
    const qb = buildUnitStatsQueryBase();
    if (!qb) return;
    const data = await apiGet(`/api/analysis/unit-stats?${qb}`);
    renderStatsTable(data.rows || [], "", "", false);
    cacheStats(data.rows || [], "", "", false, SELECTED_UNIT, data);
    $("an-status").textContent = `Период: ${data.start} — ${data.end} МСК`;
    renderCallsignPanel();
  } catch (e) {
    $("an-status").textContent = `Ошибка: ${e.message || e}`;
  }
}

async function exportCallsignForm() {
  try {
    const btn = $("an-export-form-btn");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Формирование…";
    }
    const queued = await apiPost("/api/analysis/callsigns/export-job", { days: DAYS });
    if (!queued || !queued.job_id) throw new Error("Сервер не вернул job_id");
    if ($("an-status")) $("an-status").textContent = "Экспорт в очереди…";
    await waitExportJob(queued.job_id, (msg) => {
      if ($("an-status")) $("an-status").textContent = msg;
    });
    await downloadExportJob(queued.job_id, "formulyar_pozivnyh.xlsx");
    if ($("an-status")) $("an-status").textContent = "Excel готов.";
  } catch (e) {
    $("an-status").textContent = `Ошибка экспорта формуляра: ${e.message || e}`;
  } finally {
    const btn = $("an-export-form-btn");
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<i class="bi bi-file-earmark-excel me-1"></i>Экспорт формуляра';
    }
  }
}


  function syncGraphContext() {
    window.__AN_GRAPH_CONTEXT = {
      selectedUnit: String(SELECTED_UNIT || ""),
      selectedPair: SELECTED_PAIR
        ? {
          frequency: String(SELECTED_PAIR.frequency || ""),
          group: String(SELECTED_PAIR.group || ""),
        }
        : null,
      mode: String(MODE || "pair"),
      days: Number(DAYS || 1),
      period_mode: PERIOD_MODE,
      period_start_day: PERIOD_START_DATE,
      period_end_day: PERIOD_END_DATE || PERIOD_START_DATE,
    };
  }

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  async function boot() {
    if (!window.AnalysisRuntime?.isModule("callsigns")) return;
    window.__ANALYSIS_ACTIVE_BUNDLE__ = "callsigns";

    const csSubdock = document.getElementById("an-mobile-subdock-callsigns");
    if (csSubdock) {
      csSubdock.addEventListener("click", function (ev) {
        const btn = ev.target && ev.target.closest ? ev.target.closest("[data-an-cs-sub]") : null;
        if (!btn) return;
        setAnalysisMobileCallsignsSub(btn.getAttribute("data-an-cs-sub"));
      });
    }
    initAnCallsignsMessengerUi();

    const formExportBtn = $("an-export-form-btn");
    if (formExportBtn) formExportBtn.addEventListener("click", exportCallsignForm);

    const unitFilter = $("unit-filter");
    if (unitFilter) {
      unitFilter.addEventListener("input", scheduleRenderUnitsFromFilter);
      unitFilter.addEventListener("blur", flushAndRenderUnits);
    }
    const unitAllBtn = $("unit-all-btn");
    if (unitAllBtn) {
      unitAllBtn.addEventListener("click", async () => {
        if (!SELECTED_UNIT) return;
        SELECTED_PAIR = null;
        MODE = "unit";
        syncGraphContext();
        updateAnSelection();
        updateUnitAllButton();
        renderScopeTree();
        clearMain();
        await loadUnitStats();
        requestGraphRefresh();
      });
    }
    const anCsFilter = $("an-cs-filter");
    if (anCsFilter) {
      anCsFilter.addEventListener("input", scheduleRenderCallsignPanelFromFilter);
      anCsFilter.addEventListener("blur", () => {
        flushCallsignPanelFilterTimer();
        renderCallsignPanel();
      });
    }
    if ($("an-cs-tag-filter")) $("an-cs-tag-filter").addEventListener("change", renderCallsignPanel);
    if ($("an-cs-active-only")) $("an-cs-active-only").addEventListener("change", renderCallsignPanel);
    if ($("an-corr-filter")) $("an-corr-filter").addEventListener("input", rerenderStats);
    if ($("an-corr-min")) $("an-corr-min").addEventListener("input", rerenderStats);
    if ($("an-corr-sort")) $("an-corr-sort").addEventListener("change", rerenderStats);
    if ($("p-1d")) $("p-1d").addEventListener("click", () => setPeriod(1));
    if ($("p-3d")) $("p-3d").addEventListener("click", () => setPeriod(3));
    if ($("p-7d")) $("p-7d").addEventListener("click", () => setPeriod(7));
    if ($("an-period-apply")) $("an-period-apply").addEventListener("click", applyCalendarPeriodFromInputs);

    if ($("an-callsigns-root")) {
      setPeriod(1);
      await loadState();
    }

    window.__analysisCallsignsSyncGraph = syncGraphContext;
    syncGraphContext();
  }

  window.__analysisCallsignsSyncGraph = syncGraphContext;
  window.AnalysisRuntime?.onReady(boot);
})();
