async function apiGet(url) {
  const res = await fetch(url, { method: "GET" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function apiPost(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function apiUpload(url, formData) {
  const res = await fetch(url, { method: "POST", body: formData });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function $(id) {
  return document.getElementById(id);
}

function setText(id, text) {
  const el = $(id);
  if (el) el.textContent = text || "";
}

function debounce(fn, wait = 250) {
  let t = null;
  return (...args) => {
    if (t) clearTimeout(t);
    t = setTimeout(() => fn(...args), wait);
  };
}

function showToast(message, variant) {
  const toastEl = $("app-toast");
  const bodyEl = $("app-toast-body");
  if (!toastEl || !bodyEl || !window.bootstrap) return;
  bodyEl.textContent = message || "";
  toastEl.classList.remove(
    "text-bg-success",
    "text-bg-danger",
    "text-bg-warning",
    "text-bg-info"
  );
  if (variant) toastEl.classList.add(`text-bg-${variant}`);
  const toast = window.bootstrap.Toast.getOrCreateInstance(toastEl, {
    delay: 2500,
  });
  toast.show();
}

// БД выбирается автоматически сервером (DEFAULT_DB_NAME), UI выбора БД убран.

let OFFSET = 0;
const LIMIT = 200;
let HEADERS = ["col1", "col2", "col3", "col4", "col5", "col6", "col7", "col8", "col9"];
let META = { freq_col: 1, gid_col: 2, note_col: 9 };
let SORT_BY = "frequency"; // default: frequency
let SORT_DIR = "desc"; // default: big -> small
let COL_MAP = {
  freq: 1,
  gid: 2,
  id: 3,
  corr: 4,
  confirm: 0,
  discovery: 0,
  coords: 0,
  key_db: 0,
};
let FILTERS = {}; // Активные фильтры {column: value}
let ALL_GROUPS = []; // Все уникальные группы для фильтра
let LAST_LOAD_TIME = null; // Время последней загрузки для определения новых данных
let ROW_MAP = new Map();
let SELECTED_ROW_ID = null;
let MANUAL_UNIT_GROUPS = [];
let MANUAL_GROUP_UNITS = [];

function _unitKeyFromRow(r) {
  const n = String(r?.note ?? "").trim();
  return n ? n : "__none__";
}

function _unitLabelFromKey(k) {
  return k === "__none__" ? "Без подразделения" : k;
}

/** Короткая подпись для дочерней карточки в объединении подразделений. */
function _unitChildLabel(label, key) {
  const raw = String(key || "").trim();
  const fallback = String(label || "").trim();
  if (!raw) return fallback || "Подразделение";
  // Поддерживаем «155 ОМБр 1 мсб» и «1 мсб 155 ОМБр».
  const suffix = raw.match(/(?:^|\s)(\d+\s*(?:мсб|шб|бат|ббпс|бмп|бон))\s*$/iu);
  const prefix = raw.match(/^(\d+\s*(?:мсб|шб|бат|ббпс|бмп|бон))(?:\s|$)/iu);
  if (suffix) return suffix[1].replace(/\s+/g, " ");
  if (prefix) return prefix[1].replace(/\s+/g, " ");
  return fallback && fallback !== "Записи" ? fallback : raw;
}

function _groupRowsByUnit(list) {
  const m = new Map();
  for (const r of list || []) {
    const k = _unitKeyFromRow(r);
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(r);
  }
  return m;
}

function _orderedUnitKeys(map) {
  const keys = Array.from(map.keys());
  const named = keys.filter((k) => k !== "__none__").sort((a, b) => a.localeCompare(b, "ru"));
  if (keys.includes("__none__")) {
    named.push("__none__");
  }
  return named;
}


function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function fmtMskTs(s) {
  const str = String(s || "").trim();
  if (!str) return "";
  // ожидаем "YYYY-MM-DD HH:MM:SS" в UTC (SQLite CURRENT_TIMESTAMP) -> МСК (UTC+3)
  const m = str.match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})(?::(\d{2}))?/);
  if (!m) return str.includes("МСК") ? str : `${str} МСК`;
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

function sortIndicator() {
  const arrow = SORT_DIR === "asc" ? "↑" : "↓";
  if (SORT_BY === "id") return ` ${arrow}`;
  if (SORT_BY === "frequency") return ` ${arrow}`;
  return "";
}

function setHeadLabel(id, text) {
  const el = $(id);
  if (!el) return;
  const label = el.querySelector(".os-h-label");
  if (label) {
    label.textContent = text;
  } else {
    const span = el.querySelector(".th-content span");
    if (span) span.textContent = text;
    else el.textContent = text;
  }
}

function normHeader(s) {
  return String(s || "").trim().toLowerCase();
}

function findHeaderIdx(pred) {
  for (let i = 0; i < (HEADERS || []).length; i++) {
    const h = normHeader(HEADERS[i]);
    if (pred(h)) return i + 1; // col index 1..9
  }
  return 0;
}

function rebuildColMap() {
  // из meta (если есть) + из заголовков (если meta не заполнен / старые данные)
  const freq = META && META.freq_col ? META.freq_col : 1;
  const gid = META && META.gid_col ? META.gid_col : 2;
  const note = META && META.note_col ? META.note_col : 9;

  COL_MAP.freq = freq;
  COL_MAP.gid = gid;
  COL_MAP.id =
    findHeaderIdx((h) => h === "id" || (h.includes("id") && !h.includes("груп"))) || 3;
  COL_MAP.corr = findHeaderIdx((h) => h.includes("корр")) || 4;
  COL_MAP.confirm =
    findHeaderIdx((h) => h.includes("дата") || h.includes("подтверж")) || 6;
  COL_MAP.discovery =
    findHeaderIdx(
      (h) =>
        h.includes("обнаруж") ||
        h.includes("discovery") ||
        h.includes("обнар")
    ) || 7;
  COL_MAP.coords = 0;
  COL_MAP.key_db = findHeaderIdx((h) => h.includes("ключ")) || 0;

  // note_col используется только для синхронизации обратно в excel-колонку,
  // в UI примечание всегда показываем из r.note
  COL_MAP.note = note;
}

function colVal(r, idx1) {
  if (!idx1 || idx1 < 1) return "";
  return r[`col${idx1}`] ?? "";
}

function updateGroupFilterOptions() {
  const select = $("os-filter-group");
  if (!select) return;
  const current = FILTERS.group_id || "";
  select.innerHTML = '<option value="">Все группы</option>';
  for (const group of ALL_GROUPS) {
    const selected = current === group ? "selected" : "";
    select.innerHTML += `<option value="${escapeHtml(group)}" ${selected}>${escapeHtml(group)}</option>`;
  }
}

function syncFilterUiFromState() {
  const c = $("os-filter-confirm");
  if (c) c.value = FILTERS.confirm || "";
  const updated = $("os-filter-updated");
  if (updated) updated.checked = FILTERS.updated_at === "today";
}

/**
 * Синхронизирует в FILTERS только дату и «24 ч» — не затирает фильтры по столбцам (шапка таблицы).
 */
function readFiltersFromUi() {
  const confirm = String($("os-filter-confirm")?.value || "").trim();
  const updatedOnly = $("os-filter-updated")?.checked;
  if (confirm) FILTERS.confirm = confirm;
  else delete FILTERS.confirm;
  if (updatedOnly) FILTERS.updated_at = "today";
  else delete FILTERS.updated_at;
}

function renderDetail(row) {
  const body = $("os-detail-body");
  const noteBlock = $("os-detail-note-edit");
  const noteInput = $("os-detail-note");
  if (!body) return;
  if (!row) {
    body.innerHTML = `<div class="wp-subtle">Запись не выбрана.</div>`;
    if (noteBlock) noteBlock.style.display = "none";
    return;
  }
  const freqVal = row.frequency || colVal(row, COL_MAP.freq);
  const groupVal = row.group_id || colVal(row, COL_MAP.gid);
  const idVal = colVal(row, COL_MAP.id);
  const corrVal = colVal(row, COL_MAP.corr);
  const noteVal = row.note ?? "";
  const confirmVal = colVal(row, COL_MAP.confirm);
  const updatedVal = row.updated_at ? fmtMskTs(row.updated_at) : "";
  const isNew = isNewData(row.updated_at);

  body.innerHTML = `
    <div class="d-flex align-items-center gap-2">
      <div class="fw-semibold">${escapeHtml(String(freqVal || "—"))}</div>
      <span class="badge text-bg-light border">${escapeHtml(String(groupVal || "—"))}</span>
      ${isNew ? '<span class="badge bg-success">NEW</span>' : ""}
    </div>
    <div class="small wp-subtle mt-1">ID: ${escapeHtml(String(idVal || "—"))}</div>
    <div class="mt-2"><strong>Корреспонденты:</strong> ${escapeHtml(String(corrVal || "—"))}</div>
    <div class="mt-2"><strong>Подразделение:</strong> ${escapeHtml(String(noteVal || "—"))}</div>
    <div class="mt-2"><strong>Дата:</strong> ${escapeHtml(String(confirmVal || "—"))}</div>
    <div class="mt-2"><strong>Обновлено:</strong> ${escapeHtml(String(updatedVal || "—"))}</div>
  `;

  if (noteBlock) noteBlock.style.display = "";
  if (noteInput) noteInput.value = String(noteVal || "");
}

function selectRow(row, cardEl) {
  SELECTED_ROW_ID = row ? Number(row.id || 0) : null;
  document.querySelectorAll("#os-units-list .os-wb-card, #os-units-list .os-search-card").forEach((el) => {
    el.classList.toggle("os-row-selected", cardEl && el === cardEl);
  });
  renderDetail(row);
}

function renderHead(headers) {
  HEADERS = headers && headers.length === 9 ? headers : HEADERS;
  rebuildColMap();

  setHeadLabel("th-freq", `Частота${SORT_BY === "frequency" ? sortIndicator() : ""}`);
  setHeadLabel("th-num", `№${SORT_BY === "id" ? sortIndicator() : ""}`);
  setHeadLabel("th-gid", HEADERS[COL_MAP.gid - 1] || "Группа");
  setHeadLabel("th-id", HEADERS[COL_MAP.id - 1] || "ID");
  setHeadLabel("th-corr", HEADERS[COL_MAP.corr - 1] || "Корр.");
  setHeadLabel("th-note", HEADERS[COL_MAP.note - 1] || "Подразд.");
  setHeadLabel("th-confirm", COL_MAP.confirm ? (HEADERS[COL_MAP.confirm - 1] || "Дата") : "Дата");
}

function isNewData(updatedAt) {
  if (!updatedAt || !LAST_LOAD_TIME) return false;
  // Считаем новыми данные, обновленные за последние 24 часа
  try {
    const updated = new Date(updatedAt);
    if (isNaN(updated.getTime())) return false;
    const now = new Date();
    const diffHours = (now - updated) / (1000 * 60 * 60);
    return diffHours <= 24;
  } catch {
    return false;
  }
}


function _osWbBuildCardMedia(avatarUrl) {
  const media = document.createElement("div");
  media.className = "os-wb-card__media";
  if (avatarUrl) {
    const im = document.createElement("img");
    im.src = String(avatarUrl);
    im.alt = "";
    im.loading = "lazy";
    im.decoding = "async";
    im.addEventListener("error", () => {
      im.remove();
      media.innerHTML = '<div class="os-wb-card__ph" aria-hidden="true"><i class="bi bi-image"></i></div>';
    });
    media.appendChild(im);
  } else {
    media.innerHTML = '<div class="os-wb-card__ph" aria-hidden="true"><i class="bi bi-shield"></i></div>';
  }
  return media;
}

function _osWbAppendChips(wrap, children, plab) {
  const bar = document.createElement("div");
  bar.className = "os-wb-card__chips";
  bar.setAttribute("role", "group");
  bar.setAttribute("aria-label", `Состав: ${plab}`);
  const tilesWrap = document.createElement("div");
  tilesWrap.className = "os-wb-card__chips-tiles";
  if (children && children.length > 1) {
    const sub = document.createElement("div");
    sub.className = "os-wb-card__chips-h";
    sub.textContent = "Состав / варианты";
    bar.appendChild(sub);
  }
  for (const ch of children) {
    const uk = ch.unit_key;
    const cLab = _unitChildLabel(ch.label, uk);
    const cCnt = Number(ch.row_count || 0);
    const tile = document.createElement("a");
    tile.className = "os-unit-tile";
    tile.href = `/search-online/battalion?k=${encodeURIComponent(uk)}`;
    const aria = `${cLab} — ${cCnt} зн.`;
    tile.setAttribute("aria-label", `Страница варианта: ${aria}`);
    if (_unitLabelFromKey(uk) !== cLab) {
      tile.setAttribute("title", _unitLabelFromKey(uk));
    }
    tile.innerHTML = `<span class="os-unit-tile__name">${escapeHtml(cLab)}</span>
            <span class="os-unit-tile__n">${cCnt}</span>`;
    tilesWrap.appendChild(tile);
  }
  bar.appendChild(tilesWrap);
  wrap.appendChild(bar);
}

async function refreshUnitsList() {
  const listEl = $("os-units-list");
  if (!listEl) return;
  try {
    const qRaw = ($("q") && $("q").value) || "";
    const q = String(qRaw).trim();
    const qParam = q ? `?q=${encodeURIComponent(q)}` : "";
    const data = await apiGet(`/api/online-search/units${qParam}`);
    const families = data.families || [];
    const units = data.units || [];
    listEl.innerHTML = "";
    listEl.classList.remove("os-units-grid--ready");
    const hasFam = families && families.length > 0;
    const hasUnits = units.length > 0;
    if (!hasFam && !hasUnits) {
      if (q) {
        listEl.innerHTML = `<div class="os-units-list__empty text-muted small py-3 px-1 w-100">По запросу «${escapeHtml(
          q
        )}» подразделений нет. Очистите поиск или измените строку — карточки фильтруются по тому же полю, что и таблица.</div>`;
      } else {
        listEl.innerHTML =
          '<div class="os-units-list__empty text-muted small py-3 px-1 w-100">В таблице online_search нет записей — подразделения не сформированы.</div>';
      }
      return;
    }
    listEl.classList.add("os-units-grid--ready");

    if (hasFam) {
      for (const fam of families) {
        const pkey = String(fam.parent_key || "");
        const plab = String(fam.parent_label || pkey);
        const total = Number(fam.row_count || 0);
        const children = fam.children || [];
        const avatarUrl = fam.avatar_url || "";

        const card = document.createElement("article");
        card.className = "os-wb-card";
        card.setAttribute("role", "listitem");
        if (pkey === "__none__") {
          card.classList.add("os-wb-card--fallback");
        }

        const mainL = document.createElement("a");
        mainL.className = "os-wb-card__mainlink";
        mainL.href = `/search-online/unit?p=${encodeURIComponent(pkey)}`;
        mainL.setAttribute("aria-label", `Страница подразделения: ${plab}`);

        mainL.appendChild(_osWbBuildCardMedia(avatarUrl));

        const body = document.createElement("div");
        body.className = "os-wb-card__body";
        body.innerHTML = `<h3 class="os-wb-card__title mb-0">${escapeHtml(plab)}</h3>
          <div class="os-wb-card__meta">
            <span class="os-wb-card__total">${total} в базе</span>
          </div>`;
        mainL.appendChild(body);
        card.appendChild(mainL);

        _osWbAppendChips(card, children, plab);
        listEl.appendChild(card);
      }
      return;
    }

    for (const u of units) {
      const uk = u.unit_key;
      const cnt = Number(u.row_count || 0);
      const label = _unitLabelFromKey(uk);
      const card = document.createElement("article");
      card.className = "os-wb-card";
      card.setAttribute("role", "listitem");
      if (uk === "__none__") {
        card.classList.add("os-wb-card--fallback");
      }
      const mainL = document.createElement("a");
      mainL.className = "os-wb-card__mainlink";
      mainL.href = `/search-online/battalion?k=${encodeURIComponent(uk)}`;
      mainL.setAttribute("aria-label", `Открыть: ${label}`);
      mainL.appendChild(_osWbBuildCardMedia(""));
      const body = document.createElement("div");
      body.className = "os-wb-card__body";
      body.innerHTML = `<h3 class="os-wb-card__title mb-0">${escapeHtml(label)}</h3>
        <div class="os-wb-card__meta"><span class="os-wb-card__total">${cnt} в базе</span></div>`;
      mainL.appendChild(body);
      card.appendChild(mainL);
      listEl.appendChild(card);
    }
  } catch (e) {
    listEl.innerHTML = `<div class="text-danger small p-2">Список подразделений: ${escapeHtml(e.message || e)}</div>`;
  }
}

function renderRows(rows) {
  const emptyEl = $("os-empty-state");
  ROW_MAP = new Map();
  for (const r of rows || []) {
    if (r && r.id) ROW_MAP.set(Number(r.id), r);
  }

  const groupsSet = new Set();
  for (const r of rows || []) {
    const gid = r.group_id || colVal(r, COL_MAP.gid);
    if (gid) groupsSet.add(String(gid));
  }
  ALL_GROUPS = Array.from(groupsSet).sort();
  updateGroupFilterOptions();

  const list = rows || [];
  if (!list.length) {
    if (emptyEl) {
      emptyEl.classList.remove("d-none");
    }
  } else if (emptyEl) {
    emptyEl.classList.add("d-none");
  }

  SELECTED_ROW_ID = null;
  renderDetail(null);
}

function updateInsights(rows, total) {
  const list = Array.isArray(rows) ? rows : [];
  const frequencies = new Set();
  const groups = new Set();
  const units = new Set();
  for (const row of list) {
    const frequency = String(row?.frequency || colVal(row, COL_MAP.freq) || "").trim();
    const group = String(row?.group_id || colVal(row, COL_MAP.gid) || "").trim();
    const unit = String(row?.note || "").trim();
    if (frequency) frequencies.add(frequency);
    if (group) groups.add(group);
    if (unit) units.add(unit);
  }
  setText("os-insight-total", String(Number(total) || 0));
  setText("os-insight-frequencies", String(frequencies.size));
  setText("os-insight-groups", String(groups.size));
  setText("os-insight-units", String(units.size));
}

async function load() {
  const qRaw = ($("q").value || "").trim();
  let q = qRaw;
  let groupOnly = "";
  const gMatch = qRaw.match(/^g\s*0*(\d+)$/i);
  if (gMatch && gMatch[1]) {
    groupOnly = gMatch[1];
    q = "";
  }
  setText("status", "Загрузка…");
  const unitsP = refreshUnitsList();
  try {
    // Формируем параметры запроса с фильтрами
    const params = new URLSearchParams();
    if (q) params.append("q", q);
    params.append("limit", String(LIMIT));
    params.append("offset", String(OFFSET));
    params.append("sort_by", SORT_BY);
    params.append("sort_dir", SORT_DIR);

    // Добавляем фильтры
    for (const [col, value] of Object.entries(FILTERS)) {
      if (value) {
        params.append(`filter_${col}`, String(value));
      }
    }
    if (groupOnly && !FILTERS.group_id) {
      params.append("filter_group_id", groupOnly);
    }

    const data = await apiGet(`/api/online-search?${params.toString()}`);
    META = data.meta || META;
    LAST_LOAD_TIME = new Date(); // Сохраняем время загрузки
    renderHead(data.headers || HEADERS);
    renderRows(data.rows || []);
    const total = data.total || 0;
    if ($("os-total-pill")) setText("os-total-pill", String(total));
    updateInsights(data.rows || [], total);
    setText("pager", `Показано ${Math.min(LIMIT, (data.rows || []).length)} / всего ${total}. OFFSET=${OFFSET}`);
    setText("status", "");
    updateFilterIndicators();
    syncFilterUiFromState();
    await unitsP;
  } catch (e) {
    setText("status", `Ошибка: ${e.message || e}`);
    try {
      await unitsP;
    } catch (_) {
      /* список подразделений мог отобразить свою ошибку */
    }
  }
}

function toggleSort(by) {
  if (SORT_BY === by) {
    SORT_DIR = SORT_DIR === "asc" ? "desc" : "asc";
  } else {
    SORT_BY = by;
    SORT_DIR = by === "frequency" ? "desc" : "asc";
  }
  OFFSET = 0;
  load();
}

async function saveNoteInline(rowId, note) {
  setText("status", "Сохранение…");
  try {
    const data = await apiPost("/api/online-search/note", { id: rowId, note });
    const u = data.unit_sync || null;
    setText(
      "status",
      u ? `Сохранено. unit: inserted=${u.inserted}, updated=${u.updated}, matched=${u.matched_pairs}` : "Сохранено."
    );
    // обновим только видимую страницу
    await load();
  } catch (e) {
    setText("status", `Ошибка: ${e.message || e}`);
  }
}

async function saveDetailNote() {
  if (!SELECTED_ROW_ID) return;
  const noteInput = $("os-detail-note");
  if (!noteInput) return;
  const note = String(noteInput.value || "").trim();
  await saveNoteInline(SELECTED_ROW_ID, note);
}

function startInlineEdit(cell, row) {
  const rowId = Number(row.id || 0);
  if (!rowId) return;
  const prev = cell.textContent || "";
  cell.innerHTML = `<input class="form-control form-control-sm" data-inline="1" value="${escapeHtml(prev)}" />`;
  const inp = cell.querySelector('input[data-inline="1"]');
  inp.focus();
  inp.select();
  const finish = async (mode) => {
    const val = (inp.value || "").trim();
    if (mode === "cancel") {
      cell.textContent = prev;
      return;
    }
    if (val === prev) {
      cell.textContent = prev;
      return;
    }
    cell.textContent = val;
    await saveNoteInline(rowId, val);
  };
  inp.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") finish("save");
    if (ev.key === "Escape") finish("cancel");
  });
  inp.addEventListener("blur", () => finish("save"));
}

async function deleteRow(id) {
  if (!confirm(`Удалить строку #${id}?`)) return;
  setText("status", "Удаление…");
  try {
    await apiPost("/api/online-search/delete", { id });
    setText("status", "Удалено.");
    await load();
  } catch (e) {
    setText("status", `Ошибка: ${e.message || e}`);
  }
}

async function addRow() {
  const freq = prompt("Частота (col1):");
  if (!freq) return;
  const gid = prompt("Групповой ID (col2):");
  if (!gid) return;
  const note = prompt("Примечание:");
  const payload = {
    col1: freq,
    col2: gid,
    col9: note || "",
    frequency: freq,
    group_id: gid,
    note: note || "",
  };
  setText("status", "Добавление…");
  try {
    await apiPost("/api/online-search", { row: payload });
    setText("status", "Добавлено.");
    OFFSET = 0;
    await load();
  } catch (e) {
    setText("status", `Ошибка: ${e.message || e}`);
  }
}

async function importXlsx() {
  const input = $("import-xlsx");
  if (!input.files || !input.files.length) return;
  const importId = `imp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const fd = new FormData();
  // note → unit применяется автоматически
  fd.append("file", input.files[0]);
  fd.append("apply_to_unit", "1");
  fd.append("import_id", importId);
  let stopPolling = false;
  let pollTimer = null;
  const pollProgress = async () => {
    if (stopPolling) return;
    try {
      const data = await apiGet(`/api/online-search/import-progress?import_id=${encodeURIComponent(importId)}`);
      const p = data.progress || {};
      const percent = Number(p.percent || 0);
      const done = !!p.done;
      const total = Number(p.total_rows || 0);
      const processed = Number(p.processed_rows || 0);
      const message = String(p.message || "");
      const suffix = total > 0 ? ` (${processed}/${total})` : "";
      if (!done) {
        setText("status", `Импорт: ${percent}%${suffix}${message ? ` — ${message}` : ""}`);
      }
    } catch (_) {
      // игнорируем сбои polling
    } finally {
      if (!stopPolling) {
        pollTimer = setTimeout(pollProgress, 450);
      }
    }
  };
  setText("status", "Импорт: 0% — подготовка...");
  pollProgress();
  try {
    const data = await apiUpload("/api/online-search/import-xlsx", fd);
    stopPolling = true;
    if (pollTimer) clearTimeout(pollTimer);
    const syncNote = data.unit_sync ? ` | unit updated=${data.unit_sync.updated || 0}` : "";
    setText("status", `Импортировано строк: ${data.imported || 0}${syncNote}`);
    OFFSET = 0;
    await load();
  } catch (e) {
    stopPolling = true;
    if (pollTimer) clearTimeout(pollTimer);
    setText("status", `Ошибка: ${e.message || e}`);
  }
}

async function syncUnitsFromOnlineSearch() {
  const btn = $("sync-units-btn");
  if (btn) {
    btn.disabled = true;
    btn.dataset.origText = btn.innerHTML;
    btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Синхронизация...`;
  }
  setText("status", "Синхронизация unit...");
  try {
    const data = await apiPost("/api/online-search/sync-units", {});
    const info = data.stats
      ? `inserted=${data.stats.inserted || 0}, updated=${data.stats.updated || 0}, matched=${data.stats.matched_pairs || 0}`
      : "";
    setText("status", `Синхронизация завершена. ${info}`);
    showToast("Синхронизация unit завершена", "success");
  } catch (e) {
    setText("status", `Ошибка: ${e.message || e}`);
    showToast(`Ошибка: ${e.message || e}`, "danger");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = btn.dataset.origText || 'Синхронизировать unit';
    }
  }
}

