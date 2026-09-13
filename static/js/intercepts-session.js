(function () {
  "use strict";

async function startNewShift() {
  if (!CAN_START) return;
  const pending = hasPendingInterceptChanges();
  const msg = pending
    ? "В бланке или в поле ввода есть несохранённый текст. Закрыть текущую смену и начать новую? Потерянный ввод восстановить будет нельзя."
    : "Закрыть текущую смену и начать новую?";
  if (!confirm(msg)) return;
  setText("intercepts-status", "Создаю новую смену…");
  try {
    await apiPost("/api/intercepts/session/start-new", {});
    await loadState();
    setText("intercepts-status", "Новая смена создана.");
    // очистим редактор
    ACTIVE_ITEM_ID = 0;
    $("intercept-text").value = "";
    const inpAfterNew = $("intercept-input");
    if (inpAfterNew) inpAfterNew.value = "";
    updateBlankEditState();
    setText("editor-subtitle", "Выбери группу слева");
    syncIxChatHeader();
  } catch (e) {
    setText("intercepts-status", `Ошибка: ${e.message || e}`);
  }
}

function getSelectedShiftSessionId() {
  const sel = $("shift-select");
  const fromSelect = Number(sel && sel.value ? sel.value : 0);
  if (fromSelect > 0) return fromSelect;
  return Number(ACTIVE_SESSION_ID || 0);
}

function getSelectedShiftLabel() {
  const sel = $("shift-select");
  if (!sel || sel.selectedIndex < 0) return "";
  const opt = sel.options[sel.selectedIndex];
  return opt ? String(opt.textContent || "").trim() : "";
}

async function exportDocx() {
  if (!CAN_EXPORT) return;
  const sessionId = getSelectedShiftSessionId();
  if (!sessionId) {
    setInterceptsStatus("Выберите смену в списке слева перед экспортом.");
    return;
  }
  ACTIVE_SESSION_ID = sessionId;
  const shiftLabel = getSelectedShiftLabel();
  try {
    const jobId = await queueExportJob(
      "/api/intercepts/export-docx-job",
      { session_id: sessionId },
      (msg) =>
        setInterceptsStatus(
          shiftLabel ? `Экспорт смены ${shiftLabel}: ${msg}` : msg
        )
    );
    await downloadExportJob(jobId, "merged_intercepts.docx");
    setInterceptsStatus("DOCX готов.");
    setTimeout(() => setInterceptsStatus(""), 4000);
  } catch (e) {
    setInterceptsStatus(`Ошибка экспорта DOCX: ${e.message || e}`);
  }
}


async function loadState(sessionId, opts) {
  const o = opts || {};
  const parts = [];
  if (sessionId != null && sessionId !== undefined && Number(sessionId) > 0) {
    parts.push(`session_id=${encodeURIComponent(sessionId)}`);
  }
  if (o.explicitPick) {
    parts.push("explicit_pick=1");
  }
  const qs = parts.length ? `?${parts.join("&")}` : "";
  _itemCacheClear();
  _invalidateInterceptsClientCache();
  const data = await apiGetWithTimeout(`/api/intercepts/state${qs}`, 20000);
  LAST_STATE_SIG = _stateSig(data);
  const cat = Array.isArray(data.catalog) ? data.catalog : [];
  const cs = Array.isArray(data.callsigns) ? data.callsigns : [];
  let catMax = "";
  for (const c of cat) {
    const v = String((c && c.updated_at) || "");
    if (v > catMax) catMax = v;
  }
  let csMax = "";
  for (const c of cs) {
    const v = String((c && c.updated_at) || "");
    if (v > csMax) csMax = v;
  }
  LAST_CATALOG_SIG = `${cat.length}|${catMax}|${cs.length}|${csMax}`;
  PREV_ITEMS_MAX_UPDATED_AT = String(data.items_max_updated_at || "");
  applyStateData(data);
  startPollingState();
}

function getInterceptDeepLink() {
  try {
    const params = new URLSearchParams(window.location.search || "");
    const sessionId = Number(params.get("session_id") || 0);
    const frequency = String(params.get("frequency") || "").trim();
    const groupCode = String(params.get("group_code") || "").trim();
    const highlight = String(params.get("highlight") || "").trim();
    if (!sessionId || !frequency || !groupCode) return null;
    return { sessionId, frequency, groupCode, highlight };
  } catch (_) {
    return null;
  }
}

function highlightDeepLinkFragment(term) {
  const needle = String(term || "").trim();
  if (!needle) return false;
  const editor = $("intercept-text");
  if (!editor) return false;
  const text = String(editor.value || "");
  const idx = text.toLowerCase().indexOf(needle.toLowerCase());
  if (idx < 0) return false;
  try {
    editor.focus({ preventScroll: true });
  } catch (_) {
    try { editor.focus(); } catch (_e) { }
  }
  try {
    editor.setSelectionRange(idx, idx + needle.length);
  } catch (_) { }
  if (editor.scrollIntoView) {
    setTimeout(() => editor.scrollIntoView({ behavior: "smooth", block: "center" }), 100);
  }
  setText("intercepts-status", `Открыт бланк, выделен фрагмент: ${needle}.`);
  return true;
}

async function openInterceptDeepLinkIfNeeded() {
  const link = getInterceptDeepLink();
  if (!link) return;
  if (!ACTIVE_SESSION_ID || Number(ACTIVE_SESSION_ID) !== Number(link.sessionId)) {
    await loadState(link.sessionId, { explicitPick: true });
  }
  const catalog = (STATE && Array.isArray(STATE.catalog) ? STATE.catalog : []).find((c) =>
    String(c.frequency || "").trim() === link.frequency &&
    String(c.group_code || "").trim() === link.groupCode
  );
  if (!catalog) {
    setText(
      "intercepts-status",
      `Бланк ${link.frequency} / ${link.groupCode} не найден в выбранной смене.`
    );
    return;
  }
  await openItem(Number(catalog.id || 0), catalog);
  setText("intercepts-status", `Открыт бланк ${link.frequency} / ${link.groupCode}.`);
  if (highlightDeepLinkFragment(link.highlight)) return;
  const editor = $("intercept-text");
  if (editor && editor.scrollIntoView) {
    setTimeout(() => editor.scrollIntoView({ behavior: "smooth", block: "center" }), 100);
  }
}


  window.startNewShift = startNewShift;
  window.exportDocx = exportDocx;
  window.loadState = loadState;
  window.getSelectedShiftSessionId = getSelectedShiftSessionId;
  window.getSelectedShiftLabel = getSelectedShiftLabel;
  window.getInterceptDeepLink = getInterceptDeepLink;
  window.highlightDeepLinkFragment = highlightDeepLinkFragment;
  window.openInterceptDeepLinkIfNeeded = openInterceptDeepLinkIfNeeded;
})();
