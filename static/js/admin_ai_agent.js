/* eslint-disable no-undef */
(function () {
  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  async function loadAiAgentActions() {
    const limit = document.getElementById("ai-agent-limit")?.value || "100";
    const tool = document.getElementById("ai-agent-tool-filter")?.value?.trim() || "";
    let url = `/api/admin/ai-agent/actions?limit=${encodeURIComponent(String(limit))}`;
    if (tool) url += `&tool=${encodeURIComponent(tool)}`;
    const data = await apiGet(url);
    const tbody = document.getElementById("ai-agent-actions-tbody");
    if (!tbody) return;
    tbody.textContent = "";
    (data.actions || []).forEach((a) => {
      const tr = document.createElement("tr");
      const argsStr = JSON.stringify(a.args || {}).slice(0, 400);
      const resStr = JSON.stringify(a.result || {}).slice(0, 300);
      const cells = [a.created_at, a.username, a.tool, (a.goal || "").slice(0, 120), argsStr, resStr];
      cells.forEach((val) => {
        const td = document.createElement("td");
        td.className = "small align-top";
        td.textContent = val != null ? String(val) : "";
        if (String(val).length > 200) td.style.maxWidth = "280px";
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  }

  async function loadWatch() {
    const el = document.getElementById("ai-agent-watch-body");
    if (!el) return;
    el.textContent = "Загрузка...";
    try {
      const data = await apiGet("/api/admin/ai-agent/watch-status");
      const snap = data.snapshot || {};
      const ms = snap.main_db_stats || {};
      const lines = [
        `Сгенерировано: ${snap.generated_at || "—"}`,
        `Событий в журнале агента за 24ч: ${snap.actions_total_24h ?? "—"}`,
        `По инструментам: ${JSON.stringify(snap.actions_by_tool_24h || {}, null, 0)}`,
        `main.sqlite: ${snap.main_db || "—"}`,
        `Сеансы с полуночи: ${ms.seanses_since_midnight ?? "—"}`,
        `Строк в unit: ${ms.unit_rows ?? "—"}`,
        `Ручные привязки unit: ${ms.unit_manual_rows ?? "—"}`,
      ];
      if (ms.error) lines.push(`Ошибка main DB: ${ms.error}`);
      if (data.persisted && data.persisted.last_run_at) {
        lines.push(`Файл снимка (последняя запись): ${data.persisted.last_run_at}`);
      }
      el.innerHTML = lines.map((l) => `<div class="mb-1 small">${escapeHtml(l)}</div>`).join("");
    } catch (e) {
      el.textContent = e.message || String(e);
    }
  }

  async function runWatch() {
    const el = document.getElementById("ai-agent-watch-body");
    if (el) el.textContent = "Сохраняю снимок...";
    try {
      await apiPost("/api/admin/ai-agent/watch-run", {});
      await loadWatch();
    } catch (e) {
      if (el) el.textContent = e.message || String(e);
    }
  }

  function formatPct(x) {
    if (x == null || Number.isNaN(x)) return "—";
    return `${(x * 100).toFixed(1)}%`;
  }

  async function loadChatFeedback() {
    const summaryEl = document.getElementById("ai-agent-feedback-summary");
    const tbody = document.getElementById("ai-agent-feedback-tbody");
    const lim = document.getElementById("ai-agent-feedback-limit")?.value || "50";
    if (summaryEl) summaryEl.textContent = "Загрузка...";
    if (tbody) {
      tbody.textContent = "";
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 6;
      td.className = "text-muted small";
      td.textContent = "Загрузка...";
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
    try {
      const data = await apiGet(
        `/api/admin/ai-agent/chat-feedback?limit=${encodeURIComponent(String(lim))}`
      );
      const st = data.stats || {};
      if (summaryEl) {
        const helpful = st.helpful_ratio;
        const net = st.net_score;
        const parts = [
          `<div class="col-6 col-md-4 col-lg-2"><div class="border rounded p-2 h-100"><div class="text-muted">Всего оценок</div><div class="fw-bold">${st.total_ratings ?? 0}</div></div></div>`,
          `<div class="col-6 col-md-4 col-lg-2"><div class="border rounded p-2 h-100"><div class="text-muted"><i class="bi bi-hand-thumbs-up text-success"></i> Полезен</div><div class="fw-bold text-success">${st.thumbs_up ?? 0}</div></div></div>`,
          `<div class="col-6 col-md-4 col-lg-2"><div class="border rounded p-2 h-100"><div class="text-muted"><i class="bi bi-hand-thumbs-down text-danger"></i> Не полезен</div><div class="fw-bold text-danger">${st.thumbs_down ?? 0}</div></div></div>`,
          `<div class="col-6 col-md-4 col-lg-2"><div class="border rounded p-2 h-100"><div class="text-muted">Баланс (±)</div><div class="fw-bold">${net != null ? net : "—"}</div></div></div>`,
          `<div class="col-6 col-md-4 col-lg-2"><div class="border rounded p-2 h-100"><div class="text-muted">Доля «полезен»</div><div class="fw-bold">${formatPct(helpful)}</div></div></div>`,
          `<div class="col-6 col-md-4 col-lg-2"><div class="border rounded p-2 h-100"><div class="text-muted">Уник. сообщ.</div><div class="fw-bold">${st.unique_messages_rated ?? 0}</div><div class="text-muted" style="font-size:0.75rem">оценок от ${st.unique_voters ?? 0} польз.</div></div></div>`,
        ];
        summaryEl.innerHTML = `<div class="row g-2">${parts.join("")}</div>`;
      }
      if (tbody) {
        tbody.textContent = "";
        const rows = data.recent || [];
        if (rows.length === 0) {
          const tr = document.createElement("tr");
          const td = document.createElement("td");
          td.colSpan = 6;
          td.className = "text-muted small";
          td.textContent = "Пока нет оценок";
          tr.appendChild(td);
          tbody.appendChild(tr);
        } else {
          rows.forEach((a) => {
            const tr = document.createElement("tr");
            const who = a.voter_callsign || a.voter_username || a.user_id;
            const mark =
              a.rating === 1
                ? "полезен"
                : a.rating === -1
                  ? "не полезен"
                  : String(a.rating);
            const cells = [
              a.updated_at,
              mark,
              who,
              a.message_id,
              (a.message_preview || "").slice(0, 220),
              (a.comment || "").slice(0, 200),
            ];
            cells.forEach((val) => {
              const td = document.createElement("td");
              td.className = "small align-top";
              td.textContent = val != null ? String(val) : "";
              if (String(val).length > 80) td.style.maxWidth = "280px";
              tr.appendChild(td);
            });
            tbody.appendChild(tr);
          });
        }
      }
    } catch (e) {
      if (summaryEl) summaryEl.textContent = e.message || String(e);
      if (tbody) {
        tbody.textContent = "";
        const tr = document.createElement("tr");
        const td = document.createElement("td");
        td.colSpan = 6;
        td.className = "text-danger small";
        td.textContent = e.message || String(e);
        tr.appendChild(td);
        tbody.appendChild(tr);
      }
    }
  }

  async function loadLlmTrainingStats() {
    const el = document.getElementById("ai-llm-training-stats");
    if (!el) return;
    el.textContent = "Загрузка…";
    try {
      const data = await apiGet("/api/admin/ai-agent/llm-training-stats");
      const t = data.total_pairs ?? 0;
      const p = data.positive_rated_pairs ?? 0;
      const n = data.negative_preference_hints ?? 0;
      el.textContent = `Пар в датасете: ${t}; «полезен»: ${p}; записей «не полезен» (для DPO): ${n}.`;
    } catch (e) {
      el.textContent = e.message || String(e);
    }
  }

  function downloadLlmSft() {
    const onlyRated = document.getElementById("ai-llm-only-rated")?.checked;
    const onlyPos = document.getElementById("ai-llm-only-positive")?.checked;
    let u = "/api/admin/ai-agent/llm-training-export?";
    u += "only_rated=" + (onlyRated ? "1" : "0");
    u += "&only_positive=" + (onlyPos ? "1" : "0");
    window.location.assign(u);
  }

  function downloadLlmPreferenceHints() {
    window.location.assign("/api/admin/ai-agent/llm-preference-hints-export");
  }

  document.getElementById("ai-llm-export-btn")?.addEventListener("click", downloadLlmSft);
  document.getElementById("ai-llm-pref-export-btn")?.addEventListener("click", downloadLlmPreferenceHints);
  document.getElementById("ai-agent-refresh-btn")?.addEventListener("click", () => {
    loadAiAgentActions();
    loadWatch();
    loadChatFeedback();
    loadLlmTrainingStats();
  });
  document.getElementById("ai-agent-feedback-refresh-btn")?.addEventListener("click", () => {
    loadChatFeedback();
  });
  document.getElementById("ai-agent-watch-btn")?.addEventListener("click", runWatch);

  const tab = document.getElementById("admin-ai-agent-tab");
  if (tab) {
    tab.addEventListener("shown.bs.tab", () => {
      loadAiAgentActions();
      loadWatch();
      loadChatFeedback();
      loadLlmTrainingStats();
    });
  }
})();
