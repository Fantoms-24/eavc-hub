(function () {
  "use strict";

const CHAT_ACCESS_CHANNEL = "work_atmosphere";

async function loadChatAccess() {
  const container = $("chat-access-roles");
  const statusEl = $("chat-access-status");
  if (!container) return;
  try {
    container.innerHTML = '<span class="small text-muted">Загрузка...</span>';
    const [accessData, rolesData] = await Promise.all([
      apiGet("/api/admin/chat-access?channel=" + encodeURIComponent(CHAT_ACCESS_CHANNEL)),
      apiGet("/api/admin/roles"),
    ]);
    const allowedRoles = new Set((accessData.roles || []).map((r) => String(r).trim()));
    const rolesForCheck = rolesData.roles_for_assignment || rolesData.roles || [];
    const roles = rolesForCheck.length ? rolesForCheck : [
      { role: "admin", label: "Администратор" },
      { role: "moderator", label: "Модератор" },
      { role: "search_editor", label: "Редактор поиска" },
      { role: "viewer", label: "Наблюдатель" },
    ];
    container.innerHTML = roles.map((r) => {
      const role = String(r.role || "").trim();
      const label = String(r.label || r.role || role);
      const checked = allowedRoles.has(role);
      return `
        <div class="form-check">
          <input class="form-check-input chat-access-role-cb" type="checkbox" value="${escapeHtml(role)}" id="chat-access-${escapeHtml(role)}" ${checked ? "checked" : ""}>
          <label class="form-check-label small" for="chat-access-${escapeHtml(role)}">${escapeHtml(label)}</label>
        </div>
      `;
    }).join("");
    if (statusEl) statusEl.textContent = "";
  } catch (e) {
    container.innerHTML = '<span class="small text-danger">Ошибка загрузки</span>';
    if (statusEl) statusEl.textContent = "Ошибка: " + (e.message || e);
  }
}

async function saveChatAccess() {
  const statusEl = $("chat-access-status");
  const checkboxes = document.querySelectorAll(".chat-access-role-cb:checked");
  const roles = Array.from(checkboxes).map((cb) => cb.value).filter(Boolean);
  try {
    if (statusEl) statusEl.textContent = "Сохранение...";
    await apiPost("/api/admin/chat-access", { channel: CHAT_ACCESS_CHANNEL, roles });
    if (statusEl) {
      statusEl.textContent = "Сохранено.";
      statusEl.className = "small mt-2 text-success";
    }
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = "Ошибка: " + (e.message || e);
      statusEl.className = "small mt-2 text-danger";
    }
  }
}

async function loadAsrTraining() {
  const statusEl = $("asr-training-status");
  const enabledCb = $("asr-training-enabled-cb");
  const blankCb = $("asr-learn-blank-cb");
  const feedbackCb = $("asr-learn-feedback-cb");
  if (!enabledCb) return;
  try {
    if (statusEl) statusEl.textContent = "Загрузка...";
    const data = await apiGet("/api/admin/asr-training");
    const policy = (data && data.policy) || {};
    enabledCb.checked = !!policy.training_enabled;
    if (blankCb) blankCb.checked = policy.learn_on_blank_send !== false;
    if (feedbackCb) feedbackCb.checked = policy.learn_on_feedback !== false;
    if (statusEl) statusEl.textContent = "";
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = "Ошибка: " + (e.message || e);
      statusEl.className = "small mt-2 text-danger";
    }
  }
}

async function saveAsrTraining() {
  const statusEl = $("asr-training-status");
  const enabledCb = $("asr-training-enabled-cb");
  const blankCb = $("asr-learn-blank-cb");
  const feedbackCb = $("asr-learn-feedback-cb");
  if (!enabledCb) return;
  try {
    if (statusEl) statusEl.textContent = "Сохранение...";
    await apiPost("/api/admin/asr-training", {
      training_enabled: !!enabledCb.checked,
      learn_on_blank_send: blankCb ? !!blankCb.checked : true,
      learn_on_feedback: feedbackCb ? !!feedbackCb.checked : true,
    });
    if (statusEl) {
      statusEl.textContent = "Сохранено.";
      statusEl.className = "small mt-2 text-success";
    }
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = "Ошибка: " + (e.message || e);
      statusEl.className = "small mt-2 text-danger";
    }
  }
}

