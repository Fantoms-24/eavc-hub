(function () {
  "use strict";

function fmtMskLabel(s) {
  if (!s) return "";
  const str = String(s).trim();
  if (!str) return "";
  // ожидаем "YYYY-MM-DD HH:MM:SS" в UTC (SQLite CURRENT_TIMESTAMP) -> показываем в МСК (UTC+3)
  const m = str.match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})(?::(\d{2}))?/);
  if (m) {
    const y = Number(m[1]);
    const mo = Number(m[2]);
    const d = Number(m[3]);
    const hh = Number(m[4]);
    const mm = Number(m[5]);
    const ss = Number(m[6] || 0);
    const utcMs = Date.UTC(y, mo - 1, d, hh, mm, ss);
    const msk = new Date(utcMs + 3 * 60 * 60 * 1000);
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(msk.getUTCDate())}.${pad(msk.getUTCMonth() + 1)}.${msk.getUTCFullYear()} ${pad(
      msk.getUTCHours()
    )}:${pad(msk.getUTCMinutes())} МСК`;
  }
  return str.includes("МСК") ? str : `${str} МСК`;
}

function fmtShift(s) {
  return fmtMskLabel(s);
}

function renderShifts(sessions, selectedSession) {
  const sel = $("shift-select");
  sel.innerHTML = "";
  const currId = selectedSession ? Number(selectedSession.id || 0) : 0;
  for (const s of sessions || []) {
    const start = fmtShift(s.started_at);
    const end = s.ended_at ? fmtShift(s.ended_at) : "…";
    const opt = document.createElement("option");
    opt.value = String(s.id);
    opt.textContent = `${start} — ${end}`;
    if (Number(s.id) === currId) opt.selected = true;
    sel.appendChild(opt);
  }
  ACTIVE_SESSION_ID = currId;
  try {
    SHIFT_SELECT_PREV_VALUE = String(sel.value || "");
  } catch (_) { }
}

function _unitLabel(name) {
  const raw = String(name || "").trim();
  return raw || "—";
}

function _unitKey(name) {
  const raw = String(name || "").trim();
  if (!raw) return "";
  return raw.toLocaleLowerCase("ru-RU");
}

let _IX_OS_UNIT_LINK_INIT = false;

function _escapeAttr(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;");
}

function _formatCatalogPreviewHtml(c, extraSuffix) {
  const unitName = _unitLabel(c.unit_name);
  const loc = String(c.location || "").trim();
  const unitKey = String(c.unit_name || "").trim();
  const parts = [];
  if (unitKey && unitName !== "—") {
    parts.push(
      `<span role="link" tabindex="0" class="tg-chat-preview__unit" data-os-unit-key="${_escapeAttr(unitKey)}" title="Карточка в поиске онлайн">${escapeHtml(unitName)}</span>`
    );
  } else if (unitName && unitName !== "—") {
    parts.push(escapeHtml(unitName));
  }
  if (loc) {
    parts.push(`<span class="tg-chat-preview__loc">${escapeHtml(loc)}</span>`);
  }
  let html = parts.join('<span class="tg-chat-preview__sep" aria-hidden="true"> · </span>');
  if (extraSuffix) html += escapeHtml(extraSuffix);
  return html || escapeHtml(unitName);
}

function _ensureOnlineUnitLinkListener() {
  if (_IX_OS_UNIT_LINK_INIT) return;
  _IX_OS_UNIT_LINK_INIT = true;
  document.addEventListener("click", (ev) => {
    const el = ev.target.closest(".tg-chat-preview__unit[data-os-unit-key]");
    if (!el) return;
    ev.preventDefault();
    ev.stopPropagation();
    const uk = el.getAttribute("data-os-unit-key");
    if (!uk) return;
    if (typeof window.openOnlineSearchUnitModal === "function") {
      void window.openOnlineSearchUnitModal(uk);
    } else {
      window.location.href = `/search-online/battalion?k=${encodeURIComponent(uk)}`;
    }
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    const el = ev.target.closest(".tg-chat-preview__unit[data-os-unit-key]");
    if (!el) return;
    ev.preventDefault();
    el.click();
  });
}

function _normalizeUnitSet(set) {
  const next = new Set();
  for (const unit of set || []) {
    const key = _unitKey(unit);
    next.add(key || "—");
  }
  return next;
}

function _normalizeUnitOrder(order) {
  if (!Array.isArray(order)) return [];
  const out = [];
  for (const v of order) {
    const k = String(v || "").trim();
    if (k) out.push(k.toLocaleLowerCase("ru-RU"));
  }
  return out;
}

function _orderedUnitEntries(unitsMap) {
  const order = _normalizeUnitOrder(UNIT_ORDER);
  const out = [];
  const used = new Set();
  for (const key of order) {
    if (unitsMap.has(key)) {
      out.push([key, unitsMap.get(key)]);
      used.add(key);
    }
  }
  const rest = Array.from(unitsMap.entries()).filter(([k]) => !used.has(k));
  rest.sort((a, b) => String(a[1]?.label || "").localeCompare(String(b[1]?.label || ""), "ru"));
  return out.concat(rest);
}

async function saveUnitOrderFromDom(list) {
  if (!list) return;
  const order = Array.from(list.querySelectorAll(".unit-block"))
    .map((el) => String(el.getAttribute("data-unit-key") || "").trim())
    .filter(Boolean);
  UNIT_ORDER = order;
  try {
    await apiPost("/api/intercepts/unit-order", { order });
  } catch (e) {
    setText("intercepts-status", `Ошибка сохранения порядка: ${e.message || e}`);
  }
}

function _closeUnitMenus() {
  document.querySelectorAll(".unit-actions-menu").forEach((el) => {
    el.style.display = "none";
  });
}

function _ensureUnitMenuListener() {
  if (UNIT_MENU_LISTENER_SET) return;
  UNIT_MENU_LISTENER_SET = true;
  document.addEventListener("click", (ev) => {
    if (ev && ev.target && ev.target.closest(".unit-actions")) {
      return;
    }
    _closeUnitMenus();
  });
}

function _getGroupsSearchQuery() {
  const el = $("groups-search-input");
  if (el) return String(el.value || "").trim();
  return "";
}

function _updateGroupsSearchClearButton() {
  const btn = $("groups-search-clear");
  if (!btn) return;
  const q = _getGroupsSearchQuery();
  btn.style.display = q ? "inline-flex" : "none";
}

/**
 * Сопоставление строки поиска с записью каталога (подразделение, частота, группа, населённый пункт).
 */
function _catalogRowMatchesSearch(c, qLower) {
  if (!qLower) return true;
  const u = _unitLabel(c.unit_name).toLowerCase();
  const f = String(c.frequency || "").trim().toLowerCase();
  const g = String(c.group_code || "").trim().toLowerCase();
  const loc = String(c.location || "").trim().toLowerCase();
  const compactF = f.replace(/\s/g, "");
  const compactG = g.replace(/\s/g, "");
  const blob = `${u} ${f} ${g} ${loc} ${compactF} ${compactG}`;
  if (blob.includes(qLower)) return true;
  const qc = qLower.replace(/\s/g, "");
  if (qc && (compactF.includes(qc) || compactG.includes(qc) || u.replace(/\s/g, "").includes(qc))) {
    return true;
  }
  const tokens = qLower.split(/\s+/).filter(Boolean);
  if (tokens.length > 1) {
    return tokens.every((t) => t && blob.includes(t));
  }
  return false;
}

function _filterCatalogByGroupsSearch(catalog) {
  const q = _getGroupsSearchQuery().toLowerCase();
  if (!q) return (catalog || []).slice();
  return (catalog || []).filter((c) => _catalogRowMatchesSearch(c, q));
}

function _ixUseMobileCatalogList() {
  return (
    _ixIsMessengerUi() &&
    typeof ixViewportIsNarrow === "function" &&
    ixViewportIsNarrow() &&
    !(typeof ixViewportIsCompact === "function" && ixViewportIsCompact())
  );
}

function _catalogRowKey(c) {
  const id = Number((c && c.id) || 0);
  if (id > 0) return `id:${id}`;
  const f = String((c && c.frequency) || "").trim();
  const g = String((c && c.group_code) || "").trim();
  return f && g ? `pair:${f}|${g}` : "";
}

function _catalogMatchesActive(c) {
  if (!c) return false;
  const cid = Number(c.id || 0);
  if (cid > 0 && Number(ACTIVE_CATALOG_ID || 0) === cid) return true;
  if (!ACTIVE_CAT) return false;
  const cf = String(c.frequency || "").trim();
  const cg = String(c.group_code || "").trim();
  const af = String(ACTIVE_CAT.frequency || "").trim();
  const ag = String(ACTIVE_CAT.group_code || "").trim();
  return !!(cf && cg && af && ag && cf === af && cg === ag);
}

function _catalogPrefsKeyFromEntry(e) {
  const id = Number((e && e.catalog_id) || 0);
  if (id > 0) return `id:${id}`;
  const f = String((e && e.frequency) || "").trim();
  const g = String((e && e.group_code) || "").trim();
  return f && g ? `pair:${f}|${g}` : "";
}

function _catalogPrefsFavoriteSet() {
  const set = new Set();
  for (const e of (CATALOG_PREFS && CATALOG_PREFS.favorites) || []) {
    const k = _catalogPrefsKeyFromEntry(e);
    if (k) set.add(k);
  }
  return set;
}

function _catalogPrefsArchivedSet() {
  const set = new Set();
  for (const e of (CATALOG_PREFS && CATALOG_PREFS.archived) || []) {
    const k = _catalogPrefsKeyFromEntry(e);
    if (k) set.add(k);
  }
  return set;
}

function _parseCatalogUpdatedMs(raw) {
  const str = String(raw || "").trim();
  const m = str.match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})/);
  if (!m) return 0;
  return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]));
}

function _formatCatalogListTime(raw) {
  const ms = _parseCatalogUpdatedMs(raw);
  if (!ms) return "";
  const d = new Date(ms);
  const now = new Date();
  const sameDay =
    d.getUTCFullYear() === now.getUTCFullYear() &&
    d.getUTCMonth() === now.getUTCMonth() &&
    d.getUTCDate() === now.getUTCDate();
  const pad = (n) => String(n).padStart(2, "0");
  if (sameDay) return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
  return `${pad(d.getUTCDate())}.${pad(d.getUTCMonth() + 1)}`;
}

function _catalogIsStale(c) {
  const ms = _parseCatalogUpdatedMs(c && c.updated_at);
  if (!ms) return false;
  return Date.now() - ms > IX_CATALOG_STALE_MS;
}

// Защита от гонок: пока пользователь только что переключил избранное/архив,
// игнорируем входящие prefs из фонового /state — он мог стартовать раньше POST
// и принести устаревшие данные, перезатирающие свежий выбор.
let _CATALOG_PREFS_LOCK_UNTIL = 0;
const _CATALOG_PREFS_LOCK_MS = 1500;

function _catalogPrefsBumpLock() {
  _CATALOG_PREFS_LOCK_UNTIL = Date.now() + _CATALOG_PREFS_LOCK_MS;
}

function _catalogPrefsLocked() {
  return Date.now() < _CATALOG_PREFS_LOCK_UNTIL;
}

function _applyCatalogPrefs(data) {
  if (_catalogPrefsLocked()) return;
  const p = data && data.catalog_prefs;
  CATALOG_PREFS = {
    favorites: Array.isArray(p && p.favorites) ? p.favorites : [],
    archived: Array.isArray(p && p.archived) ? p.archived : [],
  };
}

async function _toggleCatalogFavorite(c) {
  if (!c) return;
  const key = _catalogRowKey(c);
  if (!key) return;
  const prevPrefs = {
    favorites: Array.isArray(CATALOG_PREFS.favorites) ? CATALOG_PREFS.favorites.slice() : [],
    archived: Array.isArray(CATALOG_PREFS.archived) ? CATALOG_PREFS.archived.slice() : [],
  };
  const wasFav = _catalogPrefsFavoriteSet().has(key);
  if (!wasFav && prevPrefs.favorites.length >= 5) {
    setText("intercepts-status", "В избранное можно добавить не больше 5 чатов");
    return;
  }
  const nextFavs = prevPrefs.favorites.filter((e) => _catalogPrefsKeyFromEntry(e) !== key);
  if (!wasFav) {
    nextFavs.push({
      catalog_id: Number(c.id || 0),
      frequency: String(c.frequency || ""),
      group_code: String(c.group_code || ""),
    });
  }
  CATALOG_PREFS = { favorites: nextFavs, archived: prevPrefs.archived };
  _catalogPrefsBumpLock();
  renderGroups((STATE && STATE.catalog) || []);
  try {
    const res = await apiPost("/api/intercepts/catalog/favorite", {
      catalog_id: Number(c.id || 0),
      frequency: String(c.frequency || ""),
      group_code: String(c.group_code || ""),
    });
    if (res && res.catalog_prefs) {
      CATALOG_PREFS = res.catalog_prefs;
      _catalogPrefsBumpLock();
      renderGroups((STATE && STATE.catalog) || []);
    }
    const added = !!res.added;
    setText(
      "intercepts-status",
      added ? "Добавлено в избранное" : "Убрано из избранного"
    );
  } catch (e) {
    CATALOG_PREFS = prevPrefs;
    _CATALOG_PREFS_LOCK_UNTIL = 0;
    renderGroups((STATE && STATE.catalog) || []);
    setText("intercepts-status", `Избранное: ${e.message || e}`);
  }
}

async function _toggleCatalogArchive(c) {
  if (!c) return;
  _catalogPrefsBumpLock();
  try {
    const res = await apiPost("/api/intercepts/catalog/archive", {
      catalog_id: Number(c.id || 0),
      frequency: String(c.frequency || ""),
      group_code: String(c.group_code || ""),
    });
    if (res && res.catalog_prefs) {
      CATALOG_PREFS = res.catalog_prefs;
      _catalogPrefsBumpLock();
      renderGroups((STATE && STATE.catalog) || []);
    }
  } catch (e) {
    setText("intercepts-status", `Ошибка: ${e.message || e}`);
  }
}

function _buildCatalogCatObj(c) {
  return {
    id: c.id,
    unit_name: c.unit_name || "",
    frequency: c.frequency || "",
    group_code: c.group_code || "",
    location: String(c.location || "").trim(),
    archived_only: !!c.archived_only,
  };
}

function _createCatalogFavButton(c, className) {
  const key = _catalogRowKey(c);
  const isFav = _catalogPrefsFavoriteSet().has(key);
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = `${className || "tg-chat-item__fav"}${isFav ? " is-active" : ""}`;
  btn.title = isFav ? "Убрать из избранного" : "В избранное (не больше 5)";
  btn.setAttribute("aria-label", isFav ? "Убрать из избранного" : "В избранное");
  btn.innerHTML = `<i class="bi ${isFav ? "bi-star-fill" : "bi-star"}" aria-hidden="true"></i>`;
  btn.addEventListener("click", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    _toggleCatalogFavorite(c);
  });
  return btn;
}

function _appendTgMobileChatRow(list, c, opts) {
  const catObj = _buildCatalogCatObj(c);
  const key = _catalogRowKey(c);
  const isActive = _catalogMatchesActive(c);
  const favSet = opts.favSet || _catalogPrefsFavoriteSet();
  const isFav = favSet.has(key);
  const inArchiveView = !!opts.inArchiveView;
  const unitName = _unitLabel(c.unit_name);
  const stale = _catalogIsStale(c);
  const timeLabel = _formatCatalogListTime(c.updated_at);

  const row = document.createElement("div");
  row.className = `tg-mobile-chat${isActive ? " tg-mobile-chat--active ix-catalog-row--selected" : ""}`;
  if (isActive) row.setAttribute("aria-current", "true");
  row.dataset.catalogKey = key;
  row.dataset.catalogId = String(c.id || 0);
  row.dataset.frequency = String(c.frequency || "").trim();
  row.dataset.groupCode = String(c.group_code || "").trim();
  row.addEventListener("mouseenter", () => _prefetchOpenItem(catObj.id, catObj), { passive: true });

  const hue = _tgAvatarHue(`${c.frequency}${c.group_code}`);
  const letter = String(c.group_code || c.frequency || "?").trim().charAt(0).toUpperCase() || "?";
  const staleHint = stale ? " · давно не в эфире" : "";
  const previewHtml = _formatCatalogPreviewHtml(c, staleHint);

  row.innerHTML = `
    <button type="button" class="tg-mobile-chat__open">
      <span class="tg-mobile-chat__avatar" style="--tg-avatar-hue:${hue}">${escapeHtml(letter)}</span>
      <span class="tg-mobile-chat__body">
        <span class="tg-mobile-chat__top">
          <span class="tg-mobile-chat__title">${escapeHtml(c.frequency || "")} ${escapeHtml(c.group_code || "")}</span>
          ${timeLabel ? `<span class="tg-mobile-chat__time">${escapeHtml(timeLabel)}</span>` : ""}
        </span>
        <span class="tg-mobile-chat__preview">${previewHtml}</span>
      </span>
      ${isFav ? '<span class="tg-mobile-chat__pin" title="Избранное"><i class="bi bi-pin-angle-fill"></i></span>' : ""}
    </button>
    <div class="tg-mobile-chat__actions"></div>
  `;

  row.querySelector(".tg-mobile-chat__open")?.addEventListener("click", () => {
    // Подсветку двигает только openItem: иначе при отказе от переключения
    // выделен один чат, а бланк остаётся от другого подразделения.
    openItem(catObj.id, catObj);
  });
  const actions = row.querySelector(".tg-mobile-chat__actions");
  if (actions) {
    actions.appendChild(_createCatalogFavButton(c, "tg-mobile-chat__act"));
    const arcBtn = document.createElement("button");
    arcBtn.type = "button";
    arcBtn.className = "tg-mobile-chat__act";
    arcBtn.dataset.act = "archive";
    arcBtn.title = inArchiveView ? "Из архива" : "В архив";
    arcBtn.setAttribute("aria-label", inArchiveView ? "Из архива" : "В архив");
    arcBtn.innerHTML = `<i class="bi ${inArchiveView ? "bi-box-arrow-up" : "bi-archive"}" aria-hidden="true"></i>`;
    arcBtn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      _toggleCatalogArchive(c);
    });
    actions.appendChild(arcBtn);
  }
  list.appendChild(row);
}

function _appendTgMobileSectionLabel(list, text) {
  const el = document.createElement("div");
  el.className = "tg-mobile-section-label";
  el.textContent = text;
  list.appendChild(el);
}

function renderGroupsMobileTg(catalogFiltered) {
  const list = $("groups-list");
  if (!list) return;
  list.innerHTML = "";
  list.classList.add("tg-mobile-catalog-list");

  const favSet = _catalogPrefsFavoriteSet();
  const arcSet = _catalogPrefsArchivedSet();
  const rows = (catalogFiltered || []).slice();
  const archivedRows = [];
  const favoriteRows = [];
  const mainRows = [];

  for (const c of rows) {
    const key = _catalogRowKey(c);
    if (!key) continue;
    if (arcSet.has(key)) {
      archivedRows.push(c);
      continue;
    }
    if (favSet.has(key)) favoriteRows.push(c);
    else mainRows.push(c);
  }

  const sortByActivity = (a, b) => _parseCatalogUpdatedMs(b.updated_at) - _parseCatalogUpdatedMs(a.updated_at);
  favoriteRows.sort(sortByActivity);
  mainRows.sort(sortByActivity);
  archivedRows.sort(sortByActivity);

  const showArchiveView = IX_MOBILE_CATALOG_LIST === "archive";
  const nav = $("ix-mobile-catalog-nav");
  if (nav) nav.hidden = false;

  if (!showArchiveView && archivedRows.length) {
    const archiveBtn = document.createElement("button");
    archiveBtn.type = "button";
    archiveBtn.className = "tg-mobile-archive-row";
    archiveBtn.innerHTML = `
      <span class="tg-mobile-archive-row__icon"><i class="bi bi-archive-fill"></i></span>
      <span class="tg-mobile-archive-row__body">
        <span class="tg-mobile-archive-row__title">Архив</span>
        <span class="tg-mobile-archive-row__sub">${archivedRows.length} чат(ов)</span>
      </span>
      <span class="tg-mobile-archive-row__badge">${archivedRows.length}</span>
    `;
    archiveBtn.addEventListener("click", () => {
      IX_MOBILE_CATALOG_LIST = "archive";
      renderGroups((STATE && STATE.catalog) || []);
    });
    list.appendChild(archiveBtn);
  }

  if (showArchiveView) {
    const back = document.createElement("button");
    back.type = "button";
    back.className = "tg-mobile-archive-back";
    back.innerHTML = '<i class="bi bi-arrow-left me-2"></i>К чатам';
    back.addEventListener("click", () => {
      IX_MOBILE_CATALOG_LIST = "main";
      renderGroups((STATE && STATE.catalog) || []);
    });
    list.appendChild(back);
    if (!archivedRows.length) {
      const empty = document.createElement("div");
      empty.className = "tg-mobile-empty";
      empty.textContent = "Архив пуст";
      list.appendChild(empty);
    } else {
      for (const c of archivedRows) _appendTgMobileChatRow(list, c, { favSet, inArchiveView: true });
    }
    return;
  }

  if (favoriteRows.length) {
    _appendTgMobileSectionLabel(list, "Избранное");
    for (const c of favoriteRows) _appendTgMobileChatRow(list, c, { favSet });
  }

  if (mainRows.length) {
    if (favoriteRows.length) _appendTgMobileSectionLabel(list, "Все чаты");
    for (const c of mainRows) _appendTgMobileChatRow(list, c, { favSet });
  }

  if (!favoriteRows.length && !mainRows.length && !archivedRows.length) {
    const empty = document.createElement("div");
    empty.className = "tg-mobile-empty";
    empty.textContent = "Каталог пуст. Добавьте группу.";
    list.appendChild(empty);
  }
}

function renderGroups(catalog) {
  const list = $("groups-list");
  if (!list) return;
  list.innerHTML = "";
  list.classList.remove("tg-mobile-catalog-list");
  const rawCatalog = catalog || [];
  if (!rawCatalog.length) {
    list.innerHTML = `<div class="ix-mobile-empty-state md3-groups-empty md3-groups-empty--muted" role="status">
      <span class="ix-mobile-empty-state__icon" aria-hidden="true"><i class="bi bi-chat-dots"></i></span>
      <p class="ix-mobile-empty-state__title">Каталог пуст</p>
      <p class="ix-mobile-empty-state__text">Добавьте группу через кнопку ниже или дождитесь загрузки смены.</p>
    </div>`;
    return;
  }
  const qActive = _getGroupsSearchQuery();
  const catalogFiltered = _filterCatalogByGroupsSearch(rawCatalog);
  if (qActive) {
    for (const c of catalogFiltered) {
      const uk = _unitKey(c.unit_name) || "—";
      EXPANDED_UNITS.add(uk);
      COLLAPSED_UNITS.delete(uk);
    }
  }
  if (!catalogFiltered.length) {
    list.innerHTML = `<div class="md3-groups-empty md3-groups-empty--warn">Нет совпадений по запросу. Измените поиск.</div>`;
    _updateGroupsSearchClearButton();
    return;
  }
  _updateGroupsSearchClearButton();
  _ensureUnitMenuListener();

  const favSet = _catalogPrefsFavoriteSet();
  const arcSet = _catalogPrefsArchivedSet();
  const catalogVisible = catalogFiltered.filter((c) => !arcSet.has(_catalogRowKey(c)));

  if (_ixUseMobileCatalogList()) {
    renderGroupsMobileTg(catalogFiltered);
    return;
  }

  const nav = $("ix-mobile-catalog-nav");
  if (nav) nav.hidden = true;

  // Группируем по подразделениям (с учётом поиска)
  const unitsMap = new Map();
  for (const c of catalogVisible) {
    const unitLabel = _unitLabel(c.unit_name);
    const unitKey = _unitKey(c.unit_name) || "—";
    if (!unitsMap.has(unitKey)) {
      unitsMap.set(unitKey, { label: unitLabel, items: [] });
    }
    unitsMap.get(unitKey).items.push(c);
  }

  // Определяем, развернуто ли подразделение
  const activeUnitKeyRaw = ACTIVE_CAT ? _unitKey(ACTIVE_CAT.unit_name) : "";
  const activeUnit = activeUnitKeyRaw || "—";
  const currentUnits = new Set(unitsMap.keys());

  // Нормализуем наборы (для кейса с разным регистром)
  EXPANDED_UNITS = _normalizeUnitSet(EXPANDED_UNITS);
  COLLAPSED_UNITS = _normalizeUnitSet(COLLAPSED_UNITS);

  // Очищаем состояние для подразделений, которых больше нет
  for (const unit of Array.from(EXPANDED_UNITS)) {
    if (!currentUnits.has(unit)) {
      EXPANDED_UNITS.delete(unit);
    }
  }
  for (const unit of Array.from(COLLAPSED_UNITS)) {
    if (!currentUnits.has(unit)) {
      COLLAPSED_UNITS.delete(unit);
    }
  }

  // Если есть активное подразделение, разворачиваем его (даже если было свернуто)
  if (activeUnit && currentUnits.has(activeUnit)) {
    EXPANDED_UNITS.add(activeUnit);
    COLLAPSED_UNITS.delete(activeUnit);
  }

  // Для новых подразделений (которых нет ни в EXPANDED_UNITS, ни в COLLAPSED_UNITS) - разворачиваем по умолчанию
  for (const unitName of currentUnits) {
    if (!EXPANDED_UNITS.has(unitName) && !COLLAPSED_UNITS.has(unitName)) {
      EXPANDED_UNITS.add(unitName); // По умолчанию развернуты
    }
  }

  const unitEntries = _orderedUnitEntries(unitsMap);
  // Рендерим каждое подразделение
  for (const [unitKey, bucket] of unitEntries) {
    const unitName = bucket.label;
    const items = (bucket.items || []).slice().sort((a, b) => {
      const fa = favSet.has(_catalogRowKey(a)) ? 0 : 1;
      const fb = favSet.has(_catalogRowKey(b)) ? 0 : 1;
      if (fa !== fb) return fa - fb;
      return _parseCatalogUpdatedMs(b.updated_at) - _parseCatalogUpdatedMs(a.updated_at);
    });
    // Подразделение развернуто, если оно в EXPANDED_UNITS и не в COLLAPSED_UNITS
    const isExpanded = EXPANDED_UNITS.has(unitKey) && !COLLAPSED_UNITS.has(unitKey);

    // Заголовок подразделения
    const unitBlock = document.createElement("div");
    unitBlock.className = "unit-block";
    unitBlock.dataset.unitKey = unitKey;

    const unitHeader = document.createElement("div");
    unitHeader.className = "unit-header d-flex align-items-center justify-content-between small text-uppercase fw-semibold wp-subtle mt-2";
    unitHeader.style.cursor = "pointer";
    unitHeader.style.userSelect = "none";
    unitHeader.draggable = true;

    const headerLeft = document.createElement("div");
    headerLeft.className = "d-flex align-items-center gap-2 flex-grow-1";

    // Иконка развернуто/свернуто
    const icon = document.createElement("i");
    icon.className = `bi ${isExpanded ? "bi-chevron-down" : "bi-chevron-right"}`;
    icon.style.fontSize = "0.75rem";
    icon.style.transition = "transform 0.2s";

    const grip = document.createElement("i");
    grip.className = "bi bi-grip-vertical unit-grip";
    grip.title = "Перетащить подразделение";
    const title = document.createElement("div");
    title.textContent = unitName;
    title.className = "flex-grow-1";

    headerLeft.appendChild(grip);
    headerLeft.appendChild(icon);
    headerLeft.appendChild(title);
    unitHeader.appendChild(headerLeft);

    const canManageUnit = CAN_START && unitName !== "—" && items.length > 0 && !items[0].archived_only;
    if (canManageUnit) {
      const actionsWrap = document.createElement("div");
      actionsWrap.className = "unit-actions";

      const settingsBtn = document.createElement("button");
      settingsBtn.type = "button";
      settingsBtn.className = "btn btn-sm btn-outline-secondary unit-manage-open-btn md3-unit-gear-btn";
      settingsBtn.innerHTML = "<i class='bi bi-gear'></i>";
      settingsBtn.title = "Настройки подразделения";
      settingsBtn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        openUnitManageModal(unitKey, unitName);
      });

      actionsWrap.appendChild(settingsBtn);
      unitHeader.appendChild(actionsWrap);
    }

    // Обработчик клика для сворачивания/разворачивания
    unitHeader.addEventListener("click", (ev) => {
      // Не сворачиваем, если кликнули на кнопку переименования или на саму кнопку
      if (ev.target.closest("button") || ev.target.tagName === "BUTTON" || ev.target.closest("i.bi-pencil")) {
        return;
      }

      ev.preventDefault();
      ev.stopPropagation();

      const currentExpanded = EXPANDED_UNITS.has(unitKey) && !COLLAPSED_UNITS.has(unitKey);
      if (currentExpanded) {
        // Сворачиваем: удаляем из развернутых и добавляем в свернутые
        EXPANDED_UNITS.delete(unitKey);
        COLLAPSED_UNITS.add(unitKey);
      } else {
        // Разворачиваем: добавляем в развернутые и удаляем из свернутых
        EXPANDED_UNITS.add(unitKey);
        COLLAPSED_UNITS.delete(unitKey);
      }

      // Перерисовываем список групп
      renderGroups(catalog);
    });

    unitHeader.addEventListener("dragstart", (ev) => {
      DRAG_UNIT_KEY = unitKey;
      unitBlock.classList.add("dragging");
      try {
        ev.dataTransfer.effectAllowed = "move";
        ev.dataTransfer.setData("text/plain", unitKey);
      } catch (_) { }
    });
    unitHeader.addEventListener("dragend", () => {
      unitBlock.classList.remove("dragging");
      list.querySelectorAll(".unit-block.drag-over").forEach((el) => el.classList.remove("drag-over"));
    });
    unitHeader.addEventListener("dragover", (ev) => {
      ev.preventDefault();
      unitBlock.classList.add("drag-over");
    });
    unitHeader.addEventListener("dragleave", () => {
      unitBlock.classList.remove("drag-over");
    });
    unitHeader.addEventListener("drop", async (ev) => {
      ev.preventDefault();
      unitBlock.classList.remove("drag-over");
      const srcKey = DRAG_UNIT_KEY || (ev.dataTransfer ? ev.dataTransfer.getData("text/plain") : "");
      if (!srcKey || srcKey === unitKey) return;
      const srcBlock = list.querySelector(`.unit-block[data-unit-key="${CSS.escape(srcKey)}"]`);
      if (!srcBlock) return;
      list.insertBefore(srcBlock, unitBlock);
      await saveUnitOrderFromDom(list);
    });

    unitBlock.appendChild(unitHeader);

    // Контейнер для групп (частот)
    const groupsContainer = document.createElement("div");
    groupsContainer.className = "unit-groups-container";
    groupsContainer.style.display = isExpanded ? "block" : "none";
    groupsContainer.style.overflow = "visible";
    groupsContainer.style.transition = "max-height 0.3s ease-out";

    // Рендерим группы этого подразделения
    for (const c of items) {
      // Убеждаемся, что объект c содержит location (может быть undefined в старых данных)
      if (typeof c.location === "undefined") {
        c.location = "";
      }
      const catObj = {
        id: c.id,
        unit_name: c.unit_name || "",
        frequency: c.frequency || "",
        group_code: c.group_code || "",
        location: String(c.location || "").trim(),
        archived_only: c.archived_only || false
      };
      const isActive = _catalogMatchesActive(c);
      const isFav = favSet.has(_catalogRowKey(c));
      const row = document.createElement("div");
      const useTgRow = _ixIsMessengerUi();
      row.className = useTgRow
        ? `list-group-item tg-chat-item${isActive ? " tg-chat-item--active active ix-catalog-row--selected" : ""}${isFav ? " tg-chat-item--favorite" : ""}`
        : `list-group-item${isActive ? " active ix-catalog-row--selected" : ""}`;
      if (isActive) row.setAttribute("aria-current", "true");
      row.dataset.catalogId = String(c.id || 0);
      row.dataset.frequency = String(c.frequency || "").trim();
      row.dataset.groupCode = String(c.group_code || "").trim();
      row.addEventListener("mouseenter", () => _prefetchOpenItem(catObj.id, catObj), { passive: true });

      const onDeleteRow = async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        if (!confirm(`Удалить ${c.unit_name} • ${c.frequency} ${c.group_code}?`)) return;
        setText("intercepts-status", "Удаляю…");
        try {
          await apiPost("/api/intercepts/catalog/delete", { id: c.id });
          if (ACTIVE_CATALOG_ID === Number(c.id || 0)) {
            ACTIVE_ITEM_ID = 0;
            ACTIVE_CATALOG_ID = 0;
            ACTIVE_CAT = null;
            $("intercept-text").value = "";
            setText("editor-subtitle", "Выбери группу слева");
            syncIxChatHeader();
          }
          await loadState(ACTIVE_SESSION_ID || null);
          setText("intercepts-status", "Удалено.");
        } catch (e) {
          setText("intercepts-status", `Ошибка: ${e.message || e}`);
        }
      };

      if (useTgRow) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "tg-chat-item__btn";
        const hue = _tgAvatarHue(`${c.frequency}${c.group_code}`);
        const letter = String(c.group_code || c.frequency || "?").trim().charAt(0).toUpperCase() || "?";
        const previewHtml = _formatCatalogPreviewHtml(c);
        btn.innerHTML = `
          <span class="tg-chat-item__avatar" style="background:hsl(${hue},48%,46%)">${escapeHtml(letter)}</span>
          <span class="tg-chat-item__body">
            <span class="tg-chat-item__top">
              <span class="tg-chat-item__title">${escapeHtml(c.frequency || "")} ${escapeHtml(c.group_code || "")}</span>
            </span>
            <span class="tg-chat-item__preview">${previewHtml}</span>
          </span>`;
        btn.addEventListener("click", () => {
          openItem(catObj.id, catObj);
        });
        btn.addEventListener("mouseenter", () => _prefetchOpenItem(catObj.id, catObj), { passive: true });
        row.appendChild(btn);
        row.appendChild(_createCatalogFavButton(c));

        if (CAN_START && !c.archived_only) {
          const del = document.createElement("button");
          del.type = "button";
          del.className = "tg-chat-item__del";
          del.innerHTML = "<i class='bi bi-x-lg' aria-hidden='true'></i>";
          del.title = "Удалить частоту/группу";
          del.setAttribute("aria-label", "Удалить");
          del.addEventListener("click", onDeleteRow);
          row.appendChild(del);
        }
      } else {
        const rowContent = document.createElement("div");
        rowContent.className = "d-flex align-items-center justify-content-between gap-2 w-100";

        const a = document.createElement("button");
        a.type = "button";
        a.className = "btn btn-link p-0 text-start flex-grow-1";
        a.innerHTML = `<span class="wp-mono fw-semibold">${escapeHtml(c.frequency || "")}  ${escapeHtml(c.group_code || "")}</span>`;
        a.addEventListener("click", () => {
          openItem(catObj.id, catObj);
        });
        a.addEventListener("mouseenter", () => _prefetchOpenItem(catObj.id, catObj), { passive: true });
        rowContent.appendChild(a);

        rowContent.appendChild(_createCatalogFavButton(c, "btn btn-sm btn-link p-0 tg-chat-item__fav"));

        if (CAN_START && !c.archived_only) {
          const del = document.createElement("button");
          del.type = "button";
          del.className = "btn btn-sm btn-outline-danger";
          del.innerHTML = "<i class='bi bi-x-lg'></i>";
          del.title = "Удалить частоту/группу";
          del.addEventListener("click", onDeleteRow);
          rowContent.appendChild(del);
        }
        row.appendChild(rowContent);
      }

      groupsContainer.appendChild(row);
    }

    unitBlock.appendChild(groupsContainer);
    list.appendChild(unitBlock);
  }
  LAST_CATALOG_RENDER_SIG = _catalogRenderSig(catalog);
}

function initInterceptsGroupsSearchControls() {
  const inp = $("groups-search-input");
  if (!inp) return;
  try {
    const saved = localStorage.getItem(GROUPS_SEARCH_STORAGE_KEY);
    if (saved && !String(inp.value || "").trim()) {
      inp.value = saved;
    }
  } catch (_) { }
  const applyFilter = () => {
    if (_groupsSearchDebounce) clearTimeout(_groupsSearchDebounce);
    _groupsSearchDebounce = setTimeout(() => {
      _groupsSearchDebounce = null;
      try {
        const t = _getGroupsSearchQuery();
        if (t) {
          localStorage.setItem(GROUPS_SEARCH_STORAGE_KEY, t);
        } else {
          localStorage.removeItem(GROUPS_SEARCH_STORAGE_KEY);
        }
      } catch (_) { }
      if (STATE && Array.isArray(STATE.catalog)) {
        renderGroups(STATE.catalog);
      }
    }, 120);
  };
  inp.addEventListener("input", applyFilter);
  inp.addEventListener("search", () => {
    if (!String(inp.value || "").trim()) {
      applyFilter();
    }
  });
  const clr = $("groups-search-clear");
  if (clr) {
    clr.addEventListener("click", (ev) => {
      ev.preventDefault();
      inp.value = "";
      try {
        localStorage.removeItem(GROUPS_SEARCH_STORAGE_KEY);
      } catch (_) { }
      if (STATE && Array.isArray(STATE.catalog)) {
        renderGroups(STATE.catalog);
      }
      _updateGroupsSearchClearButton();
      inp.focus();
    });
  }
  inp.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    inp.value = "";
    try {
      localStorage.removeItem(GROUPS_SEARCH_STORAGE_KEY);
    } catch (_) { }
    if (STATE && Array.isArray(STATE.catalog)) {
      renderGroups(STATE.catalog);
    }
    _updateGroupsSearchClearButton();
  });
  _updateGroupsSearchClearButton();
}

function _sha1Hex(str) {
  const msg = unescape(encodeURIComponent(String(str || "")));
  const words = [];
  for (let i = 0; i < msg.length; i++) {
    words[i >> 2] |= msg.charCodeAt(i) << (24 - (i % 4) * 8);
  }
  words[msg.length >> 2] |= 0x80 << (24 - (msg.length % 4) * 8);
  words[(((msg.length + 8) >> 6) << 4) + 15] = msg.length * 8;
  let h0 = 0x67452301;
  let h1 = 0xefcdab89;
  let h2 = 0x98badcfe;
  let h3 = 0x10325476;
  let h4 = 0xc3d2e1f0;
  for (let i = 0; i < words.length; i += 16) {
    const w = words.slice(i, i + 16);
    for (let j = 16; j < 80; j++) {
      w[j] = ((w[j - 3] ^ w[j - 8] ^ w[j - 14] ^ w[j - 16]) << 1) | ((w[j - 3] ^ w[j - 8] ^ w[j - 14] ^ w[j - 16]) >>> 31);
    }
    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    for (let j = 0; j < 80; j++) {
      let f;
      let k;
      if (j < 20) {
        f = (b & c) | (~b & d);
        k = 0x5a827999;
      } else if (j < 40) {
        f = b ^ c ^ d;
        k = 0x6ed9eba1;
      } else if (j < 60) {
        f = (b & c) | (b & d) | (c & d);
        k = 0x8f1bbcdc;
      } else {
        f = b ^ c ^ d;
        k = 0xca62c1d6;
      }
      const temp = (((a << 5) | (a >>> 27)) + f + e + k + (w[j] | 0)) | 0;
      e = d;
      d = c;
      c = ((b << 30) | (b >>> 2)) | 0;
      b = a;
      a = temp;
    }
    h0 = (h0 + a) | 0;
    h1 = (h1 + b) | 0;
    h2 = (h2 + c) | 0;
    h3 = (h3 + d) | 0;
    h4 = (h4 + e) | 0;
  }
  const hex = (n) => ("00000000" + (n >>> 0).toString(16)).slice(-8);
  return hex(h0) + hex(h1) + hex(h2) + hex(h3) + hex(h4);
}

function _catalogPrefsFp(prefs) {
  if (!prefs || typeof prefs !== "object") return "";
  try {
    const raw = JSON.stringify({
      archived: Array.isArray(prefs.archived) ? prefs.archived : [],
      favorites: Array.isArray(prefs.favorites) ? prefs.favorites : [],
    });
    return _sha1Hex(raw).slice(0, 12);
  } catch (_) {
    return "";
  }
}

function _stateSig(data) {
  if (data && data.state_sig) return String(data.state_sig);
  const cat = data && data.catalog ? data.catalog : [];
  const cs = data && data.callsigns ? data.callsigns : [];
  const sess = data && data.sessions ? data.sessions : [];
  let catMax = "";
  for (const c of cat) catMax = String(catMax > String(c.updated_at || "") ? catMax : (c.updated_at || ""));
  let csMax = "";
  for (const c of cs) csMax = String(csMax > String(c.updated_at || "") ? csMax : (c.updated_at || ""));
  let sessMax = "";
  for (const s of sess) {
    const a = String(s.started_at || "");
    const b = String(s.ended_at || "");
    sessMax = String(sessMax > a ? sessMax : a);
    sessMax = String(sessMax > b ? sessMax : b);
  }
  const selected = (data && (data.selected_session || data.current_session)) || null;
  const sid = selected ? String(selected.id || 0) : "0";
  const duty = data && data.assignments ? String((data.assignments || {}).duty || "") : "";
  const prefsFp = _catalogPrefsFp(data && data.catalog_prefs);
  const unitOrder = data && Array.isArray(data.unit_order) ? data.unit_order : [];
  const unitOrderFp = _sha1Hex(JSON.stringify(unitOrder)).slice(0, 8);
  const itemsMax = data ? String(data.items_max_updated_at || "") : "";
  return `${cat.length}|${catMax}|${cs.length}|${csMax}|${sess.length}|${sessMax}|${sid}|${duty}|${prefsFp}|${unitOrderFp}|${itemsMax}`;
}

// Функция для обновления состояния редактирования бланка
function applyStateData(data) {
  if (data && data.catalog_omitted && STATE) {
    data = {
      ...data,
      catalog: Array.isArray(data.catalog) ? data.catalog : (STATE.catalog || []),
      callsigns: Array.isArray(data.callsigns) ? data.callsigns : (STATE.callsigns || []),
    };
  }
  const selected = data.selected_session || data.current_session || null;
  const newSid = Number(selected && selected.id ? selected.id : 0);
  const prevApplied = PREV_APPLIED_SELECTED_SESSION_ID;

  if (prevApplied && newSid && prevApplied !== newSid) {
    ACTIVE_ITEM_ID = 0;
    ACTIVE_CATALOG_ID = 0;
    ACTIVE_CAT = null;
    stopPolling();
    if ($("typing-indicator")) $("typing-indicator").textContent = "";
    const taSw = $("intercept-text");
    if (taSw) taSw.value = "";
    const inpSw = $("intercept-input");
    if (inpSw) inpSw.value = "";
    clearAiProofreadPanel();
    BLANK_EDIT_ENABLED = false;
    const toggleSw = $("edit-blank-toggle");
    if (toggleSw) toggleSw.checked = false;
    LAST_SAVED = "";
    LAST_TIME_HEADER = "";
    HAS_REMOTE_NEW = false;
    const badgeSw = $("remote-new-badge");
    if (badgeSw) badgeSw.style.display = "none";
    const mergeSw = $("merge-updates-btn");
    if (mergeSw) mergeSw.style.display = "none";
    setText("editor-subtitle", "Выбери группу слева");
    syncIxChatHeader();
    _itemCacheClear();
  }

  STATE = data;
  CAN_EDIT = !!data.can_edit;
  CAN_EXPORT = !!data.can_export;
  CAN_START = !!data.can_start;

  BLANK_VIEW_MODE = "plain";

  $("start-new-btn").disabled = !CAN_START;
  $("export-intercepts-btn").disabled = !CAN_EXPORT;
  document.querySelectorAll(".wp-add-group-btn").forEach((btn) => {
    btn.disabled = !CAN_START;
  });

  renderShifts(data.sessions || [], selected);
  const nextCatalogSig = _catalogRenderSig(data.catalog || []);
  if (nextCatalogSig !== LAST_CATALOG_RENDER_SIG) {
    LAST_CATALOG_RENDER_SIG = nextCatalogSig;
    renderGroups(data.catalog || []);
  } else {
    _highlightActiveCatalogRow(ACTIVE_CATALOG_ID, ACTIVE_CAT);
  }

  if (data.selected_closed) {
    ACTIVE_CLOSED = true;
  } else {
    ACTIVE_CLOSED = false;
  }

  // Обновляем состояние бланка
  updateBlankEditState();
  updateBlankViewMode();

  // Обновляем заголовок бланка, если открыт активный элемент
  if (data.catalog && ACTIVE_CAT) {
    let catalogItem = null;
    // Ищем по id, если он есть
    if (ACTIVE_CATALOG_ID && Number(ACTIVE_CATALOG_ID || 0) > 0) {
      catalogItem = data.catalog.find(item => Number(item.id || 0) === Number(ACTIVE_CATALOG_ID || 0));
    }
    // Если не нашли по id, ищем по frequency и group_code
    if (!catalogItem && ACTIVE_CAT.frequency && ACTIVE_CAT.group_code) {
      catalogItem = data.catalog.find(item =>
        String(item.frequency || "").trim() === String(ACTIVE_CAT.frequency || "").trim() &&
        String(item.group_code || "").trim() === String(ACTIVE_CAT.group_code || "").trim()
      );
    }
    if (catalogItem) {
      const newLocation = String(catalogItem.location || "").trim();
      ACTIVE_CAT.location = newLocation;
      const isArchivedOnly = !!(catalogItem.archived_only);
      const subtitleText = `${ACTIVE_CAT.unit_name} • ${ACTIVE_CAT.frequency} ${ACTIVE_CAT.group_code}${isArchivedOnly ? " (архив)" : ""}`;
      setText("editor-subtitle", subtitleText);
      syncIxChatHeader();
    } else {
    }
  }

  // Обновляем состояние кнопки сохранения
  updateBlankDirtyUi();

  ALL_CALLSIGNS = data.callsigns || [];
  if (data && typeof data.assignments === "object") {
    ACTIVE_ASSIGNMENTS = data.assignments || {};
  }
  if (Array.isArray(data.unit_order)) {
    UNIT_ORDER = data.unit_order;
  }
  _applyCatalogPrefs(data);
  applyCallsignScope();
  updateAddCallsignButton();
  _renderPreview();
  updateBlankCallsignLegend();

  // Обновляем состояние кнопки отправки
  if (typeof updateSendButton === "function") {
    updateSendButton();
  }

  PREV_APPLIED_SELECTED_SESSION_ID = newSid;

  const itemsMax = String(data.items_max_updated_at || "");
  if (
    PREV_ITEMS_MAX_UPDATED_AT &&
    itemsMax &&
    itemsMax !== PREV_ITEMS_MAX_UPDATED_AT &&
    ACTIVE_ITEM_ID &&
    ACTIVE_CATALOG_ID
  ) {
    LAST_REMOTE_SIG = "";
    pollItemOnce().catch(() => { });
  }
  PREV_ITEMS_MAX_UPDATED_AT = itemsMax;
}

function _scheduleStatePoll(delayMs) {
  if (STATE_POLL_TIMER) clearTimeout(STATE_POLL_TIMER);
  STATE_POLL_TIMER = setTimeout(() => {
    pollStateOnce();
  }, delayMs == null ? STATE_POLL_MS : delayMs);
}

async function pollCatalogOnce() {
  if (document.hidden) return false;
  try {
    const sigQs = LAST_CATALOG_SIG
      ? `?catalog_sig=${encodeURIComponent(LAST_CATALOG_SIG)}`
      : "?";
    const data = await apiGet(`/api/intercepts/catalog${sigQs}`);
    if (data && data.unchanged) return false;
    if (data && data.catalog_sig) LAST_CATALOG_SIG = String(data.catalog_sig || "");
    if (!STATE) STATE = {};
    STATE.catalog = data.catalog || [];
    STATE.callsigns = data.callsigns || [];
    ALL_CALLSIGNS = STATE.callsigns || [];
    const nextCatalogSig = _catalogRenderSig(STATE.catalog || []);
    if (nextCatalogSig !== LAST_CATALOG_RENDER_SIG) {
      LAST_CATALOG_RENDER_SIG = nextCatalogSig;
      renderGroups(STATE.catalog || []);
    } else {
      _highlightActiveCatalogRow(ACTIVE_CATALOG_ID, ACTIVE_CAT);
    }
    _refreshCallsignsUi();
    return true;
  } catch (e) {
    return false;
  }
}

async function pollStateOnce() {
  if (STATE_POLL_INFLIGHT) {
    _scheduleStatePoll(STATE_POLL_MS);
    return;
  }
  if (document.hidden) {
    _scheduleStatePoll(STATE_POLL_MS_MAX);
    return;
  }
  STATE_POLL_INFLIGHT = true;
  try {
    const base = ACTIVE_SESSION_ID
      ? `?session_id=${encodeURIComponent(ACTIVE_SESSION_ID)}&explicit_pick=1`
      : `?`;
    const pairQs =
      ACTIVE_CAT && ACTIVE_CAT.frequency && ACTIVE_CAT.group_code
        ? `&frequency=${encodeURIComponent(String(ACTIVE_CAT.frequency || ""))}&group_code=${encodeURIComponent(
          String(ACTIVE_CAT.group_code || "")
        )}`
        : "";
    const sigQs = LAST_STATE_SIG ? `&state_sig=${encodeURIComponent(LAST_STATE_SIG)}` : "";
    const skipQs = LAST_STATE_SIG ? "&skip_catalog=1" : "";
    const qs = `${base}${pairQs}${sigQs}${skipQs}`;
    const data = await apiGet(`/api/intercepts/state${qs}`);
    if (data && data.unchanged) {
      STATE_POLL_UNCHANGED_STREAK += 1;
      STATE_POLL_MS = Math.min(
        STATE_POLL_MS_MAX,
        STATE_POLL_MS_MIN + STATE_POLL_UNCHANGED_STREAK * 400
      );
      return;
    }
    STATE_POLL_MS = STATE_POLL_MS_MIN;
    STATE_POLL_UNCHANGED_STREAK = 0;
    const sig = _stateSig(data);
    if (sig) LAST_STATE_SIG = sig;
    if (data && data.catalog_omitted) {
      await pollCatalogOnce();
      data = {
        ...data,
        catalog: (STATE && STATE.catalog) || [],
        callsigns: ALL_CALLSIGNS || [],
      };
    }
    applyStateData(data);
  } catch (e) {
    // молча — UI не должен "дергаться" из-за временных сетевых проблем
  } finally {
    STATE_POLL_INFLIGHT = false;
    _scheduleStatePoll();
  }
}

function startPollingState() {
  if (STATE_POLL_TIMER) clearTimeout(STATE_POLL_TIMER);
  STATE_POLL_MS = STATE_POLL_MS_MIN;
  STATE_POLL_UNCHANGED_STREAK = 0;
  pollStateOnce();
}

function startPollingItem() {
  startPollingCurrent();
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    if (STATE_POLL_TIMER) clearTimeout(STATE_POLL_TIMER);
    STATE_POLL_TIMER = null;
    if (POLL_TIMER) clearTimeout(POLL_TIMER);
    POLL_TIMER = null;
    return;
  }
  startPollingState();
  startPollingItem();
});

function _catalogRenderSig(catalog) {
  let max = "";
  for (const c of catalog || []) {
    const v = String((c && c.updated_at) || "");
    if (v > max) max = v;
  }
  const exp = Array.from(EXPANDED_UNITS || []).sort().join("\u001f");
  return `${(catalog || []).length}|${max}|${exp}|${Number(ACTIVE_CATALOG_ID || 0)}`;
}

function _buildOpenItemUrl(sessionId, catalogId, cat) {
  const isArchivedOnly = !!(cat && cat.archived_only);
  if (isArchivedOnly) {
    return `/api/intercepts/item?session_id=${encodeURIComponent(sessionId)}&frequency=${encodeURIComponent(
      String(cat.frequency || "")
    )}&group_code=${encodeURIComponent(String(cat.group_code || ""))}`;
  }
  return `/api/intercepts/item?session_id=${encodeURIComponent(sessionId)}&catalog_id=${encodeURIComponent(catalogId)}`;
}

function _prefetchOpenItem(catalogId, cat) {
  if (!ACTIVE_SESSION_ID) return;
  const cacheKey = _itemCacheKey(ACTIVE_SESSION_ID, catalogId, cat);
  if (!cacheKey || _itemCacheGet(cacheKey)) return;
  const url = _buildOpenItemUrl(ACTIVE_SESSION_ID, catalogId, cat);
  apiGet(url)
    .then((data) => {
      if (data && data.ok !== false) _itemCacheSet(cacheKey, data);
    })
    .catch(() => { });
}

function _findCatalogRowInList(list, catalogId, cat) {
  if (!list) return null;
  const cid = Number(catalogId || 0);
  if (cid > 0) {
    const byId = list.querySelector(`[data-catalog-id="${cid}"]`);
    if (byId) return byId;
  }
  if (cat && cat.frequency && cat.group_code) {
    const f = String(cat.frequency).trim();
    const g = String(cat.group_code).trim();
    const rows = list.querySelectorAll("[data-catalog-id][data-frequency][data-group-code]");
    for (const el of rows) {
      if (
        String(el.dataset.frequency || "").trim() === f &&
        String(el.dataset.groupCode || "").trim() === g
      ) {
        return el;
      }
    }
  }
  return null;
}

function _selectCatalogRowElement(row) {
  const list = $("groups-list");
  if (!row || !list) return;
  list
    .querySelectorAll(
      ".ix-catalog-row--selected, .tg-chat-item--active, .list-group-item.active, .tg-mobile-chat--active"
    )
    .forEach((el) => {
      el.classList.remove(
        "ix-catalog-row--selected",
        "tg-chat-item--active",
        "active",
        "tg-mobile-chat--active"
      );
      el.removeAttribute("aria-current");
    });
  list.querySelectorAll(".unit-block--has-selection").forEach((el) => {
    el.classList.remove("unit-block--has-selection");
  });
  row.classList.add("ix-catalog-row--selected");
  if (row.classList.contains("tg-mobile-chat")) {
    row.classList.add("tg-mobile-chat--active");
  } else {
    row.classList.add("active");
    if (row.classList.contains("tg-chat-item")) row.classList.add("tg-chat-item--active");
  }
  row.setAttribute("aria-current", "true");
  const block = row.closest(".unit-block");
  if (block) block.classList.add("unit-block--has-selection");
}

function _highlightActiveCatalogRow(catalogId, cat) {
  const list = $("groups-list");
  if (!list) return;
  const row = _findCatalogRowInList(list, catalogId, cat);
  if (row) {
    _selectCatalogRowElement(row);
    try {
      row.scrollIntoView({ block: "nearest", inline: "nearest" });
    } catch (_) { }
  }
}

function _expandUnitForCatalog(cat) {
  if (!cat || !cat.unit_name) return "";
  const unitKey = _unitKey(cat.unit_name) || "—";
  if (!unitKey) return "";
  EXPANDED_UNITS.add(unitKey);
  COLLAPSED_UNITS.delete(unitKey);
  const block = document.querySelector(`.unit-block[data-unit-key="${CSS.escape(unitKey)}"]`);
  if (!block) return unitKey;
  const container = block.querySelector(".unit-groups-container");
  if (container) container.style.display = "block";
  const chevron = block.querySelector(".unit-header i.bi-chevron-right");
  if (chevron) {
    chevron.classList.remove("bi-chevron-right");
    chevron.classList.add("bi-chevron-down");
  }
  return unitKey;
}

function _applyOpenItemPayload(catalogId, cat, data, opts) {
  const options = opts || {};
  const soft = !!options.soft;
  const item = (data && data.item) || {};
  const catalogMeta = data && typeof data.catalog === "object" && data.catalog ? data.catalog : null;
  if (catalogMeta && typeof catalogMeta.location !== "undefined") {
    cat = cat || {};
    cat.location = String(catalogMeta.location || "").trim();
  }
  if (data && typeof data.assignments === "object") {
    ACTIVE_ASSIGNMENTS = data.assignments || {};
  } else if (!soft) {
    ACTIVE_ASSIGNMENTS = {};
  }

  const nextSig = _contentSig(item.updated_at || "", item.content || "");
  if (soft && nextSig === LAST_REMOTE_SIG && Number(item.id || 0) === Number(ACTIVE_ITEM_ID || 0)) {
    const typing = Array.isArray(data.typing) ? data.typing : [];
    const ti = $("typing-indicator");
    if (ti) ti.textContent = typing.length ? `печатает: ${typing.join(", ")}` : "";
    return;
  }

  ACTIVE_ITEM_ID = Number(item.id || 0);
  ACTIVE_CATALOG_ID = Number(catalogId || 0);
  ACTIVE_CAT = cat
    ? {
      unit_name: cat.unit_name || "",
      frequency: cat.frequency || "",
      group_code: cat.group_code || "",
      location: cat.location || "",
    }
    : null;
  applyCallsignScope();
  const closed = !!data.closed;
  ACTIVE_CLOSED = closed;
  if (typeof data.can_edit !== "undefined") CAN_EDIT = !!data.can_edit;

  const ta = $("intercept-text");
  const previewVisible = $("intercept-preview") && $("intercept-preview").style.display !== "none";
  const canReplaceBlank = !soft || !ta || String(ta.value || "") === String(LAST_SAVED || "");
  if (ta && canReplaceBlank) {
    ta.value = item.content || "";
    clearAiProofreadPanel();
    try {
      _applyCallsignDecorationsInPlain(ta);
    } catch (_) { }
  }

  updateBlankEditState();
  updateBlankViewMode();

  if (!soft) {
    requestAnimationFrame(() => {
      try {
        const previewBox = $("intercept-preview");
        const wrap = $("intercept-text-wrapper");
        const input = $("intercept-input");
        const editorVisible = wrap && wrap.style.display !== "none" && ta;
        if (previewVisible && previewBox) {
          _scrollToBottom(previewBox);
        } else if (editorVisible && ta) {
          ta.scrollTop = ta.scrollHeight;
          if (!ta.disabled) {
            const len = ta.value.length;
            ta.setSelectionRange(len, len);
          }
        }
        if (input && CAN_EDIT && !ACTIVE_CLOSED && ACTIVE_ITEM_ID) {
          input.focus();
          const len = input.value.length;
          input.setSelectionRange(len, len);
        }
      } catch (_) { }
    });
  }

  const actualLocation = String((cat && cat.location) || "").trim();
  if (cat) cat.location = actualLocation;
  if (ACTIVE_CAT) ACTIVE_CAT.location = actualLocation;
  const isArchivedOnly = !!(cat && cat.archived_only);
  const subtitleText = `${cat.unit_name} • ${cat.frequency} ${cat.group_code}${isArchivedOnly ? " (архив)" : ""}`;
  setText("editor-subtitle", subtitleText);
  syncIxChatHeader();
  if (document.body.classList.contains("ix-mobile-intercepts") && typeof window.setInterceptsMobilePanel === "function") {
    const root = document.querySelector(".md3-intercepts");
    window.setInterceptsMobilePanel(root && root.dataset.ixPanel ? root.dataset.ixPanel : "blank");
  }
  setSaveStatus("saved", item.updated_at ? `Последнее сохранение: ${fmtShift(item.updated_at)}` : "");
  setText(
    "who-status",
    closed ? "Смена закрыта (только просмотр)" : CAN_EDIT ? "Редактирование включено" : "Только просмотр"
  );
  updateBlankCallsignLegend();
  updateBlankDirtyUi();
  if (canReplaceBlank && ta) {
    LAST_SAVED = ta.value;
    LAST_TIME_HEADER = extractLastTimeHeader(LAST_SAVED);
    LAST_TYPING_HEADER_SENT = LAST_TIME_HEADER || "";
  }
  updateAiProofreadButtonState();
  LAST_REMOTE_UPDATED_AT = String(item.updated_at || "");
  LAST_REMOTE_SIG = nextSig;
  ITEM_SYNC_EPOCH += 1;
  HAS_REMOTE_NEW = false;
  const badge = $("remote-new-badge");
  if (badge) badge.style.display = "none";
  const mergeBtn = $("merge-updates-btn");
  if (mergeBtn) mergeBtn.style.display = "none";
  if (!isArchivedOnly) startPollingCurrent();
  _highlightActiveCatalogRow(catalogId, cat);
  if (typeof updateSendButton === "function") updateSendButton();
}

function ixCollapseGroupsDrawer() {
  if (!document.body.classList.contains("groups-drawer-mode")) return;
  document.body.classList.add("groups-drawer-collapsed");
  try {
    localStorage.setItem("intercept-groups-drawer-collapsed", "1");
  } catch (_) { }
}

function ixExpandGroupsDrawer() {
  if (!document.body.classList.contains("groups-drawer-mode")) return;
  document.body.classList.remove("groups-drawer-collapsed");
  try {
    localStorage.setItem("intercept-groups-drawer-collapsed", "0");
  } catch (_) { }
}

async function openItem(catalogId, cat) {
  let sessionId = Number(ACTIVE_SESSION_ID || 0);
  if (!sessionId && STATE) {
    const s = STATE.selected_session || STATE.current_session;
    sessionId = Number(s && s.id ? s.id : 0);
    if (sessionId) ACTIVE_SESSION_ID = sessionId;
  }
  if (!sessionId) {
    setInterceptsStatus(
      "Сначала выберите смену вверху слева или нажмите «+» для новой смены."
    );
    return;
  }

  const nextKey = _itemCacheKey(sessionId, catalogId, cat);
  const currentKey = _itemCacheKey(ACTIVE_SESSION_ID, ACTIVE_CATALOG_ID, ACTIVE_CAT);
  if (hasPendingInterceptChanges() && nextKey !== currentKey) {
    const ok = window.confirm(
      "Есть несохранённые изменения в бланке. Переключить чат без сохранения?"
    );
    if (!ok) return;
  }

  const cacheKey = _itemCacheKey(sessionId, catalogId, cat);
  const cid = Number(catalogId || 0);
  const gen = ++OPEN_ITEM_GEN;
  OPEN_ITEM_TARGET_KEY = cacheKey;
  OPEN_ITEM_INFLIGHT = true;
  setInterceptsStatus("");

  if (cat) {
    ACTIVE_CATALOG_ID = cid;
    ACTIVE_CAT = {
      unit_name: cat.unit_name || "",
      frequency: cat.frequency || "",
      group_code: cat.group_code || "",
      location: cat.location || "",
    };
    syncIxChatHeader();
  }

  if (document.body.classList.contains("ix-mobile-intercepts") && typeof window.setInterceptsMobilePanel === "function") {
    window.setInterceptsMobilePanel("blank");
  } else if (document.body.classList.contains("groups-drawer-mode")) {
    ixCollapseGroupsDrawer();
  }

  const unitKey = _expandUnitForCatalog(cat);
  _highlightActiveCatalogRow(cid, cat);

  const url = _buildOpenItemUrl(sessionId, catalogId, cat);
  let usedCache = false;

  try {
    if (gen !== OPEN_ITEM_GEN) return;

    let data = _itemCacheGet(cacheKey);
    if (data) {
      usedCache = true;
      if (gen === OPEN_ITEM_GEN) {
        _applyOpenItemPayload(catalogId, cat, data);
        setInterceptsStatus("");
      }
    } else {
      setInterceptsStatus("Загрузка бланка…");
      data = await apiGet(url);
      if (gen !== OPEN_ITEM_GEN) return;
      _itemCacheSet(cacheKey, data);
      _applyOpenItemPayload(catalogId, cat, data);
      setInterceptsStatus("");
    }

    if (usedCache) {
      // Бланк уже показан из кеша, здесь только сверка с сервером. Оператор
      // может успеть сохранить правку раньше, чем придёт ответ, — тогда ответ
      // описывает состояние до сохранения и вернул бы удалённое сообщение.
      const epochAtRefresh = ITEM_SYNC_EPOCH;
      apiGet(url)
        .then((fresh) => {
          if (OPEN_ITEM_TARGET_KEY !== cacheKey || gen !== OPEN_ITEM_GEN) return;
          if (epochAtRefresh !== ITEM_SYNC_EPOCH) return;
          _itemCacheSet(cacheKey, fresh);
          _applyOpenItemPayload(catalogId, cat, fresh, { soft: true });
        })
        .catch(() => { });
    }

    if (gen !== OPEN_ITEM_GEN) return;

    if (unitKey && STATE && STATE.catalog) {
      const block = document.querySelector(`.unit-block[data-unit-key="${CSS.escape(unitKey)}"]`);
      if (!block) {
        LAST_CATALOG_RENDER_SIG = "";
        renderGroups(STATE.catalog);
        _highlightActiveCatalogRow(cid, cat);
      }
    }
  } catch (e) {
    if (gen !== OPEN_ITEM_GEN) return;
    setInterceptsStatus(`Ошибка открытия бланка: ${e.message || e}`);
    ACTIVE_ITEM_ID = 0;
    ACTIVE_CATALOG_ID = 0;
    ACTIVE_CAT = null;
    const taErr = $("intercept-text");
    if (taErr) taErr.value = "";
    syncIxChatHeader();
    _highlightActiveCatalogRow(0, null);
    updateBlankEditState();
  } finally {
    if (gen === OPEN_ITEM_GEN) {
      OPEN_ITEM_INFLIGHT = false;
    }
  }
}

function stopPolling() {
  if (POLL_TIMER) clearTimeout(POLL_TIMER);
  POLL_TIMER = null;
}


  window.fmtMskLabel = fmtMskLabel;
  window.fmtShift = fmtShift;
  window.renderShifts = renderShifts;
  window.renderGroups = renderGroups;
  window.applyStateData = applyStateData;
  window.pollStateOnce = pollStateOnce;
  window.startPollingState = startPollingState;
  window.startPollingItem = startPollingItem;
  window.stopPolling = stopPolling;
  window.openItem = openItem;
  window.initInterceptsGroupsSearchControls = initInterceptsGroupsSearchControls;
  window.ixCollapseGroupsDrawer = ixCollapseGroupsDrawer;
  window.ixExpandGroupsDrawer = ixExpandGroupsDrawer;
  window._stateSig = _stateSig;
  window._unitKey = _unitKey;
})();
