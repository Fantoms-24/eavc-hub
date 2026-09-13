async function apiGet(url) {
  const res = await fetch(url, { method: "GET", cache: "no-store" });
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

/** Зона частоты (целые МГц) — как freq_zone_for_sessions_merge на сервере. */
function freqZoneForSessionsMerge(freq) {
  const s = String(freq || "").trim().replace(",", ".");
  if (!s) return "";
  const n = Number.parseFloat(s);
  if (!Number.isFinite(n)) return "";
  return String(Math.trunc(n));
}

function sessionsRowIsFavorite(frequency, group, favoritesList) {
  const rf = String(frequency || "").trim();
  const rg = String(group || "").trim();
  const zr = freqZoneForSessionsMerge(rf);
  for (const f of favoritesList || []) {
    const ff = String(f.frequency || "").trim();
    const fg = String(f.group || "").trim();
    if (!ff || ff === "__unit__") continue;
    if (fg !== rg) continue;
    const zf = freqZoneForSessionsMerge(ff);
    if (zr && zf && zr === zf) return true;
    if (rf === ff) return true;
  }
  return false;
}

function findMatchingSessionsFavorite(frequency, group, favoritesList) {
  const rf = String(frequency || "").trim();
  const rg = String(group || "").trim();
  const zr = freqZoneForSessionsMerge(rf);
  for (const f of favoritesList || []) {
    const ff = String(f.frequency || "").trim();
    const fg = String(f.group || "").trim();
    if (!ff || ff === "__unit__") continue;
    if (fg !== rg) continue;
    const zf = freqZoneForSessionsMerge(ff);
    if (zr && zf && zr === zf) return f;
    if (rf === ff) return f;
  }
  return null;
}

function findUnitFavoriteEntry(unitName, favoritesList) {
  const u = String(unitName || "").trim().toLowerCase();
  if (!u) return null;
  for (const f of favoritesList || []) {
    if (String(f.frequency || "").trim() !== "__unit__") continue;
    const g = String(f.group || "").trim();
    if (g.toLowerCase() === u) return f;
  }
  return null;
}

function recomputeSessionsRowFavorites(rows) {
  for (const row of rows || []) {
    row.is_favorite = sessionsRowIsFavorite(row.frequency, row.group, favorites);
  }
}

function countPairFavorites(favoritesList) {
  return (favoritesList || []).filter(
    (f) => String(f.frequency || "").trim() && String(f.frequency || "").trim() !== "__unit__"
  ).length;
}

/** Подразделение с реальным названием (не пусто и не «н/у …»). */
function sessionsRowHasNamedUnit(row) {
  const n = String(row?.name || "").trim().toLowerCase();
  if (!n) return false;
  if (n.startsWith("н/у") || n.includes("н/у подразделение")) return false;
  if (["n/a", "na", "unknown", "без привязки", "не определено"].includes(n)) return false;
  return true;
}

function countNamedFavoriteRows(data) {
  return (data || []).filter(
    (row) =>
      sessionsRowIsFavorite(row.frequency, row.group, favorites) &&
      sessionsRowHasNamedUnit(row)
  ).length;
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

function canEditUnitName() {
  return $("sessions-perms")?.dataset?.canEditUnit === "1";
}

function _setWatchUiRunning(running) {
  const startBtn = $("start-watch-btn");
  const stopBtn = $("stop-watch-btn");
  const statusCard = $("watch-status-card");
  if (startBtn) startBtn.style.display = running ? "none" : "inline-block";
  if (stopBtn) stopBtn.style.display = running ? "inline-block" : "none";
  if (statusCard) statusCard.style.display = "block";
}

// Состояние
let isProcessing = false;
let isWatching = false;
let lastWatchStatus = null;
let tableData = [];
let tableTotal = 0;
let favorites = [];
let showFavoritesOnly = false;
let watchStatusTimer = null;
let watchPollCancelled = false;
/** >0 пока выполняется watchStatusPollOnce (в т.ч. await); чтобы startWatch не сбрасывал опрос изнутри тика */
let watchPollTickDepth = 0;
let watchVisibilityHookInstalled = false;
/** Интервалы опроса /api/sessions/watch-status: реже в простое и в фоне — меньше нагрузка на UI и сервер. */
const WATCH_POLL_ACTIVE_MS = 7000;
const WATCH_POLL_ACTIVE_SCAN_MS = 2500;
const WATCH_POLL_IDLE_MS = 26000;
const WATCH_POLL_HIDDEN_MS = 90000;
let tableHandlersInstalled = false;
let tableControlsInstalled = false;
let tableFilters = {
  query: "",
  frequency: "",
  group: "",
  name: "",
  ids: "",
  countMin: "",
};
let tableSort = {
  key: "frequency",
  dir: "desc",
};

function _frequencySortValue(freq) {
  const s = String(freq || "").trim().replace(",", ".");
  const n = parseFloat(s);
  return Number.isFinite(n) ? n : 0;
}

function _groupSortValue(group) {
  const s = String(group || "").trim();
  const m = s.match(/\d+/);
  if (m) {
    const n = parseInt(m[0], 10);
    return Number.isFinite(n) ? n : 0;
  }
  return 0;
}

function _compareSessionsRows(a, b, key, dir) {
  const d = dir === "asc" ? 1 : -1;
  if (key === "count") {
    return (Number(a.count || 0) - Number(b.count || 0)) * d;
  }
  if (key === "frequency") {
    const diff = (_frequencySortValue(a.frequency) - _frequencySortValue(b.frequency)) * d;
    if (diff !== 0) return diff;
    return String(a.frequency || "").localeCompare(String(b.frequency || ""), "ru", {
      numeric: true,
      sensitivity: "base",
    }) * d;
  }
  if (key === "group") {
    const diff = (_groupSortValue(a.group) - _groupSortValue(b.group)) * d;
    if (diff !== 0) return diff;
    return String(a.group || "").localeCompare(String(b.group || ""), "ru", {
      numeric: true,
      sensitivity: "base",
    }) * d;
  }
  const av = String(a.name || "");
  const bv = String(b.name || "");
  return av.localeCompare(bv, "ru", { numeric: true, sensitivity: "base" }) * d;
}

function _sortSessionsTableRows(rows) {
  const key = tableSort.key || "frequency";
  const dir = tableSort.dir || "desc";
  const secondaryKey =
    key === "frequency" ? "group" : key === "group" ? "frequency" : "";
  return rows.slice().sort((a, b) => {
    const primary = _compareSessionsRows(a, b, key, dir);
    if (primary !== 0 || !secondaryKey) return primary;
    return _compareSessionsRows(a, b, secondaryKey, "desc");
  });
}
const SESSIONS_FOLDER_PATH_KEY = "wp_sessions_folder_path";

function _todayYmdLocal() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function _replaceTrailingYmd(path, ymd) {
  const s = String(path || "").trim();
  if (!s) return s;
  return s.replace(/(\d{4}-\d{2}-\d{2})([\\/]*$)/, `${ymd}$2`);
}

function _syncFolderPathDateWithLocalNow(folderPathInput) {
  if (!folderPathInput) return;
  const current = String(folderPathInput.value || "");
  const next = _replaceTrailingYmd(current, _todayYmdLocal());
  if (next !== current) {
    folderPathInput.value = next;
    folderPathInput.dispatchEvent(new Event("input"));
  }
}

const SN_MOBILE_MQ = window.matchMedia("(max-width: 767.98px)");
const SN_SECTION_KEY = "wp.sessions.mobileSection";
const SN_PANEL_KEY = "wp.sessions.mainPanel";
const SN_SECTIONS = ["folder", "table", "stats"];
const SN_MAIN_PANELS = ["table", "ai", "overview"];

function setSessionsMainPanel(panel) {
  const root = document.querySelector(".md3-sessions.sn-workbench-ui");
  if (!root) return;
  const p = SN_MAIN_PANELS.includes(panel) ? panel : "table";
  root.setAttribute("data-sn-panel", p);
  root.querySelectorAll(".sn-panel[data-sn-panel]").forEach((el) => {
    const name = el.getAttribute("data-sn-panel");
    if (name === p) el.removeAttribute("hidden");
    else el.setAttribute("hidden", "");
  });
  root.querySelectorAll("[data-sn-tab]").forEach((btn) => {
    const on = btn.getAttribute("data-sn-tab") === p;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
  try {
    localStorage.setItem(SN_PANEL_KEY, p);
  } catch (_e) {
    // ignore
  }
}

function setSessionsMobileSection(section) {
  const root = document.querySelector(".md3-sessions");
  const dock = document.getElementById("sn-mobile-dock");
  if (!root || !dock) return;
  const s = SN_SECTIONS.includes(section) ? section : "folder";
  root.setAttribute("data-sn-section", s);
  const idx = SN_SECTIONS.indexOf(s);
  dock.style.setProperty("--sn-dock-index", String(idx >= 0 ? idx : 0));
  dock.querySelectorAll("[data-sn-section]").forEach((btn) => {
    const on = btn.getAttribute("data-sn-section") === s;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
  if (s === "table") setSessionsMainPanel("table");
  if (s === "stats") {
    root.querySelectorAll(".sn-panel[data-sn-panel='ai'], .sn-panel[data-sn-panel='overview']").forEach((el) => {
      el.removeAttribute("hidden");
    });
    const tablePanel = root.querySelector(".sn-panel[data-sn-panel='table']");
    if (tablePanel) tablePanel.setAttribute("hidden", "");
  }
  try {
    localStorage.setItem(SN_SECTION_KEY, s);
  } catch (_e) {
    // ignore
  }
}

window.setSessionsMobileSection = setSessionsMobileSection;
window.setSessionsMainPanel = setSessionsMainPanel;

function applySessionsMobileUi() {
  const root = document.querySelector(".md3-sessions");
  const dock = document.getElementById("sn-mobile-dock");
  if (!root || !dock) return;
  const on = !!SN_MOBILE_MQ.matches;
  root.classList.toggle("sn-mobile-ui", on);
  dock.hidden = !on;
  if (on) {
    let s = "folder";
    try {
      const saved = localStorage.getItem(SN_SECTION_KEY);
      if (SN_SECTIONS.includes(saved)) s = saved;
    } catch (_e) {
      // ignore
    }
    setSessionsMobileSection(s);
  }
}

// Инициализация
document.addEventListener("DOMContentLoaded", function () {
  const folderPathInput = $("folder-path");
  const browseBtn = $("browse-folder-btn");
  const processBtn = $("process-folder-btn");
  const audioArchiveInput = $("audio-archive-path");
  const audioArchiveBtn = $("import-audio-archive-btn");
  const audioArchiveDryRun = $("audio-archive-dry-run");
  const refreshStatsBtn = $("refresh-stats-btn");
  const startWatchBtn = $("start-watch-btn");
  const stopWatchBtn = $("stop-watch-btn");
  const loadTableBtn = $("load-table-btn");
  const exportWordBtn = $("export-word-btn");
  const exportExcelBtn = $("export-excel-btn");
  const exportExcelBtnTable = $("export-excel-btn-table");
  const dateFrom = $("date-from");
  const timeFrom = $("time-from");
  const dateTo = $("date-to");
  const timeTo = $("time-to");
  const showFavoritesOnlyCheckbox = $("show-favorites-only");
  const clearFiltersBtn = $("clear-filters-btn");
  const datePresets = document.querySelectorAll("#date-presets [data-range]");
  const sessionsAiRunBtn = $("sessions-ai-run-btn");
  const sessionsAiTodayBtn = $("sessions-ai-today-btn");
  const sessionsAiWeekBtn = $("sessions-ai-week-btn");
  const sessionsAiMonthBtn = $("sessions-ai-month-btn");

  // Устанавливаем даты по умолчанию (сегодня)
  const today = _todayYmdLocal();
  if (dateFrom) dateFrom.value = today;
  if (dateTo) dateTo.value = today;
  if (timeFrom) timeFrom.value = "00:00";
  if (timeTo) timeTo.value = "23:59";
  _updateSessionsExportUnitBtn();

  // Загрузка статистики и таблицы при загрузке страницы
  loadStats();
  loadFavorites();
  loadTableData();
  initIdWatchUi();
  initSessionsTableHandlers();
  initSessionsTableControls();
  startWatchStatusPolling();

  // Restore folder path from localStorage
  try {
    if (folderPathInput && !folderPathInput.value) {
      const saved = localStorage.getItem(SESSIONS_FOLDER_PATH_KEY);
      if (saved) {
        folderPathInput.value = saved;
        folderPathInput.dispatchEvent(new Event("input"));
      }
    }
  } catch (_e) {
    // ignore
  }
  _syncFolderPathDateWithLocalNow(folderPathInput);
  if (folderPathInput) folderPathInput.dispatchEvent(new Event("input"));
  setInterval(() => _syncFolderPathDateWithLocalNow(folderPathInput), 30_000);

  if (audioArchiveInput) {
    audioArchiveInput.addEventListener("input", function () {
      const path = audioArchiveInput.value.trim();
      if (audioArchiveBtn) {
        audioArchiveBtn.disabled = !path || isProcessing;
      }
    });
    audioArchiveInput.dispatchEvent(new Event("input"));
  }

  if (audioArchiveBtn) {
    audioArchiveBtn.addEventListener("click", async function () {
      const path = (audioArchiveInput?.value || "").trim();
      if (!path) {
        alert("Укажите путь к файлу .zip");
        return;
      }
      const dryRun = !!(audioArchiveDryRun && audioArchiveDryRun.checked);
      const ok = window.confirm(
        dryRun
          ? `Проверить архив без записи в БД?\n\n${path}`
          : `Загрузить сеансы из архива в базу данных?\n\n${path}\n\nОперация может занять несколько минут.`
      );
      if (!ok) return;
      await importAudioArchive(path, dryRun);
    });
  }

  // Переключение показа только избранного
  if (showFavoritesOnlyCheckbox) {
    showFavoritesOnlyCheckbox.addEventListener("change", function () {
      showFavoritesOnly = this.checked;
      displayTable(tableData);
    });
  }

  // Обновление статистики
  if (refreshStatsBtn) {
    refreshStatsBtn.addEventListener("click", loadStats);
  }

  // Валидация пути
  if (folderPathInput) {
    folderPathInput.addEventListener("input", function () {
      const path = folderPathInput.value.trim();
      // Persist to localStorage
      try {
        localStorage.setItem(SESSIONS_FOLDER_PATH_KEY, path);
      } catch (_e) {
        // ignore
      }
      if (processBtn) {
        processBtn.disabled = !path || isProcessing;
      }
      if (startWatchBtn) {
        startWatchBtn.disabled = !path || isWatching;
      }
    });
  }

  // Кнопка обзора папок
  if (browseBtn) {
    browseBtn.addEventListener("click", async function () {
      try {
        const data = await apiGet("/api/pick-folder");
        showCommonPaths(data);
      } catch (error) {
        alert("Ошибка получения списка папок: " + error.message);
      }
    });
  }

  // Обработка папки
  if (processBtn) {
    processBtn.addEventListener("click", async function () {
      _syncFolderPathDateWithLocalNow(folderPathInput);
      const path = folderPathInput.value.trim();
      if (!path) {
        alert("Укажите путь к папке");
        return;
      }
      await processFolder(path);
    });
  }

  // Запуск автопоиска
  if (startWatchBtn) {
    startWatchBtn.addEventListener("click", async function () {
      _syncFolderPathDateWithLocalNow(folderPathInput);
      const path = folderPathInput.value.trim();
      if (!path) {
        alert("Укажите путь к папке");
        return;
      }
      await startWatch(path);
    });
  }

  // Остановка автопоиска
  if (stopWatchBtn) {
    stopWatchBtn.addEventListener("click", async function () {
      await stopWatch();
    });
  }

  // Загрузка таблицы
  if (loadTableBtn) {
    loadTableBtn.addEventListener("click", loadTableData);
  }

  if (clearFiltersBtn) {
    clearFiltersBtn.addEventListener("click", () => {
      tableFilters = { query: "", frequency: "", group: "", name: "", ids: "", countMin: "" };
      const ids = ["filter-all", "filter-frequency", "filter-group", "filter-name", "filter-ids", "filter-count-min"];
      ids.forEach((id) => {
        const el = $(id);
        if (el) el.value = "";
      });
      displayTable(tableData);
    });
  }

  if (datePresets && datePresets.length) {
    datePresets.forEach((btn) => {
      btn.addEventListener("click", () => {
        const range = btn.getAttribute("data-range");
        applyDatePreset(range);
      });
    });
  }
  if (sessionsAiRunBtn) sessionsAiRunBtn.addEventListener("click", runSessionsAiAnalysis);
  if (sessionsAiTodayBtn) sessionsAiTodayBtn.addEventListener("click", () => applyDatePreset("today"));
  if (sessionsAiWeekBtn) sessionsAiWeekBtn.addEventListener("click", () => applyDatePreset("7"));
  if (sessionsAiMonthBtn) sessionsAiMonthBtn.addEventListener("click", () => applyDatePreset("30"));

  // Экспорт в Word
  if (exportWordBtn) {
    exportWordBtn.addEventListener("click", exportToWord);
    if (exportExcelBtn) exportExcelBtn.addEventListener("click", exportToExcel);
    if (exportExcelBtnTable) exportExcelBtnTable.addEventListener("click", exportToExcel);
  }
  const exportUnitBtn = $("export-unit-btn");
  if (exportUnitBtn) exportUnitBtn.addEventListener("click", exportUnitToExcel);
  const exportUnitName = $("export-unit-name");
  if (exportUnitName) {
    exportUnitName.addEventListener("input", _updateSessionsExportUnitBtn);
    exportUnitName.addEventListener("change", _updateSessionsExportUnitBtn);
  }

  let savedPanel = "table";
  try {
    const sp = localStorage.getItem(SN_PANEL_KEY);
    if (SN_MAIN_PANELS.includes(sp)) savedPanel = sp;
  } catch (_e) {
    // ignore
  }
  setSessionsMainPanel(savedPanel);

  document.querySelectorAll("[data-sn-tab]").forEach((btn) => {
    btn.addEventListener("click", function () {
      const panel = btn.getAttribute("data-sn-tab");
      setSessionsMainPanel(panel);
      if (SN_MOBILE_MQ.matches) setSessionsMobileSection("table");
    });
  });

  const snBack = document.getElementById("sn-main-back");
  if (snBack) {
    snBack.addEventListener("click", function () {
      if (window.EavcMobileNav && typeof window.EavcMobileNav.goBack === "function") {
        window.EavcMobileNav.goBack();
      } else {
        setSessionsMobileSection("folder");
      }
    });
  }

  applySessionsMobileUi();
  SN_MOBILE_MQ.addEventListener("change", applySessionsMobileUi);
  const snDock = document.getElementById("sn-mobile-dock");
  if (snDock) {
    snDock.addEventListener("click", function (ev) {
      const btn = ev.target.closest("[data-sn-section]");
      if (!btn) return;
      setSessionsMobileSection(btn.getAttribute("data-sn-section"));
    });
  }
});

function initSessionsTableHandlers() {
  if (tableHandlersInstalled) return;
  const tbody = $("sessions-table-body");
  if (!tbody) return;
  tableHandlersInstalled = true;

  // Клик по звезде "избранное"
  tbody.addEventListener("click", async function (ev) {
    const el = ev.target && ev.target.closest ? ev.target.closest("[data-action]") : null;
    if (!el) return;
    const action = el.getAttribute("data-action");
    if (!action) return;
    ev.preventDefault();

    const frequency = (el.getAttribute("data-frequency") || "").trim();
    const group = (el.getAttribute("data-group") || "").trim();
    const name = (el.getAttribute("data-name") || "").trim();

    if (action === "toggle-favorite") {
      if (!frequency || !group) return;
      await toggleFavorite(frequency, group, name);
      return;
    }
    if (action === "edit-unit") {
      if (!frequency || !group) return;
      await promptEditUnitName(frequency, group, name);
      return;
    }
    if (action === "copy-frequency") {
      if (!frequency) return;
      copyTextToClipboard(frequency);
      return;
    }
    if (action === "copy-group") {
      if (!group) return;
      copyTextToClipboard(group);
      return;
    }
    if (action === "copy-pair") {
      if (!frequency || !group) return;
      copyTextToClipboard(`${frequency} ${group}`);
      return;
    }
    if (action === "debug-unit") {
      if (!frequency || !group) return;
      await showUnitDebug(frequency, group);
      return;
    }
  });

  // Двойной клик по названию подразделения — редактирование
  tbody.addEventListener("dblclick", async function (ev) {
    const el = ev.target && ev.target.closest ? ev.target.closest("[data-action]") : null;
    if (!el) return;
    const action = el.getAttribute("data-action");
    if (action !== "edit-unit-name") return;
    ev.preventDefault();

    const frequency = (el.getAttribute("data-frequency") || "").trim();
    const group = (el.getAttribute("data-group") || "").trim();
    const currentName = (el.getAttribute("data-name") || "").trim();
    if (!frequency || !group) return;
    await promptEditUnitName(frequency, group, currentName);
  });
}

async function promptEditUnitName(frequency, group, currentName) {
  if (!canEditUnitName()) {
    alert("Недостаточно прав для изменения подразделения.");
    return;
  }
  const promptText = "Введите название подразделения (пусто — убрать):";
  const next = window.prompt(promptText, currentName);
  if (next === null) return;

  const newName = String(next || "").trim();
  try {
    await apiPost("/api/sessions/update-unit-name", {
      frequency: frequency,
      group: group,
      name: newName,
    });
    await loadTableData();
  } catch (error) {
    alert("Ошибка сохранения подразделения: " + error.message);
  }
}

function copyTextToClipboard(text) {
  if (!text) return;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).catch(() => {
      window.prompt("Скопируйте значение:", text);
    });
  } else {
    window.prompt("Скопируйте значение:", text);
  }
}

function initSessionsTableControls() {
  if (tableControlsInstalled) return;
  tableControlsInstalled = true;

  const filterAll = $("filter-all");
  const filterFrequency = $("filter-frequency");
  const filterGroup = $("filter-group");
  const filterName = $("filter-name");
  const filterIds = $("filter-ids");
  const filterCountMin = $("filter-count-min");
  const table = $("sessions-table");
  const renderDebounced = debounce(() => displayTable(tableData), 220);

  if (filterAll) {
    filterAll.addEventListener("input", () => {
      tableFilters.query = String(filterAll.value || "").trim().toLowerCase();
      renderDebounced();
    });
  }
  if (filterFrequency) {
    filterFrequency.addEventListener("input", () => {
      tableFilters.frequency = String(filterFrequency.value || "").trim().toLowerCase();
      renderDebounced();
    });
  }
  if (filterGroup) {
    filterGroup.addEventListener("input", () => {
      tableFilters.group = String(filterGroup.value || "").trim().toLowerCase();
      renderDebounced();
    });
  }
  if (filterName) {
    filterName.addEventListener("input", () => {
      tableFilters.name = String(filterName.value || "").trim().toLowerCase();
      renderDebounced();
    });
  }
  if (filterIds) {
    filterIds.addEventListener("input", () => {
      tableFilters.ids = String(filterIds.value || "").trim().toLowerCase();
      renderDebounced();
    });
  }
  if (filterCountMin) {
    filterCountMin.addEventListener("input", () => {
      tableFilters.countMin = String(filterCountMin.value || "").trim();
      renderDebounced();
    });
  }

  if (table) {
    table.addEventListener("click", (ev) => {
      const btn = ev.target && ev.target.closest ? ev.target.closest("[data-sort]") : null;
      if (!btn) return;
      const key = String(btn.getAttribute("data-sort") || "").trim();
      if (!key) return;
      if (tableSort.key === key) {
        tableSort.dir = tableSort.dir === "desc" ? "asc" : "desc";
      } else {
        tableSort.key = key;
        tableSort.dir = "desc";
      }
      updateSortIndicators();
      displayTable(tableData);
    });
  }

  updateSortIndicators();
}

// Показать быстрые пути
function showCommonPaths(data) {
  const container = $("common-paths-container");
  const list = $("common-paths-list");
  const folderPathInput = $("folder-path");

  if (!container || !list) return;

  container.style.display = "block";
  list.innerHTML = "";

  // Диски
  if (data.drives && data.drives.length > 0) {
    data.drives.forEach((drive) => {
      const btn = document.createElement("button");
      btn.className = "btn btn-outline-secondary btn-sm";
      btn.textContent = drive;
      btn.addEventListener("click", function () {
        folderPathInput.value = drive;
        folderPathInput.dispatchEvent(new Event("input"));
      });
      list.appendChild(btn);
    });
  }

  // Общие пути
  if (data.common_paths && data.common_paths.length > 0) {
    data.common_paths.forEach((path) => {
      const btn = document.createElement("button");
      btn.className = "btn btn-outline-secondary btn-sm";
      btn.textContent = path;
      btn.addEventListener("click", function () {
        folderPathInput.value = path;
        folderPathInput.dispatchEvent(new Event("input"));
      });
      list.appendChild(btn);
    });
  }
}

async function pollAudioArchiveImportProgress(importId, ui) {
  const deadline = Date.now() + 60 * 60 * 1000;
  while (Date.now() < deadline) {
    const st = await apiGet(
      `/api/sessions/import-audio-archive/progress?import_id=${encodeURIComponent(importId)}`
    );
    const p = st.progress || {};
    if (ui.message) {
      ui.message.textContent = p.message || p.phase || "Импорт архива…";
    }
    if (p.done) {
      if (p.phase === "error" || p.error) {
        throw new Error(p.error || p.message || "Ошибка импорта архива");
      }
      return st.result || p;
    }
    await new Promise((resolve) => setTimeout(resolve, 800));
  }
  throw new Error("Таймаут импорта архива");
}

async function importAudioArchive(zipPath, dryRun) {
  if (isProcessing) return;

  isProcessing = true;
  const btn = $("import-audio-archive-btn");
  const statusEl = $("audio-archive-status");
  const resultsCard = $("results-card");
  const message = $("processing-message");

  if (statusEl) {
    statusEl.style.display = "block";
    statusEl.className = "small text-muted mt-2";
    statusEl.textContent = dryRun ? "Проверка архива…" : "Импорт архива…";
  }
  if (btn) btn.disabled = true;

  try {
    const importId = `audio-${Date.now()}`;
    const queued = await apiPost("/api/sessions/import-audio-archive", {
      zip_path: zipPath,
      import_id: importId,
      dry_run: !!dryRun,
    });
    const data =
      queued.queued && queued.import_id
        ? await pollAudioArchiveImportProgress(queued.import_id, { message: statusEl || message })
        : queued;

    const summary =
      `Файлов в архиве: ${data.members || 0}, WAV: ${data.wav_members || 0}, ` +
      `распознано сеансов: ${data.parsed || 0}` +
      (dryRun ? " (без записи в БД)" : `, записано: ${data.total_records || 0}`);

    if (statusEl) {
      statusEl.className = "small text-success mt-2";
      statusEl.textContent = summary;
    }
    if (resultsCard && !dryRun && (data.total_records || 0) > 0) {
      resultsCard.style.display = "block";
      showResults({
        total_files: 1,
        total_records: data.total_records || 0,
      });
    }
    loadStats();
    loadTableData();
  } catch (error) {
    if (statusEl) {
      statusEl.className = "small text-danger mt-2";
      statusEl.textContent = "Ошибка: " + (error.message || error);
    }
  } finally {
    isProcessing = false;
    const path = ($("audio-archive-path")?.value || "").trim();
    if (btn) btn.disabled = !path;
  }
}

async function pollFolderImportProgress(importId, ui) {
  const deadline = Date.now() + 30 * 60 * 1000;
  while (Date.now() < deadline) {
    const st = await apiGet(
      `/api/sessions/process-folder/progress?import_id=${encodeURIComponent(importId)}`
    );
    const p = st.progress || {};
    if (ui.message) {
      ui.message.textContent = p.message || p.phase || "Обработка файлов…";
    }
    if (p.done) {
      if (p.phase === "error" || p.error) {
        throw new Error(p.error || p.message || "Ошибка импорта");
      }
      return st.result || p;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error("Таймаут импорта папки");
}

// Обработка папки
async function processFolder(path) {
  if (isProcessing) return;

  isProcessing = true;
  const processBtn = $("process-folder-btn");
  const statusCard = $("processing-status-card");
  const resultsCard = $("results-card");
  const spinner = $("processing-spinner");
  const message = $("processing-message");
  const progress = $("processing-progress");

  // Сброс UI
  if (resultsCard) resultsCard.style.display = "none";
  if (statusCard) statusCard.style.display = "block";
  if (processBtn) processBtn.disabled = true;
  if (spinner) spinner.style.display = "block";
  if (message) message.textContent = "Обработка файлов...";
  if (progress) {
    progress.style.width = "0%";
    progress.textContent = "0%";
  }

  try {
    const importId = `seans-${Date.now()}`;
    const queued = await apiPost("/api/sessions/process-folder", {
      folder_path: path,
      import_id: importId,
    });
    const data =
      queued.queued && queued.import_id
        ? await pollFolderImportProgress(queued.import_id, { message })
        : queued;

    // Успешная обработка
    if (statusCard) statusCard.style.display = "none";
    if (resultsCard) {
      resultsCard.style.display = "block";
      showResults(data);
    }
    // Обновляем статистику и таблицу
    loadStats();
    loadTableData();
  } catch (error) {
    // Ошибка
    if (statusCard) statusCard.style.display = "none";
    if (resultsCard) {
      resultsCard.style.display = "block";
      showError(error.message);
    }
  } finally {
    isProcessing = false;
    if (processBtn) processBtn.disabled = false;
  }
}

// Показать результаты
function showResults(data) {
  const resultsContent = $("results-content");
  if (!resultsContent) return;

  let statsHtml = `<div class="mb-2"><strong>Обработано файлов:</strong> ${data.total_files || 0}</div>`;
  statsHtml += `<div><strong>Сохранено записей:</strong> ${data.total_records || 0}</div>`;

  let errorsHtml = "";
  if (data.errors && data.errors.length > 0) {
    errorsHtml = `
      <div class="mt-3">
        <strong>Ошибки:</strong>
        <ul class="mb-0 mt-2">
          ${data.errors.map((e) => `<li class="text-danger">${escapeHtml(e)}</li>`).join("")}
        </ul>
      </div>
    `;
  }

  resultsContent.innerHTML = `
    <div class="alert alert-success mb-0">
      <div class="d-flex align-items-center gap-2 mb-2">
        <i class="bi bi-check-circle-fill"></i>
        <strong>Обработка завершена успешно!</strong>
      </div>
      <div id="results-stats">${statsHtml}</div>
      ${errorsHtml ? `<div id="results-errors">${errorsHtml}</div>` : '<div id="results-errors" style="display: none;"></div>'}
    </div>
  `;
}

// Показать ошибку
function showError(message) {
  const resultsContent = $("results-content");
  if (!resultsContent) return;

  resultsContent.innerHTML = `
    <div class="alert alert-danger mb-0">
      <div class="d-flex align-items-center gap-2">
        <i class="bi bi-exclamation-triangle-fill"></i>
        <strong>Ошибка обработки:</strong>
      </div>
      <div class="mt-2">${escapeHtml(message)}</div>
    </div>
  `;
}

// Загрузка статистики
async function loadStats() {
  const statsDiv = $("db-stats");
  if (!statsDiv) return;

  statsDiv.innerHTML = `
    <div class="text-center text-muted py-3">
      <div class="spinner-border spinner-border-sm text-primary mb-2" role="status">
        <span class="visually-hidden">Загрузка...</span>
      </div>
      <div>Загрузка статистики...</div>
    </div>
  `;

  try {
    const data = await apiGet("/api/sessions/stats");
    displayStats(data.stats);
  } catch (error) {
    statsDiv.innerHTML = `
      <div class="alert alert-danger mb-0">
        <i class="bi bi-exclamation-triangle-fill me-2"></i>
        Ошибка загрузки статистики: ${escapeHtml(error.message)}
      </div>
    `;
  }
}

// Отображение статистики
function displayStats(stats) {
  const statsDiv = $("db-stats");
  if (!statsDiv || !stats) return;

  const totalRecords = stats.total_records || 0;
  const totalSeanses = stats.total_seanses || 0;
  const totalDays = stats.total_days || 0;
  const lastDatetime = stats.last_datetime || "Нет данных";

  statsDiv.innerHTML = `
    <div class="row g-3">
      <div class="col-md-3">
        <div class="card md3-sessions-stat-tile border-0">
          <div class="card-body text-center py-3">
            <div class="md3-sessions-stat-value mb-0">${formatNumber(totalRecords)}</div>
            <div class="md3-sessions-stat-label">Всего записей</div>
          </div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="card md3-sessions-stat-tile border-0">
          <div class="card-body text-center py-3">
            <div class="md3-sessions-stat-value mb-0">${formatNumber(totalSeanses)}</div>
            <div class="md3-sessions-stat-label">Всего сеансов</div>
          </div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="card md3-sessions-stat-tile border-0">
          <div class="card-body text-center py-3">
            <div class="md3-sessions-stat-value mb-0">${formatNumber(totalDays)}</div>
            <div class="md3-sessions-stat-label">Дней</div>
          </div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="card md3-sessions-stat-tile border-0">
          <div class="card-body text-center py-3">
            <div class="md3-sessions-stat-sub mb-0">${escapeHtml(lastDatetime)}</div>
            <div class="md3-sessions-stat-label">Последняя запись</div>
          </div>
        </div>
      </div>
    </div>
  `;
}

// Вспомогательные функции
function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatSessionsAiHtml(text) {
  const source = String(text || "");
  let escaped = escapeHtml(source);
  escaped = escaped
    .replace(/^###\s+(.+)$/gm, '<div class="fw-semibold mt-3 mb-1">$1</div>')
    .replace(/^##\s+(.+)$/gm, '<div class="fw-semibold mt-3 mb-1 fs-6">$1</div>')
    .replace(/^#\s+(.+)$/gm, '<div class="fw-semibold mt-3 mb-1 fs-6">$1</div>')
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/^(\s*)-\s+(.+)$/gm, '$1<span class="text-primary">•</span> $2')
    .replace(/^(\s*)\*\s+(.+)$/gm, '$1<span class="text-primary">•</span> $2')
    .replace(/\n/g, "<br>");
  return escaped;
}

function setSessionsAiStatus(text, isError = false) {
  const el = $("sessions-ai-status");
  if (!el) return;
  el.textContent = text || "—";
  el.classList.toggle("text-danger", !!isError);
}

function setSessionsAiBusy(isBusy) {
  ["sessions-ai-run-btn", "sessions-ai-today-btn", "sessions-ai-week-btn", "sessions-ai-month-btn"].forEach((id) => {
    const btn = $(id);
    if (btn) btn.disabled = !!isBusy;
  });
}

function readSessionsAiRange() {
  const dateFrom = $("date-from");
  const timeFrom = $("time-from");
  const dateTo = $("date-to");
  const timeTo = $("time-to");
  const df = dateFrom ? String(dateFrom.value || "").trim() : "";
  const tf = timeFrom ? String(timeFrom.value || "00:00").trim() : "00:00";
  const dt = dateTo ? String(dateTo.value || "").trim() : "";
  const tt = timeTo ? String(timeTo.value || "23:59").trim() : "23:59";
  if (!df || !dt) return null;
  return { start: `${df} ${tf || "00:00"}:00`, end: `${dt} ${tt || "23:59"}:59` };
}

function sleepSessionsAi(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitSessionsAiJob(jobId) {
  const id = Number(jobId || 0);
  if (!id) throw new Error("Сервер не вернул job_id");
  let delay = 1200;
  for (;;) {
    if (document.hidden) {
      await sleepSessionsAi(Math.max(delay, 10000));
      continue;
    }
    const data = await apiGet(`/api/analysis/ai/jobs/${encodeURIComponent(id)}`);
    const job = data.job || {};
    const status = String(job.status || "").toLowerCase();
    if (status === "completed") return job;
    if (status === "failed" || status === "cancelled") {
      throw new Error(job.error_text || "AI-задача завершилась с ошибкой");
    }
    setSessionsAiStatus(status === "pending" ? "AI-задача в очереди..." : "AI-задача выполняется...");
    await sleepSessionsAi(delay);
    delay = Math.min(5000, Math.round(delay * 1.25));
  }
}

async function runSessionsAiAnalysis() {
  const range = readSessionsAiRange();
  if (!range) {
    setSessionsAiStatus("Укажите период в фильтре таблицы.", true);
    return;
  }
  const questionEl = $("sessions-ai-question");
  const resultEl = $("sessions-ai-result");
  const question = questionEl ? String(questionEl.value || "").trim() : "";
  try {
    setSessionsAiBusy(true);
    setSessionsAiStatus("AI-задача ставится в очередь...");
    if (resultEl) {
      resultEl.style.display = "block";
      resultEl.textContent = "Анализ сеансов формируется в фоне. Можно продолжать работу.";
    }
    const data = await apiPost("/api/sessions/ai/analyze", {
      start: range.start,
      end: range.end,
      question,
    });
    const job = await waitSessionsAiJob(data.job_id);
    const result = job.result || {};
    if (resultEl) {
      resultEl.style.display = "block";
      resultEl.innerHTML = formatSessionsAiHtml(result.report_text || "AI-анализ готов. Откройте отчет в истории AI-анализов.");
    }
    setSessionsAiStatus("AI-анализ готов.");
  } catch (error) {
    setSessionsAiStatus("Ошибка: " + (error.message || error), true);
    if (resultEl) {
      resultEl.style.display = "block";
      resultEl.innerHTML = `<span class="text-danger">${escapeHtml(error.message || error)}</span>`;
    }
  } finally {
    setSessionsAiBusy(false);
  }
}

function formatNumber(n) {
  return new Intl.NumberFormat("ru-RU").format(n);
}

function _clearSessionsTableEtagCache() {
  // No-op kept for older call sites; sessions requests intentionally bypass caches.
}

// Загрузка данных таблицы
async function loadTableData() {
  const tbody = $("sessions-table-body");
  const dateFrom = $("date-from");
  const timeFrom = $("time-from");
  const dateTo = $("date-to");
  const timeTo = $("time-to");
  const exportBtn = $("export-word-btn");
  const queryBadge = $("table-query-ms");

  if (!tbody) return;

  const from = dateFrom ? dateFrom.value : "";
  const fromTime = timeFrom ? timeFrom.value : "00:00";
  const to = dateTo ? dateTo.value : "";
  const toTime = timeTo ? timeTo.value : "23:59";

  tbody.innerHTML = `
    <tr>
      <td colspan="8" class="text-center text-muted py-4">
        <div class="spinner-border spinner-border-sm text-primary mb-2" role="status">
          <span class="visually-hidden">Загрузка...</span>
        </div>
        <div>Загрузка данных...</div>
      </td>
    </tr>
  `;

  try {
    _clearSessionsTableEtagCache();
    const params = new URLSearchParams();
    if (from) params.append("date_from", from);
    if (fromTime) params.append("time_from", fromTime);
    if (to) params.append("date_to", to);
    if (toTime) params.append("time_to", toTime);
    const useExactPeriod =
      (fromTime && fromTime !== "00:00") || (toTime && toTime !== "23:59");
    params.append("exact_period", useExactPeriod ? "1" : "0");

    const data = await apiGet(`/api/sessions/table-data?${params.toString()}`);
    tableData = data.data || [];
    tableTotal = Number(data.total || tableData.length || 0);
    if (Array.isArray(data.favorites)) {
      favorites = data.favorites;
    }
    recomputeSessionsRowFavorites(tableData);
    displayTable(tableData);
    if (exportBtn) exportBtn.disabled = tableData.length === 0;
    const excelBtn = $("export-excel-btn");
    const excelBtnTable = $("export-excel-btn-table");
    const exportUnitBtn = $("export-unit-btn");
    if (excelBtn) excelBtn.disabled = tableData.length === 0;
    if (excelBtnTable) excelBtnTable.disabled = tableData.length === 0;
    if (exportUnitBtn) exportUnitBtn.disabled = !from || !to || !_sessionsExportUnitName();
    if (queryBadge) {
      const sqlMs =
        typeof data.sql_ms === "number" ? Math.round(data.sql_ms) : null;
      const totalMs =
        typeof data.total_ms === "number"
          ? Math.round(data.total_ms)
          : typeof data.query_ms === "number"
            ? Math.round(data.query_ms)
            : null;
      if (totalMs != null) {
        queryBadge.style.display = "inline-block";
        let label =
          sqlMs != null && Math.abs(totalMs - sqlMs) > 3
            ? `SQL: ${sqlMs}ms · всего ${totalMs}ms`
            : `Запрос: ${totalMs}ms`;
        label += ` · сетей ${tableData.length}`;
        queryBadge.textContent = label;
        queryBadge.title =
          "sql_ms — время агрегации в БД; total_ms — весь ответ API (избранное и т.д.)";
      } else {
        queryBadge.style.display = "none";
        queryBadge.textContent = "";
        queryBadge.title = "";
      }
    }
  } catch (error) {
    tbody.innerHTML = `
      <tr>
        <td colspan="8" class="text-center text-danger py-4">
          <i class="bi bi-exclamation-triangle-fill me-2"></i>
          Ошибка загрузки данных: ${escapeHtml(error.message)}
        </td>
      </tr>
    `;
    if (exportBtn) exportBtn.disabled = true;
    const excelBtnErr = $("export-excel-btn");
    const excelBtnTableErr = $("export-excel-btn-table");
    if (excelBtnErr) excelBtnErr.disabled = true;
    if (excelBtnTableErr) excelBtnTableErr.disabled = true;
    if (queryBadge) {
      queryBadge.style.display = "none";
      queryBadge.textContent = "";
    }
  }
}

// Отображение таблицы
function displayTable(data) {
  const tbody = $("sessions-table-body");
  if (!tbody) return;

  const pairFavCount = countPairFavorites(favorites);

  // Фильтруем по избранному если включен фильтр
  let filteredData = data;
  if (showFavoritesOnly) {
    filteredData = data.filter(
      (row) =>
        sessionsRowIsFavorite(row.frequency, row.group, favorites) &&
        sessionsRowHasNamedUnit(row)
    );
  }

  // Фильтруем по поиску
  const query = tableFilters.query;
  const freqFilter = tableFilters.frequency;
  const groupFilter = tableFilters.group;
  const nameFilter = tableFilters.name;
  const idsFilter = tableFilters.ids;
  const countMinRaw = tableFilters.countMin;
  const countMin = countMinRaw !== "" && !Number.isNaN(Number(countMinRaw)) ? Number(countMinRaw) : null;
  if (query) {
    filteredData = filteredData.filter((row) => {
      const rf = String(row.frequency || "").toLowerCase();
      const rg = String(row.group || "").toLowerCase();
      const rn = String(row.name || "").toLowerCase();
      return rf.includes(query) || rg.includes(query) || rn.includes(query);
    });
  }
  if (freqFilter) {
    filteredData = filteredData.filter((row) =>
      String(row.frequency || "").toLowerCase().includes(freqFilter)
    );
  }
  if (groupFilter) {
    filteredData = filteredData.filter((row) =>
      String(row.group || "").toLowerCase().includes(groupFilter)
    );
  }
  if (nameFilter) {
    filteredData = filteredData.filter((row) =>
      String(row.name || "").toLowerCase().includes(nameFilter)
    );
  }
  if (idsFilter) {
    filteredData = filteredData.filter((row) => {
      const ids = String(row.ids_pretty || row.ids_csv || "").toLowerCase();
      return ids.includes(idsFilter);
    });
  }
  if (countMin !== null) {
    filteredData = filteredData.filter((row) => Number(row.count || 0) >= countMin);
  }

  filteredData = _sortSessionsTableRows(filteredData);

  const countEl = $("table-count");
  if (countEl) {
    const loaded = data.length;
    const favHint =
      showFavoritesOnly && pairFavCount > 0
        ? ` · избранное ${countNamedFavoriteRows(data)} (без н/у)`
        : "";
    countEl.textContent = `${filteredData.length} из ${loaded}${favHint}`;
  }

  if (!filteredData || filteredData.length === 0) {
    const hasTextFilters = !!(query || freqFilter || groupFilter || nameFilter || idsFilter || countMin !== null);
    const onlyFavorites = showFavoritesOnly && !hasTextFilters;
    tbody.innerHTML = `
      <tr>
        <td colspan="8" class="text-center text-muted py-4">
          ${onlyFavorites
        ? "Нет избранных сетей с названием подразделения"
        : showFavoritesOnly || hasTextFilters
          ? "Нет данных по выбранным фильтрам"
          : "Нет данных за выбранный период"}
        </td>
      </tr>
    `;
    return;
  }

  let html = "";
  let rowIndex = 0;
  const allowUnitEdit = canEditUnitName();
  filteredData.forEach((row) => {
    const freqRaw = String(row.frequency || "");
    const groupRaw = String(row.group || "");
    const nameRaw = String(row.name || "");

    const freq = escapeHtml(freqRaw);
    const group = escapeHtml(groupRaw);
    const name = escapeHtml(nameRaw);
    const count = row.count || 0;
    const ids = escapeHtml(row.ids_pretty || row.ids_csv || "");
    const isFavorite = sessionsRowIsFavorite(freqRaw, groupRaw, favorites);
    const favoriteIcon = isFavorite
      ? '<i class="bi bi-star-fill text-warning"></i>'
      : '<i class="bi bi-star text-muted"></i>';

    rowIndex++;
    const rowClass = isFavorite ? "md3-sessions-row-fav" : "";
    const titleText = isFavorite ? "Удалить из избранного" : "Добавить в избранное";
    html += `
      <tr class="${rowClass}">
        <td class="text-center">
          <button type="button"
                  class="btn btn-link p-0"
                  style="text-decoration:none; cursor:pointer;"
                  data-action="toggle-favorite"
                  data-frequency="${escapeHtml(freqRaw)}"
                  data-group="${escapeHtml(groupRaw)}"
                  title="${escapeHtml(titleText)}">${favoriteIcon}</button>
        </td>
        <td>${rowIndex}</td>
        <td>${freq}</td>
        <td>${group}</td>
        <td data-action="${allowUnitEdit ? "edit-unit-name" : ""}"
            data-frequency="${escapeHtml(freqRaw)}"
            data-group="${escapeHtml(groupRaw)}"
            data-name="${escapeHtml(nameRaw)}"
            style="${allowUnitEdit ? "cursor: pointer;" : ""}"
            title="${allowUnitEdit ? "Двойной клик — редактировать" : "Нет прав на редактирование"}">${name || "<span class='text-muted'>н/у</span>"}</td>
        <td>${formatNumber(count)}</td>
        <td><small>${ids}</small></td>
        <td class="text-end">
          <div class="dropdown">
            <button class="btn btn-outline-secondary btn-sm dropdown-toggle" type="button" data-bs-toggle="dropdown">
              Действия
            </button>
            <ul class="dropdown-menu">
              <li><button class="dropdown-item" data-action="copy-frequency" data-frequency="${escapeHtml(freqRaw)}">Скопировать частоту</button></li>
              <li><button class="dropdown-item" data-action="copy-group" data-group="${escapeHtml(groupRaw)}">Скопировать группу</button></li>
              <li><button class="dropdown-item" data-action="copy-pair" data-frequency="${escapeHtml(freqRaw)}" data-group="${escapeHtml(groupRaw)}">Скопировать пару</button></li>
              ${allowUnitEdit ? `<li><button class="dropdown-item" data-action="edit-unit" data-frequency="${escapeHtml(freqRaw)}" data-group="${escapeHtml(groupRaw)}" data-name="${escapeHtml(nameRaw)}">Редактировать подразделение</button></li>` : ""}
              <li><button class="dropdown-item" data-action="debug-unit" data-frequency="${escapeHtml(freqRaw)}" data-group="${escapeHtml(groupRaw)}">Debug привязки</button></li>
            </ul>
          </div>
        </td>
      </tr>
    `;
  });

  tbody.innerHTML = html;
}

function updateSortIndicators() {
  const buttons = document.querySelectorAll(".sessions-sort[data-sort]");
  buttons.forEach((btn) => {
    const label = String(btn.getAttribute("data-label") || "").trim();
    const key = String(btn.getAttribute("data-sort") || "").trim();
    if (!label) return;
    if (key && key === tableSort.key) {
      const arrow = tableSort.dir === "asc" ? " ↑" : " ↓";
      btn.textContent = `${label}${arrow}`;
    } else {
      btn.textContent = label;
    }
  });
}

function applyDatePreset(range) {
  const dateFrom = $("date-from");
  const timeFrom = $("time-from");
  const dateTo = $("date-to");
  const timeTo = $("time-to");
  if (!dateFrom || !dateTo) return;

  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  let start = today;
  let end = today;

  if (range === "yesterday") {
    start = new Date(today.getTime() - 24 * 60 * 60 * 1000);
    end = start;
  } else if (range === "7") {
    start = new Date(today.getTime() - 6 * 24 * 60 * 60 * 1000);
  } else if (range === "30") {
    start = new Date(today.getTime() - 29 * 24 * 60 * 60 * 1000);
  }

  const fmt = (d) => d.toISOString().split("T")[0];
  dateFrom.value = fmt(start);
  dateTo.value = fmt(end);
  if (timeFrom) timeFrom.value = "00:00";
  if (timeTo) timeTo.value = "23:59";
  _updateSessionsExportUnitBtn();
  loadTableData();
}

// Переключение избранного
async function toggleFavorite(frequency, group, unitName) {
  try {
    const isFavorite = sessionsRowIsFavorite(frequency, group, favorites);
    const unitEntry = findUnitFavoriteEntry(unitName, favorites);

    if (isFavorite) {
      if (unitEntry) {
        await apiPost("/api/sessions/favorites/remove", {
          unit_name: unitEntry.group,
        });
        await refreshFavoritesFromServer();
      } else {
        const match = findMatchingSessionsFavorite(frequency, group, favorites);
        const removeFreq = match ? match.frequency : frequency;
        const removeGroup = match ? match.group : group;
        await apiPost("/api/sessions/favorites/remove", {
          frequency: removeFreq,
          group: removeGroup,
        });
        favorites = favorites.filter(
          (f) => !(f.frequency === removeFreq && f.group === removeGroup)
        );
      }
      recomputeSessionsRowFavorites(tableData);
    } else {
      await apiPost("/api/sessions/favorites/add", {
        frequency: frequency,
        group: group,
      });
      favorites.push({ frequency: frequency, group: group });
      recomputeSessionsRowFavorites(tableData);
    }

    displayTable(tableData);
  } catch (error) {
    alert("Ошибка: " + error.message);
  }
}

async function refreshFavoritesFromServer() {
  const data = await apiGet("/api/sessions/favorites?include_units=1");
  favorites = data.favorites || [];
  recomputeSessionsRowFavorites(tableData);
}

async function showUnitDebug(frequency, group) {
  try {
    const data = await apiGet(
      `/api/sessions/unit-debug?frequency=${encodeURIComponent(
        frequency
      )}&group=${encodeURIComponent(group)}`
    );
    console.log("unit-debug", data);
    const body = $("unit-debug-body");
    if (body) body.textContent = JSON.stringify(data, null, 2);
    const modalEl = $("unitDebugModal");
    if (modalEl && window.bootstrap) {
      const m = window.bootstrap.Modal.getOrCreateInstance(modalEl);
      m.show();
    }
  } catch (e) {
    setText("table-count", `Ошибка debug: ${e.message || e}`);
  }
}

// (backward compat) на случай старого inline onclick
window.toggleFavorite = toggleFavorite;

// Загрузка избранного
async function loadFavorites() {
  try {
    const data = await apiGet("/api/sessions/favorites?include_units=1");
    favorites = data.favorites || [];
    if (countPairFavorites(favorites) > 0) {
      const checkbox = $("show-favorites-only");
      if (checkbox) {
        checkbox.checked = true;
        showFavoritesOnly = true;
      }
    }
    if (tableData.length > 0) {
      recomputeSessionsRowFavorites(tableData);
      displayTable(tableData);
    }
  } catch (error) {
    // Игнорируем ошибки загрузки избранного
    console.warn("Error loading favorites:", error);
  }
}

// Запуск автопоиска
async function startWatch(path) {
  const opts = (arguments[1] && typeof arguments[1] === "object") ? arguments[1] : {};
  const silent = !!opts.silent;
  if (isWatching) return true;

  try {
    await apiPost("/api/sessions/start-watch", { folder_path: path });
    isWatching = true;
    _setWatchUiRunning(true);
    /* Не вызывать startWatchStatusPolling() здесь: он делает stopWatchStatusPolling и рвёт текущий тик автозапуска.
       Сразу запросить статус только если startWatch вызван с UI (не изнутри watchStatusPollOnce). */
    if (watchPollTickDepth === 0) {
      _clearWatchPollTimerOnly();
      if (!watchPollCancelled) {
        watchStatusTimer = setTimeout(watchStatusPollOnce, 0);
      }
    }
    if (!silent) {
      alert("Автопоиск запущен. Новые файлы будут обрабатываться автоматически.");
    }
    return true;
  } catch (error) {
    if (!silent) {
      alert("Ошибка запуска автопоиска: " + error.message);
    }
    return false;
  }
}

function _clearWatchPollTimerOnly() {
  if (watchStatusTimer) {
    clearTimeout(watchStatusTimer);
    watchStatusTimer = null;
  }
}

function stopWatchStatusPolling() {
  watchPollCancelled = true;
  _clearWatchPollTimerOnly();
}

function renderWatchStatus(st) {
  lastWatchStatus = st || null;
  const running = !!(st && st.running);
  _setWatchUiRunning(running);
  setText("watch-folder", st.watch_folder || st.folder_path || "-");
  setText("watch-last-check", st.last_check_at || "-");
  const scanActive = !!st.scan_in_progress;
  const scanPct = Number(st.scan_progress_pct ?? 0);
  const scanMsg =
    st.last_message ||
    (scanActive
      ? `Сканирование ${scanPct}%`
      : running
        ? "Автопоиск работает"
        : "Автопоиск остановлен");
  setText("watch-last-message", scanMsg);
  setText("watch-files-seen", String(st.files_seen ?? 0));
  setText("watch-files-processed", String(st.files_processed ?? 0));
  setText("watch-rows-parsed", String(st.rows_parsed ?? 0));
  setText("watch-freq-dirs", String(st.freq_dirs_scanned ?? 0));
  setText("watch-time-dirs", String(st.time_dirs_scanned ?? 0));
  setText("watch-cycle-ms", String(st.last_cycle_ms ?? 0));

  let pct = 0;
  if (scanActive) {
    pct = Math.max(0, Math.min(100, Math.round(scanPct)));
  } else {
    const seen = Number(st.files_seen ?? 0);
    const processed = Number(st.files_processed ?? 0);
    pct = seen > 0 ? Math.min(100, Math.round((processed / seen) * 100)) : 0;
  }
  const bar = $("watch-progress-bar");
  const label = $("watch-progress-label");
  if (bar) bar.style.width = `${pct}%`;
  if (label) {
    if (scanActive) {
      const fd = Number(st.scan_freq_done ?? 0);
      const ft = Number(st.scan_freq_total ?? 0);
      label.textContent = `${pct}% · ${fd}/${ft} частот`;
    } else {
      label.textContent = `${pct}%`;
    }
  }

  const errBox = $("watch-last-error-box");
  const errText = $("watch-last-error");
  const err = (st.last_error || "").toString().trim();
  if (err) {
    if (errText) errText.textContent = err;
    if (errBox) errBox.style.display = "block";
  } else {
    if (errBox) errBox.style.display = "none";
  }

  const umBox = $("watch-unmatched-box");
  const umEl = $("watch-unmatched");
  const ex = Array.isArray(st.unmatched_examples) ? st.unmatched_examples : [];
  if (ex.length > 0) {
    if (umEl) umEl.innerHTML = ex.map((x) => `<div><code>${escapeHtml(String(x))}</code></div>`).join("");
    if (umBox) umBox.style.display = "block";
  } else {
    if (umBox) umBox.style.display = "none";
    if (umEl) umEl.innerHTML = "";
  }
}

function _nextWatchPollDelayMs() {
  if (document.hidden) return WATCH_POLL_HIDDEN_MS;
  if (isWatching && lastWatchStatus && lastWatchStatus.scan_in_progress) {
    return WATCH_POLL_ACTIVE_SCAN_MS;
  }
  return isWatching ? WATCH_POLL_ACTIVE_MS : WATCH_POLL_IDLE_MS;
}

async function watchStatusPollOnce() {
  if (watchPollCancelled) return;

  watchPollTickDepth++;
  const folderPathInput = $("folder-path");

  try {
    if (document.hidden) {
      _clearWatchPollTimerOnly();
      if (!watchPollCancelled) {
        watchStatusTimer = setTimeout(watchStatusPollOnce, _nextWatchPollDelayMs());
      }
      return;
    }

    try {
      const data = await apiGet("/api/sessions/watch-status");
      const st = data.status || {};
      isWatching = !!st.running;
      renderWatchStatus(st);
    } catch (_e) {
      // не мешаем работе автопоиска из-за статуса
    } finally {
      if (watchPollCancelled) return;
      _clearWatchPollTimerOnly();
      if (!watchPollCancelled) {
        watchStatusTimer = setTimeout(watchStatusPollOnce, _nextWatchPollDelayMs());
      }
    }
  } finally {
    watchPollTickDepth--;
  }
}

function startWatchStatusPolling() {
  stopWatchStatusPolling();
  watchPollCancelled = false;

  if (!watchVisibilityHookInstalled) {
    watchVisibilityHookInstalled = true;
    document.addEventListener("visibilitychange", () => {
      if (document.hidden || watchPollCancelled) return;
      _clearWatchPollTimerOnly();
      watchStatusPollOnce();
    });
  }

  watchStatusPollOnce();
}

// Остановка автопоиска
async function stopWatch() {
  if (!isWatching) return;

  try {
    await apiPost("/api/sessions/stop-watch", {});
    isWatching = false;
    stopWatchStatusPolling();
    _setWatchUiRunning(false);
    setText("watch-last-message", "Автопоиск остановлен");
    alert("Автопоиск остановлен.");
  } catch (error) {
    alert("Ошибка остановки автопоиска: " + error.message);
  }
}

function _parseIdWatchInput(raw) {
  return String(raw || "")
    .split(/[\s,;]+/)
    .map((s) => s.trim())
    .filter((s) => /^\d{1,10}$/.test(s));
}

async function loadIdWatchList() {
  const listEl = $("id-watch-list");
  if (!listEl) return;
  try {
    const data = await apiGet("/api/sessions/id-watch");
    const items = Array.isArray(data.items) ? data.items : [];
    if (!items.length) {
      listEl.innerHTML = '<span class="text-muted">Список пуст — добавьте ID</span>';
      return;
    }
    listEl.innerHTML = items
      .map(
        (item) => `
      <div class="d-flex align-items-center justify-content-between gap-2 mb-1 sn-id-watch-row">
        <span class="wp-mono fw-semibold">${escapeHtml(item.correspondent_id || "")}</span>
        <button type="button" class="btn btn-link btn-sm text-danger p-0"
          data-id-watch-remove="${escapeHtml(item.correspondent_id || "")}" title="Убрать из отслеживания">&times;</button>
      </div>`
      )
      .join("");
  } catch (e) {
    listEl.textContent = `Ошибка: ${e.message || e}`;
  }
}

async function addIdWatchFromInput() {
  const input = $("id-watch-input");
  const btn = $("id-watch-add-btn");
  if (!input) return;
  const raw = String(input.value || "").trim();
  const ids = _parseIdWatchInput(raw);
  if (!ids.length) {
    showToast("Введите корректный ID (1–10 цифр)", "warning");
    return;
  }
  if (btn) btn.disabled = true;
  try {
    const data = await apiPost("/api/sessions/id-watch/add", {
      ids: raw,
    });
    input.value = "";
    await loadIdWatchList();
    const added = Array.isArray(data.added) ? data.added.length : Number(data.count || 0);
    if (Number(data.alerts_created || 0) > 0 && typeof window.wpIdWatchPollNow === "function") {
      window.wpIdWatchPollNow();
    }
    showToast(
      added ? `Добавлено ID: ${added}` : "ID не добавлены (возможно, уже в списке)",
      added ? "success" : "warning"
    );
  } catch (e) {
    showToast(`Ошибка: ${e.message || e}`, "danger");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function removeIdWatchId(cid) {
  const id = String(cid || "").trim();
  if (!id) return;
  try {
    await apiPost("/api/sessions/id-watch/remove", { correspondent_id: id });
    await loadIdWatchList();
    showToast(`ID ${id} убран из отслеживания`, "info");
  } catch (e) {
    showToast(`Ошибка: ${e.message || e}`, "danger");
  }
}

function initIdWatchUi() {
  const addBtn = $("id-watch-add-btn");
  const input = $("id-watch-input");
  const listEl = $("id-watch-list");
  if (!addBtn && !listEl) return;
  if (addBtn) addBtn.addEventListener("click", () => addIdWatchFromInput());
  if (input) {
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        addIdWatchFromInput();
      }
    });
  }
  if (listEl) {
    listEl.addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-id-watch-remove]");
      if (!btn) return;
      const cid = btn.getAttribute("data-id-watch-remove");
      if (cid) removeIdWatchId(cid);
    });
  }
  loadIdWatchList();
}

function _sessionsExportUnitName() {
  const el = $("export-unit-name");
  return el ? String(el.value || "").trim() : "";
}

function _updateSessionsExportUnitBtn() {
  const exportUnitBtn = $("export-unit-btn");
  if (!exportUnitBtn) return;
  const dateFrom = $("date-from");
  const dateTo = $("date-to");
  const from = dateFrom ? dateFrom.value : "";
  const to = dateTo ? dateTo.value : "";
  exportUnitBtn.disabled = !from || !to || !_sessionsExportUnitName();
}

// Экспорт в Word
async function exportToWord() {
  const dateFrom = $("date-from");
  const timeFrom = $("time-from");
  const dateTo = $("date-to");
  const timeTo = $("time-to");
  const exportBtn = $("export-word-btn");

  if (!dateFrom || !dateTo) return;

  const from = dateFrom.value;
  const fromTime = timeFrom ? timeFrom.value : "00:00";
  const to = dateTo ? dateTo.value : "";
  const toTime = timeTo ? timeTo.value : "23:59";

  if (!from || !to) {
    alert("Укажите период для экспорта");
    return;
  }

  if (exportBtn) exportBtn.disabled = true;

  try {
    const jobId = await queueExportJob(
      "/api/sessions/export-word-job",
      {
        date_from: from,
        time_from: fromTime,
        date_to: to,
        time_to: toTime,
        favorites_only: !!showFavoritesOnly,
        unit_name: _sessionsExportUnitName(),
      },
      (msg) => {
        if (exportBtn) exportBtn.title = msg;
      }
    );
    await downloadExportJob(jobId, `seanses_${from}_${to}.docx`);
  } catch (error) {
    alert("Ошибка экспорта: " + error.message);
  } finally {
    if (exportBtn) exportBtn.disabled = false;
  }
}

// Выгрузка в Excel (тот же период и позиция, формат: Время выхода, Частота, ID, Группа, AES, Color Voice, Время сек)
async function exportToExcel() {
  const dateFrom = $("date-from");
  const timeFrom = $("time-from");
  const dateTo = $("date-to");
  const timeTo = $("time-to");
  const exportExcelBtn = $("export-excel-btn");
  const exportExcelBtnTable = $("export-excel-btn-table");

  if (!dateFrom || !dateTo) return;

  const from = dateFrom.value;
  const fromTime = timeFrom ? timeFrom.value : "00:00";
  const to = dateTo.value;
  const toTime = timeTo ? timeTo.value : "23:59";

  if (!from || !to) {
    alert("Укажите период для выгрузки");
    return;
  }

  if (exportExcelBtn) exportExcelBtn.disabled = true;
  if (exportExcelBtnTable) exportExcelBtnTable.disabled = true;

  try {
    const jobId = await queueExportJob(
      "/api/sessions/export-excel-job",
      {
        date_from: from,
        time_from: fromTime,
        date_to: to,
        time_to: toTime,
        unit_name: _sessionsExportUnitName(),
      },
      (msg) => {
        if (exportExcelBtn) exportExcelBtn.title = msg;
        if (exportExcelBtnTable) exportExcelBtnTable.title = msg;
      }
    );
    await downloadExportJob(jobId, `seanses_${from}_${to}.xlsx`);
  } catch (error) {
    alert("Ошибка выгрузки Excel: " + error.message);
  } finally {
    if (exportExcelBtn) exportExcelBtn.disabled = false;
    if (exportExcelBtnTable) exportExcelBtnTable.disabled = false;
  }
}

async function exportUnitToExcel() {
  const unit = _sessionsExportUnitName();
  if (!unit) {
    alert("Укажите подразделение для выборочной выгрузки");
    return;
  }
  await exportToExcel();
}
