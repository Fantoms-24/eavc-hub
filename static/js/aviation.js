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

function $(id) {
  return document.getElementById(id);
}

function setText(id, text) {
  const el = $(id);
  if (el) el.textContent = text || "";
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function normalizeFrequencyValue(value) {
  return String(value || "")
    .replaceAll(",", ".")
    .replace(/\s+/g, "")
    .trim();
}

function setSaveStatus(state, message) {
  const indicator = $("save-indicator");
  const textEl = $("save-text");
  if (indicator) {
    indicator.className = "save-indicator " + (state || "idle");
  }
  if (textEl) {
    textEl.textContent = message || "";
  }
}

let ACTIVE_FREQUENCY_ID = 0;
let ACTIVE_FREQUENCY = null;
let FREQUENCIES = [];
let CALLSIGNS = [];
let SAVE_TIMER = null;
let LAST_SAVED = "";
let WORK_DATE = ""; // Выбранный рабочий день
let ALL_CALLSIGNS = []; // Все позывные для боковой панели
let SELECTED_CALLSIGN = null; // Выбранный позывной в боковой панели {label, code}

const AV_MOBILE_MQ = window.matchMedia("(max-width: 767.98px)");
const AV_SECTION_KEY = "wp.aviation.mobileSection";
const AV_PANEL_KEY = "wp.aviation.mainPanel";
const AV_SECTIONS = ["freq", "work", "more"];
const AV_MAIN_PANELS = ["blank", "callsigns", "stats"];

function setAviationMainPanel(panel) {
  const root = document.querySelector(".av-workbench-ui");
  if (!root) return;
  const p = AV_MAIN_PANELS.includes(panel) ? panel : "blank";
  root.setAttribute("data-av-panel", p);
  root.querySelectorAll(".av-panel[data-av-panel]").forEach((el) => {
    const name = el.getAttribute("data-av-panel");
    if (name === p) el.removeAttribute("hidden");
    else el.setAttribute("hidden", "");
  });
  root.querySelectorAll("[data-av-tab]").forEach((btn) => {
    const on = btn.getAttribute("data-av-tab") === p;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
  try {
    localStorage.setItem(AV_PANEL_KEY, p);
  } catch (_e) {
    // ignore
  }
}

function setAviationMobileSection(section) {
  const root = document.querySelector(".av-workbench-ui");
  const dock = document.getElementById("av-mobile-dock");
  if (!root || !dock) return;
  const s = AV_SECTIONS.includes(section) ? section : "freq";
  root.setAttribute("data-av-section", s);
  const idx = AV_SECTIONS.indexOf(s);
  dock.style.setProperty("--av-dock-index", String(idx >= 0 ? idx : 0));
  dock.querySelectorAll("[data-av-section]").forEach((btn) => {
    const on = btn.getAttribute("data-av-section") === s;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
  if (s === "work") setAviationMainPanel("blank");
  if (s === "more") {
    root.querySelectorAll(".av-panel[data-av-panel='callsigns'], .av-panel[data-av-panel='stats']").forEach((el) => {
      el.removeAttribute("hidden");
    });
    const blank = root.querySelector(".av-panel[data-av-panel='blank']");
    if (blank) blank.setAttribute("hidden", "");
  }
  try {
    localStorage.setItem(AV_SECTION_KEY, s);
  } catch (_e) {
    // ignore
  }
}
window.setAviationMobileSection = setAviationMobileSection;

function applyAviationMobileUi() {
  const root = document.querySelector(".av-workbench-ui");
  const dock = document.getElementById("av-mobile-dock");
  if (!root || !dock) return;
  const on = !!AV_MOBILE_MQ.matches;
  root.classList.toggle("av-mobile-ui", on);
  dock.hidden = !on;
  if (on) {
    let s = "freq";
    try {
      const saved = localStorage.getItem(AV_SECTION_KEY);
      if (AV_SECTIONS.includes(saved)) s = saved;
    } catch (_e) {
      // ignore
    }
    setAviationMobileSection(s);
  }
}

// --- Автосохранение (авиация) ---
// Сохраняем "по блокам времени":
// - когда появляется новая строка времени (например "12.11" или "12:11")
// - или если не было ввода 60 секунд
const AUTO_SAVE_IDLE_MS = 60_000;
let AUTO_SAVE_IDLE_TIMER = null;
let LAST_TIME_HEADER = "";

function fmtMskLabel(s) {
  if (!s) return "";
  const str = String(s).trim();
  if (!str) return "";
  const m = str.match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})(?::(\d{2}))?/);
  if (m) {
    const y = Number(m[1]);
    const mo = Number(m[2]);
    const d = Number(m[3]);
    let hh = Number(m[4]);
    const mm = Number(m[5]);
    hh = (hh + 3) % 24;
    return `${String(d).padStart(2, "0")}.${String(mo).padStart(2, "0")} ${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
  }
  return str;
}

function fmtAviationWorkDate(workDate) {
  if (!workDate) return "";
  const m = String(workDate).trim().match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return String(workDate);
  return `${m[3]}.${m[2]}.${m[1]}`;
}

function fmtAviationLastRecord(at, workDate) {
  if (!at) return "—";
  const time = fmtMskLabel(at);
  const day = fmtAviationWorkDate(workDate);
  return day ? `${day} • ${time}` : time;
}

let FREQ_SEARCH_QUERY = "";

function _freqMatchesSearch(f, query) {
  if (!query) return true;
  const freq = String(f.frequency || "").toLowerCase().replace(/,/g, ".");
  const type = String(f.aviation_type || "").toLowerCase();
  return freq.includes(query) || type.includes(query);
}

function renderFrequencies() {
  const list = $("frequencies-list");
  if (!list) return;
  list.innerHTML = "";
  
  if (!FREQUENCIES || FREQUENCIES.length === 0) {
    list.innerHTML = '<div class="list-group-item text-muted small md3-aviation-empty">Нет частот. Добавьте частоту.</div>';
    return;
  }
  
  const query = FREQ_SEARCH_QUERY.trim().toLowerCase().replace(/,/g, ".");
  const visible = FREQUENCIES.filter((f) => _freqMatchesSearch(f, query));
  if (!visible.length) {
    list.innerHTML = '<div class="list-group-item text-muted small md3-aviation-empty">Ничего не найдено.</div>';
    return;
  }
  
  const byType = {};
  for (const f of visible) {
    const type = f.aviation_type || "Неизвестно";
    if (!byType[type]) byType[type] = [];
    byType[type].push(f);
  }
  
  for (const [type, freqs] of Object.entries(byType)) {
    const header = document.createElement("div");
    header.className = "list-group-item md3-aviation-list-header";
    header.textContent = type;
    list.appendChild(header);
    
    for (const f of freqs) {
      const row = document.createElement("div");
      const isActive = ACTIVE_FREQUENCY_ID === Number(f.id || 0);
      row.className = `list-group-item list-group-item-action d-flex align-items-center justify-content-between gap-2 ${isActive ? "active" : ""}`;
      
      const a = document.createElement("button");
      a.type = "button";
      a.className = "btn btn-link p-0 text-start flex-grow-1";
      const lastHint = f.last_record_at
        ? `<span class="small text-muted d-block">${escapeHtml(fmtAviationLastRecord(f.last_record_at, f.last_work_date))}</span>`
        : `<span class="small text-muted d-block">нет записей</span>`;
      a.innerHTML = `<span class="wp-mono fw-semibold">${escapeHtml(f.frequency || "")}</span>${lastHint}`;
      a.addEventListener("click", () => openFrequency(f.id, f));
      row.appendChild(a);
      
      const del = document.createElement("button");
      del.type = "button";
      del.className = "btn btn-sm btn-outline-danger";
      del.innerHTML = "<i class='bi bi-x-lg'></i>";
      del.title = "Удалить частоту";
      del.addEventListener("click", async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        if (!confirm(`Удалить частоту ${f.frequency} (${f.aviation_type})?`)) return;
        setText("aviation-status", "Удаляю…");
        try {
          await apiPost("/api/aviation/frequency/delete", { frequency_id: f.id });
          if (ACTIVE_FREQUENCY_ID === Number(f.id || 0)) {
            ACTIVE_FREQUENCY_ID = 0;
            ACTIVE_FREQUENCY = null;
            $("aviation-text").value = "";
            setText("editor-subtitle", "Выберите частоту слева");
            const typeSelect = $("editor-aviation-type");
            if (typeSelect) typeSelect.style.display = "none";
            $("aviation-text").disabled = true;
            $("manual-save-btn").disabled = true;
            $("start-new-aviation-btn").disabled = true;
            $("export-aviation-btn").disabled = true;
          }
          await loadFrequencies();
          setText("aviation-status", "Удалено.");
        } catch (e) {
          setText("aviation-status", `Ошибка: ${e.message || e}`);
        }
      });
      row.appendChild(del);
      list.appendChild(row);
    }
  }
}

async function openFrequency(frequencyId, freq) {
  setText("aviation-status", "Загрузка…");
  try {
    // Если выбран рабочий день, загружаем данные за этот день
    let url = `/api/aviation/intercept?frequency_id=${encodeURIComponent(frequencyId)}`;
    if (WORK_DATE) {
      url += `&date=${encodeURIComponent(WORK_DATE)}`;
    }
    
    const data = await apiGet(url);
    const intercept = data.intercept || {};
    
    ACTIVE_FREQUENCY_ID = Number(frequencyId || 0);
    ACTIVE_FREQUENCY = freq;
    
    const content = intercept.content || "";
    $("aviation-text").value = content;
    $("aviation-text").disabled = false;
    $("manual-save-btn").disabled = false;
    $("start-new-aviation-btn").disabled = false;
    $("export-aviation-btn").disabled = false;
    
    let subtitle = `${freq.frequency} • ${freq.aviation_type}`;
    if (WORK_DATE) {
      subtitle += ` • ${WORK_DATE}`;
    }
    setText("editor-subtitle", subtitle);
    const typeSelect = $("editor-aviation-type");
    if (typeSelect) {
      typeSelect.value = freq.aviation_type || "н/у";
      typeSelect.style.display = "";
    }
    
    setSaveStatus("saved", intercept.updated_at ? `Последнее сохранение: ${fmtMskLabel(intercept.updated_at)}` : "");
    LAST_SAVED = content;
    LAST_TIME_HEADER = extractLastTimeHeader(content);
    
    await loadCallsigns(frequencyId);
    setText("aviation-status", "");
    updateAddCallsignButton();
  } catch (e) {
    setText("aviation-status", `Ошибка: ${e.message || e}`);
  }
}

async function loadFrequencies() {
  try {
    // Частоты должны быть доступны всегда, независимо от выбранного рабочего дня.
    const data = await apiGet("/api/aviation/frequencies");
    FREQUENCIES = data.frequencies || [];
    renderFrequencies();
  } catch (e) {
    setText("aviation-status", `Ошибка загрузки частот: ${e.message || e}`);
  }
}

async function loadCallsigns(frequencyId) {
  try {
    const data = await apiGet(`/api/aviation/callsigns?frequency_id=${encodeURIComponent(frequencyId)}`);
    CALLSIGNS = data.callsigns || [];
    renderCallsigns();
  } catch (e) {
    console.error("Ошибка загрузки позывных:", e);
  }
}

function renderCallsigns() {
  const list = $("cs-list");
  if (!list) return;
  list.innerHTML = "";
  
  if (!CALLSIGNS || CALLSIGNS.length === 0) {
    list.innerHTML = '<div class="list-group-item text-muted small md3-aviation-empty">Нет позывных</div>';
    return;
  }
  
  const byType = {};
  for (const c of CALLSIGNS) {
    const type = c.card_type || "НПУ";
    if (!byType[type]) byType[type] = [];
    byType[type].push(c);
  }
  
  for (const [type, callsigns] of Object.entries(byType)) {
    const header = document.createElement("div");
    header.className = "list-group-item md3-aviation-list-header";
    header.textContent = type;
    list.appendChild(header);
    
    for (const c of callsigns) {
      const row = document.createElement("div");
      row.className = "list-group-item d-flex align-items-center justify-content-between gap-2";
      
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-link p-0 text-start flex-grow-1";
      btn.innerHTML = `<span class="wp-mono">${escapeHtml(c.label || "")}</span>`;
      btn.addEventListener("click", () => {
        insertAtCursor(c.label || "");
      });
      row.appendChild(btn);
      
      const statsBtn = document.createElement("button");
      statsBtn.type = "button";
      statsBtn.className = "btn btn-sm btn-outline-primary";
      statsBtn.innerHTML = "<i class='bi bi-bar-chart'></i>";
      statsBtn.title = "Статистика по дням";
      statsBtn.addEventListener("click", () => showCallsignStats(c.label, c));
      row.appendChild(statsBtn);
      
      const historyBtn = document.createElement("button");
      historyBtn.type = "button";
      historyBtn.className = "btn btn-sm btn-outline-secondary";
      historyBtn.innerHTML = "<i class='bi bi-clock-history'></i>";
      historyBtn.title = "История";
      historyBtn.addEventListener("click", () => showCallsignHistory(c.label, c));
      row.appendChild(historyBtn);
      
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "btn btn-sm btn-outline-danger";
      delBtn.innerHTML = "<i class='bi bi-x-lg'></i>";
      delBtn.title = "Удалить";
      delBtn.addEventListener("click", async () => {
        if (!confirm(`Удалить позывной ${c.label}?`)) return;
        try {
          await apiPost("/api/aviation/callsign/delete", { 
            label: c.label,
            frequency_id: ACTIVE_FREQUENCY_ID 
          });
          await loadCallsigns(ACTIVE_FREQUENCY_ID);
          setText("aviation-status", "Позывной удалён");
        } catch (e) {
          setText("aviation-status", `Ошибка: ${e.message || e}`);
        }
      });
      row.appendChild(delBtn);
      
      list.appendChild(row);
    }
  }
}

function normalizeTimeHeader(s) {
  const m = String(s || "").trim().match(/^(\d{1,2})[.:](\d{2})$/);
  if (!m) return "";
  const hh = String(Math.max(0, Math.min(23, Number(m[1]) || 0))).padStart(2, "0");
  const mm = String(Math.max(0, Math.min(59, Number(m[2]) || 0))).padStart(2, "0");
  return `${hh}.${mm}`;
}

function extractLastTimeHeader(text) {
  const lines = String(text || "").split(/\r?\n/);
  for (let i = lines.length - 1; i >= 0; i--) {
    const t = normalizeTimeHeader(lines[i]);
    if (t) return t;
  }
  return "";
}

function _lineBoundsAtPos(text, pos) {
  const s = String(text || "");
  const p = Math.max(0, Math.min(s.length, Number(pos) || 0));
  const start = s.lastIndexOf("\n", p - 1) + 1;
  const endIdx = s.indexOf("\n", p);
  const end = endIdx === -1 ? s.length : endIdx;
  return { start, end };
}

function _fixDashIfTimeHeaderAtCursor() {
  const ta = $("aviation-text");
  if (!ta || ta.disabled) return;
  const v = String(ta.value || "");
  const pos = ta.selectionStart || 0;
  const { start, end } = _lineBoundsAtPos(v, pos);
  const line = v.slice(start, end);
  // Если строка выглядит как "-15.12" / "-15:12" -> превращаем в "15.12"
  const m = line.match(/^\s*-(\d{1,2}[.:]\d{2})\s*$/);
  if (!m) return;
  const th = normalizeTimeHeader(m[1]);
  if (!th) return;
  const before = v.slice(0, start);
  const after = v.slice(end);
  ta.value = before + th + after;
  // курсор сдвигаем на -1 (убрали '-'), но не ломаем границы
  const newPos = Math.max(start, (pos || 0) - 1);
  try {
    ta.setSelectionRange(newPos, newPos);
  } catch (_) { }
}

function _autoScrollEditorIfNeeded(ta) {
  if (!ta) return;
  // Автопрокрутка только когда пользователь "держится" внизу.
  // Если он прокрутил вверх (читает/правит старые строки), не мешаем.
  const nearBottom = (ta.scrollTop + ta.clientHeight) >= (ta.scrollHeight - 24);
  if (!nearBottom) return;
  requestAnimationFrame(() => {
    try {
      ta.scrollTop = ta.scrollHeight;
    } catch (_) { }
  });
}

function insertAtCursor(text) {
  const ta = $("aviation-text");
  if (!ta || ta.disabled) return;
  const wasNearBottom = (ta.scrollTop + ta.clientHeight) >= (ta.scrollHeight - 24);
  const start = ta.selectionStart || 0;
  const end = ta.selectionEnd || 0;
  const v = ta.value || "";
  ta.value = v.slice(0, start) + text + v.slice(end);
  const pos = start + text.length;
  ta.setSelectionRange(pos, pos);
  ta.focus();
  scheduleSave();
  if (wasNearBottom) {
    requestAnimationFrame(() => {
      try {
        ta.scrollTop = ta.scrollHeight;
      } catch (_) { }
    });
  }
}

async function autoSaveIfDirty(reason) {
  if (!ACTIVE_FREQUENCY_ID) return;
  const ta = $("aviation-text");
  if (!ta) return;
  const text = String(ta.value || "");
  if (text === LAST_SAVED) return;
  // При автосохранении используем sync=true для сортировки блоков по времени
  const r = String(reason || "");
  const doSync = r === "new_time" || r === "idle";
  await saveNow({ sync: doSync });
}

function scheduleIdleAutoSave() {
  if (AUTO_SAVE_IDLE_TIMER) clearTimeout(AUTO_SAVE_IDLE_TIMER);
  AUTO_SAVE_IDLE_TIMER = setTimeout(() => {
    autoSaveIfDirty("idle").catch(() => {
      setSaveStatus("error", "Ошибка автосохранения");
    });
  }, AUTO_SAVE_IDLE_MS);
}

function scheduleSave() {
  // Автосохранение: "по времени" + простой 60 сек.
  if (!ACTIVE_FREQUENCY_ID) return;
  const ta = $("aviation-text");
  if (!ta) return;

  // Если пользователь начал вводить время, а автотире уже подставилось — уберём тире.
  _fixDashIfTimeHeaderAtCursor();

  const lastHeader = extractLastTimeHeader(ta.value || "");
  // Если появился новый заголовок времени — фиксируем и сохраняем сразу
  if (lastHeader && lastHeader !== LAST_TIME_HEADER) {
    LAST_TIME_HEADER = lastHeader;
    autoSaveIfDirty("new_time").catch(() => {
      setSaveStatus("error", "Ошибка автосохранения");
    });
  }

  // Если ввода не будет 60 секунд — сохраним
  scheduleIdleAutoSave();
  
  // Также сохраняем через 2 секунды после последнего изменения
  if (SAVE_TIMER) clearTimeout(SAVE_TIMER);
  SAVE_TIMER = setTimeout(() => saveNow(), 2000);
  setSaveStatus("saving", "Сохранение…");
}

async function saveNow(opts) {
  if (!ACTIVE_FREQUENCY_ID) return;
  const options = opts || {};
  const sync = !!options.sync; // если true — после сохранения подменяем текст на отсортированный
  const ta = $("aviation-text");
  const content = (ta && ta.value) ? ta.value : "";
  
  if (content === LAST_SAVED && !sync) return;
  
  setSaveStatus("saving", "Сохранение…");
  try {
    await apiPost("/api/aviation/intercept/update", {
      frequency_id: ACTIVE_FREQUENCY_ID,
      content: content,
      ...(WORK_DATE ? { work_date: WORK_DATE } : {}),
    });
    
    // Парсим контент и обновляем историю позывных
    await updateCallsignHistory(content);
    
    LAST_SAVED = content;
    setSaveStatus("saved", "Сохранено");
    
    // Если sync=true, можно обновить текст с сервера (для сортировки)
    // Но пока сервер не возвращает отсортированный контент, просто сохраняем
  } catch (e) {
    setSaveStatus("error", `Ошибка: ${e.message || e}`);
  }
}

async function startNewEntries() {
  if (!FREQUENCIES || FREQUENCIES.length === 0) {
    setText("aviation-status", "Список частот уже пуст");
    return;
  }
  if (!confirm("Удалить все частоты авиации и начать заново?")) return;
  setText("aviation-status", "Удаляю частоты…");
  setSaveStatus("saving", "Сброс авиации…");
  try {
    const result = await apiPost("/api/aviation/reset", {});
    ACTIVE_FREQUENCY_ID = 0;
    ACTIVE_FREQUENCY = null;
    CALLSIGNS = [];
    LAST_SAVED = "";
    LAST_TIME_HEADER = "";
    SELECTED_CALLSIGN = null;
    const ta = $("aviation-text");
    if (ta) {
      ta.value = "";
      ta.disabled = true;
    }
    const csList = $("cs-list");
    if (csList) {
      csList.innerHTML = '<div class="list-group-item text-muted small md3-aviation-empty">Нет позывных</div>';
    }
    const typeSelect = $("editor-aviation-type");
    if (typeSelect) {
      typeSelect.style.display = "none";
    }
    if ($("manual-save-btn")) $("manual-save-btn").disabled = true;
    if ($("start-new-aviation-btn")) $("start-new-aviation-btn").disabled = true;
    if ($("export-aviation-btn")) $("export-aviation-btn").disabled = true;
    setText("editor-subtitle", "Выберите частоту слева");
    await loadFrequencies();
    LAST_SAVED = "";
    setSaveStatus("saved", "Сохранено");
    setText("aviation-status", `Авиация сброшена. Удалено частот: ${Number(result.deleted || 0)}`);
  } catch (e) {
    setSaveStatus("error", `Ошибка: ${e.message || e}`);
    setText("aviation-status", `Ошибка: ${e.message || e}`);
  }
}

async function updateCallsignHistory(content) {
  if (!content || !ACTIVE_FREQUENCY_ID) return;
  
  try {
    // Отправляем контент на сервер для парсинга и обновления истории
    await apiPost("/api/aviation/parse-content", {
      frequency_id: ACTIVE_FREQUENCY_ID,
      content: content,
    });
  } catch (e) {
    console.error("Ошибка обновления истории позывных:", e);
  }
}

async function showCallsignHistory(label, callsign) {
  try {
    // Добавляем фильтр по рабочему дню, если он выбран
    let url = `/api/aviation/callsign/history?label=${encodeURIComponent(label)}`;
    if (ACTIVE_FREQUENCY_ID) {
      url += `&frequency_id=${encodeURIComponent(ACTIVE_FREQUENCY_ID)}`;
    }
    if (WORK_DATE) {
      url += `&date=${encodeURIComponent(WORK_DATE)}`;
    }
    const data = await apiGet(url);
    const history = data.history || [];
    
    // Форматируем дату для отображения
    const formatDay = (dayStr) => {
      if (!dayStr) return "";
      if (dayStr.match(/^\d{4}-\d{2}-\d{2}$/)) {
        const parts = dayStr.split("-");
        return `${parts[2]}.${parts[1]}.${parts[0]}`;
      }
      return dayStr;
    };
    
    const header = $("callsign-history-header");
    if (header) {
      header.innerHTML = `
        <div class="fw-semibold">${escapeHtml(callsign.label || "")}</div>
        <div class="small text-muted">Тип: ${escapeHtml(callsign.card_type || "")}</div>
        <div class="small text-muted">Всего выходов: ${history.length} (одна частота = один выход)</div>
      `;
    }
    
    const body = $("callsign-history-body");
    if (body) {
      body.innerHTML = "";
      if (history.length === 0) {
        body.innerHTML = '<tr><td colspan="3" class="text-muted text-center">История пуста</td></tr>';
      } else {
        for (const h of history) {
          const tr = document.createElement("tr");
          const dayFormatted = formatDay(h.day || "");
          const timeFormatted = fmtMskLabel(h.timestamp || "");
          // Показываем дату и время отдельно
          const dateTimeDisplay = dayFormatted && timeFormatted 
            ? `${dayFormatted} ${timeFormatted.split(" ")[1] || ""}`.trim()
            : timeFormatted || dayFormatted || "";
          
          tr.innerHTML = `
            <td class="wp-mono small">${escapeHtml(dateTimeDisplay)}</td>
            <td class="wp-mono small">${escapeHtml(h.frequency || "")}</td>
            <td class="small">${escapeHtml(h.content_snippet || "")}</td>
          `;
          body.appendChild(tr);
        }
      }
    }
    
    const modalEl = $("callsignHistoryModal");
    if (window.bootstrap && modalEl) {
      const modal = new bootstrap.Modal(modalEl);
      modal.show();
    }
  } catch (e) {
    setText("aviation-status", `Ошибка загрузки истории: ${e.message || e}`);
  }
}

async function addCallsign() {
  const label = ($("cs-label").value || "").trim();
  const cardType = $("cs-card-type").value || "НПУ";
  
  if (!label) {
    setText("aviation-status", "Укажите позывной", true);
    return;
  }
  
  try {
    const frequencyId = ACTIVE_FREQUENCY_ID ? ACTIVE_FREQUENCY_ID : null;
    const payload = {
      frequency_id: frequencyId,
      label: label,
      card_type: cardType,
    };
    if (WORK_DATE) payload.work_date = WORK_DATE;
    await apiPost("/api/aviation/callsign/create", payload);
    $("cs-label").value = "";
    await loadCallsigns(ACTIVE_FREQUENCY_ID || 0);
    if (typeof loadAllCallsigns === "function") loadAllCallsigns();
    setText("aviation-status", "Позывной добавлен");
  } catch (e) {
    setText("aviation-status", `Ошибка: ${e.message || e}`);
  }
}

function updateAddCallsignButton() {
  const btn = $("cs-add-btn");
  const label = ($("cs-label").value || "").trim();
  if (btn) {
    btn.disabled = !label;
  }
}

async function exportWord() {
  if (!ACTIVE_FREQUENCY_ID || !ACTIVE_FREQUENCY) {
    setText("aviation-status", "Выберите частоту для экспорта");
    return;
  }

  try {
    setText("aviation-status", "Экспорт Word…");
    const queued = await apiPost("/api/aviation/export-word-job", {
      frequency_id: ACTIVE_FREQUENCY_ID,
      date: WORK_DATE || "",
    });
    if (!queued || !queued.job_id) throw new Error("Сервер не вернул job_id");
    setText("aviation-status", "Экспорт в очереди…");
    await waitExportJob(queued.job_id, (msg) => setText("aviation-status", msg));
    const safeFreq = ACTIVE_FREQUENCY.frequency.replace(/[^a-zA-Z0-9]/g, "_");
    const dayPart = WORK_DATE || new Date().toISOString().split("T")[0];
    await downloadExportJob(queued.job_id, `aviation_${safeFreq}_${dayPart}.docx`);
    setText("aviation-status", "Экспорт завершён");
  } catch (e) {
    setText("aviation-status", `Ошибка экспорта: ${e.message || e}`);
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  // Кнопка открытия боковой панели позывных
  if ($("callsigns-panel-btn")) {
    $("callsigns-panel-btn").addEventListener("click", () => {
      toggleCallsignsSidebar();
    });
  }
  
  // Кнопка закрытия боковой панели
  if ($("close-callsigns-sidebar")) {
    $("close-callsigns-sidebar").addEventListener("click", () => {
      toggleCallsignsSidebar();
    });
  }
  
  // Поиск по позывным
  if ($("callsign-search")) {
    $("callsign-search").addEventListener("input", (e) => {
      filterCallsigns(e.target.value || "");
    });
  }
  
  // Поиск по частотам
  if ($("freq-search-input")) {
    $("freq-search-input").addEventListener("input", (e) => {
      FREQ_SEARCH_QUERY = String(e.target.value || "");
      renderFrequencies();
    });
  }
  
  // Кнопки
  if ($("add-frequency-btn")) {
    $("add-frequency-btn").addEventListener("click", () => {
      const modalEl = $("addFrequencyModal");
      if (window.bootstrap && modalEl) {
        const modal = new bootstrap.Modal(modalEl);
        modal.show();
      }
    });
  }
  
  if ($("modal-save-frequency-btn")) {
    $("modal-save-frequency-btn").addEventListener("click", async () => {
      const frequency = normalizeFrequencyValue($("modal-frequency").value || "");
      const aviationType = $("modal-aviation-type").value || "Армейская авиация";
      
      if (!frequency) {
        setText("aviation-status", "Введите частоту", true);
        return;
      }
      
      try {
        await apiPost("/api/aviation/frequency/create", {
          frequency: frequency,
          aviation_type: aviationType,
        });
        $("modal-frequency").value = "";
        const modalEl = $("addFrequencyModal");
        if (window.bootstrap && modalEl) {
          const modal = bootstrap.Modal.getInstance(modalEl);
          if (modal) modal.hide();
        }
        await loadFrequencies();
        setText("aviation-status", "Частота добавлена");
      } catch (e) {
        setText("aviation-status", `Ошибка: ${e.message || e}`);
      }
    });
  }

  if ($("start-new-aviation-btn")) {
    $("start-new-aviation-btn").addEventListener("click", startNewEntries);
  }
  
  if ($("editor-aviation-type")) {
    $("editor-aviation-type").addEventListener("change", async () => {
      const typeSelect = $("editor-aviation-type");
      const newType = typeSelect && typeSelect.value ? typeSelect.value : "";
      if (!ACTIVE_FREQUENCY_ID || !newType) return;
      setText("aviation-status", "Обновление типа…");
      try {
        await apiPost("/api/aviation/frequency/update", {
          frequency_id: ACTIVE_FREQUENCY_ID,
          aviation_type: newType,
        });
        if (ACTIVE_FREQUENCY) ACTIVE_FREQUENCY.aviation_type = newType;
        await loadFrequencies();
        let subtitle = `${ACTIVE_FREQUENCY?.frequency || ""} • ${newType}`;
        if (WORK_DATE) subtitle += ` • ${WORK_DATE}`;
        setText("editor-subtitle", subtitle);
        setText("aviation-status", "Тип авиации обновлён");
      } catch (e) {
        setText("aviation-status", `Ошибка: ${e.message || e}`);
      }
    });
  }

  if ($("manual-save-btn")) {
    $("manual-save-btn").addEventListener("click", () => saveNow());
  }
  
  if ($("export-aviation-btn")) {
    $("export-aviation-btn").addEventListener("click", exportWord);
  }
  
  if ($("cs-add-btn")) {
    $("cs-add-btn").addEventListener("click", addCallsign);
  }
  
  if ($("cs-label")) {
    $("cs-label").addEventListener("input", updateAddCallsignButton);
    // Enter для быстрого добавления
    $("cs-label").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey) {
        e.preventDefault();
        const btn = $("cs-add-btn");
        if (btn && !btn.disabled) {
          addCallsign();
        }
      }
    });
  }
  
  // Обработка клавиатуры
  document.addEventListener("keydown", (e) => {
    // Ctrl+Shift+S — сохранить
    if (e.ctrlKey && e.shiftKey && String(e.key || "").toLowerCase() === "s") {
      e.preventDefault();
      if (ACTIVE_FREQUENCY_ID) saveNow({ sync: true });
      return;
    }

    // Автопрефикс строки "-": при Enter начинаем новую строку с "-"
    // Но если оператор начинает вводить время — тире будет автоматически убрано (_fixDashIfTimeHeaderAtCursor()).
    if (e.key === "Enter" && !e.ctrlKey && !e.altKey && !e.metaKey) {
      const ta = $("aviation-text");
      if (ta && document.activeElement === ta && !ta.disabled) {
        // Не вмешиваемся в Enter с Shift (если нужно вставить "пустую" строку без тире)
        if (!e.shiftKey) {
          e.preventDefault();
          insertAtCursor("\n-");
          return;
        }
      }
    }
  });
  
  // Автосохранение при вводе
  if ($("aviation-text")) {
    $("aviation-text").addEventListener("input", (ev) => {
      const ta = ev && ev.target ? ev.target : $("aviation-text");
      scheduleSave();
      _autoScrollEditorIfNeeded(ta);
    });
  }
  
  // Фильтры
  if ($("apply-filters-btn")) {
    $("apply-filters-btn").addEventListener("click", async () => {
      await loadStats();
    });
  }
  
  // Установить сегодняшнюю дату по умолчанию
  const today = new Date().toISOString().split("T")[0];
  if ($("filter-date")) {
    $("filter-date").value = today;
  }
  if ($("work-date")) {
    $("work-date").value = today;
    WORK_DATE = today;
  }
  
  // Обработчик изменения рабочего дня
  if ($("work-date")) {
    $("work-date").addEventListener("change", async (e) => {
      WORK_DATE = e.target.value || "";
      // Единый день в сводке — чтобы таблица «Сводка» совпадала с рабочим днём редактора
      const fd = $("filter-date");
      if (fd && WORK_DATE) {
        fd.value = WORK_DATE;
      }
      if (ACTIVE_FREQUENCY_ID && ACTIVE_FREQUENCY) {
        await openFrequency(ACTIVE_FREQUENCY_ID, ACTIVE_FREQUENCY);
      }
      await loadFrequencies();
      await loadStats();
    });
  }
  
  let savedPanel = "blank";
  try {
    const sp = localStorage.getItem(AV_PANEL_KEY);
    if (AV_MAIN_PANELS.includes(sp)) savedPanel = sp;
  } catch (_e) {
    // ignore
  }
  setAviationMainPanel(savedPanel);

  document.querySelectorAll("[data-av-tab]").forEach((btn) => {
    btn.addEventListener("click", function () {
      setAviationMainPanel(btn.getAttribute("data-av-tab"));
      if (AV_MOBILE_MQ.matches) setAviationMobileSection("work");
    });
  });

  const avBack = document.getElementById("av-main-back");
  if (avBack) {
    avBack.addEventListener("click", function () {
      setAviationMobileSection("freq");
    });
  }

  applyAviationMobileUi();
  AV_MOBILE_MQ.addEventListener("change", applyAviationMobileUi);
  const avDock = document.getElementById("av-mobile-dock");
  if (avDock) {
    avDock.addEventListener("click", function (ev) {
      const btn = ev.target.closest("[data-av-section]");
      if (!btn) return;
      setAviationMobileSection(btn.getAttribute("data-av-section"));
    });
  }

  // Загрузка данных
  await loadFrequencies();
  await loadStats();
});

async function loadStats() {
  const aviationType = $("filter-aviation-type")?.value || "";
  const date = $("filter-date")?.value || "";
  
  try {
    const params = new URLSearchParams();
    if (aviationType) params.append("aviation_type", aviationType);
    if (date) params.append("date", date);
    
    const data = await apiGet(`/api/aviation/stats?${params.toString()}`);
    const stats = data.stats || [];
    renderStats(stats);
    
    const subtitle = $("stats-subtitle");
    if (subtitle) {
      let text = `Найдено: ${stats.length}`;
      if (aviationType) text += ` • ${aviationType}`;
      if (date) text += ` • блоки за ${date}`;
      else text += ` • блоки по всем данным`;
      text += ` • сортировка по последней записи`;
      subtitle.textContent = text;
    }
  } catch (e) {
    setText("aviation-status", `Ошибка загрузки статистики: ${e.message || e}`);
  }
}

function renderStats(stats) {
  const tbody = $("stats-table-body");
  if (!tbody) return;
  tbody.innerHTML = "";
  
  if (!stats || stats.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="text-muted text-center">Нет данных</td></tr>';
    return;
  }
  
  for (const s of stats) {
    const tr = document.createElement("tr");
    const lastLabel = fmtAviationLastRecord(s.last_record_at || s.last_updated, s.last_work_date);
    const blocksCell = s.time_blocks
      ? `<span class="fw-semibold">${s.time_blocks}</span>`
      : `<span class="text-muted">0</span>`;
    tr.innerHTML = `
      <td class="wp-mono fw-semibold">${escapeHtml(s.frequency || "")}</td>
      <td><span class="badge ${s.aviation_type === "Армейская авиация" ? "text-bg-danger" : (s.aviation_type === "н/у" ? "text-bg-secondary" : (s.aviation_type === "ЯК" ? "text-bg-warning" : (s.aviation_type === "F-16" ? "text-bg-info" : "text-bg-primary")))}">${escapeHtml(s.aviation_type || "")}</span></td>
      <td class="text-center">${blocksCell}</td>
      <td class="text-center">${s.callsigns_count || 0}</td>
      <td class="wp-mono small ${s.last_record_at || s.last_updated ? "" : "text-muted"}">${escapeHtml(lastLabel)}</td>
      <td class="text-end">
        <button class="btn btn-outline-primary btn-sm" data-action="open" data-frequency-id="${s.frequency_id}">
          <i class="bi bi-folder-open me-1"></i>Открыть
        </button>
      </td>
    `;
    
    const openBtn = tr.querySelector('[data-action="open"]');
    openBtn.addEventListener("click", () => {
      const freq = FREQUENCIES.find(f => f.id === s.frequency_id);
      if (freq) {
        openFrequency(s.frequency_id, freq);
        // Прокрутить к верху страницы
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    });
    
    tbody.appendChild(tr);
  }
}

async function showCallsignStats(label, callsign) {
  try {
    let url = `/api/aviation/callsign/stats?label=${encodeURIComponent(label)}`;
    if (ACTIVE_FREQUENCY_ID) {
      url += `&frequency_id=${encodeURIComponent(ACTIVE_FREQUENCY_ID)}`;
    }
    if (WORK_DATE) {
      url += `&date=${encodeURIComponent(WORK_DATE)}`;
    }
    const data = await apiGet(url);
    const stats = data.stats || [];
    
    const header = $("callsign-stats-header");
    if (header) {
      header.innerHTML = `
        <div class="fw-semibold">${escapeHtml(callsign.label || "")}</div>
        <div class="small text-muted">Тип карточки: ${escapeHtml(callsign.card_type || "")}</div>
        <div class="small text-muted">Всего дней: ${stats.length}</div>
      `;
    }
    
    const body = $("callsign-stats-body");
    if (body) {
      body.innerHTML = "";
      if (stats.length === 0) {
        body.innerHTML = '<tr><td colspan="5" class="text-muted text-center">Нет данных</td></tr>';
      } else {
        for (const s of stats) {
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td class="wp-mono">${escapeHtml(s.day || "")}</td>
            <td><span class="badge ${s.aviation_type === "Армейская авиация" ? "text-bg-danger" : (s.aviation_type === "н/у" ? "text-bg-secondary" : (s.aviation_type === "ЯК" ? "text-bg-warning" : (s.aviation_type === "F-16" ? "text-bg-info" : "text-bg-primary")))}">${escapeHtml(s.aviation_type || "")}</span></td>
            <td class="wp-mono">${escapeHtml(s.frequency || "")}</td>
            <td class="text-center">${s.entries_count || 0}</td>
            <td class="text-end">
              <button class="btn btn-outline-primary btn-sm" data-action="view-day" data-frequency-id="${s.frequency_id || ""}" data-day="${s.day || ""}">
                <i class="bi bi-eye me-1"></i>Просмотр
              </button>
            </td>
          `;
          
          const viewBtn = tr.querySelector('[data-action="view-day"]');
          viewBtn.addEventListener("click", () => {
            viewDayIntercept(s.frequency_id, s.day, s.frequency);
          });
          
          body.appendChild(tr);
        }
      }
    }
    
    const modalEl = $("callsignStatsModal");
    if (window.bootstrap && modalEl) {
      const modal = new bootstrap.Modal(modalEl);
      modal.show();
    }
  } catch (e) {
    setText("aviation-status", `Ошибка загрузки статистики: ${e.message || e}`);
  }
}

