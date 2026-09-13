(function () {
  "use strict";

function _resolveDutyTarget(c) {
  const activeFrequency = String((ACTIVE_CAT && ACTIVE_CAT.frequency) || "").trim();
  const activeGroup = String((ACTIVE_CAT && ACTIVE_CAT.group_code) || "").trim();
  if (activeFrequency && activeGroup) {
    return { frequency: activeFrequency, group: activeGroup };
  }
  const itemFrequency = String((c && c.frequency) || "").trim();
  const itemGroup = String((c && c.group_code) || "").trim();
  if (itemFrequency && itemGroup) {
    return { frequency: itemFrequency, group: itemGroup };
  }
  return { frequency: "", group: "" };
}

async function toggleInterceptsDuty(c) {
  if (!c) return;
  const target = _resolveDutyTarget(c);
  const frequency = String(target.frequency || "").trim();
  const group = String(target.group || "").trim();
  if (!frequency || !group) {
    setText("intercepts-status", "Не выбрана частота/группа для назначения Опер.д.");
    return;
  }
  try {
    await apiPost("/api/analysis/assign", {
      frequency,
      group,
      role_type: "duty",
      code: String(c.code || "").trim(),
      mode: "toggle",
    });
    if (typeof loadState === "function") await loadState(ACTIVE_SESSION_ID || null);
  } catch (e) {
    setText("intercepts-status", `Ошибка: ${e.message || e}`);
  }
}

function renderCallsigns(list) {
  CALLSIGNS = list || [];
  const wrap = $("cs-list");
  if (!wrap) return;
  wrap.innerHTML = "";
  if (!CALLSIGNS.length) {
    wrap.innerHTML = `<div class="md3-callsign-empty" role="status">Пока пусто</div>`;
    const dutyEl = $("cs-duty");
    if (dutyEl) {
      dutyEl.textContent = "";
      dutyEl.style.display = "none";
    }
    return;
  }

  // duty officer display
  try {
    const dutyEl = $("cs-duty");
    const dutyCode = String((ACTIVE_ASSIGNMENTS || {}).duty || "").trim();
    if (dutyEl) {
      if (dutyCode) {
        const found = (CALLSIGNS || []).find((x) => String(x.code || "") === dutyCode);
        const name = found ? String(found.label || "") : "";
        dutyEl.innerHTML = `<i class="bi bi-headset me-1"></i><strong>Опер.д.</strong>: ${escapeHtml(
          name || "—"
        )} <span class="wp-mono">(${escapeHtml(dutyCode)})</span>`;
        dutyEl.style.display = "";
      } else {
        dutyEl.textContent = "";
        dutyEl.style.display = "none";
      }
    }
  } catch (_) { }

  for (const c of CALLSIGNS) {
    const row = document.createElement("div");
    row.className = "callsign-card md3-callsign-card";
    const dutyCode = String((ACTIVE_ASSIGNMENTS || {}).duty || "").trim();
    const isDuty = dutyCode && String(c.code || "") === dutyCode;
    const tag = String(c.tag || "").trim();
    const tagColor = String(c.tag_color || "").trim();
    const tagDesc = String(c.tag_desc || "").trim();
    const dutyTarget = _resolveDutyTarget(c);
    const canDuty = !!(String(dutyTarget.frequency || "").trim() && String(dutyTarget.group || "").trim());
    const csLabel = String(c.label || "").trim();
    const csCode = String(c.code || "").trim();
    row.dataset.callsignCode = csCode;
    row.innerHTML = `
      <div class="callsign-card-header">
        <div class="min-w-0">
          <div class="callsign-card-title">
            <i class="bi bi-person-circle text-primary"></i>
            <span>${escapeHtml(csLabel || "Без названия")}</span>
            ${isDuty ? '<span class="badge text-bg-primary"><i class="bi bi-headset me-1"></i>Опер.д.</span>' : ""}
            ${tag ? tagBadgeHtml(tag, tagColor, tagDesc) : ""}
          </div>
          <div class="callsign-card-meta small wp-subtle wp-mono">
            <span class="cs-code-link" data-code="${escapeHtml(csCode)}" role="button" title="Вставить код">(${escapeHtml(csCode)})</span>
          </div>
        </div>
        <div class="callsign-card-actions">
          <button class="btn btn-outline-primary btn-sm callsign-action-btn" data-action="settings" title="Настроить">
            <i class="bi bi-sliders"></i>
          </button>
        </div>
      </div>
      <div class="callsign-card-settings" data-role="settings">
        <div class="small fw-semibold mb-1">
          <i class="bi bi-gear me-1"></i>Настройка позывного
        </div>
        <div class="d-flex align-items-center gap-2 mb-2 flex-wrap">
          <button class="btn btn-outline-secondary btn-sm callsign-action-btn" data-action="settings-tag" type="button">
            <i class="bi bi-tag me-1"></i>Тег
          </button>
          <button class="btn btn-outline-primary btn-sm callsign-action-btn" data-action="settings-duty" type="button">
            <i class="bi bi-headset me-1"></i>Опер.д.
          </button>
        </div>
        <label class="form-label small mb-1">Название позывного</label>
        <div class="input-group input-group-sm">
          <input class="form-control" data-role="label-input" value="${escapeHtml(csLabel)}" placeholder="Введите позывной" />
          <button class="btn btn-primary" data-action="save" type="button">
            <i class="bi bi-check2 me-1"></i>Сохранить
          </button>
        </div>
        <div class="d-flex align-items-center gap-2 mt-2">
          <button class="btn btn-outline-danger btn-sm callsign-action-btn" data-action="del" title="Удалить">
            <i class="bi bi-trash me-1"></i>Удалить
          </button>
          <button class="btn btn-outline-secondary btn-sm callsign-action-btn" data-action="close" title="Закрыть">
            Закрыть
          </button>
        </div>
      </div>
    `;
    row.querySelector(".cs-code-link")?.addEventListener("click", () => insertCallsignAtCursor(csCode));
    const tagBtn = row.querySelector('[data-action="settings-tag"]');
    if (tagBtn) tagBtn.addEventListener("click", () => {
      if (typeof openCallsignTagModal === "function") {
        openCallsignTagModal(c, () => { if (typeof loadState === "function") loadState(ACTIVE_SESSION_ID || null); });
      }
    });
    const dutyBtn = row.querySelector('[data-action="settings-duty"]');
    if (dutyBtn) dutyBtn.addEventListener("click", () => toggleInterceptsDuty(c));
    const settingsEl = row.querySelector('[data-role="settings"]');
    const settingsBtn = row.querySelector('[data-action="settings"]');
    const closeBtn = row.querySelector('[data-action="close"]');
    const labelInput = row.querySelector('[data-role="label-input"]');
    const toggleSettings = (forceOpen = null) => {
      if (!settingsEl) return;
      const nowOpen = settingsEl.classList.contains("is-open");
      const shouldOpen = forceOpen === null ? !nowOpen : !!forceOpen;
      settingsEl.classList.toggle("is-open", shouldOpen);
      settingsBtn?.classList.toggle("active", shouldOpen);
      if (shouldOpen && labelInput) {
        labelInput.focus();
        labelInput.select();
      }
    };
    if (settingsBtn) settingsBtn.addEventListener("click", () => toggleSettings());
    if (closeBtn) closeBtn.addEventListener("click", () => toggleSettings(false));
    row.querySelector('[data-action="save"]').addEventListener("click", async () => {
      try {
        await _saveCallsignProfileLabel(c, labelInput?.value);
      } catch (e) {
        setText("intercepts-status", `Ошибка: ${e.message || e}`);
      }
    });
    if (labelInput) {
      labelInput.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" && !ev.isComposing && ev.keyCode !== 229) {
          ev.preventDefault();
          row.querySelector('[data-action="save"]')?.click();
        }
        if (ev.key === "Escape") {
          ev.preventDefault();
          toggleSettings(false);
        }
      });
    }
    row.querySelector('[data-action="del"]').addEventListener("click", async () => {
      if (!confirm(`Удалить позывной ${csLabel} (${csCode})?`)) return;
      try {
        await apiPost("/api/intercepts/callsigns/delete", { id: c.id });
        await loadState(ACTIVE_SESSION_ID || null);
      } catch (e) {
        setText("intercepts-status", `Ошибка: ${e.message || e}`);
      }
    });
    wrap.appendChild(row);
  }
}

