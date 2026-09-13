(function () {
  "use strict";

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function highlightQueryInText(text, query) {
    if (!query || !text) return escapeHtml(String(text || ""));
    const escaped = escapeHtml(String(text));
    const q = String(query).trim();
    if (!q) return escaped;
    const re = new RegExp("(" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi");
    return escaped.replace(re, "<mark>$1</mark>");
  }

  function setBlanksSearchStatus(text, isError) {
    const statusEl = $("blanks-search-status");
    if (!statusEl) return;
    statusEl.textContent = text || "—";
    statusEl.classList.toggle("bs2__status--error", !!isError);
  }

  function renderBlanksSearchEmpty(kind, query) {
    if (kind === "no-results") {
      return `<div class="bs2-empty">
      <span class="bs2-empty__icon" aria-hidden="true"><i class="bi bi-search"></i></span>
      <p class="bs2-empty__title">Ничего не найдено</p>
      <p class="bs2-empty__sub">По запросу «${escapeHtml(query || "")}» совпадений в бланках нет. Попробуйте другие слова.</p>
    </div>`;
    }
    return `<div class="bs2-empty">
    <span class="bs2-empty__icon" aria-hidden="true"><i class="bi bi-journal-text"></i></span>
    <p class="bs2-empty__title">Результаты появятся здесь</p>
    <p class="bs2-empty__sub">Введите запрос и нажмите «Искать» или Enter</p>
  </div>`;
  }

  function renderBlanksSearchResults(results, query, container) {
    if (!container) return;
    if (!results.length) {
      container.innerHTML = renderBlanksSearchEmpty("no-results", query);
      return;
    }
    const parts = [];
    for (const r of results) {
      const freq = escapeHtml(String(r.frequency || "—"));
      const group = escapeHtml(String(r.group_code || "—"));
      const unit = String(r.unit_name || "").trim();
      const pos = String(r.position_name || "").trim();
      const started = r.started_at ? fmtLocalDateTime(r.started_at) : "—";
      const ended = r.ended_at ? fmtLocalDateTime(r.ended_at) : "—";
      const contentHtml = highlightQueryInText(r.content || "", query);
      const tags = [];
      if (unit) tags.push(`<span class="bs2-hit__tag">${escapeHtml(unit)}</span>`);
      if (pos) tags.push(`<span class="bs2-hit__tag">${escapeHtml(pos)}</span>`);
      parts.push(
        `<article class="bs2-hit">
        <header class="bs2-hit__meta">
          <span class="bs2-hit__pair">${freq} · ${group}</span>
          ${tags.join("")}
          <time class="bs2-hit__time" datetime="">${escapeHtml(started)} — ${escapeHtml(ended)}</time>
        </header>
        <pre class="bs2-hit__body">${contentHtml}</pre>
      </article>`
      );
    }
    container.innerHTML = parts.join("");
  }

  async function runBlanksSearch() {
    const queryEl = $("blanks-search-query");
    const resultsEl = $("blanks-search-results");
    const q = queryEl ? String(queryEl.value || "").trim() : "";
    if (!q) {
      setBlanksSearchStatus("Введите ключевые слова.", false);
      if (resultsEl) resultsEl.innerHTML = renderBlanksSearchEmpty("idle");
      return;
    }
    const params = new URLSearchParams();
    params.set("q", q);
    try {
      setBlanksSearchStatus("Поиск…", false);
      if (resultsEl) resultsEl.innerHTML = "";
      const data = await apiGet("/api/analysis/intercepts-search?" + params.toString());
      if (!data.ok) throw new Error(data.error || "Ошибка запроса");
      const results = Array.isArray(data.results) ? data.results : [];
      if (!results.length) {
        setBlanksSearchStatus("Ничего не найдено.", false);
        if (resultsEl) resultsEl.innerHTML = renderBlanksSearchEmpty("no-results", q);
        return;
      }
      const capNote = results.length >= 200 ? " · показаны первые 200" : "";
      setBlanksSearchStatus(`Найдено: ${results.length}${capNote}`, false);
      renderBlanksSearchResults(results, q, resultsEl);
    } catch (e) {
      setBlanksSearchStatus("Ошибка: " + (e.message || e), true);
      if (resultsEl) resultsEl.innerHTML = renderBlanksSearchEmpty("idle");
    }
  }

  function boot() {
    if (!window.AnalysisRuntime?.isModule("blanks-search")) return;
    window.__ANALYSIS_ACTIVE_BUNDLE__ = "blanks-search";
    const blanksSearchBtn = $("blanks-search-btn");
    const blanksSearchQuery = $("blanks-search-query");
    if (blanksSearchBtn) blanksSearchBtn.addEventListener("click", runBlanksSearch);
    if (blanksSearchQuery) {
      blanksSearchQuery.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          runBlanksSearch();
        }
      });
    }
  }

  window.AnalysisRuntime?.onReady(boot);
})();