async function viewDayIntercept(frequencyId, day, frequency) {
  try {
    const data = await apiGet(`/api/aviation/intercept/by-date?frequency_id=${encodeURIComponent(frequencyId)}&date=${encodeURIComponent(day)}`);
    const content = data.content || "";
    
    const header = $("day-intercept-header");
    if (header) {
      header.innerHTML = `
        <div class="fw-semibold">${escapeHtml(frequency || "")} • ${escapeHtml(day || "")}</div>
      `;
    }
    
    const contentEl = $("day-intercept-content");
    if (contentEl) {
      contentEl.textContent = content || "Нет данных за этот день";
    }
    
    const modalEl = $("dayInterceptModal");
    if (window.bootstrap && modalEl) {
      const modal = new bootstrap.Modal(modalEl);
      modal.show();
    }
  } catch (e) {
    setText("aviation-status", `Ошибка загрузки перехвата: ${e.message || e}`);
  }
}

function toggleCallsignsSidebar() {
  const sidebar = $("callsigns-sidebar");
  const root = document.querySelector(".av-workbench-ui") || document.querySelector(".aviation-layout");
  if (!sidebar || !root) return;

  const open = !root.classList.contains("av-callsigns-open");
  root.classList.toggle("av-callsigns-open", open);
  document.body.classList.toggle("av-callsigns-open", open);
  sidebar.style.display = open ? "flex" : "none";
  if (open) loadAllCallsigns();
}

