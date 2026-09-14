(function () {
  "use strict";

function updateBlankCallsignLegend() {
  // Легенду в обычном бланке отключили по UX-запросу.
}

function _renderPreview() {
  const box = $("intercept-preview");
  const ta = $("intercept-text");
  if (!box || !ta) return;
  const resizer = $("intercept-preview-resizer");

  // visibility is controlled by updateBlankViewMode(); here we just render

  const text = String(ta.value || "");
  const lines = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  const frag = document.createDocumentFragment();

  const timeRe = /^\s*(\d{1,2}[.:]\d{2})\s*$/;
  const idRe = /\((\d{1,10})\)/g;

  let hadAny = false;
  for (const rawLine of lines) {
    const line = String(rawLine || "");
    const tmatch = line.match(timeRe);
    if (tmatch) {
      const tnorm = _normalizeTimeLike(tmatch[1]) || String(tmatch[1] || "").trim();
      const h = document.createElement("div");
      h.className = "ip-time";
      h.textContent = tnorm;
      frag.appendChild(h);
      hadAny = true;
      continue;
    }

    const msgMatch = line.match(/^\s*-\s*(.*)$/);
    if (msgMatch) {
      const msgText = String(msgMatch[1] || "");
      let lastId = "";
      try {
        let m;
        while ((m = idRe.exec(msgText)) !== null) {
          lastId = String(m[1] || "");
        }
      } catch (_) { }
      try { idRe.lastIndex = 0; } catch (_) { }

      const row = document.createElement("div");
      row.className = "ip-msg d-flex justify-content-between align-items-start gap-2";
      row.dataset.code = lastId ? String(lastId) : "";
      if (PREVIEW_HIGHLIGHT_CODE && lastId && PREVIEW_HIGHLIGHT_CODE === lastId) {
        row.classList.add("ip-highlight");
      }

      const txt = document.createElement("div");
      txt.className = "ip-text flex-grow-1";
      // Показываем (ID) как кликабельный код + чип с позывным (или "н/у").
      txt.innerHTML = "";
      _appendTextWithIdBadges(txt, msgText);

      // Цветная линия снизу по ID, чтобы визуально было видно смену корреспондента
      if (lastId) {
        const col = _colorForCode(lastId);
        // мягче: тоньше и полупрозрачная линия (без color-mix, чтобы работало везде)
        txt.style.borderBottom = `2px solid ${col.line}`;
      } else {
        txt.style.borderBottom = "2px solid transparent";
      }

      row.appendChild(txt);

      // Бейдж с тегом / оперативным дежурным справа
      if (lastId) {
        const cs = _callsignByCode(lastId);
        const dutyCode = String((ACTIVE_ASSIGNMENTS || {}).duty || "").trim();
        const isDuty = !!dutyCode && String(lastId) === dutyCode;
        const badgeWrap = document.createElement("div");
        badgeWrap.className = "ip-meta text-end flex-shrink-0";

        if (cs && (cs.tag || cs.tag_desc || cs.tag_color || isDuty)) {
          const badge = document.createElement("div");
          badge.className = "badge text-bg-light border small";

          let parts = [];
          if (cs.tag) parts.push(String(cs.tag));
          if (isDuty) parts.push("Опер.д.");
          badge.textContent = parts.join(" • ") || "—";

          let bgColor = "";
          const tagColorStr = String(cs.tag_color || "").trim();
          if (tagColorStr && /^#[0-9a-fA-F]{6}$/.test(tagColorStr)) {
            bgColor = tagColorStr;
          } else if (isDuty) {
            bgColor = "#0d6efd";
          } else if (lastId) {
            const col = _colorForCode(lastId);
            bgColor = col.borderHex || col.border;
          }
          if (bgColor) {
            badge.style.backgroundColor = bgColor;
            badge.style.borderColor = bgColor;
            badge.style.color = /^#[0-9a-fA-F]{6}$/.test(bgColor) ? (_tagTextColor(bgColor) || "#111") : "#fff";
          }

          if (cs.tag_desc) {
            badge.title = String(cs.tag_desc);
          }

          badgeWrap.appendChild(badge);
        }

        if (badgeWrap.childNodes.length > 0) {
          row.appendChild(badgeWrap);
        }
      }

      frag.appendChild(row);
      hadAny = true;
      continue;
    }

    // Неформатные строки (показываем как есть, чтобы ничего не “пропадало”)
    if (String(line || "").trim()) {
      const raw = document.createElement("div");
      raw.className = "ip-raw";
      raw.textContent = line;
      frag.appendChild(raw);
      hadAny = true;
      continue;
    }
  }

  box.innerHTML = "";
  if (!hadAny) {
    const empty = document.createElement("div");
    empty.className = "ip-subtle";
    empty.textContent = "Нет данных для просмотра (добавь строки вида 12.10 и -Текст (ID)).";
    box.appendChild(empty);
    if (resizer) box.appendChild(resizer);
    return;
  }
  box.appendChild(frag);
  if (resizer) box.appendChild(resizer);
}

function _isNearBottom(el, thresholdPx = 24) {
  try {
    return (el.scrollTop + el.clientHeight) >= (el.scrollHeight - thresholdPx);
  } catch (_) {
    return true;
  }
}

function _scrollToBottom(el) {
  try {
    el.scrollTop = el.scrollHeight;
  } catch (_) { }
}
function setSaveStatus(state, message) {
  // state: "saving" | "saved" | "error" | "idle"
  const indicator = $("save-indicator");
  const textEl = $("save-text");
  if (indicator) {
    indicator.className = "save-indicator " + (state || "idle");
  }
  if (textEl) {
    textEl.textContent = message || "";
  }
}
function updateBlankEditState() {
  const ta = $("intercept-text");
  const toggle = $("edit-blank-toggle");
  if (!ta) return;

  const noItemPlaceholder =
    "Выберите частоту в списке слева — здесь откроется бланк перехвата";
  const viewOnlyPlaceholder =
    "Текст бланка ниже. Включите «Редакт.» в шапке, чтобы изменить.";

  // Если смена закрыта - только просмотр
  if (ACTIVE_CLOSED) {
    ta.disabled = false;
    ta.readOnly = true;
    ta.placeholder = ACTIVE_ITEM_ID ? "Смена закрыта — только просмотр." : noItemPlaceholder;
    if (toggle) {
      toggle.disabled = true;
      toggle.checked = false;
    }
    BLANK_EDIT_ENABLED = false;
    updateAiProofreadButtonState();
    return;
  }

  // Если нет прав или нет активного элемента
  if (!CAN_EDIT || !ACTIVE_ITEM_ID) {
    ta.disabled = true;
    ta.readOnly = false;
    ta.placeholder = noItemPlaceholder;
    if (toggle) {
      toggle.disabled = true;
      toggle.checked = false;
    }
    BLANK_EDIT_ENABLED = false;
    updateAiProofreadButtonState();
    return;
  }

  // Включаем переключатель, если есть права и активный элемент
  if (toggle) {
    toggle.disabled = false;
    toggle.checked = !!BLANK_EDIT_ENABLED;
  }

  if (BLANK_EDIT_ENABLED) {
    ta.disabled = false;
    ta.readOnly = false;
    ta.placeholder = "12.12\n-Текст. (1231)";
  } else {
    ta.disabled = false;
    ta.readOnly = true;
    ta.placeholder = viewOnlyPlaceholder;
  }
  updateAiProofreadButtonState();
}

function updateAiProofreadButtonState() {
  document.querySelectorAll("#ai-proofread-btn").forEach((btn) => {
    if (!AI_PROOFREAD_ENABLED) {
      btn.hidden = true;
      btn.disabled = true;
      return;
    }
    btn.hidden = false;
    btn.disabled =
      AI_PROOFREAD_DISABLED_UNTIL_RELOAD ||
      AI_PROOFREAD_INFLIGHT ||
      !(CAN_EDIT && ACTIVE_ITEM_ID && !ACTIVE_CLOSED);
  });
}

function clearAiProofreadPanel() {
  AI_PROOFREAD_RESULT = null;
  document.querySelectorAll("#ai-proofread-panel").forEach((panel) => {
    panel.style.display = "none";
    panel.hidden = true;
  });
  document.querySelectorAll("#ai-proofread-summary").forEach((el) => {
    el.textContent = "—";
  });
  document.querySelectorAll("#ai-proofread-issues").forEach((el) => {
    el.innerHTML = "";
  });
  document.querySelectorAll("#ai-proofread-apply-btn").forEach((btn) => {
    btn.disabled = true;
  });
}

function selectAiProofreadIssue(original, startHint) {
  const ta = $("intercept-text");
  if (!ta || !original) return;
  const text = String(ta.value || "");
  let start = Number(startHint);
  if (!Number.isFinite(start) || start < 0) {
    start = text.indexOf(String(original));
  }
  if (start < 0) return;
  const end = start + String(original).length;
  try {
    ta.focus();
    ta.setSelectionRange(start, end);
    const ratio = text.length ? start / text.length : 0;
    ta.scrollTop = Math.max(0, Math.floor(ta.scrollHeight * ratio) - 80);
  } catch (_) { }
}

function deriveAiProofreadIssues(sourceText, correctedText) {
  const source = String(sourceText || "");
  const corrected = String(correctedText || "");
  if (!source || !corrected || source === corrected) return [];
  let left = 0;
  while (left < source.length && left < corrected.length && source[left] === corrected[left]) left++;
  let rightSource = source.length - 1;
  let rightCorrected = corrected.length - 1;
  while (rightSource >= left && rightCorrected >= left && source[rightSource] === corrected[rightCorrected]) {
    rightSource--;
    rightCorrected--;
  }
  while (left > 0 && /[А-Яа-яЁёA-Za-z0-9-]/.test(source[left - 1] || "")) left--;
  while (rightSource + 1 < source.length && /[А-Яа-яЁёA-Za-z0-9-]/.test(source[rightSource + 1] || "")) rightSource++;
  while (rightCorrected + 1 < corrected.length && /[А-Яа-яЁёA-Za-z0-9-]/.test(corrected[rightCorrected + 1] || "")) rightCorrected++;
  const original = source.slice(left, rightSource + 1).trim();
  const fixed = corrected.slice(left, rightCorrected + 1).trim();
  if (!original || !fixed || original === fixed) return [];
  return [{ original, corrected: fixed, reason: "AI предложил точечное исправление в последнем сообщении." }];
}

function renderAiProofreadResult(result, sourceText) {
  if (!AI_PROOFREAD_ENABLED) {
    clearAiProofreadPanel();
    return;
  }
  const panel = $("ai-proofread-panel");
  const summary = $("ai-proofread-summary");
  const issuesBox = $("ai-proofread-issues");
  const applyBtn = $("ai-proofread-apply-btn");
  if (!panel || !summary || !issuesBox || !applyBtn) return;
  panel.style.display = "";
  issuesBox.innerHTML = "";

  let issues = Array.isArray(result && result.issues) ? result.issues : [];
  const changed = !!(result && result.changed);
  const aiError = String((result && result.ai_error) || "");
  if (changed && !issues.length) {
    issues = deriveAiProofreadIssues(sourceText, result.corrected_text);
    result.issues = issues;
  }
  if (!changed && !issues.length) {
    summary.textContent = aiError
      ? `AI-корректор сейчас недоступен, текст не изменен. ${aiError}`
      : "AI не нашел очевидных ошибок. Текст оставлен без изменений.";
    applyBtn.disabled = true;
    return;
  }

  summary.textContent = issues.length
    ? `Найдено исправлений: ${issues.length}. Нажмите на подсказку, чтобы выделить слово в бланке.`
    : "AI предложил исправленную версию текста.";
  applyBtn.disabled = !changed;

  let searchFrom = 0;
  const baseStart = Number(result && result.source_start);
  const startOffset = Number.isFinite(baseStart) && baseStart > 0 ? baseStart : 0;
  issues.forEach((issue, idx) => {
    const original = String(issue.original || "");
    const corrected = String(issue.corrected || "");
    let start = original ? String(sourceText || "").indexOf(original, searchFrom) : -1;
    if (start < 0 && original) start = String(sourceText || "").indexOf(original);
    if (start >= 0) searchFrom = start + original.length;
    const absoluteStart = start >= 0 ? startOffset + start : -1;

    const row = document.createElement("div");
    row.className = "ai-proofread-issue";
    row.dataset.original = original;
    row.dataset.start = String(absoluteStart);

    const top = document.createElement("div");
    top.className = "d-flex flex-wrap align-items-center gap-2";
    const n = document.createElement("span");
    n.className = "badge text-bg-info";
    n.textContent = String(idx + 1);
    const oldWord = document.createElement("span");
    oldWord.className = "ai-proofread-word text-danger text-decoration-line-through";
    oldWord.textContent = original || "—";
    const arrow = document.createElement("span");
    arrow.className = "text-muted";
    arrow.textContent = "->";
    const newWord = document.createElement("span");
    newWord.className = "ai-proofread-word text-success fw-semibold";
    newWord.textContent = corrected || "—";
    top.append(n, oldWord, arrow, newWord);

    const reason = document.createElement("div");
    reason.className = "small text-muted mt-1";
    reason.textContent = String(issue.reason || "Очевидная опечатка по смыслу.");

    row.append(top, reason);
    row.addEventListener("click", () => selectAiProofreadIssue(original, absoluteStart));
    issuesBox.appendChild(row);
  });
}

async function runAiProofread(options) {
  if (!AI_PROOFREAD_ENABLED) {
    clearAiProofreadPanel();
    return;
  }
  const ta = $("intercept-text");
  if (!ta || !ACTIVE_ITEM_ID || ACTIVE_CLOSED || !CAN_EDIT) return;
  const opts = options || {};
  const wholeText = String(ta.value || "");
  const text = String(typeof opts.text === "string" ? opts.text : wholeText);
  const sourceStartRaw = Number(opts.sourceStart);
  const sourceStart = Number.isFinite(sourceStartRaw) && sourceStartRaw >= 0 ? sourceStartRaw : 0;
  const sourceEnd = sourceStart + text.length;
  const mode = opts.text ? "segment" : "full";
  if (!text.trim()) {
    setText("intercepts-status", "Бланк пуст: AI-проверка не нужна.");
    return;
  }
  AI_PROOFREAD_INFLIGHT = true;
  updateAiProofreadButtonState();
  const panel = $("ai-proofread-panel");
  const summary = $("ai-proofread-summary");
  const issuesBox = $("ai-proofread-issues");
  const applyBtn = $("ai-proofread-apply-btn");
  if (panel) panel.style.display = "";
  if (summary) summary.textContent = mode === "segment" ? "AI проверяет последнее добавленное сообщение…" : "AI проверяет текст бланка…";
  if (issuesBox) issuesBox.innerHTML = "";
  if (applyBtn) applyBtn.disabled = true;
  try {
    const result = await apiPost("/api/intercepts/ai/proofread", {
      item_id: ACTIVE_ITEM_ID,
      text,
      frequency: ACTIVE_CAT ? ACTIVE_CAT.frequency : "",
      group_code: ACTIVE_CAT ? ACTIVE_CAT.group_code : "",
    });
    AI_PROOFREAD_RESULT = Object.assign({}, result, {
      source_text: text,
      source_start: sourceStart,
      source_end: sourceEnd,
      mode,
    });
    renderAiProofreadResult(AI_PROOFREAD_RESULT, text);
  } catch (e) {
    const panel = $("ai-proofread-panel");
    const summary = $("ai-proofread-summary");
    const issuesBox = $("ai-proofread-issues");
    const applyBtn = $("ai-proofread-apply-btn");
    if (panel) panel.style.display = "";
    if (summary) summary.textContent = `AI-корректор недоступен: ${e.message || e}`;
    if (issuesBox) issuesBox.innerHTML = "";
    if (applyBtn) applyBtn.disabled = true;
    setText("intercepts-status", `AI-корректор недоступен: ${e.message || e}`);
    setTimeout(() => setText("intercepts-status", ""), 5000);
  } finally {
    AI_PROOFREAD_INFLIGHT = false;
    updateAiProofreadButtonState();
  }
}

async function applyAiProofreadFixes() {
  const ta = $("intercept-text");
  const result = AI_PROOFREAD_RESULT || {};
  const corrected = String(result.corrected_text || "");
  const source = String(result.source_text || "");
  if (!ta || !corrected || corrected === source) return;
  const mode = String(result.mode || "full");
  const current = String(ta.value || "");
  if (mode === "segment") {
    let start = Number(result.source_start);
    let end = Number(result.source_end);
    if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end < start || current.slice(start, end) !== source) {
      start = current.lastIndexOf(source);
      end = start >= 0 ? start + source.length : -1;
    }
    if (start < 0 || end < start) {
      setText("intercepts-status", "Последнее сообщение изменилось после AI-проверки. Запустите проверку заново.");
      return;
    }
    ta.value = current.slice(0, start) + corrected + current.slice(end);
  } else {
    if (current !== source) {
      setText("intercepts-status", "Текст изменился после AI-проверки. Запустите проверку заново.");
      return;
    }
    ta.value = corrected;
  }
  try { _applyCallsignDecorationsInPlain(ta); } catch (_) { }
  try { _renderPreview(); } catch (_) { }
  updateBlankCallsignLegend();
  clearAiProofreadPanel();
  await saveNow({ sync: true, force: true });
  setText("intercepts-status", "AI-исправления применены и сохранены.");
  setTimeout(() => setText("intercepts-status", ""), 3000);
}

function updateBlankViewMode() {
  // Поддерживаем только обычный бланк (textarea).
  BLANK_VIEW_MODE = "plain";
  const taWrap = $("intercept-text-wrapper");
  const preview = $("intercept-preview");
  if (taWrap) taWrap.style.display = "";
  if (preview) {
    preview.style.display = "none";
    preview.classList.remove("plain-assist");
  }
  try { _applyCallsignDecorationsInPlain($("intercept-text")); } catch (_) { }
  updateBlankCallsignLegend();
}

function updateViewModeButton() {
  // Переключатель вида удалён. Оставлено как no-op для совместимости.
}

async function saveViewMode(mode) {
  void mode;
}

function insertAtCursor(text, textareaId = "intercept-text") {
  const ta = $(textareaId);
  if (!ta || ta.disabled) return;
  const previewBox = $("intercept-preview");
  const previewVisible = previewBox && previewBox.style.display !== "none";
  const start = ta.selectionStart || 0;
  const end = ta.selectionEnd || 0;
  const v = ta.value || "";
  ta.value = v.slice(0, start) + text + v.slice(end);
  const pos = start + text.length;
  ta.setSelectionRange(pos, pos);
  ta.focus();
  if (textareaId === "intercept-text") {
    scheduleSave();
    // programmatic change doesn't fire input; update preview explicitly
    if (previewVisible) {
      _renderPreview();
      requestAnimationFrame(() => _scrollToBottom(previewBox));
    }
  }
  requestAnimationFrame(() => {
    try {
      ta.scrollTop = ta.scrollHeight;
    } catch (_) { }
  });
}

function _autoUppercaseAfterDot(ev, textareaId) {
  // Автокапитализация: после ". ", "! " или "? " следующая буква становится заглавной.
  // Не вмешиваемся в хоткеи/служебные клавиши/вставку/выделение.
  if (!ev || ev.ctrlKey || ev.altKey || ev.metaKey) return false;
  if (ev.key == null) return false;
  const key = String(ev.key);
  if (key.length !== 1) return false;
  // Если Shift уже зажат — пользователь сам сделал заглавную
  if (ev.shiftKey) return false;
  const ta = $(textareaId);
  if (!ta || ta.disabled) return false;
  const start = ta.selectionStart ?? 0;
  const end = ta.selectionEnd ?? 0;
  if (start !== end) return false;
  const left = String(ta.value || "").slice(0, start);
  // Условие: перед курсором ". ", "! " или "? " (знак + хотя бы один пробел/перенос)
  if (!/[.!?][\s\u00A0]+$/u.test(left)) return false;
  // Только буквы (латиница/кириллица и т.п.)
  if (!/^\p{L}$/u.test(key)) return false;
  ev.preventDefault();
  insertAtCursor(key.toLocaleUpperCase("ru-RU"), textareaId);
  return true;
}

function _lineBoundsAtPos(text, pos) {
  const s = String(text || "");
  const p = Math.max(0, Math.min(s.length, Number(pos) || 0));
  const start = s.lastIndexOf("\n", p - 1) + 1;
  const endIdx = s.indexOf("\n", p);
  const end = endIdx === -1 ? s.length : endIdx;
  return { start, end };
}

let _CARET_MIRROR = null;

function _getCaretTopInTextarea(ta, pos) {
  if (!ta) return 0;
  const p = Math.max(0, Math.min((ta.value || "").length, Number(pos) || 0));
  const style = window.getComputedStyle(ta);
  if (!_CARET_MIRROR) {
    _CARET_MIRROR = document.createElement("div");
    _CARET_MIRROR.style.position = "absolute";
    _CARET_MIRROR.style.visibility = "hidden";
    _CARET_MIRROR.style.whiteSpace = "pre-wrap";
    _CARET_MIRROR.style.wordWrap = "break-word";
    _CARET_MIRROR.style.top = "0";
    _CARET_MIRROR.style.left = "-9999px";
    document.body.appendChild(_CARET_MIRROR);
  }
  const mirror = _CARET_MIRROR;
  const props = [
    "fontFamily",
    "fontSize",
    "fontWeight",
    "fontStyle",
    "letterSpacing",
    "textTransform",
    "paddingTop",
    "paddingRight",
    "paddingBottom",
    "paddingLeft",
    "borderTopWidth",
    "borderRightWidth",
    "borderBottomWidth",
    "borderLeftWidth",
    "boxSizing",
    "lineHeight",
    "textAlign",
    "width",
  ];
  for (const prop of props) {
    mirror.style[prop] = style[prop];
  }
  mirror.textContent = (ta.value || "").slice(0, p);
  const span = document.createElement("span");
  span.textContent = (ta.value || "").slice(p) || ".";
  mirror.appendChild(span);
  return span.offsetTop || 0;
}

function _fixDashIfTimeHeaderAtCursor(textareaId = "intercept-text", optionalEl = null) {
  const ta = optionalEl && optionalEl.id === textareaId ? optionalEl : $(textareaId);
  if (!ta || ta.disabled) return;
  const v = String(ta.value || "");
  const pos = ta.selectionStart || 0;
  const { start, end } = _lineBoundsAtPos(v, pos);
  const line = v.slice(start, end);
  // Если строка выглядит как "-15.12" / "-15:12" -> превращаем в "15.12"
  const m = line.match(/^\s*-(\d{1,2}[.:]\d{2})\s*$/);
  if (!m) return;
  const th = normalizeTimeHeader(m[1]);
  if (!th) return;
  const before = v.slice(0, start);
  const after = v.slice(end);
  ta.value = before + th + after;
  // курсор сдвигаем на -1 (убрали '-'), но не ломаем границы
  const newPos = Math.max(start, (pos || 0) - 1);
  try {
    ta.setSelectionRange(newPos, newPos);
  } catch (_) { }
}

function _resolveActiveCatalogFromState() {
  if (!STATE || !Array.isArray(STATE.catalog)) return null;
  if (ACTIVE_CATALOG_ID && Number(ACTIVE_CATALOG_ID) > 0) {
    const byId = STATE.catalog.find((c) => Number(c.id || 0) === Number(ACTIVE_CATALOG_ID));
    if (byId) return byId;
  }
  if (ACTIVE_CAT && ACTIVE_CAT.frequency && ACTIVE_CAT.group_code) {
    return (
      STATE.catalog.find(
        (c) =>
          String(c.frequency || "").trim() === String(ACTIVE_CAT.frequency || "").trim() &&
          String(c.group_code || "").trim() === String(ACTIVE_CAT.group_code || "").trim()
      ) || null
    );
  }
  return null;
}

async function _ensureActiveItemOpen() {
  if (ACTIVE_ITEM_ID) return true;
  if (!ACTIVE_CAT || !ACTIVE_CAT.frequency || !ACTIVE_CAT.group_code) return false;

  if (!ACTIVE_SESSION_ID && STATE) {
    const sel = STATE.selected_session || STATE.current_session;
    const sid = Number(sel && sel.id ? sel.id : 0);
    if (sid > 0) ACTIVE_SESSION_ID = sid;
  }
  if (!ACTIVE_SESSION_ID) return false;

  const cat = _resolveActiveCatalogFromState();
  if (!cat || typeof openItem !== "function") return false;

  try {
    await openItem(Number(cat.id || 0), {
      id: cat.id,
      unit_name: cat.unit_name || "",
      frequency: cat.frequency || "",
      group_code: cat.group_code || "",
      location: String(cat.location || "").trim(),
      archived_only: !!cat.archived_only,
    });
  } catch (_) { }

  return !!ACTIVE_ITEM_ID;
}


function _autoScrollEditorIfNeeded(ta) {
  if (!ta) return;
  // Автопрокрутка только когда пользователь "держится" внизу.
  // Если он прокрутил вверх (читает/правит старые строки), не мешаем.
  const nearBottom = (ta.scrollTop + ta.clientHeight) >= (ta.scrollHeight - 24);
  if (!nearBottom) return;
  requestAnimationFrame(() => {
    try {
      ta.scrollTop = ta.scrollHeight;
    } catch (_) { }
  });
}

const CALLSIGN_SUGGEST_MAX = 100;

function _normCallsignSearch(s) {
  return String(s || "").trim().toLocaleLowerCase("ru");
}

function _callsignSuggestKey(c) {
  const code = _normalizeCallsignCode(c && c.code);
  const freq = String((c && c.frequency) || "").trim();
  const grp = String((c && c.group_code) || "").trim();
  return `${code}|${freq}|${grp}`;
}

function _callsignScopedPool() {
  const all = Array.isArray(ALL_CALLSIGNS) ? ALL_CALLSIGNS : [];
  if (_ixCallsignListScoped()) {
    return all.filter(callsignMatchesActiveScope);
  }
  const scoped = Array.isArray(CALLSIGNS) ? CALLSIGNS : [];
  return scoped.length ? scoped : all;
}

function _callsignSuggestLabel(it) {
  const label = String((it && it.label) || "").trim() || "—";
  const code = _normalizeCallsignCode(it && it.code);
  return code ? `${label} (${code})` : label;
}

function getCallsignQueryAtCursor(textareaId = "intercept-text") {
  let ta = $(textareaId);
  if (textareaId === "intercept-input" && document.activeElement && document.activeElement.id === "intercept-input") {
    ta = document.activeElement;
  }
  if (!ta) return null;
  const pos = ta.selectionStart || 0;
  const before = (ta.value || "").slice(0, pos);
  const m = before.match(/\(([^\)]*)$/);
  if (!m) return null;
  return m[1] || "";
}

function getCodePrefixAtCursor(textareaId = "intercept-text") {
  return getCallsignQueryAtCursor(textareaId);
}

function _callsignMatchesQuery(c, query) {
  const qRaw = String(query ?? "");
  const q = _normCallsignSearch(qRaw);
  if (!q) return true;
  const code = String(c.code || "").trim();
  const label = _normCallsignSearch(c.label || "");
  if (/^\d+$/.test(qRaw.trim())) {
    return code.startsWith(qRaw.trim());
  }
  if (label.startsWith(q) || label.includes(q)) return true;
  if (code.toLocaleLowerCase("ru").startsWith(q)) return true;
  return false;
}

function _callsignSortScore(c, query) {
  const qRaw = String(query ?? "").trim();
  const q = _normCallsignSearch(qRaw);
  if (!q) return 0;
  const code = String(c.code || "").trim();
  const label = _normCallsignSearch(c.label || "");
  if (/^\d+$/.test(qRaw)) {
    return code.startsWith(qRaw) ? 1000 - code.length : -1;
  }
  if (label.startsWith(q)) return 900 - label.length;
  if (code.toLocaleLowerCase("ru").startsWith(q)) return 800 - code.length;
  const idx = label.indexOf(q);
  if (idx >= 0) return 600 - idx;
  return -1;
}

function _filterCallsignSuggestions(pool, query, limit = CALLSIGN_SUGGEST_MAX) {
  const seen = new Set();
  const items = (pool || [])
    .filter((c) => {
      if (!_callsignMatchesQuery(c, query)) return false;
      const key = _callsignSuggestKey(c);
      if (!key || key.startsWith("|")) return false;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .sort((a, b) => {
      const sb = _callsignSortScore(b, query);
      const sa = _callsignSortScore(a, query);
      if (sb !== sa) return sb - sa;
      const lc = String(a.label || "").localeCompare(String(b.label || ""), "ru", { numeric: true });
      if (lc !== 0) return lc;
      return String(a.code || "").localeCompare(String(b.code || ""), "ru", { numeric: true });
    });
  return limit > 0 ? items.slice(0, limit) : items;
}

function _suggestSig(items) {
  try {
    return (items || []).map((x) => String(x.code || "")).join("|");
  } catch (_) {
    return "";
  }
}

function setSuggest(open, items, prefix) {
  const nextOpen = !!open;
  const nextItems = items || [];
  const nextPrefix = prefix || "";

  // Если подсказка уже открыта и мы просто "перерисовываем" тот же набор (например, из-за keyup),
  // не сбрасываем выбранный индекс — иначе стрелки будут "прыгать" назад.
  const same =
    SUGGEST.open &&
    nextOpen &&
    String(SUGGEST.prefix || "") === String(nextPrefix || "") &&
    _suggestSig(SUGGEST.items) === _suggestSig(nextItems);

  SUGGEST.open = nextOpen;
  SUGGEST.items = nextItems;
  if (!same) SUGGEST.idx = 0;
  SUGGEST.prefix = nextPrefix;
  renderSuggest();
}

function setSuggestInput(open, items, prefix) {
  const nextOpen = !!open;
  const nextItems = items || [];
  const nextPrefix = prefix || "";

  const same =
    SUGGEST_INPUT.open &&
    nextOpen &&
    String(SUGGEST_INPUT.prefix || "") === String(nextPrefix || "") &&
    _suggestSig(SUGGEST_INPUT.items) === _suggestSig(nextItems);

  SUGGEST_INPUT.open = nextOpen;
  SUGGEST_INPUT.items = nextItems;
  if (!same) SUGGEST_INPUT.idx = 0;
  SUGGEST_INPUT.prefix = nextPrefix;
  renderSuggestInput();
}

function renderSuggestInput() {
  const box = $("cs-suggest-input");
  if (!box) return;
  if (!SUGGEST_INPUT.open || !SUGGEST_INPUT.items.length) {
    box.style.display = "none";
    box.innerHTML = "";
    return;
  }
  const prevScrollTop = box.scrollTop || 0;
  box.style.display = "block";
  box.innerHTML = "";
  for (let i = 0; i < SUGGEST_INPUT.items.length; i++) {
    const it = SUGGEST_INPUT.items[i];
    const a = document.createElement("button");
    a.type = "button";
    a.className = `list-group-item list-group-item-action ${i === SUGGEST_INPUT.idx ? "active" : ""}`;
    const tag = String(it.tag || "").trim();
    const tagColor = String(it.tag_color || "").trim();
    a.innerHTML = `
      <div class="d-flex align-items-center justify-content-between gap-2">
        <div class="fw-semibold">${escapeHtml(_callsignSuggestLabel(it))}</div>
        <div>${tag ? tagBadgeHtml(tag, tagColor) : ""}</div>
      </div>
    `;
    // Важно: используем mousedown/touchstart, чтобы выбор мышью срабатывал ДО blur у textarea.
    a.addEventListener("mousedown", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      acceptSuggestInput(i);
    });
    a.addEventListener(
      "touchstart",
      (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        acceptSuggestInput(i);
      },
      { passive: false }
    );
    box.appendChild(a);
  }
  try {
    box.scrollTop = prevScrollTop;
    const active = box.querySelector(".list-group-item.active");
    if (active && typeof active.scrollIntoView === "function") {
      active.scrollIntoView({ block: "nearest" });
    }
  } catch (_) { }
  try {
    let ta = $("intercept-input");
    if (ta && document.activeElement && document.activeElement.id === "intercept-input") {
      ta = document.activeElement;
    }
    if (ta) {
      const wrap = ta.closest(".tg-composer__field") || ta.parentElement;
      const lineHeight = parseFloat(window.getComputedStyle(ta).lineHeight) || 18;
      const caretTop = _getCaretTopInTextarea(ta, ta.selectionStart || 0);
      const caretInView = Math.max(0, caretTop - (ta.scrollTop || 0));
      const offsetTop = caretInView + lineHeight + 6;
      box.style.position = "absolute";
      box.style.zIndex = "1060";
      box.style.bottom = "auto";
      box.style.maxHeight = "min(50vh, 320px)";
      box.style.overflowY = "auto";
      box.style.width = "auto";
      box.style.left = "0";
      box.style.right = "0";
      box.style.transform = "";
      if (wrap) {
        const belowCaret = ta.offsetTop + offsetTop;
        const spaceBelow = (wrap.clientHeight || 0) - belowCaret;
        if (spaceBelow < 100 && caretInView > 40) {
          box.style.top = `${Math.max(4, ta.offsetTop + caretInView - 4)}px`;
          box.style.transform = "translateY(-100%)";
        } else {
          box.style.top = `${belowCaret}px`;
        }
      }
    }
  } catch (_) { }
}

function renderSuggest() {
  const box = $("cs-suggest");
  if (!box) return;
  if (!SUGGEST.open || !SUGGEST.items.length) {
    box.style.display = "none";
    box.innerHTML = "";
    return;
  }
  // сохраняем scroll, чтобы при перерисовке список не "прыгал" в начало
  const prevScrollTop = box.scrollTop || 0;
  box.style.display = "block";
  box.innerHTML = "";
  for (let i = 0; i < SUGGEST.items.length; i++) {
    const it = SUGGEST.items[i];
    const a = document.createElement("button");
    a.type = "button";
    a.className = `list-group-item list-group-item-action ${i === SUGGEST.idx ? "active" : ""}`;
    const tag = String(it.tag || "").trim();
    const tagColor = String(it.tag_color || "").trim();
    a.innerHTML = `
      <div class="d-flex align-items-center justify-content-between gap-2">
        <div class="fw-semibold">${escapeHtml(_callsignSuggestLabel(it))}</div>
        <div>${tag ? tagBadgeHtml(tag, tagColor) : ""}</div>
      </div>
    `;
    // Важно: используем mousedown/touchstart, чтобы выбор мышью срабатывал ДО blur у textarea.
    a.addEventListener("mousedown", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      acceptSuggest(i);
    });
    a.addEventListener(
      "touchstart",
      (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        acceptSuggest(i);
      },
      { passive: false }
    );
    box.appendChild(a);
  }
  // восстановим scroll и гарантируем, что active видим
  try {
    box.scrollTop = prevScrollTop;
    const active = box.querySelector(".list-group-item.active");
    if (active && typeof active.scrollIntoView === "function") {
      active.scrollIntoView({ block: "nearest" });
    }
  } catch (_) { }
}

function acceptSuggest(i, textareaId = "intercept-text", suggestObj = SUGGEST) {
  const it = suggestObj.items[i];
  if (!it) return;
  const ta = $(textareaId);
  if (!ta) return;
  const pos = ta.selectionStart || 0;
  const v = ta.value || "";
  const before = v.slice(0, pos);
  const after = v.slice(pos);
  const m = before.match(/\(([^\)]*)$/);
  if (!m) return;
  const code = _normalizeCorrespondentId(it.code);
  if (!code) return;
  const openIdx = before.lastIndexOf("(");
  if (openIdx < 0) return;
  const newBefore = `${before.slice(0, openIdx + 1)}${code})`;
  ta.value = newBefore + after;
  const newPos = newBefore.length;
  ta.setSelectionRange(newPos, newPos);
  ta.focus();
  if (textareaId === "intercept-text") {
    setSuggest(false, [], "");
    scheduleSave();
  } else {
    setSuggestInput(false, [], "");
  }
}

function acceptSuggestInput(i) {
  acceptSuggest(i, "intercept-input", SUGGEST_INPUT);
}

function _loadCorrIdSuggestEnabled() {
  try {
    const v = localStorage.getItem(CORR_ID_SUGGEST_LS_KEY);
    if (v === "0" || v === "false") return false;
  } catch (_) { }
  return true;
}

function _syncCorrIdSuggestButtons() {
  document.querySelectorAll("[data-corr-id-suggest-toggle]").forEach((btn) => {
    const on = !!CORR_ID_SUGGEST_ENABLED;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.title = on
      ? "Автоподстановка ID включена — при «(» показывается меню"
      : "Автоподстановка ID выключена — меню при «(» не показывается";
    const label = btn.querySelector("[data-corr-id-suggest-label]");
    if (label) label.textContent = on ? "ID авто" : "ID вруч.";
  });
}

function _setCorrIdSuggestEnabled(enabled) {
  CORR_ID_SUGGEST_ENABLED = !!enabled;
  try {
    localStorage.setItem(CORR_ID_SUGGEST_LS_KEY, CORR_ID_SUGGEST_ENABLED ? "1" : "0");
  } catch (_) { }
  _syncCorrIdSuggestButtons();
  if (!CORR_ID_SUGGEST_ENABLED) {
    setSuggest(false, [], "");
    setSuggestInput(false, [], "");
  }
}

function initCorrIdSuggestToggle() {
  CORR_ID_SUGGEST_ENABLED = _loadCorrIdSuggestEnabled();
  _syncCorrIdSuggestButtons();
  document.querySelectorAll("[data-corr-id-suggest-toggle]").forEach((btn) => {
    if (btn.dataset.corrIdSuggestBound === "1") return;
    btn.dataset.corrIdSuggestBound = "1";
    btn.addEventListener("click", () => {
      _setCorrIdSuggestEnabled(!CORR_ID_SUGGEST_ENABLED);
    });
  });
}

function updateSuggestFromCursor(ev, textareaId = "intercept-text") {
  if (!CORR_ID_SUGGEST_ENABLED) {
    if (textareaId === "intercept-text") return setSuggest(false, [], "");
    return setSuggestInput(false, [], "");
  }
  if (textareaId === "intercept-text") {
    if (!CAN_EDIT || ACTIVE_CLOSED) return setSuggest(false, [], "");
    // Проверяем, что textarea не disabled (а не BLANK_EDIT_ENABLED, так как disabled уже учитывает переключатель)
    const ta = $(textareaId);
    if (ta && ta.disabled) return setSuggest(false, [], "");
    // Если пользователь листает подсказку стрелками/Enter/Tab — не пересчитываем подсказку,
    // иначе сбросим idx и будет "прыгать".
    if (SUGGEST.open && ev && (ev.key === "ArrowDown" || ev.key === "ArrowUp" || ev.key === "Enter" || ev.key === "Tab")) {
      return;
    }
    const prefix = getCallsignQueryAtCursor(textareaId);
    if (prefix === null) return setSuggest(false, [], "");
    const items = _filterCallsignSuggestions(_callsignScopedPool(), prefix);
    if (!items.length) return setSuggest(false, [], "");
    setSuggest(true, items, prefix);
  } else {
    // Для поля ввода всегда доступно (не зависит от CAN_EDIT/ACTIVE_CLOSED)
    if (SUGGEST_INPUT.open && ev && (ev.key === "ArrowDown" || ev.key === "ArrowUp" || ev.key === "Enter" || ev.key === "Tab")) {
      return;
    }
    const prefix = getCallsignQueryAtCursor(textareaId);
    if (prefix === null) return setSuggestInput(false, [], "");
    let items = _filterCallsignSuggestions(_callsignScopedPool(), prefix);
    const digitPrefix = /^\d+$/.test(String(prefix || "").trim());
    const currentAudio = _currentAudioItem();
    const currentCode = currentAudio ? _correspondentIdFromItem(currentAudio) : "";
    if (
      digitPrefix &&
      currentCode &&
      currentCode.startsWith(String(prefix || "")) &&
      !items.some((c) => String(c.code || "") === currentCode)
    ) {
      items = [{ code: currentCode, label: `Корр. (${currentCode})`, id: null }, ...items].slice(0, CALLSIGN_SUGGEST_MAX);
    }
    if (!items.length && digitPrefix && typeof AUDIO_QUEUE !== "undefined" && Array.isArray(AUDIO_QUEUE)) {
      const seen = new Set();
      for (const it of AUDIO_QUEUE) {
        const code = _correspondentIdFromItem(it);
        if (code && code.startsWith(String(prefix || "")) && !seen.has(code)) {
          seen.add(code);
          items.push({ code, label: `Корр. (${code})`, id: null });
          if (items.length >= CALLSIGN_SUGGEST_MAX) break;
        }
      }
    }
    if (!items.length) return setSuggestInput(false, [], "");
    setSuggestInput(true, items, prefix);
  }
}

async function _saveNowOnce(opts) {
  if (!CAN_EDIT || !ACTIVE_ITEM_ID) {
    return;
  }
  if (ACTIVE_CLOSED) {
    return;
  }
  const options = opts || {};
  const sync = !!options.sync;
  const merge = !!options.merge;
  const force = !!options.force;
  const ta = $("intercept-text");
  const text = (ta && ta.value) ? ta.value : "";
  if (!force && text === LAST_SAVED) {
    return;
  }
  // Замена стирает записи, добавленные другим оператором, — спрашиваем явно.
  if (!merge && HAS_REMOTE_NEW) {
    const ok = window.confirm(
      "Другой оператор добавил записи в этот бланк.\n" +
      "Сохранение заменит бланк вашим текстом, и его записи будут удалены.\n\n" +
      "Отмена — чтобы сначала нажать «Слить и обновить»."
    );
    if (!ok) {
      setSaveStatus("idle", "Не сохранено — нажмите «Слить и обновить»");
      return;
    }
  }
  setSaveStatus("saving", "Сохранение…");
  // Ответы опроса, заказанные до записи, описывают состояние до неё.
  ITEM_SYNC_EPOCH += 1;
  try {
    const data = await apiPost("/api/intercepts/item/update", { item_id: ACTIVE_ITEM_ID, content: text, merge });
    _itemCacheSet(_itemCacheKey(ACTIVE_SESSION_ID, ACTIVE_CATALOG_ID, ACTIVE_CAT), data);
    if (typeof apiEtagCacheClear === "function") apiEtagCacheClear("/api/intercepts/item");
    const item = data.item || {};
    const merged = String(item.content || "");
    const updatedAt = String(item.updated_at || "");
    // Обновляем LAST_REMOTE_UPDATED_AT после успешного сохранения,
    // чтобы другие пользователи получили обновления через polling
    LAST_REMOTE_UPDATED_AT = updatedAt || LAST_REMOTE_UPDATED_AT;
    LAST_REMOTE_SIG = _contentSig(updatedAt || "", merged);
    ITEM_SYNC_EPOCH += 1;
    if (sync && ta) {
      const st = ta.selectionStart || 0;
      const en = ta.selectionEnd || 0;
      const scroll = ta.scrollTop || 0;
      ta.value = merged;
      // курсор не всегда можно корректно восстановить после сортировки; ставим максимально близко
      try {
        ta.setSelectionRange(Math.min(st, ta.value.length), Math.min(en, ta.value.length));
        ta.scrollTop = scroll;
      } catch (_) { }
      LAST_SAVED = ta.value;
      HAS_REMOTE_NEW = false;
      const badge = $("remote-new-badge");
      if (badge) badge.style.display = "none";
      const mergeBtn = $("merge-updates-btn");
      if (mergeBtn) mergeBtn.style.display = "none";
    } else {
      // не перет��раем textarea во время набора; считаем локально сохранённым текущий текст
      LAST_SAVED = text;
    }
    setSaveStatus("saved", updatedAt ? `Сохранено: ${fmtShift(updatedAt)}` : "Сохранено");
    // Обновляем просмотр после сохранения (programmatic change may not trigger input)
    const previewBox = $("intercept-preview");
    const previewVisible = previewBox && previewBox.style.display !== "none";
    if (previewVisible) {
      _renderPreview();
      requestAnimationFrame(() => _scrollToBottom(previewBox));
    } else if (ta && !ta.disabled) {
      requestAnimationFrame(() => {
        try { ta.scrollTop = ta.scrollHeight; } catch (_) { }
      });
    }
    // через 3 секунды скрываем текст, оставляем только индикатор
    setTimeout(() => {
      if ($("save-text")?.textContent?.includes("Сохранено")) {
        setSaveStatus("saved", "");
      }
    }, 3000);
    ITEM_POLL_MS = ITEM_POLL_MS_FAST;
    ITEM_POLL_UNCHANGED_STREAK = 0;
    pollItemOnce().catch(() => { });
    pollStateOnce().catch(() => { });
    _scheduleItemPoll(ITEM_POLL_MS_FAST);
    updateBlankDirtyUi();
  } catch (e) {
    console.error("saveNow: ошибка сохранения", e);
    setSaveStatus("error", `Ошибка: ${e.message || e}`);
    throw e; // Пробрасываем ошибку дальше, чтобы вызывающий код мог её обработать
  }
}

function saveNow(opts) {
  const wasQueued = SAVE_CHAIN_ACTIVE;
  if (wasQueued) {
    setSaveStatus("saving", "Ожидает предыдущее сохранение…");
  }
  const job = SAVE_CHAIN.catch(() => { }).then(async () => {
    SAVE_CHAIN_ACTIVE = true;
    try {
      return await _saveNowOnce(opts);
    } finally {
      SAVE_CHAIN_ACTIVE = false;
    }
  });
  SAVE_CHAIN = job;
  return job;
}

function normalizeTimeHeader(s) {
  const m = String(s || "").trim().match(/^(\d{1,2})[.:](\d{2})$/);
  if (!m) return "";
  const hh = String(Math.max(0, Math.min(23, Number(m[1]) || 0))).padStart(2, "0");
  const mm = String(Math.max(0, Math.min(59, Number(m[2]) || 0))).padStart(2, "0");
  return `${hh}.${mm}`;
}

function updateBlankDirtyUi() {
  const manualBtn = $("manual-save-btn");
  const dirty = !!(CAN_EDIT && ACTIVE_ITEM_ID && !ACTIVE_CLOSED && hasPendingInterceptChanges());
  if (manualBtn) {
    manualBtn.disabled = !dirty;
    manualBtn.classList.toggle("btn-outline-warning", dirty);
    manualBtn.classList.toggle("btn-outline-primary", !dirty);
  }
  if (dirty) {
    setSaveStatus("idle", "Есть несохранённые изменения — нажмите «Сохранить»");
  }
}

// Нормализует все форматы времени в тексте (12:17 -> 12.17)
function normalizeTimeInText(text) {
  if (text == null) return text;
  const src = String(text);
  const lines = src.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  const out = lines.map((line) => {
    const raw = String(line || "");
    const trimmed = raw.trim();

    // Строка содержит только время (возможен ведущий "-" и пробелы) -> "13:01" -> "13.01"
    const only = trimmed.match(/^-?\s*(\d{1,2})[.:](\d{2})$/);
    if (only) {
      const lead = (raw.match(/^\s*/) || [""])[0];
      const trail = (raw.match(/\s*$/) || [""])[0];
      const normalized = normalizeTimeHeader(`${only[1]}:${only[2]}`);
      return lead + normalized + trail;
    }

    // Время в начале строки перед "-" (например "13:01 -Привет") -> меняем только ":" на "."
    const head = raw.match(/^(\s*)(\d{1,2})[.:](\d{2})(\s*)(?=-)/);
    if (head) {
      const normalized = normalizeTimeHeader(`${head[2]}:${head[3]}`);
      return `${head[1]}${normalized}${head[4]}` + raw.slice(head[0].length);
    }

    return raw;
  });
  return out.join("\n");
}

// Нормализует формат времени в тексте при вводе (для поля intercept-input)
function normalizeTimeOnInput(textareaId = "intercept-input", optionalEl = null) {
  const ta = optionalEl && optionalEl.id === textareaId ? optionalEl : $(textareaId);
  if (!ta || ta.disabled) return;
  const v = String(ta.value || "");
  const pos = ta.selectionStart || 0;
  const normalized = normalizeTimeInText(v);
  if (normalized !== v) {
    // Вычисляем изменение позиции курсора из-за замен
    const beforePos = v.slice(0, pos);
    const afterPos = normalized.slice(0, pos + (normalized.length - v.length));
    const newPos = afterPos.length;
    ta.value = normalized;
    try {
      ta.setSelectionRange(newPos, newPos);
    } catch (_) { }
  }
}

function extractLastTimeHeader(text) {
  const lines = String(text || "").split(/\r?\n/);
  for (let i = lines.length - 1; i >= 0; i--) {
    const t = normalizeTimeHeader(lines[i]);
    if (t) return t;
  }
  return "";
}

/** Несохранённый бланк (относительно LAST_SAVED) или черновик в поле ввода радиоперехвата. */
function hasPendingInterceptChanges() {
  const input = $("intercept-input");
  if (input && String(input.value || "").trim().length > 0) return true;
  if (!ACTIVE_ITEM_ID || ACTIVE_CLOSED || !CAN_EDIT) return false;
  const ta = $("intercept-text");
  if (!ta) return false;
  return String(ta.value || "") !== String(LAST_SAVED || "");
}

async function autoSaveIfDirty(reason) {
  void reason;
  if (!BLANK_AUTOSAVE_ENABLED) return;
  if (!CAN_EDIT || ACTIVE_CLOSED) return;
  if (!ACTIVE_ITEM_ID) return;
  if (HAS_REMOTE_NEW) {
    setSaveStatus("idle", "Есть новые данные — сохраните вручную или нажмите «Слить и обновить»");
    return;
  }
  const ta = $("intercept-text");
  if (!ta) return;
  const text = String(ta.value || "");
  if (text === LAST_SAVED) return;
  const r = String(reason || "");
  const doSync = r === "new_time" || r === "idle" || r === "switch_shift";
  await saveNow({ sync: doSync });
}

function scheduleIdleAutoSave() {
  if (!BLANK_AUTOSAVE_ENABLED) return;
  if (AUTO_SAVE_IDLE_TIMER) clearTimeout(AUTO_SAVE_IDLE_TIMER);
  AUTO_SAVE_IDLE_TIMER = setTimeout(() => {
    autoSaveIfDirty("idle").catch(() => {
      setSaveStatus("error", "Ошибка автосохранения");
    });
  }, AUTO_SAVE_IDLE_MS);
}

function scheduleSave() {
  scheduleTypingPing();
  updateBlankDirtyUi();
  if (!BLANK_AUTOSAVE_ENABLED) return;
  if (!CAN_EDIT || ACTIVE_CLOSED) return;
  if (!ACTIVE_ITEM_ID) return;
  const ta = $("intercept-text");
  if (!ta || ta.disabled) return;

  _fixDashIfTimeHeaderAtCursor();

  const lastHeader = extractLastTimeHeader(ta.value || "");
  if (lastHeader && lastHeader !== LAST_TIME_HEADER) {
    LAST_TIME_HEADER = lastHeader;
    if (AUTO_SAVE_DEBOUNCE_TIMER) clearTimeout(AUTO_SAVE_DEBOUNCE_TIMER);
    AUTO_SAVE_DEBOUNCE_TIMER = null;
    autoSaveIfDirty("new_time").catch(() => {
      setSaveStatus("error", "Ошибка автосохранения");
    });
    scheduleIdleAutoSave();
    return;
  }

  if (AUTO_SAVE_DEBOUNCE_TIMER) clearTimeout(AUTO_SAVE_DEBOUNCE_TIMER);
  AUTO_SAVE_DEBOUNCE_TIMER = setTimeout(() => {
    AUTO_SAVE_DEBOUNCE_TIMER = null;
    autoSaveIfDirty("debounce").catch(() => {
      setSaveStatus("error", "Ошибка автосохранения");
    });
  }, AUTO_SAVE_DEBOUNCE_MS);

  scheduleIdleAutoSave();
}


  window.updateBlankCallsignLegend = updateBlankCallsignLegend;
  window._renderPreview = _renderPreview;
  window._isNearBottom = _isNearBottom;
  window._scrollToBottom = _scrollToBottom;
  window.setSaveStatus = setSaveStatus;
  window.updateBlankEditState = updateBlankEditState;
  window.updateAiProofreadButtonState = updateAiProofreadButtonState;
  window.clearAiProofreadPanel = clearAiProofreadPanel;
  window.selectAiProofreadIssue = selectAiProofreadIssue;
  window.runAiProofread = runAiProofread;
  window.applyAiProofreadFixes = applyAiProofreadFixes;
  window.updateBlankViewMode = updateBlankViewMode;
  window.insertAtCursor = insertAtCursor;
  window._autoUppercaseAfterDot = _autoUppercaseAfterDot;
  window._autoScrollEditorIfNeeded = _autoScrollEditorIfNeeded;
  window._fixDashIfTimeHeaderAtCursor = _fixDashIfTimeHeaderAtCursor;
  window.updateSuggestFromCursor = updateSuggestFromCursor;
  window.initCorrIdSuggestToggle = initCorrIdSuggestToggle;
  window.setSuggest = setSuggest;
  window.setSuggestInput = setSuggestInput;
  window.saveNow = saveNow;
  window.scheduleSave = scheduleSave;
  window.updateBlankDirtyUi = updateBlankDirtyUi;
  window.extractLastTimeHeader = extractLastTimeHeader;
  window.hasPendingInterceptChanges = hasPendingInterceptChanges;
  window.normalizeTimeOnInput = normalizeTimeOnInput;
  window.normalizeTimeInText = normalizeTimeInText;
  window._ensureActiveItemOpen = _ensureActiveItemOpen;
  window.renderSuggest = renderSuggest;
  window.renderSuggestInput = renderSuggestInput;
  window.acceptSuggest = acceptSuggest;
  window.acceptSuggestInput = acceptSuggestInput;
})();