function openCallsignSettingsByCode(code) {
  const normalized = String(code || "").replace(/\D+/g, "");
  if (!normalized) return false;
  if (_ixIsMessengerUi() && typeof openCallsignProfile === "function") {
    // Профиль в сайдбаре — раскрываем панель, иначе ПКМ «тихий» и нужен клик «Чаты».
    if (typeof ixExpandGroupsDrawer === "function") ixExpandGroupsDrawer();
    setIxSidebarView("callsigns");
    openCallsignProfile(normalized, { edit: true });
    return true;
  }
  const wrap = $("cs-list");
  // Если панель позывных скрыта из интерфейса — не пытаемся открывать её настройки.
  if (!wrap || wrap.offsetParent === null) return false;
  const esc = (window.CSS && typeof window.CSS.escape === "function")
    ? window.CSS.escape(normalized)
    : normalized.replace(/["\\]/g, "\\$&");
  const targetCard = wrap.querySelector(`[data-callsign-code="${esc}"]`);
  if (!targetCard) return false;
  const settingsBtn = targetCard.querySelector('[data-action="settings"]');
  const settingsBox = targetCard.querySelector('[data-role="settings"]');
  if (settingsBtn && settingsBox && !settingsBox.classList.contains("is-open")) {
    settingsBtn.click();
  }
  targetCard.scrollIntoView({ behavior: "smooth", block: "center" });
  const input = targetCard.querySelector('[data-role="label-input"]');
  if (input) {
    try {
      input.focus();
      input.select();
    } catch (_) { }
  }
  return true;
}

function _extractCallsignCodeFromSelection(textarea) {
  if (!textarea) return "";
  const sel = String(textarea.value || "").slice(textarea.selectionStart || 0, textarea.selectionEnd || 0);
  let m = sel.match(/\(?\s*(\d{2,8})\s*\)?/);
  if (m) return String(m[1] || "").trim();
  const pos = Number(textarea.selectionStart || 0);
  const src = String(textarea.value || "");
  const from = Math.max(0, pos - 48);
  const to = Math.min(src.length, pos + 48);
  const near = src.slice(from, to);
  m = near.match(/\((\d{2,8})\)/);
  if (m) return String(m[1] || "").trim();
  // Каретка внутри/рядом с (ID) — ПКМ без выделения (иначе браузерное меню).
  let best = "";
  let bestDist = Infinity;
  const re = /\((\d{2,8})\)/g;
  let mm;
  while ((mm = re.exec(src))) {
    const start = mm.index;
    const end = start + mm[0].length;
    const dist = pos < start ? start - pos : pos > end ? pos - end : 0;
    if (dist < bestDist) {
      bestDist = dist;
      best = String(mm[1] || "").trim();
    }
  }
  return bestDist <= 1 ? best : "";
}

function renderCallsignCardsModal(list, preferredCode = "") {
  const wrap = $("callsign-cards-modal-list");
  if (!wrap) return;
  const rows = Array.isArray(list) ? list : [];
  const preferred = String(preferredCode || "").replace(/\D+/g, "").trim();
  const hasPreferredInRows = !!(
    preferred &&
    rows.some((x) => String((x && x.code) || "").trim() === preferred)
  );
  wrap.innerHTML = "";
  if (preferred && !hasPreferredInRows) {
    const addCol = document.createElement("div");
    addCol.className = "col-12";
    addCol.innerHTML = `
      <div class="card border border-primary-subtle bg-primary-subtle">
        <div class="card-body py-2 px-3">
          <div class="fw-semibold mb-2">
            <i class="bi bi-plus-circle me-1"></i>Позывной (${escapeHtml(preferred)}) не найден
          </div>
          <div class="small text-muted mb-2">Можно добавить новый позывной в текущую частоту/группу.</div>
          <div class="input-group input-group-sm">
            <input type="text" class="form-control" data-add-role="label" placeholder="Название позывного, например: Джон" />
            <input type="text" class="form-control wp-mono" data-add-role="code" value="${escapeHtml(preferred)}" style="max-width:120px;" />
            <button class="btn btn-primary" data-add-role="submit" type="button">
              <i class="bi bi-plus-lg me-1"></i>Добавить
            </button>
          </div>
        </div>
      </div>
    `;
    const labelInput = addCol.querySelector('[data-add-role="label"]');
    const codeInput = addCol.querySelector('[data-add-role="code"]');
    const submitBtn = addCol.querySelector('[data-add-role="submit"]');
    const submit = async () => {
      const label = String(labelInput?.value || "").trim();
      const code = String(codeInput?.value || "").trim();
      if (!label || !code) return;
      if (submitBtn) submitBtn.disabled = true;
      try {
        const res = await addCallsignByValues(label, code);
        if (!res || !res.ok) {
          setText("intercepts-status", (res && res.error) || "Не удалось добавить позывной");
          return;
        }
        await loadState(ACTIVE_SESSION_ID || null);
        const modalEl = $("callsignCardsModal");
        if (modalEl && window.bootstrap && window.bootstrap.Modal) {
          const modal = window.bootstrap.Modal.getOrCreateInstance(modalEl);
          modal.hide();
        }
        setTimeout(() => {
          openCallsignSettingsByCode(res.code || code);
        }, 60);
      } catch (e) {
        setText("intercepts-status", `Ошибка: ${e.message || e}`);
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    };
    if (submitBtn) submitBtn.addEventListener("click", submit);
    if (labelInput) {
      labelInput.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" && !ev.isComposing && ev.keyCode !== 229) {
          ev.preventDefault();
          submit();
        }
      });
    }
    if (codeInput) {
      codeInput.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" && !ev.isComposing && ev.keyCode !== 229) {
          ev.preventDefault();
          submit();
        }
      });
    }
    wrap.appendChild(addCol);
  }
  if (!rows.length) {
    if (!preferred || hasPreferredInRows) {
      wrap.innerHTML = `<div class="col-12"><div class="small wp-subtle">Нет позывных для текущей группы</div></div>`;
    }
    return;
  }
  const ordered = preferred
    ? rows.slice().sort((a, b) => {
      const ac = String(a && a.code ? a.code : "").trim();
      const bc = String(b && b.code ? b.code : "").trim();
      if (ac === preferred && bc !== preferred) return -1;
      if (bc === preferred && ac !== preferred) return 1;
      return 0;
    })
    : rows;

  // Время "Тег в эфире" подгружается заранее в openCallsignCardsModal.

  for (const c of ordered) {
    const col = document.createElement("div");
    col.className = "col-12 col-md-6";
    const label = String(c && c.label ? c.label : "").trim();
    const code = String(c && c.code ? c.code : "").trim();
    const tag = String(c && c.tag ? c.tag : "").trim();
    const tagColor = String(c && c.tag_color ? c.tag_color : "").trim();
    const tagDesc = String(c && c.tag_desc ? c.tag_desc : "").trim();
    const isPreferred = preferred && code === preferred;
    const dutyCode = String((ACTIVE_ASSIGNMENTS || {}).duty || "").trim();
    const isDuty = !!dutyCode && code === dutyCode;
    const lastSeenRaw = String((CALLSIGN_LAST_SEEN && CALLSIGN_LAST_SEEN[code]) || "").trim();
    const lastSeenText = lastSeenRaw ? fmtMskLabel(lastSeenRaw) : "н/д";
    col.innerHTML = `
      <div class="card border-0 shadow-sm h-100 md3-callsign-modal-card ${isPreferred ? "md3-callsign-modal-card--preferred" : ""}">
        <div class="card-body py-2 px-3">
          <div class="d-flex align-items-center justify-content-between gap-2">
            <div class="fw-semibold d-flex align-items-center gap-2 flex-wrap md3-callsign-modal-card-title">
              <span class="md3-callsign-modal-avatar" aria-hidden="true"><i class="bi bi-person-circle"></i></span>
              ${escapeHtml(label || "Без названия")}
              ${tag ? tagBadgeHtml(tag, tagColor, tagDesc) : ""}
              ${isDuty ? '<span class="badge rounded-pill md3-callsign-badge-duty"><i class="bi bi-headset me-1"></i>Опер.д.</span>' : ""}
            </div>
            <span class="badge md3-callsign-code-badge wp-mono">(${escapeHtml(code)})</span>
          </div>
          <div class="small md3-callsign-modal-meta mt-1 d-flex align-items-center gap-1">
            <i class="bi bi-clock-history"></i>
            <span>Тег в эфире: ${escapeHtml(lastSeenText)}</span>
          </div>
          <div class="dropdown mt-2">
            <button class="btn btn-primary btn-sm dropdown-toggle md3-callsign-modal-actions-btn" type="button" data-bs-toggle="dropdown" aria-expanded="false" title="Действия с позывным">
              <i class="bi bi-list-ul me-1"></i>Действия
            </button>
            <ul class="dropdown-menu dropdown-menu-end md3-callsign-dropdown">
              <li>
                <button class="dropdown-item" type="button" data-cs-action="insert">
                  <i class="bi bi-clipboard-plus me-2 text-primary"></i>Вставить
                </button>
              </li>
              <li>
                <button class="dropdown-item" type="button" data-cs-action="tag">
                  <i class="bi bi-tag me-2 text-secondary"></i>Тег
                </button>
              </li>
              <li>
                <button class="dropdown-item" type="button" data-cs-action="edit">
                  <i class="bi bi-pencil me-2 text-secondary"></i>Изменить
                </button>
              </li>
              <li>
                <button class="dropdown-item" type="button" data-cs-action="duty">
                  <i class="bi bi-headset me-2 text-secondary"></i>Опер.д.
                </button>
              </li>
              <li><hr class="dropdown-divider"></li>
              <li>
                <button class="dropdown-item text-danger" type="button" data-cs-action="delete">
                  <i class="bi bi-trash me-2"></i>Удалить
                </button>
              </li>
            </ul>
          </div>
        </div>
      </div>
    `;
    const insertBtn = col.querySelector('[data-cs-action="insert"]');
    if (insertBtn) {
      insertBtn.addEventListener("click", () => {
        if (code) insertCallsignAtCursor(code);
      });
    }
    const tagBtn = col.querySelector('[data-cs-action="tag"]');
    if (tagBtn) {
      tagBtn.addEventListener("click", () => {
        if (typeof openCallsignTagModal === "function") {
          openCallsignTagModal(c, () => {
            if (typeof loadState === "function") loadState(ACTIVE_SESSION_ID || null);
            renderCallsignCardsModal(CALLSIGNS, preferred);
          });
        }
      });
    }
    const editBtn = col.querySelector('[data-cs-action="edit"]');
    if (editBtn) {
      editBtn.addEventListener("click", async () => {
        const next = String(
          window.prompt("Новое название позывного:", label || "") || ""
        ).trim();
        if (!next || next === label) return;
        try {
          await apiPost("/api/intercepts/callsigns/update", { id: c.id, label: next });
          await loadState(ACTIVE_SESSION_ID || null);
          renderCallsignCardsModal(CALLSIGNS, preferred || code);
        } catch (e) {
          setText("intercepts-status", `Ошибка: ${e.message || e}`);
        }
      });
    }
    const dutyBtn = col.querySelector('[data-cs-action="duty"]');
    if (dutyBtn) {
      dutyBtn.addEventListener("click", async () => {
        try {
          await toggleInterceptsDuty(c);
          renderCallsignCardsModal(CALLSIGNS, preferred || code);
        } catch (e) {
          setText("intercepts-status", `Ошибка: ${e.message || e}`);
        }
      });
    }
    const delBtn = col.querySelector('[data-cs-action="delete"]');
    if (delBtn) {
      delBtn.addEventListener("click", async () => {
        if (!confirm(`Удалить позывной ${label || "—"} (${code})?`)) return;
        try {
          await apiPost("/api/intercepts/callsigns/delete", { id: c.id });
          await loadState(ACTIVE_SESSION_ID || null);
          renderCallsignCardsModal(CALLSIGNS, preferred);
        } catch (e) {
          setText("intercepts-status", `Ошибка: ${e.message || e}`);
        }
      });
    }
    col.addEventListener("dblclick", (ev) => {
      ev.preventDefault();
      if (code) insertCallsignAtCursor(code);
    });
    wrap.appendChild(col);
  }
}