async function exportXlsx() {
  const q = ($("q").value || "").trim();
  const url = `/api/online-search/export-xlsx?q=${encodeURIComponent(q)}`;
  window.location.href = url;
}

function showColumnFilter(th) {
  const filterType = th.dataset.filterType || "none";
  const filterCol = th.dataset.filterCol || "";
  const popup = $("column-filter-popup");
  const filterBody = $("filter-body");
  const filterTitle = $("filter-title");

  if (!popup || !filterBody || filterType === "none") return;

  // Позиционируем popup относительно заголовка
  const rect = th.getBoundingClientRect();
  popup.style.left = `${rect.left}px`;
  popup.style.top = `${rect.bottom + 5}px`;
  popup.style.display = "block";

  // Устанавливаем заголовок
  const colName = th.querySelector(".th-content span")?.textContent || filterCol;
  filterTitle.textContent = `Фильтр: ${colName}`;

  // Очищаем тело фильтра
  filterBody.innerHTML = "";

  const currentFilter = FILTERS[filterCol] || "";

  if (filterType === "select" && filterCol === "group_id") {
    // Фильтр по группам
    const select = document.createElement("select");
    select.className = "form-select form-select-sm";
    select.id = "filter-select";
    select.innerHTML = '<option value="">Все группы</option>';
    for (const group of ALL_GROUPS) {
      const selected = currentFilter === group ? "selected" : "";
      select.innerHTML += `<option value="${escapeHtml(group)}" ${selected}>${escapeHtml(group)}</option>`;
    }
    filterBody.appendChild(select);
  } else if (filterType === "time" && filterCol === "updated_at") {
    // Фильтр по времени (новые данные сегодня)
    const div = document.createElement("div");
    div.innerHTML = `
      <div class="form-check mb-2">
        <input class="form-check-input" type="checkbox" id="filter-today" ${currentFilter === "today" ? "checked" : ""}>
        <label class="form-check-label" for="filter-today">
          Только новые данные (за последние 24 часа)
        </label>
      </div>
    `;
    filterBody.appendChild(div);
  } else if (filterType === "text") {
    // Текстовый фильтр
    const input = document.createElement("input");
    input.type = "text";
    input.className = "form-control form-control-sm";
    input.id = "filter-text";
    input.placeholder = `Введите значение для ${colName}`;
    input.value = currentFilter;
    filterBody.appendChild(input);
  } else if (filterType === "date") {
    // Фильтр по дате
    const input = document.createElement("input");
    input.type = "date";
    input.className = "form-control form-control-sm";
    input.id = "filter-date";
    input.value = currentFilter;
    filterBody.appendChild(input);
  }

  // Сохраняем текущий столбец для применения фильтра
  popup.dataset.filterCol = filterCol;
}