async function loadAllCallsigns() {
  try {
    const data = await apiGet("/api/aviation/callsigns");
    ALL_CALLSIGNS = data.callsigns || [];
    renderAllCallsigns(ALL_CALLSIGNS);
  } catch (e) {
    console.error("Ошибка загрузки позывных:", e);
  }
}

function filterCallsigns(searchText) {
  const search = (searchText || "").toLowerCase().trim();
  if (!search) {
    renderAllCallsigns(ALL_CALLSIGNS);
    return;
  }
  
  const filtered = ALL_CALLSIGNS.filter(c => {
    const label = String(c.label || "").toLowerCase();
    return label.includes(search);
  });
  
  renderAllCallsigns(filtered);
}

function renderAllCallsigns(callsigns) {
  const list = $("all-callsigns-list");
  if (!list) return;
  list.innerHTML = "";
  
  if (!callsigns || callsigns.length === 0) {
    list.innerHTML = '<div class="list-group-item text-muted small text-center md3-aviation-empty">Нет позывных</div>';
    return;
  }
  
  // Группируем позывные по уникальному label (независимо от частоты)
  const uniqueCallsigns = new Map();
  for (const c of callsigns) {
    const key = String(c.label || "").toLowerCase();
    if (!uniqueCallsigns.has(key)) {
      // Берем первый найденный позывной с этим label
      uniqueCallsigns.set(key, c);
    }
  }
  
  // Группируем по типу карточки
  const byType = {};
  for (const c of uniqueCallsigns.values()) {
    const type = c.card_type || "НПУ";
    if (!byType[type]) byType[type] = [];
    byType[type].push(c);
  }
  
  for (const [type, items] of Object.entries(byType)) {
    const header = document.createElement("div");
    header.className = "list-group-item md3-aviation-list-header";
    header.textContent = type;
    list.appendChild(header);
    
    for (const c of items) {
      const row = document.createElement("div");
      const isActive = SELECTED_CALLSIGN && SELECTED_CALLSIGN.label === c.label;
      row.className = `list-group-item list-group-item-action ${isActive ? "active" : ""}`;
      row.innerHTML = `
        <div class="d-flex align-items-center justify-content-between">
          <div>
            <div class="fw-semibold">${escapeHtml(c.label || "")}</div>
          </div>
          <i class="bi bi-chevron-right"></i>
        </div>
      `;
      row.addEventListener("click", () => {
        SELECTED_CALLSIGN = { label: c.label };
        showCallsignDays(c.label, c);
        renderAllCallsigns(ALL_CALLSIGNS);
      });
      list.appendChild(row);
    }
  }
}

