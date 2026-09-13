(function () {
  "use strict";

  let AI_LAST_REPORT_ID = null;
  let AI_LAST_REPORT_TEXT = "";

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function setAiStatus(text, isError = false) {
    const el = $("ai-status");
    if (!el) return;
    el.textContent = text || "—";
    el.classList.toggle("text-danger", !!isError);
  }

  function setAiBusy(isBusy) {
    [
      "ai-shift-summary-btn",
      "ai-period-report-btn",
      "ai-range-day-btn",
      "ai-range-week-btn",
      "ai-range-month-btn",
    ].forEach((id) => {
      const btn = $(id);
      if (btn) btn.disabled = !!isBusy;
    });
  }

  function formatAiReportHtml(text) {
    const source = String(text || "");
    const urlPlaceholders = [];
    let escaped = escapeHtml(source);
    escaped = escaped.replace(/\/intercepts\?[^\s<]+/g, (url) => {
      const idx = urlPlaceholders.length;
      const href = url.replace(/&amp;/g, "&");
      urlPlaceholders.push(
        `<a class="ai-open-blank-link" href="${href}" target="_blank" rel="noopener"><i class="bi bi-box-arrow-up-right me-1"></i>Открыть бланк</a>`
      );
      return `@@AI_URL_${idx}@@`;
    });
    escaped = escaped
      .replace(/^###\s+(.+)$/gm, '<div class="ai-md-heading ai-md-heading-3">$1</div>')
      .replace(/^##\s+(.+)$/gm, '<div class="ai-md-heading ai-md-heading-2">$1</div>')
      .replace(/^#\s+(.+)$/gm, '<div class="ai-md-heading ai-md-heading-1">$1</div>')
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/^(\s*)-\s+(.+)$/gm, '$1<span class="ai-md-bullet">•</span> $2')
      .replace(/^(\s*)\*\s+(.+)$/gm, '$1<span class="ai-md-bullet">•</span> $2')
      .replace(/\n/g, "<br>");
    return escaped.replace(/@@AI_URL_(\d+)@@/g, (_m, idx) => urlPlaceholders[Number(idx)] || "");
  }

  function setAiResult(text) {
    const el = $("ai-result");
    AI_LAST_REPORT_TEXT = text || "";
    if (el) el.innerHTML = formatAiReportHtml(text || "AI-отчет появится здесь.");
  }

  function initAiDates() {
    const startEl = $("ai-start");
    const endEl = $("ai-end");
    if (!startEl || !endEl) return;
    const now = new Date();
    const start = new Date(now.getTime() - 4 * 60 * 60 * 1000);
    if (!endEl.value) endEl.value = toIsoLocalMin(now);
    if (!startEl.value) startEl.value = toIsoLocalMin(start);
  }

  function setAiPeriodDays(days) {
    const startEl = $("ai-start");
    const endEl = $("ai-end");
    if (!startEl || !endEl) return;
    const count = Math.max(1, Number(days || 1));
    const now = new Date();
    const start = new Date(now.getTime() - count * 24 * 60 * 60 * 1000);
    endEl.value = toIsoLocalMin(now);
    startEl.value = toIsoLocalMin(start);
    setAiStatus(`Период выбран: последние ${count} дн.`);
  }

  async function loadAiReports() {
    const listEl = $("ai-reports-list");
    const modelEl = $("ai-model-info");
    if (!listEl) return [];
    try {
      const data = await apiGet("/api/analysis/ai/reports?limit=20");
      const ai = data.ai || {};
      if (modelEl) modelEl.textContent = `Модель: ${ai.model || "—"} (${ai.provider || "local"})`;
      const reports = Array.isArray(data.reports) ? data.reports : [];
      if (!reports.length) {
        listEl.innerHTML = "AI-отчетов пока нет.";
        return [];
      }
      listEl.innerHTML = reports
        .map((r) => {
          const title = escapeHtml(r.title || `Отчет #${r.id}`);
          const meta = escapeHtml(
            `${r.created_at || ""} · ${r.report_type || ""} · ${r.input_summary || ""}`
          );
          const text = escapeHtml(String(r.report_text || "").slice(0, 900));
          return `<div class="border rounded p-2 mb-2 ai-report-item" data-report-id="${r.id}">
          <div class="d-flex align-items-start justify-content-between gap-2">
            <div>
              <div class="fw-semibold">${title}</div>
              <div class="small text-muted">${meta}</div>
            </div>
            <button type="button" class="btn btn-outline-secondary btn-sm ai-open-report">Открыть</button>
          </div>
          <pre class="small wp-mono mt-2 mb-0 d-none" style="white-space:pre-wrap;">${text}</pre>
        </div>`;
        })
        .join("");
      listEl.querySelectorAll(".ai-open-report").forEach((btn) => {
        btn.addEventListener("click", () => {
          const item = btn.closest(".ai-report-item");
          const reportId = item ? Number(item.getAttribute("data-report-id") || 0) : 0;
          const report = reports.find((r) => Number(r.id) === reportId);
          if (!report) return;
          AI_LAST_REPORT_ID = Number(report.id);
          setAiResult(report.report_text || "");
          const feedbackBtn = $("ai-feedback-btn");
          if (feedbackBtn) feedbackBtn.disabled = false;
        });
      });
      return reports;
    } catch (e) {
      listEl.innerHTML = `<span class="text-danger">Ошибка загрузки истории: ${escapeHtml(e.message || e)}</span>`;
      return [];
    }
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function waitAiJob(jobId, readyLabel) {
    const id = Number(jobId || 0);
    if (!id) throw new Error("Сервер не вернул job_id");
    let delay = 1200;
    for (;;) {
      if (document.hidden) {
        await sleep(Math.max(delay, 10000));
        continue;
      }
      const data = await apiGet(`/api/analysis/ai/jobs/${encodeURIComponent(id)}`);
      const job = data.job || {};
      const status = String(job.status || "").toLowerCase();
      if (status === "completed") {
        const result = job.result || {};
        const reportId = Number(result.report_id || 0);
        const reports = await loadAiReports();
        const report = reportId ? reports.find((r) => Number(r.id) === reportId) : null;
        if (report) {
          AI_LAST_REPORT_ID = Number(report.id);
          setAiResult(report.report_text || "");
          const feedbackBtn = $("ai-feedback-btn");
          if (feedbackBtn) feedbackBtn.disabled = false;
        } else if (result.report_text) {
          AI_LAST_REPORT_ID = reportId || null;
          setAiResult(result.report_text || "");
        }
        setAiStatus(readyLabel || "Отчет готов.");
        return job;
      }
      if (status === "failed" || status === "cancelled") {
        throw new Error(job.error_text || "AI-задача завершилась с ошибкой");
      }
      setAiStatus(status === "pending" ? "AI-задача в очереди..." : "AI-задача выполняется...");
      await sleep(delay);
      delay = Math.min(5000, Math.round(delay * 1.25));
    }
  }

  async function runAiShiftSummary() {
    const sessionEl = $("ai-session-id");
    const payload = {};
    const sessionId = sessionEl ? String(sessionEl.value || "").trim() : "";
    if (sessionId) payload.session_id = Number(sessionId);
    try {
      setAiBusy(true);
      setAiStatus("AI-задача ставится в очередь...");
      setAiResult("Сводка формируется в фоне. Можно продолжать работу в портале.");
      const data = await apiPost("/api/analysis/ai/shift-summary", payload);
      await waitAiJob(data.job_id, "Сводка готова.");
    } catch (e) {
      setAiStatus("Ошибка: " + (e.message || e), true);
      setAiResult("");
    } finally {
      setAiBusy(false);
    }
  }

  async function runAiPeriodReport() {
    const start = $("ai-start") ? String($("ai-start").value || "").trim() : "";
    const end = $("ai-end") ? String($("ai-end").value || "").trim() : "";
    if (!start || !end) {
      setAiStatus("Укажите начало и конец периода.", true);
      return;
    }
    try {
      setAiBusy(true);
      setAiStatus("AI-задача ставится в очередь...");
      setAiResult("Полный отчет формируется в фоне. Можно переключаться между вкладками.");
      const data = await apiPost("/api/analysis/ai/period-report", { start, end });
      await waitAiJob(data.job_id, "Отчет готов.");
    } catch (e) {
      setAiStatus("Ошибка: " + (e.message || e), true);
      setAiResult("");
    } finally {
      setAiBusy(false);
    }
  }

  async function sendAiFeedback() {
    if (!AI_LAST_REPORT_ID) return;
    const rating = $("ai-feedback-rating")
      ? String($("ai-feedback-rating").value || "").trim()
      : "";
    const comment = $("ai-feedback-comment")
      ? String($("ai-feedback-comment").value || "").trim()
      : "";
    const correctedText =
      AI_LAST_REPORT_TEXT ||
      ($("ai-result") ? String($("ai-result").textContent || "") : "");
    try {
      await apiPost("/api/analysis/ai/feedback", {
        report_id: AI_LAST_REPORT_ID,
        rating,
        comment,
        corrected_text: correctedText,
      });
      setAiStatus("Feedback сохранен.");
    } catch (e) {
      setAiStatus("Ошибка feedback: " + (e.message || e), true);
    }
  }

  function boot() {
    if (!window.AnalysisRuntime?.isModule("ai")) return;
    window.__ANALYSIS_ACTIVE_BUNDLE__ = "ai";
    initAiDates();
    const aiShiftBtn = $("ai-shift-summary-btn");
    const aiPeriodBtn = $("ai-period-report-btn");
    const aiRefreshBtn = $("ai-refresh-reports-btn");
    const aiFeedbackBtn = $("ai-feedback-btn");
    if (aiShiftBtn) aiShiftBtn.addEventListener("click", runAiShiftSummary);
    if (aiPeriodBtn) aiPeriodBtn.addEventListener("click", runAiPeriodReport);
    if ($("ai-range-day-btn"))
      $("ai-range-day-btn").addEventListener("click", () => setAiPeriodDays(1));
    if ($("ai-range-week-btn"))
      $("ai-range-week-btn").addEventListener("click", () => setAiPeriodDays(7));
    if ($("ai-range-month-btn"))
      $("ai-range-month-btn").addEventListener("click", () => setAiPeriodDays(30));
    if (aiRefreshBtn) aiRefreshBtn.addEventListener("click", loadAiReports);
    if (aiFeedbackBtn) aiFeedbackBtn.addEventListener("click", sendAiFeedback);
    loadAiReports();
  }

  window.AnalysisRuntime?.onReady(boot);
})();