function hideColumnFilter() {
  const popup = $("column-filter-popup");
  if (popup) popup.style.display = "none";
}

function applyFilter() {
  const popup = $("column-filter-popup");
  const filterCol = popup.dataset.filterCol;
  if (!filterCol) return;

  const filterBody = $("filter-body");
  let value = "";

  const select = filterBody.querySelector("#filter-select");
  if (select) {
    value = select.value || "";
  } else {
    const checkbox = filterBody.querySelector("#filter-today");
    if (checkbox) {
      value = checkbox.checked ? "today" : "";
    } else {
      const input = filterBody.querySelector("#filter-text, #filter-date");
      if (input) {
        value = input.value || "";
      }
    }
  }

  if (value) {
    FILTERS[filterCol] = value;
  } else {
    delete FILTERS[filterCol];
  }

  hideColumnFilter();
  OFFSET = 0;
  load();
}

function clearFilter() {
  const popup = $("column-filter-popup");
  const filterCol = popup.dataset.filterCol;
  if (filterCol) {
    delete FILTERS[filterCol];
  }
  hideColumnFilter();
  OFFSET = 0;
  load();
}

function updateFilterIndicators() {
  // Обновляем индикаторы активных фильтров на заголовках
  const filterableThs = document.querySelectorAll("#os-head .th-filterable");
  for (const th of filterableThs) {
    const filterCol = th.dataset.filterCol;
    const icon = th.querySelector(".th-filter-icon");
    if (icon && filterCol && FILTERS[filterCol]) {
      icon.classList.add("filter-active");
      icon.style.color = "var(--wp-accent)";
    } else if (icon) {
      icon.classList.remove("filter-active");
      icon.style.color = "";
    }
  }
}