async function preloadCallsignLastSeen(rows) {
  try {
    const freq = String((ACTIVE_CAT && ACTIVE_CAT.frequency) || "").trim();
    const grp = String((ACTIVE_CAT && ACTIVE_CAT.group_code) || "").trim();
    const codes = (rows || [])
      .map((c) => String((c && c.code) || "").trim())
      .filter(Boolean)
      .sort();
    const key = `${freq}|${grp}|${codes.join(",")}`;
    if (!freq || !grp) {
      CALLSIGN_LAST_SEEN = {};
      CALLSIGN_LAST_SEEN_KEY = "";
      return false;
    }
    if (CALLSIGN_LAST_SEEN_KEY && CALLSIGN_LAST_SEEN_KEY === key) {
      return false;
    }
    if (!codes.length) {
      CALLSIGN_LAST_SEEN = {};
      CALLSIGN_LAST_SEEN_KEY = key;
      return true;
    }
    const res = await apiPost("/api/intercepts/callsigns/last-seen", {
      frequency: freq,
      group_code: grp,
      codes,
    });
    if (res && res.ok && res.last_seen && typeof res.last_seen === "object") {
      CALLSIGN_LAST_SEEN = res.last_seen;
      CALLSIGN_LAST_SEEN_KEY = key;
      return true;
    } else {
      CALLSIGN_LAST_SEEN = {};
      CALLSIGN_LAST_SEEN_KEY = key;
      return true;
    }
  } catch (_) {
    CALLSIGN_LAST_SEEN = {};
    CALLSIGN_LAST_SEEN_KEY = "";
    return false;
  }
}

async function openCallsignCardsModal(preferredCode = "") {
  const code = String(preferredCode || "").replace(/\D+/g, "").trim();
  if (_ixIsMessengerUi()) {
    setIxSidebarView("callsigns");
    if (code) {
      await openCallsignProfile(code);
    }
    return;
  }
  try {
    await preloadCallsignLastSeen(CALLSIGNS || []);
  } catch (_) { }
  renderCallsignCardsModal(CALLSIGNS, preferredCode);
  const modalEl = $("callsignCardsModal");
  if (!modalEl || !window.bootstrap || !window.bootstrap.Modal) return;
  const modal = window.bootstrap.Modal.getOrCreateInstance(modalEl);
  modal.show();
}

function callsignMatchesActiveScope(c) {
  if (!c) return false;
  // если группа не выбрана — не фильтруем (показываем всё как раньше)
  if (!ACTIVE_CAT || !String(ACTIVE_CAT.unit_name || "").trim()) return true;

  const activeUnit = _unitKey(ACTIVE_CAT.unit_name);
  const activeFreq = String(ACTIVE_CAT.frequency || "").trim();
  const activeGroup = String(ACTIVE_CAT.group_code || "").trim();

  const cu = _unitKey(c.unit_name);
  const cf = String(c.frequency || "").trim();
  const cg = String(c.group_code || "").trim();

  // При выбранной паре частота/группа — только записи этой пары.
  // Иначе один ID (Альтаир 1500) «висит» во всех группах и сохраняется в одну.
  if (activeFreq && activeGroup) {
    return cf === activeFreq && cg === activeGroup;
  }

  // "общие" (без привязки к подразделению/паре) показываем везде
  if (!cu && !cf && !cg) return true;

  // Позывной должен быть привязан к тому же подразделению
  if (!cu || cu !== activeUnit) return false;

  // Если позывной привязан к конкретной частоте/группе, проверяем совпадение
  if (cf && cg) {
    return cf === activeFreq && cg === activeGroup;
  }

  // Если позывной привязан только к подразделению (без частоты/группы), показываем для всех групп этого подразделения
  return true;
}

