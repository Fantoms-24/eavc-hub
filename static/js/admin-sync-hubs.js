(function () {
  "use strict";

async function loadSyncStatus() {
  const content = $("#sync-status-content");
  if (!content) return;

  try {
    content.innerHTML = `
      <div class="text-muted small text-center py-4">
        <i class="bi bi-arrow-clockwise spin"></i> Загрузка статуса синхронизации...
      </div>
    `;

    const data = await apiGet("/api/admin/sync/status");

    const isHub = data.is_hub === true;
    const upstream = data.upstream || "";
    const pending = data.outbox_pending || 0;
    const meta = data.meta || {};
    const stats = data.stats || {};
    const outboxHead = data.outbox_head || [];

    let html = `
      <div class="row g-3">
        <div class="col-md-6">
          <div class="card border-0 shadow-sm h-100" style="background: linear-gradient(135deg, rgba(37, 99, 235, 0.05) 0%, rgba(37, 99, 235, 0.01) 100%);">
            <div class="card-body p-3">
              <div class="d-flex align-items-center gap-2 mb-3">
                <i class="bi ${isHub ? "bi-hdd-network text-primary" : "bi-server text-success"} fs-5"></i>
                <div class="fw-bold">${isHub ? "HUB (Клиент)" : "Центральный сервер"}</div>
              </div>
              ${isHub ? `
                <div class="small mb-2"><strong>Upstream:</strong> <code class="small">${escapeHtml(upstream || "не задан")}</code></div>
                <div class="small mb-2"><strong>Sync Key:</strong> <span class="badge ${data.sync_key_set ? "bg-success" : "bg-danger"}">${data.sync_key_set ? "Установлен" : "Не установлен"}</span></div>
              ` : `
                <div class="small text-muted">Принимает данные от Hub'ов</div>
              `}
            </div>
          </div>
        </div>
        <div class="col-md-6">
          <div class="card border-0 shadow-sm h-100" style="background: linear-gradient(135deg, rgba(234, 88, 12, 0.05) 0%, rgba(234, 88, 12, 0.01) 100%);">
            <div class="card-body p-3">
              <div class="d-flex align-items-center gap-2 mb-3">
                <i class="bi bi-inbox text-warning fs-5"></i>
                <div class="fw-bold">Outbox</div>
              </div>
              <div class="h4 mb-0">${pending}</div>
              <div class="small text-muted">Ожидающих отправки событий</div>
            </div>
          </div>
        </div>
      </div>

      <div class="row g-3 mt-2">
        <div class="col-md-12">
          <div class="card border-0 shadow-sm">
            <div class="card-header bg-transparent border-0 pb-2">
              <h6 class="mb-0"><i class="bi bi-info-circle me-1"></i>Метаданные синхронизации</h6>
            </div>
            <div class="card-body p-3">
              <div class="table-responsive">
                <table class="table table-sm table-hover mb-0">
                  <thead class="table-light">
                    <tr>
                      <th>Ключ</th>
                      <th>Значение</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td><code>last_pull_ts</code></td>
                      <td><span class="wp-mono small">${escapeHtml(meta.last_pull_ts || "—")}</span></td>
                    </tr>
                    <tr>
                      <td><code>seanses_last_rowid</code></td>
                      <td><span class="wp-mono small">${escapeHtml(meta.seanses_last_rowid || "0")}</span></td>
                    </tr>
                    <tr>
                      <td><code>unit_last_rowid</code></td>
                      <td><span class="wp-mono small">${escapeHtml(meta.unit_last_rowid || "0")}</span></td>
                    </tr>
                    <tr>
                      <td><code>online_search_last_ts</code></td>
                      <td><span class="wp-mono small">${escapeHtml(meta.online_search_last_ts || "—")}</span></td>
                    </tr>
                    <tr>
                      <td><code>online_search_last_id</code></td>
                      <td><span class="wp-mono small">${escapeHtml(meta.online_search_last_id || "0")}</span></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="row g-3 mt-2">
        <div class="col-md-12">
          <div class="card border-0 shadow-sm">
            <div class="card-header bg-transparent border-0 pb-2">
              <h6 class="mb-0"><i class="bi bi-database me-1"></i>Статистика БД</h6>
            </div>
            <div class="card-body p-3">
              <div class="row g-2">
                <div class="col-md-3">
                  <div class="small text-muted">Сеансы</div>
                  <div class="h6 mb-0">${stats.seanses_total || 0}</div>
                </div>
                <div class="col-md-3">
                  <div class="small text-muted">Подразделения (unit)</div>
                  <div class="h6 mb-0">${stats.unit_total || 0}</div>
                </div>
                <div class="col-md-3">
                  <div class="small text-muted">Сессии перехватов</div>
                  <div class="h6 mb-0">${stats.intercept_sessions_total || 0}</div>
                </div>
                <div class="col-md-3">
                  <div class="small text-muted">Каталоги перехватов</div>
                  <div class="h6 mb-0">${stats.intercept_catalog_total || 0}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;

    if (outboxHead.length > 0) {
      html += `
        <div class="row g-3 mt-2">
          <div class="col-md-12">
            <div class="card border-0 shadow-sm">
              <div class="card-header bg-transparent border-0 pb-2">
                <h6 class="mb-0"><i class="bi bi-list-ul me-1"></i>Последние события в outbox (первые ${outboxHead.length})</h6>
              </div>
              <div class="card-body p-3">
                <div class="table-responsive">
                  <table class="table table-sm table-hover mb-0">
                    <thead class="table-light">
                      <tr>
                        <th style="width: 60px;">ID</th>
                        <th>Kind</th>
                        <th>Создано</th>
                        <th style="width: 80px;">Попыток</th>
                        <th>Последняя ошибка</th>
                      </tr>
                    </thead>
                    <tbody>
                      ${outboxHead.map(item => `
                        <tr>
                          <td class="small">${item.id}</td>
                          <td><code class="small">${escapeHtml(item.kind || "")}</code></td>
                          <td class="small wp-mono">${escapeHtml(item.created_at || "")}</td>
                          <td><span class="badge ${item.attempts > 3 ? "bg-danger" : item.attempts > 0 ? "bg-warning" : "bg-secondary"}">${item.attempts}</span></td>
                          <td class="small text-danger">${escapeHtml(item.last_error || "—")}</td>
                        </tr>
                      `).join("")}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
        </div>
      `;
    }

    content.innerHTML = html;
  } catch (e) {
    content.innerHTML = `
      <div class="alert alert-danger py-2 small">
        <i class="bi bi-exclamation-triangle me-1"></i>
        Ошибка загрузки статуса: ${escapeHtml(e.message || String(e))}
      </div>
    `;
  }
}

// Загрузка данных при открытии вкладки «Роли»

// Автообновление статуса синхронизации каждые 10 секунд (если вкладка активна)
let syncStatusInterval = null;
function startSyncStatusAutoRefresh() {
  if (syncStatusInterval) clearInterval(syncStatusInterval);
  const syncTab = document.querySelector("#admin-sync-tab");
  if (!syncTab) return;

  // Загружаем сразу при показе вкладки
  syncTab.addEventListener("shown.bs.tab", () => {
    loadSyncStatus();
    populateDbHealthSelect();
    if (syncStatusInterval) clearInterval(syncStatusInterval);
    syncStatusInterval = setInterval(() => {
      if (document.hidden) return;
      const syncPane = document.querySelector("#admin-sync-pane");
      if (syncPane && syncPane.classList.contains("active")) {
        loadSyncStatus();
      }
    }, 15000);
  });
}
// ===== HUB ONLINE =====

async function loadHubs() {
  const content = $("hubs-content");
  if (!content) return;

  try {
    content.innerHTML = `
      <div class="text-muted small text-center py-4">
        <i class="bi bi-arrow-clockwise spin"></i> Загрузка Hub'ов...
      </div>
    `;

    const data = await apiGet("/api/admin/hubs?max_age_minutes=60");
    const hubs = data.hubs || [];

    if (hubs.length === 0) {
      content.innerHTML = `
        <div class="hub-empty-state">
          <i class="bi bi-hdd-network"></i>
          <h5>Нет активных Hub'ов</h5>
          <div class="small">Hub'ы появятся здесь после подключения к серверу</div>
        </div>
      `;
      return;
    }

    const onlineCount = hubs.filter(h => h.status === "online").length;
    const totalCount = hubs.length;

    content.innerHTML = `
      <div class="mb-3">
        <div class="row g-2">
          <div class="col-md-3">
            <div class="card border-0 shadow-sm" style="background: linear-gradient(135deg, rgba(16, 185, 129, 0.1) 0%, rgba(16, 185, 129, 0.05) 100%);">
              <div class="card-body p-3">
                <div class="d-flex align-items-center gap-2">
                  <i class="bi bi-circle-fill text-success fs-5"></i>
                  <div>
                    <div class="fw-bold text-success">${onlineCount}</div>
                    <div class="small text-muted">Онлайн</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div class="col-md-3">
            <div class="card border-0 shadow-sm" style="background: linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(59, 130, 246, 0.05) 100%);">
              <div class="card-body p-3">
                <div class="d-flex align-items-center gap-2">
                  <i class="bi bi-hdd-network text-primary fs-5"></i>
                  <div>
                    <div class="fw-bold text-primary">${totalCount}</div>
                    <div class="small text-muted">Всего Hub'ов</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="table-responsive">
        <table class="table table-hover align-middle">
          <thead class="table-light">
            <tr>
              <th style="width: 120px;">Hub ID</th>
              <th style="width: 150px;">Имя</th>
              <th style="width: 120px;">Позиция</th>
              <th style="width: 120px;">IP адрес</th>
              <th style="width: 140px;">Статус</th>
              <th style="width: 160px;">Последняя активность</th>
              <th style="width: 150px;">Отправка данных</th>
              <th style="width: 150px;">Получение данных</th>
            </tr>
          </thead>
          <tbody>
            ${hubs.map(hub => {
      const statusClass = {
        "online": "bg-success",
        "recent": "bg-info",
        "idle": "bg-warning",
        "offline": "bg-secondary",
        "unknown": "bg-secondary"
      }[hub.status] || "bg-secondary";

      const statusIcon = {
        "online": "bi-circle-fill",
        "recent": "bi-circle-half",
        "idle": "bi-circle",
        "offline": "bi-circle",
        "unknown": "bi-question-circle"
      }[hub.status] || "bi-question-circle";

      return `
                <tr class="hub-row">
                  <td>
                    <div class="hub-id-cell d-inline-block px-2 py-1 rounded">${escapeHtml(hub.hub_id || "")}</div>
                  </td>
                  <td>
                    <div class="d-flex align-items-center gap-2">
                      <span class="hub-online-indicator ${hub.status}"></span>
                      <span class="hub-name-cell fw-semibold">${escapeHtml(hub.hub_name || hub.hub_id || "")}</span>
                    </div>
                  </td>
                  <td>${hub.position_name ? `<span class="badge hub-position-badge text-bg-light border">${escapeHtml(hub.position_name)}</span>` : '<span class="text-muted small">—</span>'}</td>
                  <td><span class="hub-ip-cell">${escapeHtml(hub.ip_address || "")}</span></td>
                  <td>
                    <span class="badge ${statusClass} hub-status-${hub.status}">
                      <i class="bi ${statusIcon} me-1"></i>${escapeHtml(hub.status_text || "")}
                    </span>
                  </td>
                  <td class="hub-time-cell">${formatDate(hub.last_seen)}</td>
                  <td class="hub-time-cell">${hub.last_push ? formatDate(hub.last_push) : '<span class="text-muted">—</span>'}</td>
                  <td class="hub-time-cell">${hub.last_pull ? formatDate(hub.last_pull) : '<span class="text-muted">—</span>'}</td>
                </tr>
              `;
    }).join("")}
          </tbody>
        </table>
      </div>
    `;
  } catch (e) {
    setStatus(`Ошибка загрузки Hub'ов: ${e.message || e}`, true);
    content.innerHTML = `<div class="text-danger small text-center py-4">Ошибка: ${escapeHtml(e.message || String(e))}</div>`;
  }
}

// Автообновление Hub'ов каждые 30 секунд
let hubsInterval = null;
function startHubsAutoRefresh() {
  if (hubsInterval) clearInterval(hubsInterval);
  const hubsTab = document.getElementById("admin-hubs-tab");
  if (hubsTab) {
    hubsTab.addEventListener("shown.bs.tab", () => {
      loadHubs();
      if (hubsInterval) clearInterval(hubsInterval);
      hubsInterval = setInterval(() => {
        if (document.hidden) return;
        loadHubs();
      }, 30000);
    });
    // Загружаем сразу, если вкладка активна
    if (hubsTab.classList.contains("active")) {
      loadHubs();
      hubsInterval = setInterval(() => {
        if (document.hidden) return;
        loadHubs();
      }, 30000);
    }
  }
}

// ===== Доступ к чату «Рабочая атмосфера» (вкладка Настройки) =====

  function init() {
    startSyncStatusAutoRefresh();
    startHubsAutoRefresh();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