async function clearClientNameRecords() {
  const input = $("clear-client-name-input");
  const statusEl = $("clear-client-name-status");
  const btn = $("clear-client-name-btn");
  const name = String(input?.value || "").trim();
  if (!name) {
    if (statusEl) {
      statusEl.textContent = "Укажи client_name для очистки.";
      statusEl.className = "small mt-2 text-danger";
    }
    return;
  }
  const confirmText = `Очистить все записи seanses с client_name="${name}"?`;
  if (!window.confirm(confirmText)) return;
  try {
    if (btn) btn.disabled = true;
    if (statusEl) {
      statusEl.textContent = "Очистка...";
      statusEl.className = "small mt-2 text-muted";
    }
    const res = await apiPost("/api/admin/clear-client-name", { client_name: name });
    if (statusEl) {
      statusEl.textContent = `Готово. Удалено записей: ${res.deleted || 0}.`;
      statusEl.className = "small mt-2 text-success";
    }
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = "Ошибка: " + (e.message || e);
      statusEl.className = "small mt-2 text-danger";
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function archiveSeansesManual() {
  const dateInput = $("archive-seanses-keep-date");
  const statusEl = $("archive-seanses-status");
  const btn = $("archive-seanses-btn");
  const keepDate = String(dateInput?.value || "").trim();
  const confirmText = keepDate
    ? `Архивировать сеансы, оставив только дату ${keepDate}?`
    : "Архивировать сеансы, оставив только текущую дату компьютера?";
  if (!window.confirm(confirmText)) return;
  try {
    if (btn) btn.disabled = true;
    if (statusEl) {
      statusEl.textContent = "Архивация...";
      statusEl.className = "small mt-2 text-muted";
    }
    const payload = {};
    if (keepDate) payload.keep_date = keepDate;
    const res = await apiPost("/api/admin/archive-seanses", payload);
    if (statusEl) {
      statusEl.textContent = `Готово. Архивировано: ${res.archived || 0}, осталось в seanses: ${res.remaining_active || 0}.`;
      statusEl.className = "small mt-2 text-success";
    }
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = "Ошибка: " + (e.message || e);
      statusEl.className = "small mt-2 text-danger";
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

function defaultArchiveFileName() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `seanses_${pad(d.getDate())}_${pad(d.getMonth() + 1)}_${d.getFullYear()}.sqlite`;
}

function dateIsoDaysAgo(days) {
  const n = Math.max(1, parseInt(String(days || "30"), 10) || 30);
  const d = new Date();
  d.setHours(12, 0, 0, 0);
  d.setDate(d.getDate() - n);
  const pad = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

async function archiveKeepLastDays() {
  const daysEl = $("archive-keep-days");
  const statusEl = $("archive-file-status");
  const btn = $("archive-keep-days-btn");
  const days = Math.max(1, parseInt(String(daysEl?.value || "30"), 10) || 30);
  const beforeDate = dateIsoDaysAgo(days);
  const fname = `seanses_keep_${days}d_${beforeDate.replace(/-/g, "_")}.sqlite`;
  const ok = window.confirm(
    `Оставить в main.sqlite сеансы с датой ${beforeDate} и новее (последние ~${days} дн.), ` +
      `остальное перенести в ${fname} и выполнить VACUUM?\n\n` +
      "Остановите автопоиск сеансов на время операции. Сделайте копию main.sqlite, если нужна страховка."
  );
  if (!ok) return;
  const beforeEl = $("archive-file-before-date");
  const nameEl = $("archive-file-name");
  const vacuumEl = $("archive-file-vacuum");
  const inclArchEl = $("archive-file-include-arch");
  if (beforeEl) beforeEl.value = beforeDate;
  if (nameEl) nameEl.value = fname;
  if (vacuumEl) vacuumEl.checked = true;
  if (inclArchEl) inclArchEl.checked = true;
  try {
    if (btn) btn.disabled = true;
    if (statusEl) {
      statusEl.textContent = "Архивация и VACUUM… (может занять несколько минут)";
      statusEl.className = "small mt-2 text-muted";
    }
    const res = await apiPost("/api/admin/archive-seanses-to-file", {
      before_date: beforeDate,
      filename: fname,
      vacuum: true,
      include_seanses_archive: true,
      overwrite: false,
    });
    if (statusEl) {
      statusEl.textContent =
        `Готово (порог ${beforeDate}). Из seanses: ${res.moved_from_seanses || 0}, из seanses_archive: ${res.moved_from_seanses_archive || 0}. ` +
        `В main осталось seanses: ${res.remaining_seanses_in_main ?? "—"}. VACUUM: ${res.vacuum_main ? "да" : "нет"}. ` +
        `Файл: ${res.archive_path || ""}`;
      statusEl.className = "small mt-2 text-success";
    }
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = "Ошибка: " + (e.message || e);
      statusEl.className = "small mt-2 text-danger";
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function archiveSeansesToFile() {
  const beforeEl = $("archive-file-before-date");
  const nameEl = $("archive-file-name");
  const vacuumEl = $("archive-file-vacuum");
  const inclArchEl = $("archive-file-include-arch");
  const overEl = $("archive-file-overwrite");
  const statusEl = $("archive-file-status");
  const btn = $("archive-file-btn");
  const beforeDate = String(beforeEl?.value || "").trim();
  if (!beforeDate) {
    if (statusEl) {
      statusEl.textContent = "Укажите дату «до какой» архивировать (строки с более ранним date_time).";
      statusEl.className = "small mt-2 text-warning";
    }
    return;
  }
  const fname = String(nameEl?.value || "").trim() || defaultArchiveFileName();
  const ok = window.confirm(
    `Перенести в файл ${fname} все сеансы, у которых день в date_time строго раньше ${beforeDate} (календарь), и удалить их из основной БД?\n` +
      "Справочники (unit) и перехваты не меняются."
  );
  if (!ok) return;
  try {
    if (btn) btn.disabled = true;
    if (statusEl) {
      statusEl.textContent = "Перенос пакетами…";
      statusEl.className = "small mt-2 text-muted";
    }
    const res = await apiPost("/api/admin/archive-seanses-to-file", {
      before_date: beforeDate,
      filename: fname,
      vacuum: !!(vacuumEl && vacuumEl.checked),
      include_seanses_archive: !!(inclArchEl && inclArchEl.checked),
      overwrite: !!(overEl && overEl.checked),
    });
    if (statusEl) {
      statusEl.textContent =
        `Готово. Из seanses: ${res.moved_from_seanses || 0}, из seanses_archive: ${res.moved_from_seanses_archive || 0}. ` +
        `В файле строк: ${res.rows_in_archive_file_seanses || 0}. В main осталось seanses: ${res.remaining_seanses_in_main ?? "—"}, seanses_archive: ${res.remaining_seanses_archive_in_main ?? "—"}. ` +
        `Файл: ${res.archive_path || ""}`;
      statusEl.className = "small mt-2 text-success";
    }
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = "Ошибка: " + (e.message || e);
      statusEl.className = "small mt-2 text-danger";
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function archiveSeansesAll() {
  const statusEl = $("archive-seanses-status");
  const btn = $("archive-seanses-all-btn");
  const ok = window.confirm(
    "Перенести ВСЕ записи из таблицы seanses в архив (seanses_archive)?\n\n" +
      "Справочник подразделений (unit), перехваты и остальные данные не изменяются.\n" +
      "Таблица seanses станет пустой — это уменьшит нагрузку на работу с «текущими» сеансами."
  );
  if (!ok) return;
  try {
    if (btn) btn.disabled = true;
    if (statusEl) {
      statusEl.textContent = "Перенос всех сеансов в архив (пакетами)...";
      statusEl.className = "small mt-2 text-muted";
    }
    const res = await apiPost("/api/admin/archive-seanses", { mode: "all" });
    if (statusEl) {
      statusEl.textContent =
        `Готово. Перенесено строк: ${res.archived || 0}. В seanses осталось: ${res.remaining_active || 0}. ` +
        `Всего в архиве: ${res.archive_total || 0}.`;
      statusEl.className = "small mt-2 text-success";
    }
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = "Ошибка: " + (e.message || e);
      statusEl.className = "small mt-2 text-danger";
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function exportSessionsToExcel() {
  const inputEl = $("export-sessions-folder-path");
  const statusEl = $("export-sessions-status");
  const btn = $("export-sessions-excel-btn");
  const progressWrap = $("export-sessions-progress-wrap");
  const stageEl = $("export-sessions-stage");
  const progressBar = $("export-sessions-progress-bar");
  const folderPath = String(inputEl?.value || "").trim();
  if (!folderPath) {
    if (statusEl) {
      statusEl.textContent = "Укажите путь к папке.";
      statusEl.className = "small mt-2 text-warning";
    }
    return;
  }
  function setProgress(visible, percent, text) {
    if (progressWrap) progressWrap.style.display = visible ? "block" : "none";
    if (stageEl) stageEl.textContent = text || "—";
    if (progressBar) {
      progressBar.style.width = percent + "%";
      progressBar.setAttribute("aria-valuenow", percent);
      progressBar.textContent = percent === 100 ? "100%" : (percent > 0 ? percent + "%" : "");
    }
  }
  try {
    if (btn) btn.disabled = true;
    if (statusEl) {
      statusEl.textContent = "";
      statusEl.className = "small mt-2";
    }
    setProgress(true, 0, "Подключение...");

    const res = await fetch("/api/admin/export-sessions-excel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder_path: folderPath }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || "HTTP " + res.status);
    }
    const contentType = res.headers.get("content-type") || "";
    if (contentType.indexOf("ndjson") !== -1 || contentType.indexOf("x-ndjson") !== -1) {
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let total = 0;
      let current = 0;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          const s = line.trim();
          if (!s) continue;
          let ev;
          try {
            ev = JSON.parse(s);
          } catch (_) {
            continue;
          }
          const stage = ev.stage;
          if (stage === "scan") {
            setProgress(true, 0, ev.message || "Сканирование папки...");
          } else if (stage === "count") {
            total = Number(ev.total) || 0;
            setProgress(true, 0, ev.message || "Найдено файлов: " + total);
          } else if (stage === "file") {
            current = Number(ev.current) || 0;
            total = Number(ev.total) || total;
            const pct = total > 0 ? Math.round((current / total) * 100) : 0;
            setProgress(true, pct, ev.message || (total ? "Обработка " + current + " / " + total : "Обработка файла " + current));
          } else if (stage === "excel") {
            setProgress(true, 100, ev.message || "Формирование Excel...");
          } else if (stage === "done") {
            setProgress(true, 100, "Готово. Скачивание...");
            const token = ev.token;
            const filename = ev.filename || "seanses_export.xlsx";
            const downRes = await fetch("/api/admin/export-sessions-excel/download/" + encodeURIComponent(token));
            if (!downRes.ok) throw new Error("Не удалось скачать файл");
            const blob = await downRes.blob();
            const a = document.createElement("a");
            a.href = URL.createObjectURL(blob);
            a.download = filename;
            a.click();
            URL.revokeObjectURL(a.href);
            setProgress(false, 0, "");
            if (statusEl) {
              statusEl.textContent = "Файл " + filename + " сформирован и скачан.";
              statusEl.className = "small mt-2 text-success";
            }
          } else if (stage === "error") {
            throw new Error(ev.error || "Ошибка на сервере");
          }
        }
      }
      if (buffer.trim()) {
        try {
          const ev = JSON.parse(buffer.trim());
          if (ev.stage === "error") throw new Error(ev.error || "Ошибка");
        } catch (_) {}
      }
    } else {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || "Неожиданный ответ сервера");
    }
  } catch (e) {
    setProgress(false, 0, "");
    if (statusEl) {
      statusEl.textContent = "Ошибка: " + (e.message || e);
      statusEl.className = "small mt-2 text-danger";
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function loadPerfMetrics() {
  const contentEl = $("perf-metrics-content");
  const statusEl = $("perf-metrics-status");
  if (!contentEl) return;
  try {
    contentEl.innerHTML = '<div class="text-muted small">Загрузка метрик...</div>';
    if (statusEl) {
      statusEl.textContent = "";
      statusEl.className = "small mt-2";
    }
    const data = await apiGet("/api/admin/perf-metrics");
    const metrics = (data && data.metrics) || {};
    const rows = Object.entries(metrics);
    if (!rows.length) {
      contentEl.innerHTML =
        '<div class="text-muted small">Пока нет данных. Откройте рабочие разделы и обновите метрики.</div>';
      return;
    }
    rows.sort((a, b) => Number((b[1] && b[1].p95_ms) || 0) - Number((a[1] && a[1].p95_ms) || 0));
    contentEl.innerHTML = `
      <div class="table-responsive">
        <table class="table table-sm align-middle mb-0">
          <thead class="table-light">
            <tr>
              <th>Endpoint</th>
              <th class="text-end">Count</th>
              <th class="text-end">Avg, ms</th>
              <th class="text-end">P95, ms</th>
              <th class="text-end">Max, ms</th>
            </tr>
          </thead>
          <tbody>
            ${rows
              .map(([name, m]) => `
                <tr>
                  <td><code>${escapeHtml(String(name || ""))}</code></td>
                  <td class="text-end">${Number(m.count || 0)}</td>
                  <td class="text-end">${Number(m.avg_ms || 0).toFixed(2)}</td>
                  <td class="text-end">${Number(m.p95_ms || 0).toFixed(2)}</td>
                  <td class="text-end">${Number(m.max_ms || 0).toFixed(2)}</td>
                </tr>
              `)
              .join("")}
          </tbody>
        </table>
      </div>
    `;
    if (statusEl) {
      statusEl.textContent = "Метрики обновлены.";
      statusEl.className = "small mt-2 text-success";
    }
  } catch (e) {
    contentEl.innerHTML = '<div class="text-danger small">Ошибка загрузки метрик.</div>';
    if (statusEl) {
      statusEl.textContent = "Ошибка: " + (e.message || e);
      statusEl.className = "small mt-2 text-danger";
    }
  }
}

let _seansDbPollTimer = null;

function _stopSeansDbPoll() {
  if (_seansDbPollTimer) {
    clearTimeout(_seansDbPollTimer);
    _seansDbPollTimer = null;
  }
}

function _renderSeansDbMigrationStatus(data) {
  const badge = $("seans-db-split-badge");
  const rec = $("seans-db-split-recommend");
  const migrateBtn = $("seans-db-migrate-btn");
  const dryBtn = $("seans-db-dry-run-btn");
  const vacuumBtn = $("seans-db-vacuum-btn");
  const purgeMainBtn = $("seans-db-purge-main-btn");
  const cm = (data.counts_main || {}).seanses;
  const cs = (data.counts_seans || {}).seanses;
  const needsPurge = !!data.needs_purge_main;
  const needsRepair = !!data.needs_repair;
  const dirWarn = (data.data_dir_warning || "").toString().trim();
  setText("seans-db-main-size", `${data.main_size_mb ?? "—"} MB`);
  setText("seans-db-seans-size", `${data.seans_db_size_mb ?? "—"} MB`);
  setText("seans-db-main-count", cm != null ? String(cm) : "—");
  setText("seans-db-seans-count", cs != null ? String(cs) : "—");
  if (badge) {
    if (data.migrated) {
      badge.textContent = "seans.sqlite активна";
      badge.className = "badge rounded-pill bg-success";
    } else if (data.recommend_migrate) {
      badge.textContent = "рекомендуется";
      badge.className = "badge rounded-pill bg-warning text-dark";
    } else {
      badge.textContent = "legacy (main.sqlite)";
      badge.className = "badge rounded-pill bg-secondary";
    }
  }
  if (rec) {
    const showRec =
      dirWarn ||
      (needsPurge && data.migrated) ||
      (data.recommend_migrate && !data.migrated);
    rec.classList.toggle("d-none", !showRec);
    if (dirWarn) {
      rec.textContent = dirWarn;
    } else if (needsPurge && data.migrated) {
      rec.textContent =
        "В main.sqlite остались дубликаты сеансов — перехваты тормозят. Нажмите «Очистить seans из main», затем VACUUM.";
    } else if (data.recommend_migrate && !data.migrated) {
      rec.textContent =
        "Рекомендуется перенести сеансы в отдельный seans.sqlite — main.sqlite станет легче для перехватов.";
    }
  }
  const mig = data.migration || {};
  const running = !!mig.running;
  if (migrateBtn) {
    migrateBtn.disabled = running || (!!data.migrated && !needsPurge && !needsRepair);
  }
  if (dryBtn) dryBtn.disabled = running || !!data.migrated;
  if (vacuumBtn) {
    vacuumBtn.classList.toggle("d-none", !data.migrated);
    vacuumBtn.disabled = running;
  }
  if (purgeMainBtn) {
    purgeMainBtn.classList.toggle("d-none", !needsPurge);
    purgeMainBtn.disabled = running;
  }
}

async function loadSeansDbMigrationPanel() {
  const statusEl = $("seans-db-split-status");
  if (!$("seans-db-split-card")) return;
  try {
    const data = await apiGet("/api/admin/seans-db/status");
    _renderSeansDbMigrationStatus(data);
    const mig = data.migration || {};
    if (statusEl) {
      if (mig.running) {
        statusEl.textContent = mig.message || "Миграция…";
        statusEl.className = "small mt-2 text-muted";
      } else if (mig.error) {
        statusEl.textContent = mig.error;
        statusEl.className = "small mt-2 text-danger";
      } else if (data.migrated) {
        statusEl.textContent = "Сеансы в отдельной БД. Перехваты не блокируются автопоиском.";
        statusEl.className = "small mt-2 text-success";
      } else if (mig.message && mig.phase === "done") {
        statusEl.textContent = mig.message;
        statusEl.className = "small mt-2 text-success";
      } else {
        statusEl.textContent = "";
        statusEl.className = "small mt-2";
      }
    }
    if (mig.running) {
      _seansDbPollTimer = setTimeout(loadSeansDbMigrationPanel, 1500);
    } else {
      _stopSeansDbPoll();
    }
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = "Ошибка загрузки: " + (e.message || e);
      statusEl.className = "small mt-2 text-danger";
    }
  }
}

async function runSeansDbMigration(dryRun) {
  const statusEl = $("seans-db-split-status");
  const migrateBtn = $("seans-db-migrate-btn");
  const dryBtn = $("seans-db-dry-run-btn");
  if (!dryRun) {
    const ok = window.confirm(
      "Перенести все сеансы из main.sqlite в seans.sqlite?\n\n" +
        "Автопоиск будет остановлен. Рекомендуется бэкап main.sqlite.\n" +
        "Операция может занять несколько минут."
    );
    if (!ok) return;
  }
  try {
    if (migrateBtn) migrateBtn.disabled = true;
    if (dryBtn) dryBtn.disabled = true;
    if (statusEl) {
      statusEl.textContent = dryRun ? "Пробный прогон…" : "Запуск миграции…";
      statusEl.className = "small mt-2 text-muted";
    }
    await apiPost("/api/admin/seans-db/migrate", {
      confirm: true,
      dry_run: !!dryRun,
      stop_watch: !dryRun,
    });
    await loadSeansDbMigrationPanel();
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = "Ошибка: " + (e.message || e);
      statusEl.className = "small mt-2 text-danger";
    }
    if (migrateBtn) migrateBtn.disabled = false;
    if (dryBtn) dryBtn.disabled = false;
  }
}

async function purgeMainSeansDuplicates() {
  const statusEl = $("seans-db-split-status");
  const btn = $("seans-db-purge-main-btn");
  if (
    !window.confirm(
      "Удалить таблицы сеансов из main.sqlite?\n\nДанные уже должны быть в seans.sqlite. После этого нажмите VACUUM main."
    )
  ) {
    return;
  }
  try {
    if (btn) btn.disabled = true;
    if (statusEl) {
      statusEl.textContent = "Очистка main.sqlite…";
      statusEl.className = "small mt-2 text-muted";
    }
    const res = await apiPost("/api/admin/seans-db/purge-main", { confirm: true });
    if (statusEl) {
      statusEl.textContent = res.message || "Готово.";
      statusEl.className = "small mt-2 text-success";
    }
    await loadSeansDbMigrationPanel();
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = "Ошибка: " + (e.message || e);
      statusEl.className = "small mt-2 text-danger";
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function vacuumMainAfterSeansMigrate() {
  const statusEl = $("seans-db-split-status");
  const btn = $("seans-db-vacuum-btn");
  if (
    !window.confirm(
      "Выполнить VACUUM на main.sqlite?\n\nУменьшит файл после переноса seans. Может занять несколько минут."
    )
  ) {
    return;
  }
  try {
    if (btn) btn.disabled = true;
    if (statusEl) {
      statusEl.textContent = "VACUUM main.sqlite…";
      statusEl.className = "small mt-2 text-muted";
    }
    const res = await apiPost("/api/admin/seans-db/vacuum-main", { confirm: true });
    if (statusEl) {
      statusEl.textContent = res.message || "VACUUM выполнен.";
      statusEl.className = "small mt-2 text-success";
    }
    await loadSeansDbMigrationPanel();
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = "Ошибка: " + (e.message || e);
      statusEl.className = "small mt-2 text-danger";
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function loadDeployAnnouncePanel() {
  const revEl = $("deploy-announce-current-rev");
  if (!revEl) return;
  try {
    const data = await apiGet("/api/client/deploy-announce");
    revEl.textContent = (data.revision || "").trim() || "—";
    setText(
      "deploy-announce-updated-at",
      (data.updated_at || "").trim() ? `обновлено: ${data.updated_at}` : ""
    );
    setText("deploy-announce-admin-status", "");
  } catch (e) {
    revEl.textContent = "—";
    setText("deploy-announce-updated-at", "");
    setText("deploy-announce-admin-status", `Ошибка загрузки: ${e.message || e}`);
  }
}

function formatUpdateBytes(value) {
  const n = Number(value || 0);
  if (!Number.isFinite(n) || n <= 0) return "";
  return `${(n / (1024 * 1024)).toFixed(1)} МБ`;
}

async function loadHubUpdatesPanel() {
  const select = $("hub-update-package");
  if (!select) return;
  try {
    const data = await apiGet("/api/admin/updates/packages");
    select.replaceChildren();
    const valid = (data.packages || []).filter((item) => item && item.valid);
    if (!valid.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "Нет корректных ZIP в папке Update";
      select.appendChild(option);
    } else {
      for (const item of valid) {
        const option = document.createElement("option");
        option.value = item.name || "";
        option.textContent = `${item.name || ""} — ${formatUpdateBytes(item.size_bytes)}`;
        select.appendChild(option);
      }
    }
    const current = data.current || {};
    const currentEl = $("hub-updates-current");
    if (currentEl) {
      currentEl.textContent = current.revision
        ? `Опубликовано: ${current.revision}`
        : "Нет опубликованной версии";
      currentEl.className = current.revision ? "badge text-bg-success" : "badge text-bg-secondary";
    }
    setText(
      "hub-update-package-help",
      data.directory ? `Папка SERVER: ${data.directory}` : ""
    );
    setText("hub-update-admin-status", "");
  } catch (e) {
    setText("hub-update-admin-status", `Ошибка загрузки пакетов: ${e.message || e}`);
  }
}

async function publishHubUpdate() {
  const packageEl = $("hub-update-package");
  const revisionEl = $("hub-update-revision");
  const titleEl = $("hub-update-title");
  const notesEl = $("hub-update-notes");
  const button = $("hub-update-publish-btn");
  const payload = {
    package: packageEl ? String(packageEl.value || "").trim() : "",
    revision: revisionEl ? String(revisionEl.value || "").trim() : "",
    title: titleEl ? String(titleEl.value || "").trim() : "",
    notes: notesEl ? String(notesEl.value || "").trim() : "",
  };
  if (!payload.package || !payload.revision || !payload.title) {
    setText("hub-update-admin-status", "Выберите пакет и заполните версию и название.");
    return;
  }
  try {
    if (button) button.disabled = true;
    setText("hub-update-admin-status", "Проверка пакета и публикация…");
    const data = await apiPost("/api/admin/updates/publish", payload);
    setText(
      "hub-update-admin-status",
      `Готово. Версия ${data.release?.revision || payload.revision} опубликована для HUB.`
    );
    await loadHubUpdatesPanel();
  } catch (e) {
    setText("hub-update-admin-status", `Ошибка: ${e.message || e}`);
  } finally {
    if (button) button.disabled = false;
  }
}

async function broadcastDeployAnnounce() {
  const ta = $("deploy-announce-message");
  const msg = ta ? String(ta.value || "").trim() : "";
  try {
    setText("deploy-announce-admin-status", "Отправка…");
    await apiPost("/api/admin/deploy-announce", { message: msg });
    await loadDeployAnnouncePanel();
    setText(
      "deploy-announce-admin-status",
      "Готово. У открытых вкладок уведомление появится в течение примерно минуты."
    );
  } catch (e) {
    setText("deploy-announce-admin-status", `Ошибка: ${e.message || e}`);
  }
}

async function clearDeployAnnounce() {
  try {
    setText("deploy-announce-admin-status", "Снятие…");
    await apiPost("/api/admin/deploy-announce", { clear: true });
    await loadDeployAnnouncePanel();
    setText("deploy-announce-admin-status", "Уведомление снято.");
  } catch (e) {
    setText("deploy-announce-admin-status", `Ошибка: ${e.message || e}`);
  }
}

function startSettingsTabLoad() {
  const settingsTab = document.querySelector("#admin-settings-tab");
  if (settingsTab) {
    settingsTab.addEventListener("shown.bs.tab", () => {
      loadChatAccess();
      loadAsrTraining();
      loadPerfMetrics();
      loadDeployAnnouncePanel();
      loadHubUpdatesPanel();
      loadSeansDbMigrationPanel();
    });
    const settingsPane = document.querySelector("#admin-settings-pane");
    if (settingsPane && settingsPane.classList.contains("active")) {
      loadChatAccess();
      loadAsrTraining();
      loadPerfMetrics();
      loadDeployAnnouncePanel();
      loadHubUpdatesPanel();
      loadSeansDbMigrationPanel();
    }
  }
  const saveBtn = $("chat-access-save-btn");
  if (saveBtn) {
    saveBtn.addEventListener("click", () => saveChatAccess());
  }
  const asrTrainingSaveBtn = $("asr-training-save-btn");
  if (asrTrainingSaveBtn) {
    asrTrainingSaveBtn.addEventListener("click", () => saveAsrTraining());
  }
  const dab = $("deploy-announce-broadcast-btn");
  if (dab) dab.addEventListener("click", () => broadcastDeployAnnounce());
  const dac = $("deploy-announce-clear-btn");
  if (dac) dac.addEventListener("click", () => clearDeployAnnounce());
  const hubUpdatePublish = $("hub-update-publish-btn");
  if (hubUpdatePublish) hubUpdatePublish.addEventListener("click", () => publishHubUpdate());
  const hubUpdateRefresh = $("hub-update-refresh-btn");
  if (hubUpdateRefresh) hubUpdateRefresh.addEventListener("click", () => loadHubUpdatesPanel());
  const seansDbMigrateBtn = $("seans-db-migrate-btn");
  if (seansDbMigrateBtn) {
    seansDbMigrateBtn.addEventListener("click", () => runSeansDbMigration(false));
  }
  const seansDbDryBtn = $("seans-db-dry-run-btn");
  if (seansDbDryBtn) {
    seansDbDryBtn.addEventListener("click", () => runSeansDbMigration(true));
  }
  const seansDbRefreshBtn = $("seans-db-refresh-btn");
  if (seansDbRefreshBtn) {
    seansDbRefreshBtn.addEventListener("click", () => loadSeansDbMigrationPanel());
  }
  const seansDbVacuumBtn = $("seans-db-vacuum-btn");
  if (seansDbVacuumBtn) {
    seansDbVacuumBtn.addEventListener("click", () => vacuumMainAfterSeansMigrate());
  }
  const seansDbPurgeMainBtn = $("seans-db-purge-main-btn");
  if (seansDbPurgeMainBtn) {
    seansDbPurgeMainBtn.addEventListener("click", () => purgeMainSeansDuplicates());
  }
  const clearBtn = $("clear-client-name-btn");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => clearClientNameRecords());
  }
  const archiveBtn = $("archive-seanses-btn");
  if (archiveBtn) {
    archiveBtn.addEventListener("click", () => archiveSeansesManual());
  }
  const archiveAllBtn = $("archive-seanses-all-btn");
  if (archiveAllBtn) {
    archiveAllBtn.addEventListener("click", () => archiveSeansesAll());
  }
  const archiveFileBtn = $("archive-file-btn");
  if (archiveFileBtn) {
    archiveFileBtn.addEventListener("click", () => archiveSeansesToFile());
  }
  const keepDaysBtn = $("archive-keep-days-btn");
  if (keepDaysBtn) {
    keepDaysBtn.addEventListener("click", () => archiveKeepLastDays());
  }
  const archiveFileName = $("archive-file-name");
  if (archiveFileName && !archiveFileName.value) {
    archiveFileName.placeholder = defaultArchiveFileName();
  }
  const exportSessionsBtn = $("export-sessions-excel-btn");
  if (exportSessionsBtn) {
    exportSessionsBtn.addEventListener("click", () => exportSessionsToExcel());
  }
  const keepDateInput = $("archive-seanses-keep-date");
  if (keepDateInput && !keepDateInput.value) {
    const d = new Date();
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    keepDateInput.value = `${yyyy}-${mm}-${dd}`;
  }
  const perfBtn = $("perf-metrics-refresh-btn");
  if (perfBtn) {
    perfBtn.addEventListener("click", () => loadPerfMetrics());
  }
}

  function init() {
    startSettingsTabLoad();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