function _tagTextColor(bgHex) {
  try {
    const h = String(bgHex || "").trim();
    if (!/^#[0-9a-fA-F]{6}$/.test(h)) return "";
    const r = parseInt(h.slice(1, 3), 16);
    const g = parseInt(h.slice(3, 5), 16);
    const b = parseInt(h.slice(5, 7), 16);
    const yiq = (r * 299 + g * 587 + b * 114) / 1000;
    return yiq >= 140 ? "#111" : "#fff";
  } catch (_) {
    return "";
  }
}

function tagBadgeHtml(tag, color, desc) {
  const t = String(tag || "").trim();
  if (!t) return "";
  const d = String(desc || "").trim();
  const c = String(color || "").trim();
  const titleAttr = d ? ` title="${escapeHtml(d)}"` : "";
  if (c && /^#[0-9a-fA-F]{6}$/.test(c)) {
    const tc = _tagTextColor(c) || "#111";
    return `<span class="badge border"${titleAttr} style="background:${escapeHtml(
      c
    )}; color:${escapeHtml(tc)};">${escapeHtml(t)}</span>`;
  }
  return `<span class="badge text-bg-light border"${titleAttr}>${escapeHtml(t)}</span>`;
}

function applyCallsignScope() {
  const all = Array.isArray(ALL_CALLSIGNS) ? ALL_CALLSIGNS : [];
  renderCallsigns(all.filter(callsignMatchesActiveScope));
  if (_ixIsMessengerUi()) {
    renderMessengerCallsigns();
    if (IX_CALLSIGN_PROFILE_CODE) {
      const c = _getCallsignForProfile(IX_CALLSIGN_PROFILE_CODE);
      if (c) {
        IX_CALLSIGN_PROFILE_REF = c;
        renderCallsignProfile(c);
      } else closeCallsignProfile();
    }
  }
}

function _invalidateInterceptsClientCache() {
  if (typeof apiEtagCacheClear === "function") {
    apiEtagCacheClear("/api/intercepts/state");
    apiEtagCacheClear("/api/intercepts/catalog");
    apiEtagCacheClear("/api/intercepts/item");
  }
}

function _refreshCallsignsUi() {
  applyCallsignScope();
  _renderPreview();
  updateBlankCallsignLegend();
}

function _normalizeCallsignLabelInput(raw, code) {
  let label = String(raw || "").trim();
  if (!label || label === "Без названия") return "";
  const normCode = _normalizeCallsignCode(code);
  if (!normCode) return label;
  const codeRe = new RegExp(`^\\(?\\s*${normCode}\\s*\\)?\\s*[,:\\-–—\\s]+`, "i");
  label = label.replace(codeRe, "").trim();
  if (label === normCode) return "";
  return label;
}

function _callsignProfileDraft(code) {
  const normalized = _normalizeCallsignCode(code);
  if (!normalized || !_ixCallsignListScoped() || !ACTIVE_CAT) return null;
  // Подсказка названия из другой группы / unit-only — без чужого id.
  const pools = [
    ...(Array.isArray(CALLSIGNS) ? CALLSIGNS : []),
    ...(Array.isArray(ALL_CALLSIGNS) ? ALL_CALLSIGNS : []),
  ];
  const related = pools.find((x) => _normalizeCallsignCode(x && x.code) === normalized);
  return {
    id: 0,
    code: normalized,
    label: String((related && related.label) || "").trim(),
    unit_name: String(ACTIVE_CAT.unit_name || "").trim(),
    frequency: String(ACTIVE_CAT.frequency || "").trim(),
    group_code: String(ACTIVE_CAT.group_code || "").trim(),
    tag: "",
    tag_color: "",
    tag_desc: "",
  };
}

function _callsignBelongsToActivePair(c) {
  if (!c || !ACTIVE_CAT) return false;
  const af = String(ACTIVE_CAT.frequency || "").trim();
  const ag = String(ACTIVE_CAT.group_code || "").trim();
  if (!af || !ag) return false;
  return (
    String(c.frequency || "").trim() === af &&
    String(c.group_code || "").trim() === ag
  );
}

function _ixCallsignListScoped() {
  return !!(
    ACTIVE_CAT &&
    String(ACTIVE_CAT.frequency || "").trim() &&
    String(ACTIVE_CAT.group_code || "").trim()
  );
}

function _callsignBindingSubtitle(c) {
  const cf = String((c && c.frequency) || "").trim();
  const cg = String((c && c.group_code) || "").trim();
  const unit = String((c && c.unit_name) || "").trim();
  if (cf && cg) {
    return unit ? `${cf} · ${cg} · ${unit}` : `${cf} · ${cg}`;
  }
  if (unit) return unit;
  return "общий";
}

function _callsignInitials(label, code) {
  const lbl = String(label || "").trim();
  if (lbl) {
    const parts = lbl.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toLocaleUpperCase("ru-RU");
    return lbl.slice(0, 2).toLocaleUpperCase("ru-RU");
  }
  const c = String(code || "").trim();
  return c ? c.slice(-2) : "?";
}

function _parseCallsignUtcMs(raw) {
  const str = String(raw || "").trim();
  const m = str.match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})(?::(\d{2}))?/);
  if (!m) return NaN;
  return Date.UTC(
    Number(m[1]),
    Number(m[2]) - 1,
    Number(m[3]),
    Number(m[4]),
    Number(m[5]),
    Number(m[6] || 0)
  );
}

function _formatCallsignLastSeenLine(raw) {
  const str = String(raw || "").trim();
  if (!str) return "в эфире: нет данных";
  const utcMs = _parseCallsignUtcMs(str);
  if (!Number.isFinite(utcMs)) return `в эфире: ${fmtMskLabel(str)}`;
  const diff = Date.now() - utcMs;
  if (diff < 45 * 1000) return "был в эфире только что";
  const min = Math.floor(diff / 60000);
  if (min < 60) {
    const n = Math.max(1, min);
    return `был в эфире ${n} мин. назад`;
  }
  const hrs = Math.floor(min / 60);
  if (hrs < 48) return `был в эфире ${hrs} ч. назад`;
  const days = Math.floor(hrs / 24);
  if (days < 14) return `был в эфире ${days} дн. назад`;
  return `в эфире: ${fmtMskLabel(str)}`;
}

let _ixSideMenuCloseTimer = null;

function _ixDropdownCloseMs() {
  const root = document.querySelector(".md3-intercepts.ix-messenger-ui") || document.documentElement;
  const raw = getComputedStyle(root).getPropertyValue("--dropdown-close-dur").trim();
  const ms = parseFloat(raw);
  return Number.isFinite(ms) ? ms : 150;
}

function _ixSideMenuOpen() {
  const menu = $("ix-tg-side-menu");
  return !!(menu && menu.classList.contains("is-open"));
}

function _setIxSideMenuOpen(open) {
  const menu = $("ix-tg-side-menu");
  const btn = $("ix-tg-menu-btn");
  if (!menu) return;
  const on = !!open;

  if (_ixSideMenuCloseTimer) {
    clearTimeout(_ixSideMenuCloseTimer);
    _ixSideMenuCloseTimer = null;
  }

  if (on) {
    menu.classList.remove("is-closing");
    menu.classList.add("is-open");
    menu.setAttribute("aria-hidden", "false");
  } else if (menu.classList.contains("is-open") || menu.classList.contains("is-closing")) {
    menu.classList.remove("is-open");
    menu.classList.add("is-closing");
    menu.setAttribute("aria-hidden", "true");
    const closeMs = _ixDropdownCloseMs();
    _ixSideMenuCloseTimer = setTimeout(() => {
      menu.classList.remove("is-closing");
      _ixSideMenuCloseTimer = null;
    }, closeMs);
  } else {
    menu.classList.remove("is-open", "is-closing");
    menu.setAttribute("aria-hidden", "true");
  }

  if (btn) {
    btn.setAttribute("aria-expanded", on ? "true" : "false");
    btn.setAttribute("aria-label", on ? "Закрыть меню" : "Меню");
    const swap = btn.querySelector(".t-icon-swap");
    if (swap) swap.setAttribute("data-state", on ? "b" : "a");
  }
}

