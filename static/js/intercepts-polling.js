(function () {
  "use strict";

function _scheduleItemPoll(delayMs) {
  if (POLL_TIMER) clearTimeout(POLL_TIMER);
  if (!ACTIVE_SESSION_ID || !ACTIVE_CATALOG_ID || !ACTIVE_ITEM_ID) return;
  POLL_TIMER = setTimeout(() => {
    pollItemLiveWait();
  }, delayMs == null ? 120 : delayMs);
}

async function pollItemLiveWait() {
  if (!ACTIVE_SESSION_ID || !ACTIVE_CATALOG_ID || !ACTIVE_ITEM_ID) return;
  if (document.hidden) {
    _scheduleItemPoll(ITEM_POLL_MS_MAX);
    return;
  }
  if (POLL_INFLIGHT || ITEM_LIVE_INFLIGHT) {
    _scheduleItemPoll(200);
    return;
  }
  ITEM_LIVE_INFLIGHT = true;
  try {
    const data = await apiGetWithTimeout(
      `/api/intercepts/item/wait?item_id=${encodeURIComponent(ACTIVE_ITEM_ID)}&item_sig=${encodeURIComponent(
        LAST_REMOTE_SIG || ""
      )}&timeout=25`,
      32000
    );
    if (data && data.changed) {
      await pollItemOnce();
      return;
    }
  } catch (_) {
    // сеть/таймаут — короткий backoff и снова wait
  } finally {
    ITEM_LIVE_INFLIGHT = false;
  }
  _scheduleItemPoll(120);
}

async function pollItemOnce() {
  if (!ACTIVE_SESSION_ID || !ACTIVE_CATALOG_ID) return;
  if (document.hidden) {
    _scheduleItemPoll(ITEM_POLL_MS_MAX);
    return;
  }
  if (POLL_INFLIGHT) {
    _scheduleItemPoll(ITEM_POLL_MS);
    return;
  }
  POLL_INFLIGHT = true;
  let unchanged = false;
  let othersTyping = false;
  const epochAtRequest = ITEM_SYNC_EPOCH;
  const itemIdAtRequest = Number(ACTIVE_ITEM_ID || 0);
  try {
    const data = await apiGet(
      `/api/intercepts/item?session_id=${encodeURIComponent(ACTIVE_SESSION_ID)}&catalog_id=${encodeURIComponent(
        ACTIVE_CATALOG_ID
      )}&item_sig=${encodeURIComponent(LAST_REMOTE_SIG || "")}`
    );
    // Пока ответ шёл, оператор мог сохранить бланк или открыть другой:
    // ответ описывает состояние до этого, применять его нельзя.
    if (epochAtRequest !== ITEM_SYNC_EPOCH || itemIdAtRequest !== Number(ACTIVE_ITEM_ID || 0)) {
      return;
    }
    if (data && data.unchanged) {
      if (data && typeof data.assignments === "object") {
        ACTIVE_ASSIGNMENTS = data.assignments || {};
      }
      const typing = Array.isArray(data.typing) ? data.typing : [];
      othersTyping = typing.length > 0;
      const ti = $("typing-indicator");
      if (ti) ti.textContent = typing.length ? `печатает: ${typing.join(", ")}` : "";
      unchanged = true;
      return;
    }
    _itemCacheSet(_itemCacheKey(ACTIVE_SESSION_ID, ACTIVE_CATALOG_ID, ACTIVE_CAT), data);
    const item = data.item || {};
    if (data && typeof data.assignments === "object") {
      const next = data.assignments || {};
      const prevDuty = String((ACTIVE_ASSIGNMENTS || {}).duty || "");
      const nextDuty = String((next || {}).duty || "");
      ACTIVE_ASSIGNMENTS = next;
      if (prevDuty !== nextDuty) {
        applyCallsignScope();
      }
    }
    const updatedAt = String(item.updated_at || "");
    const typing = Array.isArray(data.typing) ? data.typing : [];
    othersTyping = typing.length > 0;
    const ti = $("typing-indicator");
    if (ti) {
      if (typing.length) {
        ti.textContent = `печатает: ${typing.join(", ")}`;
      } else {
        ti.textContent = "";
      }
    }
    const nextSig = _contentSig(updatedAt, item.content || "");
    if (nextSig === LAST_REMOTE_SIG && updatedAt && updatedAt === LAST_REMOTE_UPDATED_AT) {
      unchanged = true;
      return;
    }

    const ta = $("intercept-text");
    const focused = document.activeElement === ta;
    const dirty = (ta && (ta.value || "") !== LAST_SAVED);
    const remoteContent = String(item.content || "");
    const currentContent = String(ta.value || "");
    const remoteIsNewer = !!(updatedAt && LAST_REMOTE_UPDATED_AT && updatedAt > LAST_REMOTE_UPDATED_AT);
    // Ответ отстал от того, что уже известно клиенту (например пришёл после
    // сохранения). Такой текст нельзя ни ставить в поле, ни считать чужой правкой.
    const remoteIsOlder = !!(updatedAt && LAST_REMOTE_UPDATED_AT && updatedAt < LAST_REMOTE_UPDATED_AT);
    if (remoteIsOlder) {
      unchanged = true;
      return;
    }
    const previewBox = $("intercept-preview");
    const previewVisible = previewBox && previewBox.style.display !== "none";
    const wrap = $("intercept-text-wrapper");
    const editorVisible = wrap && wrap.style.display !== "none" && ta && !ta.disabled;

    if ((!focused && !dirty) || (remoteIsNewer && !dirty)) {
      ta.value = remoteContent;
      LAST_SAVED = remoteContent;
      LAST_REMOTE_UPDATED_AT = updatedAt;
      LAST_REMOTE_SIG = nextSig;
      setSaveStatus("saved", updatedAt ? `Последнее сохранение: ${fmtShift(updatedAt)}` : "");
      HAS_REMOTE_NEW = false;
      const badge = $("remote-new-badge");
      if (badge) badge.style.display = "none";
      const mergeBtn = $("merge-updates-btn");
      if (mergeBtn) mergeBtn.style.display = "none";
      if (previewVisible) {
        _renderPreview();
        requestAnimationFrame(() => _scrollToBottom(previewBox));
      } else if (editorVisible) {
        requestAnimationFrame(() => {
          try { ta.scrollTop = ta.scrollHeight; } catch (_) { }
        });
      }
      return;
    }

    const lastSaved = String(LAST_SAVED || "");

    if (remoteContent !== currentContent && remoteContent.length > lastSaved.length) {
      // Дописку другого оператора можно перенести в поле только если локальный и
      // серверный тексты выросли из одной основы. Пустая основа годится лишь для
      // пустого поля: иначе «хвостом» окажется весь бланк и он задвоится.
      const sharedBase =
        (lastSaved !== "" || currentContent === "") &&
        remoteContent.startsWith(lastSaved) &&
        currentContent.startsWith(lastSaved);
      if (sharedBase) {
        const newLines = remoteContent.slice(lastSaved.length);

        if (newLines.trim()) {
          const pos = ta.selectionStart || 0;
          const end = ta.selectionEnd || 0;
          const scroll = ta.scrollTop || 0;
          const normalizedNew = newLines.trim();
          const normalizedCurrent = currentContent.trim();

          if (!normalizedCurrent.endsWith(normalizedNew)) {
            let newText = currentContent;

            if (newText && !newText.endsWith("\n")) {
              newText += "\n";
            }
            newText += normalizedNew;

            ta.value = newText;

            try {
              if (pos >= currentContent.length - 20) {
                ta.setSelectionRange(newText.length, newText.length);
              } else {
                ta.setSelectionRange(Math.min(pos, newText.length), Math.min(end, newText.length));
                ta.scrollTop = scroll;
              }

              requestAnimationFrame(() => {
                try {
                  ta.scrollTop = ta.scrollHeight;
                } catch (_) { }
              });
            } catch (_) { }

            setSaveStatus("saved", updatedAt ? `Последнее сохранение: ${fmtShift(updatedAt)}` : "");
            if (previewVisible) {
              _renderPreview();
              requestAnimationFrame(() => _scrollToBottom(previewBox));
            }

            const badge = $("remote-new-badge");
            if (badge) {
              badge.style.display = "";
              badge.textContent = "обновлено";
              setTimeout(() => {
                if (badge && badge.textContent === "обновлено") {
                  badge.style.display = "none";
                }
              }, 1500);
            }
          }
        }
      } else {
        HAS_REMOTE_NEW = true;
        const badge = $("remote-new-badge");
        if (badge) badge.style.display = "";
        const mergeBtn = $("merge-updates-btn");
        if (mergeBtn) mergeBtn.style.display = "";
      }
    } else if (remoteContent !== currentContent && remoteContent !== lastSaved) {
      HAS_REMOTE_NEW = true;
      const badge = $("remote-new-badge");
      if (badge) badge.style.display = "";
      const mergeBtn = $("merge-updates-btn");
      if (mergeBtn) mergeBtn.style.display = "";
    }

    LAST_REMOTE_UPDATED_AT = updatedAt;
    LAST_REMOTE_SIG = nextSig;
  } catch (_) {
    // молча
  } finally {
    POLL_INFLIGHT = false;
    if (unchanged) {
      ITEM_POLL_UNCHANGED_STREAK += 1;
      const taFocus = document.activeElement === $("intercept-text");
      const backoffStep = taFocus || othersTyping || HAS_REMOTE_NEW ? 200 : 400;
      ITEM_POLL_MS = Math.min(
        ITEM_POLL_MS_MAX,
        ITEM_POLL_MS_MIN + ITEM_POLL_UNCHANGED_STREAK * backoffStep
      );
      if (taFocus || othersTyping || HAS_REMOTE_NEW) {
        ITEM_POLL_MS = Math.min(ITEM_POLL_MS, ITEM_POLL_MS_MIN);
      }
    } else {
      ITEM_POLL_UNCHANGED_STREAK = 0;
      ITEM_POLL_MS = othersTyping || HAS_REMOTE_NEW ? ITEM_POLL_MS_FAST : ITEM_POLL_MS_MIN;
    }
    _scheduleItemPoll();
  }
}

async function setTyping(typing) {
  if (!ACTIVE_SESSION_ID || !ACTIVE_CATALOG_ID) return;
  try {
    const ta = $("intercept-text");
    const currentHeader = ta ? extractLastTimeHeader(String(ta.value || "")) : "";
    await apiPost("/api/intercepts/typing", {
      session_id: ACTIVE_SESSION_ID,
      catalog_id: ACTIVE_CATALOG_ID,
      typing: !!typing,
      time_header: currentHeader || "",
    });
  } catch (_) {
    // ignore
  }
}

function scheduleTypingPing() {
  if (!CAN_EDIT || ACTIVE_CLOSED) return;
  if (!ACTIVE_SESSION_ID || !ACTIVE_CATALOG_ID) return;
  // Не отправляем typing, если бланк неактивен (переключатель выключен)
  const ta = $("intercept-text");
  if (ta && ta.disabled) return;
  IS_TYPING = true;
  const now = Date.now();
  const currentHeader = ta ? extractLastTimeHeader(String(ta.value || "")) : "";
  const headerChanged = !!currentHeader && currentHeader !== LAST_TYPING_HEADER_SENT;
  // не чаще 1 раза в ~1.2 секунды (НО: если поменялся блок времени — отправляем сразу)
  if (headerChanged || now - LAST_TYPING_SENT > 650) {
    LAST_TYPING_SENT = now;
    LAST_TYPING_HEADER_SENT = currentHeader || LAST_TYPING_HEADER_SENT;
    apiPost("/api/intercepts/typing", {
      session_id: ACTIVE_SESSION_ID,
      catalog_id: ACTIVE_CATALOG_ID,
      typing: true,
      time_header: currentHeader || "",
    }).catch(() => { });
  }
  if (TYPING_TIMER) clearTimeout(TYPING_TIMER);
  TYPING_TIMER = setTimeout(() => {
    IS_TYPING = false;
    apiPost("/api/intercepts/typing", {
      session_id: ACTIVE_SESSION_ID,
      catalog_id: ACTIVE_CATALOG_ID,
      typing: false,
      time_header: LAST_TYPING_HEADER_SENT || "",
    }).catch(() => { });
  }, 2200);
}

function startPollingCurrent() {
  stopPolling();
  if (!ACTIVE_SESSION_ID || !ACTIVE_CATALOG_ID) return;
  ITEM_POLL_MS = ITEM_POLL_MS_MIN;
  ITEM_POLL_UNCHANGED_STREAK = 0;
  pollItemOnce();
}




  window._scheduleItemPoll = _scheduleItemPoll;
  window.pollItemOnce = pollItemOnce;
  window.startPollingCurrent = startPollingCurrent;
  window.scheduleTypingPing = scheduleTypingPing;
  window.setTyping = setTyping;
})();
