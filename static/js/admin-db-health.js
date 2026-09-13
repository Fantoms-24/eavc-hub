(function () {
  "use strict";

function dbHealthSeverityClass(sev) {
  const s = String(sev || "info");
  if (s === "error") return "border-danger";
  if (s === "warning") return "border-warning";
  return "border-info";
}

/** Список AES key id: элементы из newKeySet подсвечиваются (новые после якоря). */
function dbHealthRenderAesKeyList(keys, newKeySet) {
  const arr = keys || [];
  if (!arr.length) return "—";
  const nk = newKeySet || new Set();
  return arr
    .map((k) => {
      const s = String(k);
      const cls = nk.has(s) ? "text-danger fw-semibold" : "";
      return `<code class="${cls}">${escapeHtml(s)}</code>`;
    })
    .join(", ");
}

function renderDbHealthReport(data) {
  const sumEl = $("db-health-summary");
  const findEl = $("db-health-findings");
  const corrEl = $("db-health-correspondent");
  const s = data.summary || {};
  if (sumEl) {
    sumEl.innerHTML = `
      <div class="d-flex flex-wrap gap-3">
        <span><strong>Таблица сеансов:</strong> <code>${escapeHtml(String(data.seanses_table || "—"))}</code></span>
        <span><strong>Таблица unit:</strong> <code>${escapeHtml(String(data.unit_table || "—"))}</code></span>
        <span><strong>Строк в seanses:</strong> ${Number(s.seanses_count ?? 0)}</span>
        <span><strong>В unit:</strong> ${s.unit_count != null ? Number(s.unit_count) : "—"}</span>
      </div>
      <div class="mt-1 text-muted">Период: ${escapeHtml(String(s.seanses_date_min || "—"))} — ${escapeHtml(String(s.seanses_date_max || "—"))}</div>
    `;
  }
  const findings = data.findings || [];
  if (findEl) {
    findEl.innerHTML = findings
      .map((f) => {
        const rows = f.rows || [];
        const showTable = rows.length > 0;
        const keys = showTable ? Object.keys(rows[0]) : [];
        const tableHtml = showTable
          ? `<div class="table-responsive mt-2"><table class="table table-sm table-bordered mb-0"><thead><tr>${keys
              .map((k) => `<th>${escapeHtml(k)}</th>`)
              .join("")}</tr></thead><tbody>${rows
              .map(
                (r) =>
                  `<tr>${keys
                    .map((k) => `<td class="small">${escapeHtml(String(r[k] ?? ""))}</td>`)
                    .join("")}</tr>`
              )
              .join("")}</tbody></table>
          ${
            Number(f.row_count || 0) > rows.length
              ? `<div class="small text-muted mt-1">Показаны первые ${rows.length} из ${f.row_count}.</div>`
              : ""
          }
          </div>`
          : "";
        return `<div class="card mb-3 border-start border-4 ${dbHealthSeverityClass(f.severity)}">
          <div class="card-body p-3">
            <div class="fw-semibold">${escapeHtml(f.title || "")}</div>
            <div class="small text-muted mt-1">${escapeHtml(f.explanation || "")}</div>
            ${f.row_count ? `<div class="small mt-1">Записей: <strong>${f.row_count}</strong></div>` : ""}
            ${tableHtml}
          </div>
        </div>`;
      })
      .join("");
  }
  const c = data.correspondent;
  if (corrEl) {
    if (!c) {
      corrEl.innerHTML = "";
    } else if (c.error) {
      corrEl.innerHTML = `<div class="alert alert-danger py-2 small">Ошибка по ID: ${escapeHtml(c.error)}</div>`;
    } else {
      const pairs = c.pairs || [];
      const nets = c.networks_matching || [];
      const follow = c.aes_followup || [];
      const followSection =
        follow.length > 0
          ? `<div class="mb-4">
          <div class="fw-semibold small mb-1">Каналы, где был ID: сутки / окно и AES по <strong>всем</strong> сеансам на частоте+группе</div>
          <div class="small text-muted mb-2">
            Якорь — <strong>первое</strong> появление выбранного ID на паре «частота + группа».
            По умолчанию берутся <strong>календарные сутки</strong> этого дня: в выборку попадают <strong>все корреспонденты</strong> на том же канале за этот день (не только выбранный ID).
            До <strong>первого выхода</strong> выбранного ID на канале и <strong>с этого момента</strong> (в том же окне) показываются списки <strong>непустых</strong> AES key id по всем сеансам на частоте+группе.
            Ключи, которые появились только <strong>после</strong> выхода ID, выделяются <span class="text-danger fw-semibold">красным</span> (не вся строка). Хронология: те же новые ключи подсвечены в сегментах.
          </div>
          <div class="table-responsive"><table class="table table-sm table-bordered align-middle">
            <thead class="table-light"><tr>
              <th>Частота</th><th>Группа</th><th>Период</th><th>Первый выход ID</th><th>AES у этого ID</th>
              <th class="text-end">Сеансов</th><th>С ключом / без</th><th>Ключи: до ID / с появления ID<br/><span class="fw-normal text-muted">(новые — красным)</span></th>
              <th class="text-center">Состояний</th><th>Хронология на канале</th>
            </tr></thead><tbody>${follow
              .map((it) => {
                if (it.error) {
                  return `<tr class="table-warning"><td class="small" colspan="10">${escapeHtml(String(it.error))}</td></tr>`;
                }
                const newKeySet = new Set(
                  (it.nonempty_keys_new_after_first || []).map((k) => String(k))
                );
                const tim = (it.timeline || [])
                  .map((s) => {
                    const ak = String(s.aes_key ?? "");
                    const codeCls =
                      ak && ak !== "(нет ключа)" && newKeySet.has(ak)
                        ? "text-danger fw-semibold"
                        : "";
                    return `<div class="small mb-1"><code class="${codeCls}">${escapeHtml(ak)}</code> ${escapeHtml(
                      String(s.from_dt ?? "")
                    )} → ${escapeHtml(String(s.to_dt ?? ""))} <span class="text-muted">(${Number(s.row_count || 0)})</span>${
                      s.includes_correspondent ? ' <span class="badge text-bg-secondary">выбранный ID</span>' : ""
                    }</div>`;
                  })
                  .join("");
                const lim = it.window_hits_row_limit
                  ? `<div class="text-warning small mt-1">Лимит строк в выборке — картина может быть неполной.</div>`
                  : "";
                const period = `${escapeHtml(String(it.window_label ?? ""))}<div class="text-muted small">${escapeHtml(String(it.window_start_dt ?? ""))} — ${escapeHtml(String(it.window_end_dt ?? ""))}</div>`;
                const beforeList = dbHealthRenderAesKeyList(it.nonempty_keys_before_first, new Set());
                const fromList = dbHealthRenderAesKeyList(it.nonempty_keys_from_first_onward, newKeySet);
                const allDistinct = (it.nonempty_keys_distinct || []).length
                  ? `<div class="text-muted small mt-1">Все непустые в окне (${Number(it.nonempty_keys_count ?? 0)}): ${(it.nonempty_keys_distinct || [])
                      .map((k) => `<code>${escapeHtml(String(k))}</code>`)
                      .join(", ")}</div>`
                  : "";
                const emptyNote = it.only_empty_aes_in_window
                  ? `<div class="badge text-bg-secondary mt-1">В окне нет заполненного aes_key</div>`
                  : "";
                return `<tr>
                  <td class="small">${escapeHtml(String(it.frequency ?? ""))}</td>
                  <td class="small">${escapeHtml(String(it.group_ ?? ""))}</td>
                  <td class="small">${period}</td>
                  <td class="small">${escapeHtml(String(it.first_correspondent_dt ?? ""))}</td>
                  <td class="small"><code>${escapeHtml(String(it.aes_key_when_correspondent_first ?? ""))}</code></td>
                  <td class="text-end">${Number(it.channel_rows_in_window ?? 0)}</td>
                  <td class="small">${Number(it.rows_with_aes_key ?? 0)} / ${Number(it.rows_missing_aes_key ?? 0)}${emptyNote}</td>
                  <td class="small"><div class="mb-1"><span class="text-muted">До ID:</span> ${beforeList}</div><div><span class="text-muted">С ID:</span> ${fromList}</div>${allDistinct}</td>
                  <td class="text-center fw-semibold">${Number(it.distinct_keys_in_window ?? 0)}</td>
                  <td class="small">${tim || "—"}<div class="text-muted small mt-1">Порядок: <code>${escapeHtml(String(it.keys_sequence ?? ""))}</code></div>${lim}</td>
                </tr>`;
              })
              .join("")}</tbody></table></div>
        </div>`
          : "";
      const rotations = c.aes_key_rotations || [];
      const aesDetail = c.aes_keys_detail || [];
      const rotAlert =
        rotations.length > 0
          ? `<div class="alert alert-warning py-2 small mb-3">
          <div class="fw-semibold mb-1">Зафиксирована смена AES key id на канале (несколько разных ключей для той же частоты и группы)</div>
          <div class="table-responsive mb-0"><table class="table table-sm mb-0"><thead><tr>
            <th>Частота</th><th>Группа</th><th>Разных ключей</th><th>Какие key id встречались</th>
          </tr></thead><tbody>${rotations
            .map(
              (r) =>
                `<tr><td class="small">${escapeHtml(String(r.frequency ?? ""))}</td><td class="small">${escapeHtml(
                  String(r.group_ ?? "")
                )}</td><td>${Number(r.key_variants || 0)}</td><td class="small"><code>${escapeHtml(
                  String(r.aes_keys_seen ?? "")
                )}</code></td></tr>`
            )
            .join("")}</tbody></table></div>
        </div>`
          : "";
      const aesDetailTable =
        aesDetail.length > 0
          ? `<div class="fw-semibold small mb-1">AES key id по каналам: первый и последний сеанс на каждом ключе</div>
        <div class="table-responsive mb-3"><table class="table table-sm"><thead><tr>
          <th>Частота</th><th>Группа</th><th>AES key id</th><th>Сеансов</th><th>Первый на ключе</th><th>Последний на ключе</th>
        </tr></thead><tbody>${aesDetail
          .map(
            (row) =>
              `<tr><td class="small">${escapeHtml(String(row.frequency ?? ""))}</td><td class="small">${escapeHtml(
                String(row.group_ ?? "")
              )}</td><td class="small"><code>${escapeHtml(String(row.aes_key ?? ""))}</code></td><td>${Number(
                row.sessions || 0
              )}</td><td class="small">${escapeHtml(String(row.first_dt ?? ""))}</td><td class="small">${escapeHtml(
                String(row.last_dt ?? "")
              )}</td></tr>`
          )
          .join("")}</tbody></table>
        ${
          c.aes_keys_detail_truncated
            ? `<div class="text-muted small">Показаны первые строки (лимит выборки). Полная картина по каналам — в SQL или увеличением лимита на сервере.</div>`
            : ""
        }</div>`
          : "";
      corrEl.innerHTML = `
        <h3 class="h6 fw-bold">Корреспондент ID <code>${escapeHtml(String(c.id || ""))}</code></h3>
        <div class="small mb-2">Всего сеансов в БД: <strong>${Number(c.total_sessions || 0)}</strong></div>
        ${c.note ? `<div class="alert alert-info py-2 small">${escapeHtml(c.note)}</div>` : ""}
        ${followSection}
        ${rotAlert}
        <div class="fw-semibold small mb-1">Пары частота / группа в seanses</div>
        <div class="small text-muted mb-1">Колонка «Разн. AES» — число <strong>различных</strong> значений AES key id на этом канале для данного ID.</div>
        <div class="table-responsive mb-3">${
          pairs.length
            ? `<table class="table table-sm"><thead><tr>
          <th>Частота</th><th>Группа</th><th>Сеансов</th><th>Разн. AES</th><th>Первый</th><th>Последний</th>
        </tr></thead><tbody>${pairs
          .map(
            (p) =>
              `<tr><td class="small">${escapeHtml(String(p.frequency ?? ""))}</td><td class="small">${escapeHtml(
                String(p.group_ ?? "")
              )}</td><td>${Number(p.sessions || 0)}</td><td>${Number(p.aes_key_variants ?? 0)}</td><td class="small">${escapeHtml(
                String(p.first_dt ?? "")
              )}</td><td class="small">${escapeHtml(String(p.last_dt ?? ""))}</td></tr>`
          )
          .join("")}</tbody></table>`
            : `<div class="text-muted small">Нет строк (проверьте ID).</div>`
        }</div>
        ${aesDetailTable}
        <div class="fw-semibold small mb-1">Имена в unit, в анализ которых попадёт этот ID</div>
        <div class="small ${nets.length ? "" : "text-muted"}">${
        nets.length
          ? `<ul class="mb-0">${nets.map((n) => `<li><code>${escapeHtml(String(n))}</code></li>`).join("")}</ul>`
          : "—"
      }${
        c.networks_matching_truncated
          ? `<div class="text-warning small mt-1">Список обрезан лимитом; ориентируйтесь на пары каналов выше.</div>`
          : ""
      }</div>`;
    }
  }
}

async function runDbHealthCheck() {
  const sel = $("db-health-db-select");
  const idInput = $("db-health-correspondent-id");
  const stEl = $("db-health-status");
  const db = String(sel?.value || "main.sqlite").trim();
  const cid = String(idInput?.value || "").trim();
  if (stEl) {
    stEl.textContent = "Проверка…";
    stEl.className = "small mt-2 text-muted";
  }
  try {
    let url = `/api/admin/db-health?db=${encodeURIComponent(db)}`;
    if (cid) url += `&correspondent_id=${encodeURIComponent(cid)}`;
    const modeEl = $("db-health-followup-mode");
    const mode = String(modeEl?.value || "calendar_day").trim();
    if (mode === "rolling" || mode === "calendar_day") {
      url += `&aes_followup_mode=${encodeURIComponent(mode)}`;
    }
    const fhRaw = parseInt(String($("db-health-followup-hours")?.value || "24"), 10);
    if (!Number.isNaN(fhRaw) && fhRaw >= 1 && fhRaw <= 168) {
      url += `&aes_followup_hours=${encodeURIComponent(String(fhRaw))}`;
    }
    const ahRaw = parseInt(String($("db-health-after-id-hours")?.value || "0"), 10);
    if (!Number.isNaN(ahRaw) && ahRaw >= 0 && ahRaw <= 168) {
      url += `&aes_after_id_hours=${encodeURIComponent(String(ahRaw))}`;
    }
    const data = await apiGet(url);
    renderDbHealthReport(data);
    if (stEl) {
      stEl.textContent = "Готово.";
      stEl.className = "small mt-2 text-success";
    }
  } catch (e) {
    if (stEl) {
      stEl.textContent = "Ошибка: " + (e.message || e);
      stEl.className = "small mt-2 text-danger";
    }
  }
}

function renderMultiChannelDayReport(data) {
  const el = $("db-multi-channel-results");
  if (!el) return;
  const meta = `<div class="small text-muted mb-2">БД: <code>${escapeHtml(String(data.db || ""))}</code>, таблица: <code>${escapeHtml(
    String(data.seanses_table || "—")
  )}</code>. Сутки: <code>${escapeHtml(String(data.day_start_dt || ""))}</code> — <code>${escapeHtml(
    String(data.day_end_excl_dt || "")
  )}</code> (верхняя граница не включается).</div>`;
  if (data.message && !(data.items && data.items.length)) {
    el.innerHTML = `${meta}<div class="alert alert-info py-2 small mb-0">${escapeHtml(data.message)}</div>`;
    return;
  }
  const items = data.items || [];
  if (!items.length) {
    el.innerHTML = `${meta}<div class="text-muted small">Нет данных.</div>`;
    return;
  }
  const trunc = data.ids_truncated
    ? `<div class="alert alert-warning py-2 small">Показаны первые ${items.length} ID; в БД может быть больше.</div>`
    : "";
  const rows = items
    .map((it) => {
      const pairs = (it.pairs || [])
        .map(
          (p) =>
            `<tr><td class="small"><code>${escapeHtml(String(p.frequency ?? ""))}</code></td><td class="small"><code>${escapeHtml(
              String(p.group_ ?? "")
            )}</code></td><td class="text-end">${Number(p.sessions || 0)}</td><td class="small">${escapeHtml(
              String(p.first_dt ?? "")
            )}</td><td class="small">${escapeHtml(String(p.last_dt ?? ""))}</td></tr>`
        )
        .join("");
      return `<tr class="table-light"><td class="small fw-semibold" colspan="5"><code>${escapeHtml(
        String(it.id ?? "")
      )}</code> — каналов: ${Number(it.channel_count || 0)}, сеансов за день: ${Number(it.sessions || 0)}</td></tr>${pairs}`;
    })
    .join("");
  el.innerHTML = `${meta}${trunc}
    <div class="table-responsive"><table class="table table-sm table-bordered align-middle mb-0">
      <thead class="table-light"><tr>
        <th>Частота</th><th>Группа</th><th class="text-end">Сеансов</th><th>Первый</th><th>Последний</th>
      </tr></thead><tbody>${rows}</tbody></table></div>`;
}

async function runMultiChannelDayReport() {
  const sel = $("db-multi-channel-db-select");
  const dateEl = $("db-multi-channel-date");
  const onlyEl = $("db-multi-channel-only-id");
  const stEl = $("db-multi-channel-status");
  const outEl = $("db-multi-channel-results");
  const db = String(sel?.value || "main.sqlite").trim();
  const dateS = String(dateEl?.value || "").trim();
  const onlyId = String(onlyEl?.value || "").trim();
  if (outEl) outEl.innerHTML = "";
  if (!dateS) {
    if (stEl) {
      stEl.textContent = "Укажите дату.";
      stEl.className = "small text-danger";
    }
    return;
  }
  if (stEl) {
    stEl.textContent = "Загрузка…";
    stEl.className = "small text-muted";
  }
  try {
    let url = `/api/admin/seanses-multi-channel-day?db=${encodeURIComponent(db)}&date=${encodeURIComponent(dateS)}`;
    if (onlyId) url += `&correspondent_id=${encodeURIComponent(onlyId)}`;
    const data = await apiGet(url);
    renderMultiChannelDayReport(data);
    if (stEl) {
      const n = Number(data.multi_channel_id_count ?? 0);
      stEl.textContent =
        n > 0
          ? `Найдено ID с несколькими каналами: ${n}${data.only_id_filter ? " (фильтр по ID)" : ""}.`
          : "Готово.";
      stEl.className = n > 0 ? "small text-success" : "small text-muted";
    }
  } catch (e) {
    if (stEl) {
      stEl.textContent = "Ошибка: " + (e.message || e);
      stEl.className = "small text-danger";
    }
  }
}

function startDbHealthTabLoad() {
  const tab = document.querySelector("#admin-db-health-tab");
  const btn = $("db-health-refresh-btn");
  const mcb = $("db-multi-channel-btn");
  if (btn) btn.addEventListener("click", () => runDbHealthCheck());
  if (mcb) mcb.addEventListener("click", () => runMultiChannelDayReport());
  if (tab) {
    tab.addEventListener("shown.bs.tab", () => {
      populateDbHealthSelect();
      const mcd = $("db-multi-channel-date");
      if (mcd && !mcd.value) {
        const d = new Date();
        const yyyy = d.getFullYear();
        const mm = String(d.getMonth() + 1).padStart(2, "0");
        const dd = String(d.getDate()).padStart(2, "0");
        mcd.value = `${yyyy}-${mm}-${dd}`;
      }
    });
  }
}


  function init() {
    startDbHealthTabLoad();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