function setIxSidebarView(view) {
  const v = String(view || "chats").trim() || "chats";
  IX_SIDEBAR_VIEW = v === "callsigns" ? "callsigns" : "chats";
  _setIxSideMenuOpen(false);
  if (IX_SIDEBAR_VIEW !== "callsigns") closeCallsignProfile();

  const chatsView = $("tg-sidebar-view-chats");
  const csView = $("tg-sidebar-view-callsigns");
  const titleEl = $("ix-sidebar-title");
  const headTop = document.querySelector(".tg-sidebar__head-top");
  const menuBtn = $("ix-tg-menu-btn");
  const shiftRow = $("ix-sidebar-shift-row");
  const footChats = $("ix-sidebar-foot-chats");
  const sidebarHead = document.querySelector(".tg-sidebar__head");
  const isCallsigns = IX_SIDEBAR_VIEW === "callsigns";

  if (chatsView) chatsView.hidden = IX_SIDEBAR_VIEW !== "chats";
  if (csView) csView.hidden = IX_SIDEBAR_VIEW !== "callsigns";
  if (titleEl) titleEl.textContent = isCallsigns ? "Позывные" : "Чаты";
  if (menuBtn) menuBtn.hidden = isCallsigns;
  if (shiftRow) shiftRow.hidden = isCallsigns;
  if (footChats) footChats.hidden = isCallsigns;
  if (sidebarHead) sidebarHead.classList.toggle("tg-sidebar__head--callsigns", isCallsigns);

  document.querySelectorAll("#ix-tg-side-menu [data-ix-side-view], .ix-mobile-segments [data-ix-side-view]").forEach((el) => {
    const active = el.getAttribute("data-ix-side-view") === IX_SIDEBAR_VIEW;
    el.classList.toggle("tg-side-menu__item--active", active);
    el.classList.toggle("active", active);
    el.setAttribute("aria-current", active ? "page" : "false");
    if (el.getAttribute("role") === "tab") {
      el.setAttribute("aria-selected", active ? "true" : "false");
    }
  });

  const mobileSegments = document.querySelector(".ix-mobile-segments");
  if (mobileSegments) {
    mobileSegments.hidden = false;
  }
  if (headTop) {
    const mobileUi = document.body.classList.contains("ix-mobile-intercepts");
    headTop.hidden = isCallsigns && !mobileUi;
  }

  if (IX_SIDEBAR_VIEW === "callsigns") {
    if (
      document.body.classList.contains("ix-mobile-intercepts") &&
      typeof window.setInterceptsMobilePanel === "function"
    ) {
      window.setInterceptsMobilePanel("groups");
    }
    renderMessengerCallsigns();
    updateAddCallsignButton();
  }
}

async function renderMessengerCallsigns() {
  const listEl = $("tg-callsign-list");
  if (!listEl || !_ixIsMessengerUi()) return;
  if (IX_SIDEBAR_VIEW !== "callsigns") return;

  const hintEl = $("tg-callsigns-hint");
  const footCs = document.querySelector(".tg-callsigns-foot");
  const scoped = _ixCallsignListScoped();
  const q = String(($("callsigns-search-input") && $("callsigns-search-input").value) || "")
    .trim()
    .toLowerCase();

  let rows = scoped
    ? (Array.isArray(CALLSIGNS) ? CALLSIGNS.slice() : [])
    : (Array.isArray(ALL_CALLSIGNS) ? ALL_CALLSIGNS.slice() : []);

  if (q) {
    rows = rows.filter((c) => {
      const label = String((c && c.label) || "").toLowerCase();
      const code = String((c && c.code) || "").toLowerCase();
      return label.includes(q) || code.includes(q);
    });
  }

  rows.sort((a, b) => {
    const la = String((a && a.label) || "").localeCompare(String((b && b.label) || ""), "ru");
    if (la !== 0) return la;
    return String((a && a.code) || "").localeCompare(String((b && b.code) || ""), "ru");
  });

  if (scoped) {
    const freq = String(ACTIVE_CAT.frequency || "").trim();
    const grp = String(ACTIVE_CAT.group_code || "").trim();
    if (hintEl) {
      hintEl.textContent = `Частота ${freq} · группа ${grp}`;
    }
  } else if (hintEl) {
    hintEl.textContent = "Все позывные · выберите чат для времени в эфире";
  }

  if (footCs) footCs.hidden = !scoped;

  // duty (scoped)
  try {
    const dutyEl = $("cs-duty");
    const dutyCode = String((ACTIVE_ASSIGNMENTS || {}).duty || "").trim();
    if (dutyEl && scoped) {
      if (dutyCode) {
        const found = rows.find((x) => String(x.code || "") === dutyCode);
        const name = found ? String(found.label || "") : "";
        dutyEl.innerHTML = `<i class="bi bi-headset me-1"></i><strong>Опер.д.</strong>: ${escapeHtml(
          name || "—"
        )} <span class="wp-mono">(${escapeHtml(dutyCode)})</span>`;
        dutyEl.style.display = "";
      } else {
        dutyEl.textContent = "";
        dutyEl.style.display = "none";
      }
    } else if (dutyEl) {
      dutyEl.textContent = "";
      dutyEl.style.display = "none";
    }
  } catch (_) { }

  listEl.innerHTML = "";
  if (!rows.length) {
    listEl.innerHTML = `<div class="tg-callsign-empty" role="status">Позывные не найдены</div>`;
    updateAddCallsignButton();
    return;
  }

  for (const c of rows) {
    const label = String((c && c.label) || "").trim() || "Без названия";
    const code = String((c && c.code) || "").trim();
    const dutyCode = String((ACTIVE_ASSIGNMENTS || {}).duty || "").trim();
    const isDuty = scoped && dutyCode && code === dutyCode;
    const subtitle = scoped
      ? _formatCallsignLastSeenLine(CALLSIGN_LAST_SEEN && CALLSIGN_LAST_SEEN[code])
      : _callsignBindingSubtitle(c);
    const initials = _callsignInitials(label, code);
    const hue = _tgAvatarHue(code || label);

    const row = document.createElement("button");
    row.type = "button";
    row.className = "tg-contact-item";
    row.setAttribute("role", "listitem");
    if (code) row.dataset.callsignCode = code;
    row.innerHTML = `
      <span class="tg-contact-item__avatar" style="--tg-avatar-hue:${hue}">${escapeHtml(initials)}</span>
      <span class="tg-contact-item__body">
        <span class="tg-contact-item__title">
          ${escapeHtml(label)}${code ? ` <span class="tg-contact-item__code wp-mono">(${escapeHtml(code)})</span>` : ""}
          ${isDuty ? '<span class="tg-contact-item__badge"><i class="bi bi-headset"></i></span>' : ""}
        </span>
        <span class="tg-contact-item__subtitle">${escapeHtml(subtitle)}</span>
      </span>
    `;
    row.addEventListener("click", () => {
      if (code) openCallsignProfile(code);
    });
    listEl.appendChild(row);
  }

  updateAddCallsignButton();

  if (scoped && rows.length) {
    preloadCallsignLastSeen(rows)
      .then(() => {
        if (IX_SIDEBAR_VIEW !== "callsigns") return;
        const root = $("tg-callsign-list");
        if (!root) return;
        root.querySelectorAll(".tg-contact-item").forEach((row) => {
          const code = String(row.dataset.callsignCode || "").trim();
          const sub = row.querySelector(".tg-contact-item__subtitle");
          if (sub && code) {
            sub.textContent = _formatCallsignLastSeenLine(
              CALLSIGN_LAST_SEEN && CALLSIGN_LAST_SEEN[code]
            );
          }
        });
      })
      .catch(() => { });
  }
}

