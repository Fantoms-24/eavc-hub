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

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setText(id, text) {
  const el = $(id);
  if (el) el.textContent = text || "";
}

function setTableEmpty(tbodyId, cols, text) {
  const tbody = $(tbodyId);
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="${cols}" class="text-center text-muted py-3">${escapeHtml(
    text || "Нет данных"
  )}</td></tr>`;
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

let CRYPTO_DAYS = 1;

function readRange() {
  const start = String($("crypto-start")?.value || "").trim();
  const end = String($("crypto-end")?.value || "").trim();
  if (!start || !end) return null;
  const ds = new Date(start);
  const de = new Date(end);
  if (Number.isNaN(ds.getTime()) || Number.isNaN(de.getTime())) return null;
  if (de <= ds) return null;
  return { start, end };
}

function setActivePeriod(days) {
  CRYPTO_DAYS = Number(days) || 1;
  const wrap = $("crypto-period");
  if (!wrap) return;
  wrap.querySelectorAll("[data-days]").forEach((btn) => {
    const isActive = String(btn.getAttribute("data-days")) === String(CRYPTO_DAYS);
    btn.classList.toggle("btn-secondary", isActive);
    btn.classList.toggle("btn-outline-secondary", !isActive);
  });
}

async function loadConfig() {
  try {
    const data = await apiGet("/api/crypto/config");
    if ($("crypto-folder-path") && !$("crypto-folder-path").value) {
      $("crypto-folder-path").value = data.folder_path || "";
    }
    setText(
      "crypto-folder-status",
      data.folder_status || "Укажи путь к папке с XML-файлами."
    );
  } catch (e) {
    setText("crypto-folder-status", `Ошибка: ${e.message || e}`);
  }
}

async function saveConfig() {
  const path = String($("crypto-folder-path")?.value || "").trim();
  if (!path) {
    setText("crypto-folder-status", "Укажите путь к папке.");
    return;
  }
  try {
    const data = await apiPost("/api/crypto/config", { folder_path: path });
    setText("crypto-folder-status", data.folder_status || "Путь сохранен.");
  } catch (e) {
    setText("crypto-folder-status", `Ошибка: ${e.message || e}`);
  }
}

function renderActiveKeys(rows) {
  const tbody = $("crypto-active-body");
  if (!tbody) return;
  if (!rows || rows.length === 0) {
    setTableEmpty("crypto-active-body", 7, "Нет активных ключей");
    return;
  }
  tbody.innerHTML = rows
    .map((r) => {
      const groupList = (r.group_ids || []).join(", ");
      const callList = (r.callsign_ids || []).join(", ");
      const unitList = (r.unit_names || []).join(", ");
      return `<tr>
        <td class="wp-mono">${escapeHtml(r.key_uid)}</td>
        <td class="wp-mono">${escapeHtml(r.key_id || "—")}</td>
        <td>
          ${
            r.key_id_seen
              ? '<i class="bi bi-check-circle-fill text-success" title="Есть"></i>'
              : '<i class="bi bi-x-circle-fill text-danger" title="Нет"></i>'
          }
        </td>
        <td class="small">${escapeHtml(unitList || "—")}</td>
        <td class="small">${escapeHtml(groupList || "—")}</td>
        <td class="small">${escapeHtml(callList || "—")}</td>
        <td>${escapeHtml(fmtDate(r.last_seen))}</td>
      </tr>`;
    })
    .join("");
}

function renderInactiveKeys(rows) {
  const tbody = $("crypto-inactive-body");
  if (!tbody) return;
  if (!rows || rows.length === 0) {
    setTableEmpty("crypto-inactive-body", 6, "Нет ключей к удалению");
    return;
  }
  tbody.innerHTML = rows
    .map((r) => {
      const groupList = (r.group_ids || []).join(", ");
      const callList = (r.callsign_ids || []).join(", ");
      const unitList = (r.unit_names || []).join(", ");
      return `<tr>
        <td class="wp-mono">${escapeHtml(r.key_uid)}</td>
        <td class="wp-mono">${escapeHtml(r.key_id || "—")}</td>
        <td class="small">${escapeHtml(unitList || "—")}</td>
        <td class="small">${escapeHtml(groupList || "—")}</td>
        <td class="small">${escapeHtml(callList || "—")}</td>
        <td class="text-end">
          <button class="btn btn-outline-danger btn-sm crypto-delete-key" data-key-uid="${escapeHtml(
            r.key_uid
          )}">Удалить</button>
        </td>
      </tr>`;
    })
    .join("");
}

function renderInactiveGroups(rows) {
  const tbody = $("crypto-groups-body");
  if (!tbody) return;
  if (!rows || rows.length === 0) {
    setTableEmpty("crypto-groups-body", 5, "Нет неактивных групп");
    return;
  }
  tbody.innerHTML = rows
    .map((r) => {
      return `<tr>
        <td class="wp-mono">${escapeHtml(r.group_id)}</td>
        <td>${escapeHtml(String(r.key_count || 0))}</td>
        <td class="small">${escapeHtml(r.unit_name || "—")}</td>
        <td>${escapeHtml(fmtDate(r.last_seen))}</td>
        <td class="text-end">
          <button class="btn btn-outline-danger btn-sm crypto-delete-group" data-group-id="${escapeHtml(
            r.group_id
          )}">Удалить</button>
        </td>
      </tr>`;
    })
    .join("");
}

function renderInactiveCallsigns(rows) {
  const tbody = $("crypto-callsigns-body");
  if (!tbody) return;
  if (!rows || rows.length === 0) {
    setTableEmpty("crypto-callsigns-body", 3, "Нет неактивных корреспондентов");
    return;
  }
  tbody.innerHTML = rows
    .map((r) => {
      return `<tr>
        <td class="wp-mono">${escapeHtml(r.callsign_id)}</td>
        <td>${escapeHtml(String(r.key_count || 0))}</td>
        <td>${escapeHtml(fmtDate(r.last_seen))}</td>
      </tr>`;
    })
    .join("");
}

async function runCheck() {
  const range = readRange();
  const qs = range
    ? `start=${encodeURIComponent(range.start)}&end=${encodeURIComponent(range.end)}`
    : `days=${encodeURIComponent(String(CRYPTO_DAYS || 1))}`;
  setText("crypto-status", "Проверка...");
  try {
    const data = await apiGet(`/api/crypto/check?${qs}`);
    setText("crypto-status", data.info || "Готово.");
    setText("crypto-metric-active", String(data.stats?.active_keys || 0));
    setText("crypto-metric-inactive", String(data.stats?.inactive_keys || 0));
    setText("crypto-metric-groups", String(data.stats?.inactive_groups || 0));
    setText("crypto-metric-callsigns", String(data.stats?.inactive_callsigns || 0));
    renderActiveKeys(data.active_keys || []);
    renderInactiveKeys(data.inactive_keys || []);
    renderInactiveGroups(data.inactive_groups || []);
    renderInactiveCallsigns(data.inactive_callsigns || []);
  } catch (e) {
    setText("crypto-status", `Ошибка: ${e.message || e}`);
  }
}

async function deleteCryptoKey(uid) {
  if (!uid) return;
  if (!confirm(`Удалить ключ ${uid} из всех XML-файлов?`)) return;
  setText("crypto-status", "Удаление ключа...");
  try {
    const data = await apiPost("/api/crypto/delete", { type: "key", key_uid: uid });
    setText("crypto-status", data.info || "Удалено.");
    await runCheck();
  } catch (e) {
    setText("crypto-status", `Ошибка: ${e.message || e}`);
  }
}

async function deleteCryptoGroup(gid) {
  if (!gid) return;
  if (!confirm(`Удалить группу ${gid} и связанные ключи из всех XML-файлов?`)) return;
  setText("crypto-status", "Удаление группы...");
  try {
    const data = await apiPost("/api/crypto/delete", { type: "group", group_id: gid });
    setText("crypto-status", data.info || "Удалено.");
    await runCheck();
  } catch (e) {
    setText("crypto-status", `Ошибка: ${e.message || e}`);
  }
}

document.addEventListener("DOMContentLoaded", function () {
  setActivePeriod(1);
  loadConfig();

  $("crypto-save-path")?.addEventListener("click", saveConfig);
  $("crypto-check-btn")?.addEventListener("click", runCheck);

  const period = $("crypto-period");
  if (period) {
    period.querySelectorAll("[data-days]").forEach((btn) => {
      btn.addEventListener("click", () => setActivePeriod(btn.getAttribute("data-days")));
    });
  }

  document.addEventListener("click", (e) => {
    const keyBtn = e.target.closest(".crypto-delete-key");
    if (keyBtn) {
      const uid = keyBtn.getAttribute("data-key-uid");
      deleteCryptoKey(uid);
      return;
    }
    const groupBtn = e.target.closest(".crypto-delete-group");
    if (groupBtn) {
      const gid = groupBtn.getAttribute("data-group-id");
      deleteCryptoGroup(gid);
    }
  });
});
