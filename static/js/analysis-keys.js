(function () {
  "use strict";

  let KEYS_DATA = [];
  let KEYS_LAST_LOAD = null;
  let KEYS_NEW_SINCE = null;
  let KEYS_VIEWED = new Set();
  const KEYS_VIEWED_STORAGE_KEY = "wp_keys_viewed_v1";

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function keysIsoLocalMin(d) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(
      d.getMinutes()
    )}`;
  }

  function setKeysDefaultDate() {
    const dateEl = $("keys-date");
    if (!dateEl) return;
    const now = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    dateEl.value = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  }

  function keysIsNew(row) {
    try {
      if (isKeyViewed(row)) return false;
      if (KEYS_NEW_SINCE === null) return true;
      if (!row || !row.created_at) return false;
      const raw = String(row.created_at || "").trim();
      const iso = raw.includes("T") ? raw : raw.replace(" ", "T");
      const dt = new Date(iso);
      if (Number.isNaN(dt.getTime())) return false;
      const since = new Date(KEYS_NEW_SINCE);
      if (Number.isNaN(since.getTime())) return false;
      return dt.getTime() >= since.getTime();
    } catch (_e) {
      return false;
    }
  }

  function keyRowId(row) {
    const f = String(row?.frequency || "").trim();
    const g = String(row?.group || "").trim();
    const id = String(row?.aes_id || "").trim();
    const k = String(row?.aes_key || "").trim();
    return `${f}|${g}|${id}|${k}`;
  }

  function keysLastSeenTs(row) {
    const raw = String(row?.last_seen || "").trim();
    if (!raw) return 0;
    const iso = raw.includes("T") ? raw : raw.replace(" ", "T");
    const dt = new Date(iso);
    if (Number.isNaN(dt.getTime())) return 0;
    return dt.getTime();
  }

  function loadKeysViewed() {
    try {
      const raw = localStorage.getItem(KEYS_VIEWED_STORAGE_KEY);
      const arr = JSON.parse(raw || "[]");
      KEYS_VIEWED = new Set(Array.isArray(arr) ? arr.map(String) : []);
    } catch (_e) {
      KEYS_VIEWED = new Set();
    }
  }

  function saveKeysViewed() {
    try {
      const arr = Array.from(KEYS_VIEWED || []);
      localStorage.setItem(KEYS_VIEWED_STORAGE_KEY, JSON.stringify(arr));
    } catch (_e) {
      // ignore
    }
  }

  function isKeyViewed(row) {
    const id = keyRowId(row);
    return KEYS_VIEWED.has(id);
  }

  function markKeyViewed(row) {
    const id = keyRowId(row);
    if (!id) return;
    KEYS_VIEWED.add(id);
    saveKeysViewed();
  }

  function getFilteredKeysRows() {
    const q = ($("keys-filter")?.value || "").trim().toLowerCase();
    const onlyNew = !!$("keys-only-new")?.checked;
    let rows = Array.isArray(KEYS_DATA) ? KEYS_DATA.slice() : [];
    if (q) {
      rows = rows.filter((r) => {
        const hay = `${r.frequency || ""} ${r.group || ""}`.toLowerCase();
        return hay.includes(q);
      });
    }
    if (onlyNew) {
      rows = rows.filter((r) => keysIsNew(r));
    }
    return rows;
  }

  function renderKeysTable() {
    const body = $("keys-body");
    if (!body) return;
    let rows = getFilteredKeysRows();

    const status = $("keys-status");
    if (status) status.textContent = `Показано ${rows.length} из ${KEYS_DATA.length}`;

    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="10" class="k2-empty">
      <div class="k2-empty__inner">
        <span class="k2-empty__icon" aria-hidden="true"><i class="bi bi-key-fill"></i></span>
        <div class="k2-empty__title">Ничего не найдено</div>
        <div>Измените дату, фильтр или снимите «только NEW»</div>
      </div>
    </td></tr>`;
      return;
    }

    const groups = new Map();
    rows.forEach((r) => {
      const f = String(r.frequency || "");
      const g = String(r.group || "");
      const key = `${f}||${g}`;
      if (!groups.has(key)) {
        groups.set(key, { frequency: f, group: g, rows: [] });
      }
      groups.get(key).rows.push(r);
    });
    const allGroups = new Map();
    (Array.isArray(KEYS_DATA) ? KEYS_DATA : []).forEach((r) => {
      const f = String(r.frequency || "");
      const g = String(r.group || "");
      const key = `${f}||${g}`;
      if (!allGroups.has(key)) {
        allGroups.set(key, { frequency: f, group: g, rows: [] });
      }
      allGroups.get(key).rows.push(r);
    });

    const parts = [];
    const rowMap = new Map(rows.map((r) => [keyRowId(r), r]));
    const groupEntries = Array.from(groups.entries());
    groupEntries.sort((a, b) => {
      const aMax = Math.max(...a[1].rows.map((r) => keysLastSeenTs(r)));
      const bMax = Math.max(...b[1].rows.map((r) => keysLastSeenTs(r)));
      if (aMax !== bMax) return bMax - aMax;
      const fa = parseFloat(a[1].frequency || "0");
      const fb = parseFloat(b[1].frequency || "0");
      if (Number.isFinite(fa) && Number.isFinite(fb) && fa !== fb) return fa - fb;
      return String(a[1].group || "").localeCompare(String(b[1].group || ""), "ru");
    });

    groupEntries.forEach(([groupKey, grp], idx) => {
      const list = grp.rows.slice().sort((a, b) => {
        const aTs = keysLastSeenTs(a);
        const bTs = keysLastSeenTs(b);
        if (aTs !== bTs) return bTs - aTs;
        const aId = String(a.aes_id || "");
        const bId = String(b.aes_id || "");
        if (aId !== bId) return aId.localeCompare(bId, "ru");
        return String(a.aes_key || "").localeCompare(String(b.aes_key || ""), "ru");
      });
      const anyNew = list.some((r) => keysIsNew(r));
      const anyIdSeen = list.some((r) => r.id_seen);
      const matchedCount = list.filter((r) => r.session_matched !== false).length;
      const cryptoKnown = list.filter((r) => r.crypto_present === true).length;
      const cryptoTotal = list.filter((r) => r.crypto_present !== null).length;
      const cryptoBadge = cryptoTotal
        ? `<span class="badge text-bg-light border">${cryptoKnown}/${cryptoTotal}</span>`
        : "<span class='wp-subtle'>—</span>";
      const ids = Array.from(new Set(list.map((r) => String(r.aes_id || "")).filter(Boolean)));
      const keysCount = list.length;
      const toggleId = `keys-group-${idx}`;
      parts.push(`
      <tr class="${anyNew ? "keys-new-row" : ""}" data-keys-group="${toggleId}" data-keys-group-key="${escapeHtml(
        groupKey
      )}">
        <td class="wp-mono">
          <span class="me-2">${anyIdSeen ? '<span class="badge text-bg-primary">ID</span>' : ""}</span>
          <span class="me-2 keys-caret">▸</span>${escapeHtml(grp.frequency || "")}
        </td>
        <td class="wp-mono">${escapeHtml(grp.group || "")}</td>
        <td class="wp-mono">${escapeHtml(ids.slice(0, 3).join(", "))}${ids.length > 3 ? "…" : ""}</td>
        <td class="wp-mono small">ключей: ${keysCount}${matchedCount < keysCount ? ` · сеансов: ${matchedCount}` : ""}</td>
        <td>${escapeHtml(String(list[0]?.unit_name || ""))}</td>
        <td>${escapeHtml(String(list[0]?.added_date || ""))}</td>
        <td class="small wp-mono">${escapeHtml(String(list[0]?.last_seen || ""))}</td>
        <td class="text-center">${cryptoBadge}</td>
        <td class="text-end">
          ${anyNew ? '<button class="btn btn-outline-secondary btn-sm" data-keys-view="group">Просмотрено</button>' : ""}
          ${anyNew ? '<span class="badge bg-success ms-2">NEW</span>' : ""}
          <button class="btn btn-outline-success btn-sm ms-2" data-keys-add="group" data-keys-group-key="${escapeHtml(
        groupKey
      )}" title="Добавить все ${keysCount} ключ(ей) этой частоты/группы в DMR XML">
            <i class="bi bi-plus-circle-dotted me-1"></i>Добавить всё
          </button>
        </td>
      </tr>
      <tr id="${toggleId}" class="keys-group-details" style="display:none;">
        <td colspan="10">
          <div class="table-responsive">
            <table class="table table-sm table-bordered align-middle mb-0">
              <thead class="table-light">
                <tr>
                  <th>Частота</th>
                  <th>Группа</th>
                  <th>ID</th>
                  <th>Ключ</th>
                  <th>Подразделение</th>
                  <th>Дата добавления</th>
                  <th>Последняя активность</th>
                  <th class="text-center">В DMR</th>
                  <th class="text-end">NEW</th>
                  <th class="text-end">Действия</th>
                </tr>
              </thead>
              <tbody>
                ${list
          .map((r) => {
            const isNew = keysIsNew(r);
            const kid = keyRowId(r);
            const noSessions = r.session_matched === false;
            const cryptoCell = r.crypto_present === true
              ? '<i class="bi bi-check-circle-fill text-success" title="Есть в DMR XML"></i>'
              : r.crypto_present === false
                ? '<i class="bi bi-x-circle-fill text-danger" title="Нет в DMR XML"></i>'
                : '<span class="wp-subtle">—</span>';
            return `
                      <tr class="${isNew ? "keys-new-row" : ""}${noSessions ? " keys-unmatched-row" : ""}">
                        <td class="wp-mono">
                          ${r.id_seen ? '<span class="badge text-bg-primary me-2">ID</span>' : ""}
                          ${noSessions ? '<span class="badge text-bg-secondary me-2" title="Нет сеансов в БД">—</span>' : ""}
                          ${escapeHtml(r.frequency || "")}
                        </td>
                        <td class="wp-mono">${escapeHtml(r.group || "")}</td>
                        <td class="wp-mono">${escapeHtml(r.aes_id || "")}</td>
                        <td class="wp-mono small">${escapeHtml(r.aes_key || "")}</td>
                        <td>${escapeHtml(r.unit_name || "")}</td>
                        <td>${escapeHtml(r.added_date || "")}</td>
                        <td class="small wp-mono">${escapeHtml(r.last_seen || "")}</td>
                        <td class="text-center">${cryptoCell}</td>
                        <td class="text-end">
                          ${isNew ? `<button class="btn btn-outline-secondary btn-sm" data-keys-view="row" data-keys-id="${escapeHtml(
              kid
            )}">Просмотрено</button>` : ""}
                          ${isNew ? '<span class="badge bg-success ms-2">NEW</span>' : ""}
                        </td>
                        <td class="text-end">
                          <button class="btn btn-outline-success btn-sm" data-keys-add="row" data-keys-id="${escapeHtml(
              kid
            )}">
                            <i class="bi bi-plus-circle me-1"></i>Добавить
                          </button>
                        </td>
                      </tr>
                    `;
          })
          .join("")}
              </tbody>
            </table>
          </div>
        </td>
      </tr>
    `);
    });

    body.innerHTML = parts.join("");

    body.querySelectorAll("tr[data-keys-group]").forEach((row) => {
      row.addEventListener("click", (ev) => {
        if (ev.target && ev.target.closest("button")) return;
        const id = row.getAttribute("data-keys-group");
        const details = id ? document.getElementById(id) : null;
        if (!details) return;
        details.style.display = details.style.display === "none" ? "" : "none";
        const caret = row.querySelector(".keys-caret");
        if (caret) caret.textContent = details.style.display === "none" ? "▸" : "▾";
      });
    });

    body.querySelectorAll("button[data-keys-view='group']").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const row = btn.closest("tr[data-keys-group]");
        if (!row) return;
        const groupKey = row.getAttribute("data-keys-group-key") || "";
        const grp = allGroups.get(groupKey) || groups.get(groupKey);
        if (!grp || !Array.isArray(grp.rows)) return;
        grp.rows.forEach((r) => markKeyViewed(r));
        renderKeysTable();
      });
    });

    body.querySelectorAll("button[data-keys-view='row']").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const rowId = btn.getAttribute("data-keys-id") || "";
        const rowData = rowMap.get(rowId);
        if (rowData) {
          markKeyViewed(rowData);
          renderKeysTable();
        }
      });
    });

    body.querySelectorAll("button[data-keys-add='row']").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const rowId = btn.getAttribute("data-keys-id") || "";
        const rowData = rowMap.get(rowId);
        if (rowData) {
          addSingleKeyToXml(btn, rowData);
        }
      });
    });

    body.querySelectorAll("button[data-keys-add='group']").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const groupKey = btn.getAttribute("data-keys-group-key") || "";
        const grp = allGroups.get(groupKey) || groups.get(groupKey);
        if (grp && Array.isArray(grp.rows) && grp.rows.length) {
          addGroupKeysToXml(btn, grp);
        }
      });
    });
  }

  async function loadKeysCheck(options = {}) {
    const dateEl = $("keys-date");
    const matchId = $("keys-match-id")?.checked ? "1" : "0";
    const onlyNew = !!$("keys-only-new")?.checked;
    const allKeys = !!options.allKeys;
    const status = $("keys-status");
    const debugOut = $("keys-debug-output");
    if (!dateEl) return;
    const dateStr = (dateEl.value || "").trim();
    try {
      if (status) status.textContent = allKeys ? "Загрузка всех ключей..." : "Проверка...";
      if (debugOut) {
        debugOut.textContent = "";
        debugOut.style.display = "none";
      }
      const params = new URLSearchParams();
      if (dateStr && !allKeys) {
        params.set("start", `${dateStr}T00:00`);
        params.set("end", `${dateStr}T23:59`);
      }
      params.set("match_id", matchId);
      if (allKeys) params.set("all_keys", "1");
      if (onlyNew && KEYS_NEW_SINCE) params.set("new_since", String(KEYS_NEW_SINCE));
      const data = await apiGet(`/api/analysis/keys/check?${params.toString()}`);
      KEYS_DATA = data.rows || [];
      KEYS_LAST_LOAD = new Date();
      renderKeysTable();
      if (status) status.textContent = data.info || "Готово.";
      if (debugOut && data && data.debug) {
        debugOut.textContent = JSON.stringify(data.debug, null, 2);
        debugOut.style.display = "";
      }
    } catch (e) {
      if (status) status.textContent = `Ошибка: ${e.message || e}`;
    }
  }

  async function importKeysXlsx() {
    const fileInput = $("keys-import-file");
    const status = $("keys-import-status");
    if (!fileInput || !fileInput.files || !fileInput.files.length) return;
    const fd = new FormData();
    fd.append("file", fileInput.files[0]);
    try {
      if (status) status.textContent = "Импорт...";
      const res = await fetch("/api/analysis/keys/import", { method: "POST", body: fd });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
      KEYS_NEW_SINCE = data.previous_import ? String(data.previous_import).replace(" ", "T") : null;
      const onlyNewToggle = $("keys-only-new");
      if (onlyNewToggle) onlyNewToggle.checked = !!data.previous_import;
      if (status) status.textContent = `Импортировано: ${data.inserted || 0}, обновлено: ${data.updated || 0}`;
      await loadKeysCheck();
    } catch (e) {
      if (status) status.textContent = `Ошибка: ${e.message || e}`;
    }
  }

  async function addKeysToXml() {
    const status = $("keys-status");
    if (!Array.isArray(KEYS_DATA) || KEYS_DATA.length === 0) {
      if (status) status.textContent = "Нет данных для добавления. Сначала выполните проверку.";
      return;
    }
    const rows = getFilteredKeysRows();
    if (!rows.length) {
      if (status) status.textContent = "Нет строк по текущему фильтру.";
      return;
    }
    if (!confirm(`Добавить ${rows.length} ключ(ей) в DMR XML?`)) return;
    try {
      if (status) status.textContent = "Добавление...";
      const res = await fetch("/api/crypto/keys/append", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rows }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
      if (status) {
        status.textContent = `Добавлено: ${data.added || 0}, пропущено: ${data.skipped || 0}`;
      }
    } catch (e) {
      if (status) status.textContent = `Ошибка: ${e.message || e}`;
    }
  }

  async function addSingleKeyToXml(buttonEl, row) {
    const status = $("keys-status");
    if (!row) return;
    const label = `${row.frequency || ""} / ${row.group || ""} / ${row.aes_id || ""}`;
    if (!confirm(`Добавить ключ ${label} в DMR XML?`)) return;
    try {
      if (status) status.textContent = "Добавление...";
      const res = await fetch("/api/crypto/keys/append", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rows: [row] }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
      const added = Number(data.added || 0);
      if (status) {
        status.textContent = `Добавлено: ${added}, пропущено: ${data.skipped || 0}`;
      }
      if (added > 0) {
        showToast("Ключ успешно добавлен", "success");
        if (buttonEl) {
          buttonEl.disabled = true;
          buttonEl.classList.remove("btn-outline-success");
          buttonEl.classList.add("btn-outline-secondary");
          buttonEl.textContent = "Добавлено";
        }
      } else {
        showToast("Ключ уже был добавлен", "warning");
        if (buttonEl) {
          buttonEl.disabled = true;
          buttonEl.classList.remove("btn-outline-success");
          buttonEl.classList.add("btn-outline-secondary");
          buttonEl.textContent = "Добавлено";
        }
      }
    } catch (e) {
      if (status) status.textContent = `Ошибка: ${e.message || e}`;
      showToast(`Ошибка: ${e.message || e}`, "danger");
    }
  }

  async function addGroupKeysToXml(buttonEl, grp) {
    const status = $("keys-status");
    if (!grp || !Array.isArray(grp.rows) || grp.rows.length === 0) return;
    const n = grp.rows.length;
    const label = `${grp.frequency || ""} / ${grp.group || ""}`;
    if (!confirm(`Добавить все ${n} ключ(ей) (${label}) в DMR XML?`)) return;
    try {
      if (status) status.textContent = "Добавление...";
      if (buttonEl) {
        buttonEl.disabled = true;
        buttonEl.textContent = "Добавление…";
      }
      const res = await fetch("/api/crypto/keys/append", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rows: grp.rows }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
      const added = Number(data.added || 0);
      const skipped = Number(data.skipped || 0);
      if (status) {
        status.textContent = `Добавлено: ${added}, пропущено: ${skipped}`;
      }
      showToast(`Добавлено ключей: ${added}${skipped ? `, пропущено: ${skipped}` : ""}`, added > 0 ? "success" : "warning");
      if (buttonEl) {
        buttonEl.classList.remove("btn-outline-success");
        buttonEl.classList.add("btn-outline-secondary");
        buttonEl.innerHTML = "<i class=\"bi bi-check2 me-1\"></i>Добавлено";
      }
      renderKeysTable();
    } catch (e) {
      if (status) status.textContent = `Ошибка: ${e.message || e}`;
      showToast(`Ошибка: ${e.message || e}`, "danger");
      if (buttonEl) {
        buttonEl.disabled = false;
        buttonEl.innerHTML = "<i class=\"bi bi-plus-circle-dotted me-1\"></i>Добавить всё";
      }
    }
  }

  function boot() {
    if (!window.AnalysisRuntime?.isModule("keys")) return;
    window.__ANALYSIS_ACTIVE_BUNDLE__ = "keys";

    const keysDate = $("keys-date");
    const keysCheckBtn = $("keys-check-btn");
    const keysViewAllBtn = $("keys-view-all-btn");
    const keysShowAllBtn = $("keys-show-all-btn");
    const keysShowAllKeysBtn = $("keys-show-all-keys-btn");
    const keysImportBtn = $("keys-import-btn");
    const keysAddXmlBtn = $("keys-add-xml-btn");
    const keysFilter = $("keys-filter");
    const keysOnlyNew = $("keys-only-new");
    const keysMatchId = $("keys-match-id");

    loadKeysViewed();
    if (keysDate) {
      setKeysDefaultDate();
    }
    if (keysCheckBtn) keysCheckBtn.addEventListener("click", () => loadKeysCheck());
    if (keysViewAllBtn) {
      keysViewAllBtn.addEventListener("click", () => {
        const all = Array.isArray(KEYS_DATA) ? KEYS_DATA : [];
        all.forEach((r) => markKeyViewed(r));
        renderKeysTable();
      });
    }
    if (keysShowAllBtn) {
      keysShowAllBtn.addEventListener("click", () => {
        if (keysDate) keysDate.value = "";
        loadKeysCheck();
      });
    }
    if (keysShowAllKeysBtn) {
      keysShowAllKeysBtn.addEventListener("click", () => {
        if (keysDate) keysDate.value = "";
        loadKeysCheck({ allKeys: true });
      });
    }
    if (keysImportBtn) keysImportBtn.addEventListener("click", importKeysXlsx);
    if (keysAddXmlBtn) keysAddXmlBtn.addEventListener("click", addKeysToXml);
    if (keysFilter) keysFilter.addEventListener("input", renderKeysTable);
    if (keysOnlyNew) keysOnlyNew.addEventListener("change", renderKeysTable);
    if (keysMatchId) keysMatchId.addEventListener("change", loadKeysCheck);
    const keysToggleImport = $("keys-toggle-import");
    const keysImportDrawer = $("keys-import-drawer");
    if (keysToggleImport && keysImportDrawer) {
      keysToggleImport.addEventListener("click", () => {
        const open = keysImportDrawer.hidden;
        keysImportDrawer.hidden = !open;
        keysToggleImport.classList.toggle("active", open);
        keysToggleImport.setAttribute("aria-expanded", open ? "true" : "false");
      });
    }
  }

  window.AnalysisRuntime?.onReady(boot);
})();