async function preloadCallsignLastSeenForOne(c) {
  try {
    const code = String((c && c.code) || "").trim();
    if (!code) return false;
    const freq = String((c && c.frequency) || (ACTIVE_CAT && ACTIVE_CAT.frequency) || "").trim();
    const grp = String((c && c.group_code) || (ACTIVE_CAT && ACTIVE_CAT.group_code) || "").trim();
    if (!freq || !grp) return false;
    const res = await apiPost("/api/intercepts/callsigns/last-seen", {
      frequency: freq,
      group_code: grp,
      codes: [code],
    });
    if (res && res.ok && res.last_seen && typeof res.last_seen === "object") {
      CALLSIGN_LAST_SEEN = Object.assign({}, CALLSIGN_LAST_SEEN || {}, res.last_seen);
      return true;
    }
  } catch (_) { }
  return false;
}

function _callsignProfileInfoRow(icon, label, valueHtml) {
  return `
    <div class="tg-cs-profile__row">
      <span class="tg-cs-profile__row-icon"><i class="bi bi-${icon}" aria-hidden="true"></i></span>
      <span class="tg-cs-profile__row-body">
        <span class="tg-cs-profile__row-value">${valueHtml}</span>
        <span class="tg-cs-profile__row-label">${escapeHtml(label)}</span>
      </span>
    </div>
  `;
}

function closeCallsignProfile() {
  IX_CALLSIGN_PROFILE_CODE = "";
  IX_CALLSIGN_PROFILE_EDIT = false;
  IX_CALLSIGN_PROFILE_REF = null;
  const panel = $("tg-callsign-profile");
  const listScroll = document.querySelector("#tg-sidebar-view-callsigns .tg-callsign-list-scroll");
  const foot = document.querySelector("#tg-sidebar-view-callsigns .tg-callsigns-foot");
  const hint = $("tg-callsigns-hint");
  const search = document.querySelector("#tg-sidebar-view-callsigns .tg-sidebar__search");
  if (panel) {
    panel.hidden = true;
    panel.setAttribute("aria-hidden", "true");
  }
  if (listScroll) listScroll.hidden = false;
  if (foot) foot.hidden = !_ixCallsignListScoped();
  if (hint) hint.hidden = false;
  if (search) search.hidden = false;
  setCallsignProfileEditMode(false);
}

function setCallsignProfileEditMode(on) {
  IX_CALLSIGN_PROFILE_EDIT = !!on;
  const editPanel = $("tg-cs-profile-edit");
  const actions = $("tg-cs-profile-actions");
  const editBtn = $("tg-cs-profile-edit-btn");
  if (editPanel) editPanel.hidden = !IX_CALLSIGN_PROFILE_EDIT;
  if (actions) actions.hidden = IX_CALLSIGN_PROFILE_EDIT;
  if (editBtn) {
    editBtn.setAttribute("aria-pressed", IX_CALLSIGN_PROFILE_EDIT ? "true" : "false");
    editBtn.classList.toggle("tg-cs-profile__edit-btn--active", IX_CALLSIGN_PROFILE_EDIT);
  }
}

function _getCallsignForProfile(code) {
  const normalized = String(code || "").replace(/\D+/g, "").trim();
  if (!normalized) return null;
  const pools = [
    ...(Array.isArray(CALLSIGNS) ? CALLSIGNS : []),
    ...(Array.isArray(ALL_CALLSIGNS) ? ALL_CALLSIGNS : []),
  ];
  const matches = pools.filter((x) => _normalizeCallsignCode(x && x.code) === normalized);
  if (matches.length) {
    if (ACTIVE_CAT) {
      const af = String(ACTIVE_CAT.frequency || "").trim();
      const ag = String(ACTIVE_CAT.group_code || "").trim();
      if (af && ag) {
        const scoped = matches.find(
          (x) =>
            String(x.frequency || "").trim() === af &&
            String(x.group_code || "").trim() === ag
        );
        // Не подставляем карточку другой группы — черновик для текущей пары.
        return scoped || _callsignProfileDraft(normalized);
      }
    }
    return matches[0];
  }
  return _callsignByCode(normalized) || _callsignProfileDraft(normalized);
}

function renderCallsignProfile(c) {
  const panel = $("tg-callsign-profile");
  if (!panel || !c) return;
  const label = String(c.label || "").trim() || "Без названия";
  const code = String(c.code || "").trim();
  const freq = String(c.frequency || "").trim();
  const grp = String(c.group_code || "").trim();
  const unit = String(c.unit_name || "").trim();
  const tag = String(c.tag || "").trim();
  const tagColor = String(c.tag_color || "").trim();
  const tagDesc = String(c.tag_desc || "").trim();
  const dutyCode = String((ACTIVE_ASSIGNMENTS || {}).duty || "").trim();
  const isDuty = !!dutyCode && code === dutyCode;
  const initials = _callsignInitials(label, code);
  const hue = _tgAvatarHue(code || label);

  const avatarEl = $("tg-cs-profile-avatar");
  const nameEl = $("tg-cs-profile-name");
  const statusEl = $("tg-cs-profile-status");
  const infoEl = $("tg-cs-profile-info");
  const actionsEl = $("tg-cs-profile-actions");
  const labelInput = $("tg-cs-profile-label-input");

  if (avatarEl) {
    avatarEl.textContent = initials;
    avatarEl.style.setProperty("--tg-avatar-hue", String(hue));
  }
  if (nameEl) {
    nameEl.innerHTML = `${escapeHtml(label)}${
      isDuty ? ' <span class="tg-cs-profile__duty-badge"><i class="bi bi-headset"></i> Опер.д.</span>' : ""
    }`;
  }

  const lastRaw = String((CALLSIGN_LAST_SEEN && CALLSIGN_LAST_SEEN[code]) || "").trim();
  if (statusEl) {
    statusEl.textContent = lastRaw
      ? _formatCallsignLastSeenLine(lastRaw)
      : freq && grp
        ? "активность в эфире пока не зафиксирована"
        : "выберите чат (частота + группа) для времени в эфире";
  }

  if (infoEl) {
    const rows = [];
    if (code) rows.push(_callsignProfileInfoRow("hash", "Код", `<span class="wp-mono">(${escapeHtml(code)})</span>`));
    if (freq) rows.push(_callsignProfileInfoRow("broadcast", "Частота", escapeHtml(freq)));
    if (grp) rows.push(_callsignProfileInfoRow("people", "Группа", escapeHtml(grp)));
    if (unit) rows.push(_callsignProfileInfoRow("building", "Подразделение", escapeHtml(unit)));
    if (tag) {
      rows.push(
        _callsignProfileInfoRow("tag", "Тег", tagBadgeHtml(tag, tagColor, tagDesc) || escapeHtml(tag))
      );
    }
    infoEl.innerHTML = rows.length
      ? rows.join("")
      : `<div class="tg-cs-profile__row tg-cs-profile__row--muted">Нет привязки к частоте и группе</div>`;
  }

  if (labelInput) {
    labelInput.value = String(c.label || "").trim();
    labelInput.placeholder = "Введите позывной";
  }

  if (actionsEl) {
    const canEdit = !!(CAN_EDIT && !ACTIVE_CLOSED);
    actionsEl.innerHTML = `
      <button type="button" class="btn btn-primary btn-sm w-100 tg-cs-profile__action" data-cs-prof-action="insert" ${code ? "" : "disabled"}>
        <i class="bi bi-clipboard-plus me-1"></i>Вставить в бланк
      </button>
      <button type="button" class="btn btn-outline-secondary btn-sm w-100 tg-cs-profile__action" data-cs-prof-action="tag" ${canEdit ? "" : "disabled"}>
        <i class="bi bi-tag me-1"></i>Тег
      </button>
      <button type="button" class="btn btn-outline-primary btn-sm w-100 tg-cs-profile__action" data-cs-prof-action="duty" ${canEdit ? "" : "disabled"}>
        <i class="bi bi-headset me-1"></i>${isDuty ? "Снять Опер.д." : "Назначить Опер.д."}
      </button>
    `;
    actionsEl.querySelector('[data-cs-prof-action="insert"]')?.addEventListener("click", () => {
      if (code) insertCallsignAtCursor(code);
    });
    actionsEl.querySelector('[data-cs-prof-action="tag"]')?.addEventListener("click", () => {
      if (typeof openCallsignTagModal === "function") {
        openCallsignTagModal(c, async () => {
          await loadState(ACTIVE_SESSION_ID || null);
          const fresh = _getCallsignForProfile(code);
          if (fresh) renderCallsignProfile(fresh);
        });
      }
    });
    actionsEl.querySelector('[data-cs-prof-action="duty"]')?.addEventListener("click", async () => {
      try {
        await toggleInterceptsDuty(c);
        await loadState(ACTIVE_SESSION_ID || null);
        const fresh = _getCallsignForProfile(code);
        if (fresh) renderCallsignProfile(fresh);
      } catch (e) {
        setText("intercepts-status", `Ошибка: ${e.message || e}`);
      }
    });
  }

  setCallsignProfileEditMode(IX_CALLSIGN_PROFILE_EDIT);
  const saveBtn = $("tg-cs-profile-save-btn");
  const tagBtn = $("tg-cs-profile-tag-btn");
  const dutyBtn = $("tg-cs-profile-duty-btn");
  const delBtn = $("tg-cs-profile-del-btn");
  const canEdit = !!(CAN_EDIT && !ACTIVE_CLOSED);
  const hasPersistedId = Number(c.id || 0) > 0;
  if (saveBtn) saveBtn.disabled = !canEdit;
  if (tagBtn) tagBtn.disabled = !canEdit || !hasPersistedId;
  if (dutyBtn) dutyBtn.disabled = !canEdit || !hasPersistedId;
  if (delBtn) delBtn.disabled = !canEdit || !hasPersistedId;
}