async function showCallsignDays(label, callsign) {
  try {
    // Добавляем фильтр по рабочему дню, если он выбран
    let url = `/api/aviation/callsign/stats?label=${encodeURIComponent(label)}`;
    if (WORK_DATE) {
      url += `&date=${encodeURIComponent(WORK_DATE)}`;
    }
    const data = await apiGet(url);
    const stats = data.stats || [];
    
    // Группируем по дням
    const byDay = {};
    for (const s of stats) {
      const day = s.day || "";
      if (!byDay[day]) {
        byDay[day] = {
          day: day,
          items: []
        };
      }
      byDay[day].items.push(s);
    }
    
    const daysList = Object.values(byDay).sort((a, b) => (b.day || "").localeCompare(a.day || ""));
    
    // Обновляем список в боковой панели
    const list = $("all-callsigns-list");
    if (list) {
      list.innerHTML = "";
      
      // Кнопка "Назад"
      const backBtn = document.createElement("div");
      backBtn.className = "list-group-item list-group-item-action mb-2";
      backBtn.innerHTML = `
        <div class="d-flex align-items-center gap-2">
          <i class="bi bi-arrow-left"></i>
          <span>Назад к списку</span>
        </div>
      `;
      backBtn.addEventListener("click", () => {
        SELECTED_CALLSIGN = null;
        renderAllCallsigns(ALL_CALLSIGNS);
      });
      list.appendChild(backBtn);
      
      // Заголовок
      const header = document.createElement("div");
      header.className = "list-group-item mb-2 md3-aviation-sidebar-callout";
      header.innerHTML = `
        <div>${escapeHtml(callsign.label || "")}</div>
        <div class="small text-muted">Тип: ${escapeHtml(callsign.card_type || "")}</div>
      `;
      list.appendChild(header);
      
      const formatDay = (dayStr) => {
        if (!dayStr) return "";
        if (dayStr.match(/^\d{4}-\d{2}-\d{2}$/)) {
          const parts = dayStr.split("-");
          return `${parts[2]}.${parts[1]}.${parts[0]}`;
        }
        return dayStr;
      };
      
      // Список дней или история выходов
      if (daysList.length === 0) {
        let history = [];
        try {
          let historyUrl = `/api/aviation/callsign/history?label=${encodeURIComponent(label)}`;
          if (WORK_DATE) historyUrl += `&date=${encodeURIComponent(WORK_DATE)}`;
          const historyData = await apiGet(historyUrl);
          history = historyData.history || [];
        } catch (_) { }
        if (history.length > 0) {
          const subHeader = document.createElement("div");
          subHeader.className = "list-group-item md3-aviation-list-header";
          subHeader.textContent = "Дата и частота выходов, фрагмент:";
          list.appendChild(subHeader);
          for (const h of history) {
            const row = document.createElement("div");
            row.className = "list-group-item small border-start border-primary border-3";
            const dayFormatted = formatDay(h.day || "");
            const timePart = (fmtMskLabel(h.timestamp || "").split(" ")[1] || "").trim();
            const dateTimeStr = dayFormatted && timePart ? `${dayFormatted} ${timePart}` : (dayFormatted || timePart || "—");
            const snippet = String(h.content_snippet || "").trim();
            row.innerHTML = `
              <div class="fw-semibold wp-mono">${escapeHtml(dateTimeStr)}</div>
              <div class="text-muted">Частота: <span class="wp-mono">${escapeHtml(h.frequency || "—")}</span></div>
              ${snippet ? `<div class="mt-1" style="white-space: pre-wrap; word-break: break-word;">${escapeHtml(snippet.length > 150 ? snippet.slice(0, 150) + "…" : snippet)}</div>` : ""}
            `;
            list.appendChild(row);
          }
        } else {
          const noDataEl = document.createElement("div");
          noDataEl.className = "list-group-item text-muted small md3-aviation-empty";
          const freqInfo = (callsign.frequency_id && FREQUENCIES.length) ? FREQUENCIES.find((f) => Number(f.id) === Number(callsign.frequency_id)) : null;
          noDataEl.innerHTML =
            "Пока нет выходов. Сохраните бланк перехвата с этим позывным — после сохранения здесь появится дата, частота и фрагмент." +
            (freqInfo ? `<br><span class="text-primary mt-1 d-block">Привязан к частоте: ${escapeHtml(freqInfo.frequency)} (${escapeHtml(freqInfo.aviation_type || "")})</span>` : "");
          list.appendChild(noDataEl);
        }
      } else {
        for (const dayData of daysList) {
          const dayRow = document.createElement("div");
          dayRow.className = "list-group-item callsign-day-item";
          
          // Определяем тип авиации для дня (берем первый, если несколько)
          const aviationType = dayData.items[0]?.aviation_type || "Неизвестно";
          
          // Форматируем дату из YYYY-MM-DD в DD.MM.YYYY
          let formattedDay = dayData.day || "";
          if (formattedDay && formattedDay.match(/^\d{4}-\d{2}-\d{2}$/)) {
            const parts = formattedDay.split("-");
            formattedDay = `${parts[2]}.${parts[1]}.${parts[0]}`;
          } else if (formattedDay && !formattedDay.match(/^\d{2}\.\d{2}\.\d{4}$/)) {
            // Если дата в неправильном формате, пытаемся исправить
            formattedDay = formattedDay.replace(/^-\d+-/, ""); // Убираем отрицательные годы
            // Если все еще неправильный формат, пропускаем эту запись
            if (!formattedDay || formattedDay.startsWith("-")) {
              formattedDay = "Неверная дата";
            }
          }
          
          dayRow.innerHTML = `
            <div class="d-flex align-items-center justify-content-between">
              <div>
                <div class="fw-semibold">${escapeHtml(formattedDay)}</div>
                <div class="small text-muted">${escapeHtml(aviationType)}</div>
                <div class="small text-muted">${dayData.items.length} ${dayData.items.length === 1 ? "частота" : "частот"}</div>
              </div>
              <button class="btn btn-sm btn-outline-primary" data-action="expand-day" data-day="${escapeHtml(dayData.day || "")}">
                <i class="bi bi-chevron-down"></i>
              </button>
            </div>
            <div class="day-details" style="display: none; margin-top: 8px;">
              ${dayData.items.map(item => `
                <div class="d-flex align-items-center justify-content-between p-2 mb-2 md3-aviation-day-bar">
                  <div>
                    <div class="small fw-semibold">${escapeHtml(item.frequency || "")}</div>
                    <div class="small text-muted">${escapeHtml(item.aviation_type || "")}</div>
                    <div class="small text-muted">Выходов: ${item.entries_count || 0}</div>
                  </div>
                  <button class="btn btn-sm btn-primary" data-action="open-frequency" 
                    data-frequency-id="${item.frequency_id || 0}" 
                    data-day="${escapeHtml(dayData.day || "")}">
                    <i class="bi bi-folder-open me-1"></i>Открыть
                  </button>
                </div>
              `).join("")}
            </div>
          `;
          
          const expandBtn = dayRow.querySelector('[data-action="expand-day"]');
          expandBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            const details = dayRow.querySelector(".day-details");
            const isExpanded = details.style.display !== "none";
            details.style.display = isExpanded ? "none" : "block";
            dayRow.classList.toggle("expanded", !isExpanded);
            expandBtn.querySelector("i").className = isExpanded ? "bi bi-chevron-down" : "bi bi-chevron-up";
          });
          
          const openBtns = dayRow.querySelectorAll('[data-action="open-frequency"]');
          openBtns.forEach(btn => {
            btn.addEventListener("click", async (e) => {
              e.stopPropagation();
              e.preventDefault();
              const frequencyId = Number(btn.dataset.frequencyId || 0);
              const day = String(btn.dataset.day || "").trim();
              
              if (!frequencyId || frequencyId === 0) {
                setText("aviation-status", `Ошибка: frequency_id не указан (${btn.dataset.frequencyId})`);
                console.error("frequency_id is missing or 0", btn.dataset, dayData.items);
                return;
              }
              
              try {
                // Устанавливаем рабочий день (конвертируем из YYYY-MM-DD если нужно)
                let workDay = day;
                if (day && day.match(/^\d{4}-\d{2}-\d{2}$/)) {
                  workDay = day; // Оставляем в формате YYYY-MM-DD для input[type="date"]
                }
                
                if ($("work-date") && workDay) {
                  $("work-date").value = workDay;
                  WORK_DATE = workDay;
                }
                
                // Загружаем все частоты
                await loadFrequencies();
                
                // Находим частоту и открываем её
                const freq = FREQUENCIES.find(f => Number(f.id) === frequencyId);
                if (freq) {
                  await openFrequency(frequencyId, freq);
                  // Закрываем боковую панель
                  toggleCallsignsSidebar();
                  // Прокручиваем к верху
                  window.scrollTo({ top: 0, behavior: "smooth" });
                  setText("aviation-status", "Частота открыта");
                } else {
                  setText("aviation-status", `Частота с ID ${frequencyId} не найдена в списке`);
                  console.error("Frequency not found:", frequencyId, "Available:", FREQUENCIES.map(f => ({id: f.id, freq: f.frequency})));
                }
              } catch (error) {
                setText("aviation-status", `Ошибка: ${error.message || error}`);
                console.error("Error opening frequency:", error);
              }
            });
          });
          
          list.appendChild(dayRow);
        }
      }
    }
  } catch (e) {
    setText("aviation-status", `Ошибка загрузки статистики: ${e.message || e}`);
  }
}