function applySearchOnlineMobileUi() {
  const root = document.querySelector(".md3-search-online");
  if (!root) return;
  root.classList.toggle("so-mobile-ui", window.matchMedia("(max-width: 767.98px)").matches);
}

let EDITING_GROUP_INDEX = -1;

function startEditingGroup(index) {
  if (index < 0 || index >= MANUAL_UNIT_GROUPS.length) return;
  EDITING_GROUP_INDEX = index;
  const group = MANUAL_UNIT_GROUPS[index];

  if ($("os-group-label")) $("os-group-label").value = String(group.label || "");
  SELECTED_MANUAL_GROUP_UNITS = new Set(group.units || []);

  const modeBadge = $("os-group-mode-badge");
  if (modeBadge) {
    modeBadge.className = "badge rounded-pill bg-warning text-dark px-3 py-1.5 fw-semibold";
    modeBadge.innerHTML = '<i class="bi bi-pencil-fill me-1"></i>Редактирование';
  }
  const modeTitle = $("os-group-mode-title");
  if (modeTitle) {
    modeTitle.textContent = `Редактирование: ${group.label || "Группа"}`;
  }
  const cancelBtn = $("os-group-cancel-edit-btn");
  if (cancelBtn) cancelBtn.classList.remove("d-none");

  const addBtnText = $("os-group-add-btn-text");
  if (addBtnText) addBtnText.textContent = "Сохранить изменения";

  const builderCard = $("os-group-builder-card");
  if (builderCard) {
    builderCard.classList.add("border-primary", "shadow-sm");
    builderCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  renderManualGroupUnitOptions();
  renderManualGroups();
  if ($("os-group-label")) $("os-group-label").focus();
}

function cancelEditingGroup() {
  EDITING_GROUP_INDEX = -1;
  if ($("os-group-label")) $("os-group-label").value = "";
  SELECTED_MANUAL_GROUP_UNITS.clear();
  MANUAL_GROUP_SEARCH_QUERY = "";
  if ($("os-group-units-search")) $("os-group-units-search").value = "";

  const modeBadge = $("os-group-mode-badge");
  if (modeBadge) {
    modeBadge.className = "badge rounded-pill bg-primary px-3 py-1.5 fw-semibold";
    modeBadge.innerHTML = '<i class="bi bi-plus-circle me-1"></i>Новая группа';
  }
  const modeTitle = $("os-group-mode-title");
  if (modeTitle) {
    modeTitle.textContent = "Создание группы";
  }
  const cancelBtn = $("os-group-cancel-edit-btn");
  if (cancelBtn) cancelBtn.classList.add("d-none");

  const addBtnText = $("os-group-add-btn-text");
  if (addBtnText) addBtnText.textContent = "Сохранить группу";

  const builderCard = $("os-group-builder-card");
  if (builderCard) {
    builderCard.classList.remove("border-primary", "shadow-sm");
  }

  renderManualGroupUnitOptions();
  renderManualGroups();
}

function renderManualGroups() {
  const list = $("os-groups-list");
  if (!list) return;
  list.innerHTML = "";

  const query = MANUAL_GROUPS_SEARCH_QUERY.trim().toLowerCase();
  const visibleGroups = MANUAL_UNIT_GROUPS
    .map((group, index) => ({ group, index }))
    .filter(({ group }) => {
      if (!query) return true;
      const label = String(group.label || "").toLowerCase();
      const members = (group.units || []).some((unit) => String(unit || "").toLowerCase().includes(query));
      return label.includes(query) || members;
    });

  const totalBadge = $("os-groups-total-count");
  if (totalBadge) {
    totalBadge.textContent = query
      ? `${visibleGroups.length} из ${MANUAL_UNIT_GROUPS.length}`
      : String(MANUAL_UNIT_GROUPS.length);
  }

  if (!MANUAL_UNIT_GROUPS.length) {
    list.innerHTML = `
      <div class="text-center py-4 px-3 border rounded-3 bg-light text-muted">
        <i class="bi bi-folder-x fs-2 d-block mb-1 opacity-50"></i>
        <div class="small fw-semibold">Ручных групп пока нет</div>
        <div class="small text-secondary">Создайте первую группу, выбрав нужные подразделения выше</div>
      </div>`;
    return;
  }

  if (!visibleGroups.length) {
    list.innerHTML = `
      <div class="text-center py-4 px-3 border rounded-3 bg-light text-muted">
        <i class="bi bi-search fs-2 d-block mb-1 opacity-50"></i>
        <div class="small fw-semibold">Группы по запросу не найдены</div>
        <div class="small text-secondary">Попробуйте название группы или подразделения из её состава</div>
      </div>`;
    return;
  }

  visibleGroups.forEach(({ group, index }) => {
    const isEditing = EDITING_GROUP_INDEX === index;
    const item = document.createElement("div");
    item.className = `os-group-card-item rounded-3 p-3 ${isEditing ? "is-editing" : ""}`;

    const topRow = document.createElement("div");
    topRow.className = "d-flex justify-content-between align-items-start gap-2 mb-2";

    const titleWrap = document.createElement("div");
    titleWrap.className = "d-flex align-items-center gap-2 flex-wrap";

    const titleIcon = document.createElement("i");
    titleIcon.className = "bi bi-folder2-fill text-primary fs-5";

    const title = document.createElement("strong");
    title.className = "fs-6 fw-bold text-dark text-break";
    title.textContent = String(group.label || "Группа");

    const unitsCount = (group.units || []).length;
    const countBadge = document.createElement("span");
    countBadge.className = "badge bg-primary-subtle text-primary rounded-pill";
    countBadge.textContent = `${unitsCount} подразд.`;

    titleWrap.append(titleIcon, title, countBadge);

    if (isEditing) {
      const editBadge = document.createElement("span");
      editBadge.className = "badge bg-warning text-dark rounded-pill small";
      editBadge.innerHTML = '<i class="bi bi-pencil-fill me-1"></i>Редактируется';
      titleWrap.appendChild(editBadge);
    }

    const actions = document.createElement("div");
    actions.className = "d-flex gap-2 flex-shrink-0";

    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "btn btn-sm btn-outline-primary d-inline-flex align-items-center gap-1";
    editBtn.innerHTML = '<i class="bi bi-pencil"></i><span>Изменить</span>';
    editBtn.title = "Редактировать название и состав группы";
    editBtn.addEventListener("click", () => startEditingGroup(index));

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "btn btn-sm btn-outline-danger d-inline-flex align-items-center gap-1";
    remove.innerHTML = '<i class="bi bi-trash3"></i><span>Удалить</span>';
    remove.title = "Удалить группу";
    remove.addEventListener("click", async () => {
      if (!confirm(`Удалить группу "${group.label}"?`)) return;
      if (EDITING_GROUP_INDEX === index) {
        cancelEditingGroup();
      } else if (EDITING_GROUP_INDEX > index) {
        EDITING_GROUP_INDEX--;
      }
      MANUAL_UNIT_GROUPS.splice(index, 1);
      await saveManualGroups();
    });

    actions.append(editBtn, remove);
    topRow.append(titleWrap, actions);

    const membersWrap = document.createElement("div");
    membersWrap.className = "d-flex flex-wrap gap-1 mt-2";

    const unitsList = group.units || [];
    if (unitsList.length) {
      unitsList.forEach((u) => {
        const chip = document.createElement("span");
        chip.className = "os-group-unit-chip";
        chip.innerHTML = `<i class="bi bi-diagram-2 me-1 text-primary small"></i><span>${escapeHtml(u)}</span>`;
        membersWrap.appendChild(chip);
      });
    } else {
      membersWrap.innerHTML = '<span class="text-muted small">Нет выбранных подразделений</span>';
    }

    item.append(topRow, membersWrap);
    list.appendChild(item);
  });
}

let SELECTED_MANUAL_GROUP_UNITS = new Set();
let MANUAL_GROUP_SEARCH_QUERY = "";
let MANUAL_GROUPS_SEARCH_QUERY = "";

function updateManualGroupSelectedCount() {
  const badge = $("os-group-selected-count");
  if (badge) {
    badge.textContent = `Выбрано: ${SELECTED_MANUAL_GROUP_UNITS.size}`;
  }
}

function renderManualGroupUnitOptions() {
  const container = $("os-group-units-container");
  const fallbackSelect = $("os-group-units");
  if (!container && !fallbackSelect) return;

  // Если редактируем группу, её текущие подразделения не должны быть заблокированы
  const assigned = new Set(
    MANUAL_UNIT_GROUPS.flatMap((group, idx) =>
      idx === EDITING_GROUP_INDEX
        ? []
        : (group.units || []).map((u) => normalizeManualGroupNote(u))
    )
  );
  const query = MANUAL_GROUP_SEARCH_QUERY.trim().toLowerCase();

  const visibleUnits = MANUAL_GROUP_UNITS
    .map((unit, index) => {
      const key = String(unit.unit_key || "");
      const normKey = normalizeManualGroupNote(key);
      return { unit, index, key, normKey, isAssigned: assigned.has(normKey) || assigned.has(key) };
    })
    .filter((row) => !query || row.key.toLowerCase().includes(query))
    // Свободные сверху, уже распределённые (вычеркнутые) — вниз
    .sort((a, b) => {
      if (a.isAssigned !== b.isAssigned) return a.isAssigned ? 1 : -1;
      return a.key.localeCompare(b.key, "ru", { sensitivity: "base" });
    });

  if (container) {
    container.innerHTML = "";

    visibleUnits.forEach((item, renderIndex) => {
      const { unit, key, isAssigned } = item;
      const isChecked = SELECTED_MANUAL_GROUP_UNITS.has(key);

      const row = document.createElement("div");
      row.className = `form-check py-1 px-2 rounded os-unit-check-item d-flex align-items-center gap-2 mb-1 ${isChecked ? "bg-primary-subtle" : ""}`;

      const chk = document.createElement("input");
      chk.className = "form-check-input flex-shrink-0 mt-0";
      chk.type = "checkbox";
      chk.id = `os-unit-chk-${renderIndex}`;
      chk.value = key;
      chk.checked = isChecked;
      chk.disabled = isAssigned;

      chk.addEventListener("change", (e) => {
        if (e.target.checked) {
          SELECTED_MANUAL_GROUP_UNITS.add(key);
          row.classList.add("bg-primary-subtle");
        } else {
          SELECTED_MANUAL_GROUP_UNITS.delete(key);
          row.classList.remove("bg-primary-subtle");
        }
        updateManualGroupSelectedCount();
      });

      const label = document.createElement("label");
      label.className = "form-check-label d-flex justify-content-between align-items-center w-100 mb-0 user-select-none";
      label.htmlFor = `os-unit-chk-${renderIndex}`;
      label.style.cursor = isAssigned ? "not-allowed" : "pointer";

      const nameSpan = document.createElement("span");
      nameSpan.className = isAssigned ? "text-muted text-decoration-line-through small" : "fw-medium";
      nameSpan.textContent = key;

      const badgeSpan = document.createElement("span");
      if (isAssigned) {
        badgeSpan.className = "badge bg-secondary-subtle text-secondary small";
        badgeSpan.textContent = "уже в другой группе";
      } else {
        badgeSpan.className = "badge bg-light text-dark border small";
        badgeSpan.textContent = `${Number(unit.row_count || 0)} зап.`;
      }

      label.append(nameSpan, badgeSpan);
      row.append(chk, label);
      container.appendChild(row);
    });

    if (visibleUnits.length === 0) {
      const empty = document.createElement("div");
      empty.className = "text-muted small text-center py-3";
      empty.textContent = query ? "Подразделения по запросу не найдены" : "Список подразделений пуст";
      container.appendChild(empty);
    }

    updateManualGroupSelectedCount();
  }

  if (fallbackSelect) {
    fallbackSelect.innerHTML = "";
    for (const item of visibleUnits) {
      const option = document.createElement("option");
      option.value = item.key;
      option.textContent = `${item.key} — ${Number(item.unit.row_count || 0)} записей`;
      option.disabled = item.isAssigned;
      option.selected = SELECTED_MANUAL_GROUP_UNITS.has(item.key);
      fallbackSelect.appendChild(option);
    }
  }
}

function normalizeManualGroupNote(value) {
  let text = String(value || "").trim();
  text = text.replace(/[«»]/g, '"');
  text = text.replace(/[\u2018\u2019\u02bc]/g, "'");
  return text.split(/\s+/).filter(Boolean).join(" ");
}

function prepareManualGroupsPayload(groups) {
  const prepared = [];
  const labels = new Set();
  const assigned = new Map();
  for (const raw of groups || []) {
    const label = normalizeManualGroupNote(raw && raw.label);
    if (!label || label === "__none__") {
      throw new Error("Укажите название группы");
    }
    const labelKey = label.toLowerCase();
    if (labels.has(labelKey)) {
      throw new Error(`Название группы «${label}» уже используется`);
    }
    labels.add(labelKey);
    const members = [];
    const seen = new Set();
    for (const item of (raw && raw.units) || []) {
      const unit = normalizeManualGroupNote(item);
      if (!unit || unit === "__none__") continue;
      if (unit.toLowerCase() === labelKey) continue;
      if (seen.has(unit)) continue;
      if (assigned.has(unit)) {
        throw new Error(
          `Подразделение «${unit}» уже в группе «${assigned.get(unit)}», нельзя добавить в «${label}»`
        );
      }
      assigned.set(unit, label);
      seen.add(unit);
      members.push(unit);
    }
    if (members.length) prepared.push({ label, units: members });
  }
  return prepared;
}

async function saveManualGroups() {
  try {
    const payload = prepareManualGroupsPayload(MANUAL_UNIT_GROUPS);
    const data = await apiPost("/api/online-search/manual-groups", { groups: payload });
    MANUAL_UNIT_GROUPS = Array.isArray(data.groups) ? data.groups : [];
    renderManualGroups();
    renderManualGroupUnitOptions();
    await refreshUnitsList();
    showToast("Группы подразделений сохранены", "success");
    return true;
  } catch (e) {
    showToast(e.message || String(e), "danger");
    return false;
  }
}

async function openManualGroups() {
  try {
    const [groupsData, unitsData] = await Promise.all([
      apiGet("/api/online-search/manual-groups"),
      apiGet("/api/online-search/units"),
    ]);
    MANUAL_UNIT_GROUPS = Array.isArray(groupsData.groups) ? groupsData.groups : [];
    MANUAL_GROUP_UNITS = (unitsData.units || []).filter((unit) => unit.unit_key && unit.unit_key !== "__none__");
    MANUAL_GROUPS_SEARCH_QUERY = "";
    if ($("os-groups-search")) $("os-groups-search").value = "";
    cancelEditingGroup();
    if (window.bootstrap) window.bootstrap.Modal.getOrCreateInstance($("os-groups-modal")).show();
  } catch (e) {
    showToast(e.message || String(e), "danger");
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  applySearchOnlineMobileUi();
  window.matchMedia("(max-width: 767.98px)").addEventListener("change", applySearchOnlineMobileUi);

  $("load-btn").addEventListener("click", async () => {
    readFiltersFromUi();
    OFFSET = 0;
    await load();
  });
  $("prev-btn").addEventListener("click", async () => {
    OFFSET = Math.max(0, OFFSET - LIMIT);
    await load();
  });
  $("next-btn").addEventListener("click", async () => {
    OFFSET = OFFSET + LIMIT;
    await load();
  });
  if ($("add-row-btn")) $("add-row-btn").addEventListener("click", addRow);
  if ($("manage-groups-btn")) {
    $("manage-groups-btn").addEventListener("click", openManualGroups);
  }
  if ($("os-group-cancel-edit-btn")) {
    $("os-group-cancel-edit-btn").addEventListener("click", cancelEditingGroup);
  }
  if ($("os-group-units-search")) {
    $("os-group-units-search").addEventListener("input", (e) => {
      MANUAL_GROUP_SEARCH_QUERY = (e.target.value || "");
      renderManualGroupUnitOptions();
    });
  }
  if ($("os-groups-search")) {
    $("os-groups-search").addEventListener("input", (e) => {
      MANUAL_GROUPS_SEARCH_QUERY = e.target.value || "";
      renderManualGroups();
    });
  }
  if ($("os-group-units-select-all")) {
    $("os-group-units-select-all").addEventListener("click", () => {
      const assigned = new Set(
        MANUAL_UNIT_GROUPS.flatMap((group, idx) =>
          idx === EDITING_GROUP_INDEX
            ? []
            : (group.units || []).map((u) => normalizeManualGroupNote(u))
        )
      );
      const query = MANUAL_GROUP_SEARCH_QUERY.trim().toLowerCase();
      for (const unit of MANUAL_GROUP_UNITS) {
        const key = String(unit.unit_key || "");
        const normKey = normalizeManualGroupNote(key);
        if (assigned.has(normKey) || assigned.has(key)) continue;
        if (!query || key.toLowerCase().includes(query)) {
          SELECTED_MANUAL_GROUP_UNITS.add(key);
        }
      }
      renderManualGroupUnitOptions();
    });
  }
  if ($("os-group-units-clear-selection")) {
    $("os-group-units-clear-selection").addEventListener("click", () => {
      SELECTED_MANUAL_GROUP_UNITS.clear();
      renderManualGroupUnitOptions();
    });
  }
  if ($("os-group-add-btn")) {
    $("os-group-add-btn").addEventListener("click", async () => {
      const label = String($("os-group-label")?.value || "").trim();
      let selected = Array.from(SELECTED_MANUAL_GROUP_UNITS);
      if (!selected.length && $("os-group-units")) {
        selected = Array.from($("os-group-units")?.selectedOptions || []).map((option) => option.value);
      }
      if (!label || !selected.length) {
        showToast("Укажите название и выберите хотя бы одно подразделение", "warning");
        return;
      }
      const isEditing = EDITING_GROUP_INDEX >= 0;
      const labelKey = normalizeManualGroupNote(label).toLowerCase();
      const duplicateLabel = MANUAL_UNIT_GROUPS.some((group, idx) => {
        if (isEditing && idx === EDITING_GROUP_INDEX) return false;
        return normalizeManualGroupNote(group.label).toLowerCase() === labelKey;
      });
      if (duplicateLabel) {
        showToast(`Название группы «${label}» уже используется`, "warning");
        return;
      }
      if (isEditing) {
        MANUAL_UNIT_GROUPS[EDITING_GROUP_INDEX] = { label, units: selected };
      } else {
        MANUAL_UNIT_GROUPS.push({ label, units: selected });
      }
      cancelEditingGroup();
      const saved = await saveManualGroups();
      if (saved) {
        showToast(isEditing ? `Группа "${label}" обновлена` : `Группа "${label}" создана`, "success");
      }
    });
  }
  if ($("import-btn") && $("import-xlsx")) {
    $("import-btn").addEventListener("click", (e) => {
      e.preventDefault();
      $("import-xlsx").click();
    });
    $("import-xlsx").addEventListener("change", () => {
      void importXlsx();
    });
  }
  if ($("import-callout-btn") && $("import-xlsx")) {
    $("import-callout-btn").addEventListener("click", () => $("import-xlsx").click());
  }
  if ($("sync-units-btn")) $("sync-units-btn").addEventListener("click", syncUnitsFromOnlineSearch);
  $("export-btn").addEventListener("click", exportXlsx);
  if ($("mark-all-read-btn")) {
    $("mark-all-read-btn").addEventListener("click", async () => {
      if (!confirm("Отметить все записи как прочитанные? Тег 'новое' будет убран для всех записей.")) return;
      setText("status", "Отмечаю все как прочитанные…");
      try {
        const data = await apiPost("/api/online-search/mark-all-read", {});
        setText("status", `Готово. Отмечено записей: ${data.marked || 0}`);
        await load();
      } catch (e) {
        setText("status", `Ошибка: ${e.message || e}`);
      }
    });
  }

  if ($("os-search-clear")) {
    $("os-search-clear").addEventListener("click", async () => {
      FILTERS = {};
      if ($("q")) $("q").value = "";
      if ($("os-filter-confirm")) $("os-filter-confirm").value = "";
      if ($("os-filter-updated")) $("os-filter-updated").checked = false;
      updateGroupFilterOptions();
      syncFilterUiFromState();
      OFFSET = 0;
      await load();
    });
  }
  const qInput = $("q");
  if (qInput) {
    const debouncedLoad = debounce(async () => {
      readFiltersFromUi();
      OFFSET = 0;
      await load();
    }, 260);
    qInput.addEventListener("input", debouncedLoad);
    qInput.addEventListener("keydown", async (ev) => {
      if (ev.key !== "Enter") return;
      readFiltersFromUi();
      OFFSET = 0;
      await load();
    });
  }
  const dConfirm = $("os-filter-confirm");
  if (dConfirm) {
    dConfirm.addEventListener("change", async () => {
      readFiltersFromUi();
      OFFSET = 0;
      await load();
    });
  }
  const dUpdated = $("os-filter-updated");
  if (dUpdated) {
    dUpdated.addEventListener("change", async () => {
      readFiltersFromUi();
      OFFSET = 0;
      await load();
    });
  }

  if ($("os-detail-note-save")) {
    $("os-detail-note-save").addEventListener("click", saveDetailNote);
  }
  if ($("os-detail-note-cancel")) {
    $("os-detail-note-cancel").addEventListener("click", () => {
      if (SELECTED_ROW_ID && ROW_MAP.has(SELECTED_ROW_ID)) {
        renderDetail(ROW_MAP.get(SELECTED_ROW_ID));
      }
    });
  }

  // Обработчики фильтров
  if ($("filter-apply")) {
    $("filter-apply").addEventListener("click", applyFilter);
  }
  if ($("filter-clear")) {
    $("filter-clear").addEventListener("click", clearFilter);
  }
  if ($("filter-close")) {
    $("filter-close").addEventListener("click", hideColumnFilter);
  }

  // Клики по заголовкам для фильтрации
  const head = $("os-head");
  if (head) {
    head.addEventListener("click", (ev) => {
      const th = ev.target.closest(".os-filter-head-item, th");
      if (!th) return;

      const isFilterClick =
        ev.target.closest(".th-filter-icon") ||
        (ev.target.closest(".th-content") && !ev.target.closest(".os-h-label"));

      if (isFilterClick && th.classList.contains("th-filterable")) {
        ev.preventDefault();
        ev.stopPropagation();
        showColumnFilter(th);
        return;
      }

      const by = th.dataset.sort;
      if (by) {
        toggleSort(by);
      }
    });
  }

  // Закрытие фильтра при клике вне его
  document.addEventListener("click", (ev) => {
    const popup = $("column-filter-popup");
    if (popup && !popup.contains(ev.target) && !ev.target.closest(".os-filter-head-item, .th-filterable, th")) {
      hideColumnFilter();
    }
  });

  await load();
});
