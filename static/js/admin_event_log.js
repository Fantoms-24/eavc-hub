(function () {
  let autoTimer = null;

  function $(id) {
    return document.getElementById(id);
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function levelBadge(level) {
    const l = String(level || "INFO").toUpperCase();
    const cls =
      l === "CRITICAL" || l === "ERROR"
        ? "text-bg-danger"
        : l === "WARNING"
          ? "text-bg-warning"
          : "text-bg-secondary";
    return `<span class="badge ${cls}">${escapeHtml(l)}</span>`;
  }

  async function apiGet(url) {
    const res = await fetch(url, { method: "GET", cache: "no-cache" });
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

  function buildEventLogQuery() {
    const params = new URLSearchParams();
    const limit = $("event-log-limit")?.value || "200";
    params.set("limit", String(limit));
    const level = $("event-log-level")?.value || "";
    const category = $("event-log-category")?.value || "";
    const q = ($("event-log-q")?.value || "").trim();
    if (level) params.set("level", level);
    if (category) params.set("category", category);
    if (q) params.set("q", q);
    return params.toString();
  }

  function renderDetailsModal(item) {
    const body = JSON.stringify(item.details || {}, null, 2);
    const html = `
      <div class="modal fade" id="event-log-detail-modal" tabindex="-1">
        <div class="modal-dialog modal-lg modal-dialog-scrollable">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title">Событие #${item.id}</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
              <div class="small mb-2"><strong>${escapeHtml(item.message)}</strong></div>
              <pre class="small mb-0">${escapeHtml(body)}</pre>
            </div>
          </div>
        </div>
      </div>`;
    const old = document.getElementById("event-log-detail-modal");
    if (old) old.remove();
    document.body.insertAdjacentHTML("beforeend", html);
    const el = document.getElementById("event-log-detail-modal");
    const modal = window.bootstrap?.Modal ? new window.bootstrap.Modal(el) : null;
    if (modal) modal.show();
    else el?.classList.add("show");
  }

  async function checkEventLogAvailable() {
    const res = await fetch("/api/admin/event-log/status", { cache: "no-cache" });
    if (res.status === 404) {
      throw new Error(
        "API журнала не найден (404). Перезапустите сервер портала с актуальным кодом."
      );
    }
    const data = await res.json().catch(() => ({}));
    if (!data.ok) throw new Error("Сервер не поддерживает журнал событий");
    return data;
  }

  async function loadEventLog() {
    const tbody = $("event-log-tbody");
    const statusEl = $("event-log-status");
    if (!tbody) return;
    if (statusEl) statusEl.textContent = "Загрузка…";
    try {
      await checkEventLogAvailable();
      const qs = buildEventLogQuery();
      const data = await apiGet(`/api/admin/event-log?${qs}`);
      const items = data.items || [];
      if (!items.length) {
        tbody.innerHTML =
          '<tr><td colspan="7" class="text-muted small">Записей нет</td></tr>';
      } else {
        tbody.innerHTML = items
          .map((it) => {
            const req =
              it.method && it.path
                ? `${escapeHtml(it.method)} ${escapeHtml(it.path)}`
                : escapeHtml(it.path || "—");
            const user = it.username
              ? escapeHtml(it.username)
              : it.user_id
                ? `#${it.user_id}`
                : "—";
            const dur =
              it.duration_ms > 0 ? ` <span class="text-muted">${it.duration_ms} ms</span>` : "";
            const st =
              it.status_code > 0
                ? ` <span class="badge text-bg-light border">${it.status_code}</span>`
                : "";
            return `<tr>
              <td class="text-nowrap small">${escapeHtml(it.created_at)}</td>
              <td>${levelBadge(it.level)}</td>
              <td class="small">${escapeHtml(it.category)}</td>
              <td class="small">${user}</td>
              <td class="small">${req}${st}${dur}</td>
              <td class="small text-break">${escapeHtml(it.message)}</td>
              <td class="text-end">
                <button type="button" class="btn btn-link btn-sm p-0 event-log-detail-btn" data-id="${it.id}">JSON</button>
              </td>
            </tr>`;
          })
          .join("");
        const byId = Object.fromEntries(items.map((x) => [String(x.id), x]));
        tbody.querySelectorAll(".event-log-detail-btn").forEach((btn) => {
          btn.addEventListener("click", () => {
            const item = byId[btn.getAttribute("data-id") || ""];
            if (item) renderDetailsModal(item);
          });
        });
      }
      if (statusEl) {
        statusEl.textContent = `Показано ${items.length} из ${data.total || 0}`;
      }
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-danger small">${escapeHtml(e.message || e)}</td></tr>`;
      if (statusEl) statusEl.textContent = `Ошибка: ${e.message || e}`;
    }
  }

  async function loadFileTail() {
    const pre = $("event-log-file-pre");
    const meta = $("event-log-file-meta");
    if (!pre) return;
    pre.textContent = "Чтение…";
    try {
      const data = await apiGet("/api/admin/event-log/file-tail?lines=350");
      if (!data.exists) {
        pre.textContent = "Файл лога ещё не создан (появится после перезапуска сервера).";
        if (meta) meta.textContent = data.path || "";
        return;
      }
      const lines = data.lines || [];
      pre.textContent = lines.join("\n") || "(пусто)";
      if (meta) {
        const kb = data.size_bytes ? Math.round(data.size_bytes / 1024) : 0;
        meta.textContent = `${data.path || ""} · ~${kb} KB · строк: ${lines.length}`;
      }
    } catch (e) {
      pre.textContent = String(e.message || e);
      if (meta) meta.textContent = "Ошибка чтения";
    }
  }

  async function purgeOldEvents() {
    if (!window.confirm("Удалить записи журнала старше 30 дней?")) return;
    const statusEl = $("event-log-status");
    try {
      const data = await apiPost("/api/admin/event-log/purge", { days: 30 });
      if (statusEl) statusEl.textContent = `Удалено записей: ${data.deleted || 0}`;
      await loadEventLog();
    } catch (e) {
      if (statusEl) statusEl.textContent = `Ошибка очистки: ${e.message || e}`;
    }
  }

  function setAutoRefresh(on) {
    if (autoTimer) {
      clearInterval(autoTimer);
      autoTimer = null;
    }
    if (on) {
      autoTimer = setInterval(() => {
        const pane = document.querySelector("#admin-event-log-pane");
        if (pane && pane.classList.contains("active")) {
          loadEventLog();
        }
      }, 10000);
    }
  }

  function startEventLogTab() {
    const tab = document.querySelector("#admin-event-log-tab");
    if (tab) {
      tab.addEventListener("shown.bs.tab", () => {
        loadEventLog();
        loadFileTail();
      });
    }
    $("event-log-refresh-btn")?.addEventListener("click", () => loadEventLog());
    $("event-log-file-refresh-btn")?.addEventListener("click", () => loadFileTail());
    $("event-log-purge-btn")?.addEventListener("click", () => purgeOldEvents());
    $("event-log-q")?.addEventListener(
      "input",
      debounce(() => loadEventLog(), 400)
    );
    $("event-log-level")?.addEventListener("change", () => loadEventLog());
    $("event-log-category")?.addEventListener("change", () => loadEventLog());
    $("event-log-limit")?.addEventListener("change", () => loadEventLog());
    $("event-log-auto-refresh")?.addEventListener("change", (ev) => {
      setAutoRefresh(!!ev.target?.checked);
    });
  }

  function debounce(fn, wait) {
    let t = null;
    return (...args) => {
      if (t) clearTimeout(t);
      t = setTimeout(() => fn(...args), wait);
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startEventLogTab);
  } else {
    startEventLogTab();
  }
})();