async function _saveCallsignProfileLabel(c, labelOverride) {
  if (!c) {
    setText("intercepts-status", "Позывной не выбран");
    return false;
  }
  if (!CAN_EDIT || ACTIVE_CLOSED) {
    setText("intercepts-status", "Нет прав или смена закрыта");
    return false;
  }
  const code = _normalizeCallsignCode(c.code || IX_CALLSIGN_PROFILE_CODE);
  const rawLabel = labelOverride != null
    ? labelOverride
    : ($("tg-cs-profile-label-input") && $("tg-cs-profile-label-input").value);
  const next = _normalizeCallsignLabelInput(rawLabel, code);
  const prev = String(c.label || "").trim();
  if (!next) {
    setText("intercepts-status", "Введите название позывного");
    return false;
  }
  const callsignId = Number(c.id || 0);
  const inActivePair = callsignId > 0 && _callsignBelongsToActivePair(c);
  // Уже есть в этой группе и название то же — нечего писать.
  // Черновик / чужая группа: даже с тем же названием создаём запись для текущей пары.
  if (inActivePair && next === prev) {
    setText("intercepts-status", "Изменений нет");
    return false;
  }
  if (inActivePair) {
    await apiPost("/api/intercepts/callsigns/update", { id: callsignId, label: next });
    _upsertLocalCallsign({
      ...c,
      id: callsignId,
      code,
      label: next,
      unit_name: String(c.unit_name || (ACTIVE_CAT && ACTIVE_CAT.unit_name) || "").trim(),
      frequency: String(ACTIVE_CAT.frequency || "").trim(),
      group_code: String(ACTIVE_CAT.group_code || "").trim(),
    });
  } else {
    const res = await addCallsignByValues(next, code);
    if (!res || !res.ok) {
      setText("intercepts-status", (res && res.error) || "Не удалось сохранить позывной");
      return false;
    }
    _upsertLocalCallsign(res);
  }
  _invalidateInterceptsClientCache();
  _refreshCallsignsUi();
  await loadState(ACTIVE_SESSION_ID || null);
  const fresh = _getCallsignForProfile(code);
  if (fresh) {
    IX_CALLSIGN_PROFILE_REF = fresh;
    renderCallsignProfile(fresh);
  }
  setText("intercepts-status", "Позывной сохранён");
  setTimeout(() => setText("intercepts-status", ""), 2500);
  return true;
}

async function openCallsignProfile(code, options) {
  if (!_ixIsMessengerUi()) return;
  const normalized = String(code || "").replace(/\D+/g, "").trim();
  if (!normalized) return;
  const opts = options || {};
  let c = _getCallsignForProfile(normalized);
  if (!c) {
    setText("intercepts-status", `Позывной (${normalized}) не найден`);
    return;
  }

  IX_CALLSIGN_PROFILE_CODE = normalized;
  IX_CALLSIGN_PROFILE_REF = c;
  IX_CALLSIGN_PROFILE_EDIT = !!opts.edit;

  const panel = $("tg-callsign-profile");
  const listScroll = document.querySelector("#tg-sidebar-view-callsigns .tg-callsign-list-scroll");
  const foot = document.querySelector("#tg-sidebar-view-callsigns .tg-callsigns-foot");
  const hint = $("tg-callsigns-hint");
  const search = document.querySelector("#tg-sidebar-view-callsigns .tg-sidebar__search");

  if (listScroll) listScroll.hidden = true;
  if (foot) foot.hidden = true;
  if (hint) hint.hidden = true;
  if (search) search.hidden = true;
  if (panel) {
    panel.hidden = false;
    panel.removeAttribute("aria-hidden");
  }

  try {
    await preloadCallsignLastSeenForOne(c);
  } catch (_) { }
  c = _getCallsignForProfile(normalized) || c;
  IX_CALLSIGN_PROFILE_REF = c;
  renderCallsignProfile(c);
  if (opts.edit) setCallsignProfileEditMode(true);
}

function initCallsignProfileControls() {
  $("tg-cs-profile-back")?.addEventListener("click", () => closeCallsignProfile());
  $("tg-cs-profile-edit-btn")?.addEventListener("click", () => {
    setCallsignProfileEditMode(!IX_CALLSIGN_PROFILE_EDIT);
    if (IX_CALLSIGN_PROFILE_EDIT) {
      try {
        $("tg-cs-profile-label-input")?.focus();
        $("tg-cs-profile-label-input")?.select();
      } catch (_) { }
    }
  });
  $("tg-cs-profile-save-btn")?.addEventListener("click", async () => {
    const c = IX_CALLSIGN_PROFILE_REF || _getCallsignForProfile(IX_CALLSIGN_PROFILE_CODE);
    try {
      await _saveCallsignProfileLabel(c);
    } catch (e) {
      setText("intercepts-status", `Ошибка: ${e.message || e}`);
    }
  });
  $("tg-cs-profile-tag-btn")?.addEventListener("click", () => {
    const c = _getCallsignForProfile(IX_CALLSIGN_PROFILE_CODE);
    if (!c || typeof openCallsignTagModal !== "function") return;
    openCallsignTagModal(c, async () => {
      await loadState(ACTIVE_SESSION_ID || null);
      const fresh = _getCallsignForProfile(IX_CALLSIGN_PROFILE_CODE);
      if (fresh) renderCallsignProfile(fresh);
    });
  });
  $("tg-cs-profile-duty-btn")?.addEventListener("click", async () => {
    const c = _getCallsignForProfile(IX_CALLSIGN_PROFILE_CODE);
    if (!c) return;
    try {
      await toggleInterceptsDuty(c);
      await loadState(ACTIVE_SESSION_ID || null);
      const fresh = _getCallsignForProfile(IX_CALLSIGN_PROFILE_CODE);
      if (fresh) renderCallsignProfile(fresh);
      renderMessengerCallsigns();
    } catch (e) {
      setText("intercepts-status", `Ошибка: ${e.message || e}`);
    }
  });
  $("tg-cs-profile-del-btn")?.addEventListener("click", async () => {
    const c = _getCallsignForProfile(IX_CALLSIGN_PROFILE_CODE);
    if (!c || !c.id) return;
    const label = String(c.label || "").trim();
    const code = String(c.code || "").trim();
    if (!confirm(`Удалить позывной ${label || "—"} (${code})?`)) return;
    try {
      await apiPost("/api/intercepts/callsigns/delete", { id: c.id });
      await loadState(ACTIVE_SESSION_ID || null);
      closeCallsignProfile();
      renderMessengerCallsigns();
    } catch (e) {
      setText("intercepts-status", `Ошибка: ${e.message || e}`);
    }
  });
  $("tg-cs-profile-label-input")?.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.isComposing && ev.keyCode !== 229) {
      ev.preventDefault();
      $("tg-cs-profile-save-btn")?.click();
    }
    if (ev.key === "Escape") {
      ev.preventDefault();
      setCallsignProfileEditMode(false);
    }
  });
}

