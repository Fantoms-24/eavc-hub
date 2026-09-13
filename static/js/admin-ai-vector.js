(function () {
  "use strict";

function setAiVectorIndexResult(text, isError) {
  const el = $("ai-vector-index-result");
  if (!el) return;
  el.textContent = text || "";
  el.className = isError
    ? "small border border-danger bg-light rounded p-2 mt-3 mb-0 text-danger"
    : "small bg-light border rounded p-2 mt-3 mb-0";
  el.style.maxHeight = "220px";
  el.style.overflow = "auto";
  el.style.whiteSpace = "pre-wrap";
}

async function runAiVectorIndexIncremental() {
  setAiVectorIndexResult("Выполняется инкремент…", false);
  const db = ($("ai-vector-index-db-select") && $("ai-vector-index-db-select").value) || "main.sqlite";
  const mi = parseInt($("ai-vector-max-intercepts") && $("ai-vector-max-intercepts").value, 10) || 400;
  const ms = parseInt($("ai-vector-max-seanses") && $("ai-vector-max-seanses").value, 10) || 800;
  const prune = $("ai-vector-prune") && $("ai-vector-prune").checked;
  try {
    const data = await apiPost("/api/admin/ai-vector-index", {
      db,
      mode: "incremental",
      max_intercepts: mi,
      max_seanses: ms,
      prune: !!prune,
    });
    setAiVectorIndexResult(JSON.stringify(data.result, null, 2), false);
  } catch (e) {
    setAiVectorIndexResult(e.message || String(e), true);
  }
}

async function runAiVectorIndexFull() {
  if (
    !confirm(
      "Полная переиндексация: все перехваты и сеансы (с лимитами, если заданы). Может занять много времени. Продолжить?"
    )
  ) {
    return;
  }
  setAiVectorIndexResult("Выполняется полная переиндексация…", false);
  const db = ($("ai-vector-index-db-select") && $("ai-vector-index-db-select").value) || "main.sqlite";
  const il = ($("ai-vector-full-intercept-limit") && $("ai-vector-full-intercept-limit").value || "").trim();
  const sl = ($("ai-vector-full-seanses-limit") && $("ai-vector-full-seanses-limit").value || "").trim();
  const payload = { db, mode: "full" };
  if (il) {
    const n = parseInt(il, 10);
    if (!Number.isNaN(n) && n > 0) payload.intercept_limit = n;
  }
  if (sl) {
    const n = parseInt(sl, 10);
    if (!Number.isNaN(n) && n > 0) payload.seanses_limit = n;
  }
  try {
    const data = await apiPost("/api/admin/ai-vector-index", payload);
    setAiVectorIndexResult(JSON.stringify(data.result, null, 2), false);
  } catch (e) {
    setAiVectorIndexResult(e.message || String(e), true);
  }
}

function startAiVectorIndexPanel() {
  const inc = $("ai-vector-incremental-btn");
  const full = $("ai-vector-full-btn");
  if (inc) inc.addEventListener("click", () => void runAiVectorIndexIncremental());
  if (full) full.addEventListener("click", () => void runAiVectorIndexFull());
}


  function init() {
    startAiVectorIndexPanel();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