function initIxMessengerSidebar() {
  if (!_ixIsMessengerUi()) return;

  const menuBtn = $("ix-tg-menu-btn");
  const menu = $("ix-tg-side-menu");
  if (menuBtn && menu) {
    menuBtn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      _setIxSideMenuOpen(!_ixSideMenuOpen());
    });
    menu.querySelectorAll("[data-ix-side-view]").forEach((item) => {
      item.addEventListener("click", (ev) => {
        ev.stopPropagation();
        setIxSidebarView(item.getAttribute("data-ix-side-view") || "chats");
      });
    });
    document.addEventListener("click", () => _setIxSideMenuOpen(false));
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") _setIxSideMenuOpen(false);
    });
  }

  document.querySelector(".ix-mobile-segments")?.querySelectorAll("[data-ix-side-view]").forEach((item) => {
    item.addEventListener("click", (ev) => {
      ev.stopPropagation();
      setIxSidebarView(item.getAttribute("data-ix-side-view") || "chats");
    });
  });

  const csSearch = $("callsigns-search-input");
  if (csSearch) {
    let t = null;
    csSearch.addEventListener("input", () => {
      if (t) clearTimeout(t);
      t = setTimeout(() => renderMessengerCallsigns(), 120);
    });
  }

  initCallsignProfileControls();
  $("ix-callsigns-back-btn")?.addEventListener("click", () => setIxSidebarView("chats"));
  setIxSidebarView("chats");
}
function updateAddCallsignButton() {
  const btn = $("cs-add-btn");
  if (!btn) return;
  const label = ($("cs-label")?.value || "").trim();
  const code = ($("cs-code")?.value || "").trim();
  const hasScope = _ixCallsignListScoped();
  const ready = !!(CAN_EDIT && !ACTIVE_CLOSED && label && code && hasScope);
  // Не используем disabled: Bootstrap ставит pointer-events:none и клик не доходит.
  btn.disabled = false;
  btn.classList.toggle("is-ready", ready);
  btn.setAttribute("aria-disabled", ready ? "false" : "true");
}

function _normalizeCallsignCode(code) {
  return String(code || "").replace(/\D+/g, "");
}

function _upsertLocalCallsign(entry) {
  if (!entry) return;
  const normCode = _normalizeCallsignCode(entry.code);
  if (!normCode) return;
  const freq = String(entry.frequency || "").trim();
  const grp = String(entry.group_code || "").trim();
  const list = Array.isArray(ALL_CALLSIGNS) ? ALL_CALLSIGNS.slice() : [];
  const idx = list.findIndex(
    (c) =>
      _normalizeCallsignCode(c && c.code) === normCode &&
      String((c && c.frequency) || "").trim() === freq &&
      String((c && c.group_code) || "").trim() === grp
  );
  const row = {
    ...(idx >= 0 ? list[idx] : {}),
    ...entry,
    code: normCode,
    frequency: freq,
    group_code: grp,
    label: String(entry.label || (idx >= 0 ? list[idx].label : "") || "").trim(),
    unit_name: String(entry.unit_name || (idx >= 0 ? list[idx].unit_name : "") || "").trim(),
  };
  if (idx >= 0) list[idx] = row;
  else list.push(row);
  ALL_CALLSIGNS = list;
  applyCallsignScope();
}

function _removeLocalCallsignById(callsignId) {
  const cid = Number(callsignId || 0);
  if (!cid) return;
  ALL_CALLSIGNS = (Array.isArray(ALL_CALLSIGNS) ? ALL_CALLSIGNS : []).filter(
    (c) => Number(c && c.id || 0) !== cid
  );
  applyCallsignScope();
}

async function addCallsignByValues(labelRaw, codeRaw) {
  if (!CAN_EDIT || ACTIVE_CLOSED) {
    return { ok: false, error: "Нет прав или смена закрыта" };
  }
  const hasScope = ACTIVE_CAT && ACTIVE_CAT.frequency && ACTIVE_CAT.group_code;
  if (!hasScope) {
    return {
      ok: false,
      error: "Сначала выбери активную частоту/группу в каталоге, затем добавляй позывной.",
    };
  }
  const label = String(labelRaw || "").trim();
  const code = String(codeRaw || "").trim();
  if (!label || !code) return { ok: false, error: "Нужны название и код позывного" };
  const payload = {
    label,
    code,
    unit_name: ACTIVE_CAT.unit_name || "",
    frequency: ACTIVE_CAT.frequency || "",
    group_code: ACTIVE_CAT.group_code || "",
  };
  try {
    const data = await apiPost("/api/intercepts/callsigns", payload);
    const normCode = _normalizeCallsignCode(code);
    return {
      ok: true,
      code: normCode,
      id: data && data.id != null ? Number(data.id) : 0,
      label,
      unit_name: payload.unit_name,
      frequency: payload.frequency,
      group_code: payload.group_code,
    };
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e || "Не удалось сохранить позывной") };
  }
}

async function addCallsign() {
  const label = ($("cs-label")?.value || "").trim();
  const code = ($("cs-code")?.value || "").trim();
  if (!label || !code) {
    setText("intercepts-status", "Введите название и код позывного");
    setTimeout(() => setText("intercepts-status", ""), 2500);
    return;
  }
  if (!CAN_EDIT) {
    setText("intercepts-status", "Нет прав на добавление позывных");
    setTimeout(() => setText("intercepts-status", ""), 3500);
    return;
  }
  if (ACTIVE_CLOSED) {
    setText("intercepts-status", "Смена закрыта — добавление недоступно");
    setTimeout(() => setText("intercepts-status", ""), 3500);
    return;
  }
  if (!_ixCallsignListScoped()) {
    setText("intercepts-status", "Сначала выберите активную частоту/группу в списке чатов");
    setTimeout(() => setText("intercepts-status", ""), 4000);
    return;
  }
  try {
    const res = await addCallsignByValues(label, code);
    if (!res || !res.ok) {
      setText("intercepts-status", (res && res.error) || "Не удалось добавить позывной");
      return;
    }
    $("cs-label").value = "";
    $("cs-code").value = "";
    _upsertLocalCallsign(res);
    setText("intercepts-status", "Позывной добавлен");
    setTimeout(() => setText("intercepts-status", ""), 2500);
    await loadState(ACTIVE_SESSION_ID || null);
  } catch (e) {
    setText("intercepts-status", `Ошибка: ${e.message || e}`);
  } finally {
    updateAddCallsignButton();
  }
}


  window.applyCallsignScope = applyCallsignScope;
  window._refreshCallsignsUi = _refreshCallsignsUi;
  window._invalidateInterceptsClientCache = _invalidateInterceptsClientCache;
  window.updateAddCallsignButton = updateAddCallsignButton;
  window.initIxMessengerSidebar = initIxMessengerSidebar;
  window.renderCallsigns = renderCallsigns;
  window.tagBadgeHtml = tagBadgeHtml;
  window.toggleInterceptsDuty = toggleInterceptsDuty;
  window.openCallsignSettingsByCode = openCallsignSettingsByCode;
  window.openCallsignCardsModal = openCallsignCardsModal;
  window.openCallsignProfile = openCallsignProfile;
  window.setIxSidebarView = setIxSidebarView;
  window.addCallsign = addCallsign;
  window._normalizeCallsignCode = _normalizeCallsignCode;
  window.callsignMatchesActiveScope = callsignMatchesActiveScope;
  window._ixCallsignListScoped = _ixCallsignListScoped;
  window._tagTextColor = _tagTextColor;
})();
