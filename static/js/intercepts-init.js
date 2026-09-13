(function () {
  "use strict";

document.addEventListener("DOMContentLoaded", async () => {
  if (typeof window._ensureOnlineUnitLinkListener === "function") {
    window._ensureOnlineUnitLinkListener();
  }
  try {
    const savedViewMode = localStorage.getItem("intercept-blank-view-mode");
    if (savedViewMode === "pretty" || savedViewMode === "plain") {
      BLANK_VIEW_MODE = savedViewMode;
      LOCAL_VIEW_MODE = savedViewMode;
    }
  } catch (_) { }
  try {
    const collapsed = localStorage.getItem("intercept-groups-drawer-collapsed");
    if (collapsed === "1") {
      document.body.classList.add("groups-drawer-collapsed");
    }
  } catch (_) { }
  const IX_MOBILE_MQ_PHONE = window.matchMedia("(max-width: 767.98px)");
  const IX_COMPACT_MQ = window.matchMedia("(min-width: 768px) and (max-width: 1100px)");
  const IX_DRAWER_MQ = window.matchMedia("(max-width: 1280px)");
  let _ixLastUiMode = "";

  function ixIsMessengerPage() {
    const root = document.querySelector(".md3-intercepts");
    return !!(root && root.classList.contains("ix-messenger-ui"));
  }

  function ixViewportIsNarrow() {
    return IX_MOBILE_MQ_PHONE.matches;
  }

  function ixViewportIsCompact() {
    return ixIsMessengerPage() && IX_COMPACT_MQ.matches && !IX_MOBILE_MQ_PHONE.matches;
  }

  function applyGroupsDrawerMode() {
    const mobileUi = ixViewportIsNarrow();
    const enabled = !!IX_DRAWER_MQ.matches && !mobileUi;
    document.body.classList.toggle("groups-drawer-mode", enabled);
    document.body.classList.toggle("ix-mobile-intercepts", mobileUi);
    if (!enabled) {
      document.body.classList.remove("groups-drawer-collapsed");
    }
    if (mobileUi) {
      document.body.classList.add("groups-drawer-collapsed");
    } else if (enabled && ixIsMessengerPage()) {
      try {
        if (localStorage.getItem("intercept-groups-drawer-collapsed") === null) {
          document.body.classList.add("groups-drawer-collapsed");
        }
      } catch (_) { }
    }
  }

  const IX_MOBILE_PANEL_META = {
    groups: { title: "Группы", sub: "Подразделения и частоты" },
    blank: { title: "Бланк", sub: "Редактирование перехвата" },
    input: { title: "Ввод", sub: "Новая реплика в бланк" },
    audio: { title: "Слушать", sub: "Очередь и плеер" },
  };

  if (!document.body.classList.contains("eavc-page-audio")) {
    IX_MOBILE_PANEL_META.groups = { title: "Чаты", sub: "Частота и группа" };
  }

  function syncMobileAudioDockCount() {
    const dock = document.getElementById("ix-mobile-dock");
    if (!dock) return;
    const isAudioApp = document.body.classList.contains("eavc-page-audio");
    const btns = Array.from(dock.querySelectorAll("[data-ix-panel]"));
    dock.style.setProperty("--ix-dock-count", String(isAudioApp && btns.length === 2 ? 2 : btns.length || 3));
  }

  function _syncMobileAudioLayoutRef() {
    if (typeof _syncMobileAudioLayout === "function") _syncMobileAudioLayout();
  }

  function setInterceptsMobilePanel(panel) {
    const root = document.querySelector(".md3-intercepts");
    const dock = document.getElementById("ix-mobile-dock");
    if (!root || !dock) return;
    const allowed = ["groups", "blank", "input", "audio"];
    if (!allowed.includes(panel)) panel = "blank";
    if (document.body.classList.contains("eavc-page-audio") && typeof window.ixViewportIsNarrow === "function" && window.ixViewportIsNarrow()) {
      if (panel === "blank" || panel === "input") panel = "audio";
    }
    root.dataset.ixPanel = panel;
    document.body.setAttribute("data-ix-panel", panel);

    const btns = Array.from(dock.querySelectorAll("[data-ix-panel]"));
    btns.forEach(function (btn) {
      const on = btn.getAttribute("data-ix-panel") === panel;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
    const idx = Math.max(0, btns.findIndex(function (b) { return b.getAttribute("data-ix-panel") === panel; }));
    dock.style.setProperty("--ix-dock-index", String(idx));
    syncMobileAudioDockCount();

    const head = document.getElementById("ix-mobile-panel-head");
    const headTitle = document.getElementById("ix-mobile-panel-head-title");
    const headSub = document.getElementById("ix-mobile-panel-head-sub");
    const meta = IX_MOBILE_PANEL_META[panel] || IX_MOBILE_PANEL_META.blank;
    if (head) head.hidden = !root.classList.contains("ix-mobile-ui");
    if (headTitle) headTitle.textContent = meta.title;
    if (headSub) {
      if (panel === "blank" && ACTIVE_CAT && ACTIVE_CAT.frequency) {
        const loc = ACTIVE_CAT.location ? " · " + ACTIVE_CAT.location : "";
        headSub.textContent = (ACTIVE_CAT.unit_name || "") + " · " + (ACTIVE_CAT.frequency || "") + " " + (ACTIVE_CAT.group_code || "") + loc;
      } else {
        headSub.textContent = meta.sub;
      }
    }

    if (panel === "input") {
      const inp = $("intercept-input");
      if (inp) {
        window.setTimeout(function () {
          try {
            inp.focus({ preventScroll: true });
          } catch (_) {
            inp.focus();
          }
        }, 120);
      }
    }
  }

  window.setInterceptsMobilePanel = setInterceptsMobilePanel;
  window.ixViewportIsNarrow = ixViewportIsNarrow;
  window.ixViewportIsCompact = ixViewportIsCompact;

  function applyInterceptsMobileUi() {
    const root = document.querySelector(".md3-intercepts");
    const dock = document.getElementById("ix-mobile-dock");
    if (!root || !dock) return;
    const mobile = ixViewportIsNarrow();
    const compact = ixViewportIsCompact();
    root.classList.toggle("ix-mobile-ui", mobile);
    root.classList.toggle("ix-compact-ui", compact);
    dock.hidden = !mobile;
    applyGroupsDrawerMode();
    _syncMobileAudioLayoutRef();
    syncMobileAudioDockCount();
    const head = document.getElementById("ix-mobile-panel-head");
    if (head) head.hidden = !mobile;
    if (mobile) {
      let cur = root.dataset.ixPanel || "groups";
      if (cur === "blank" && !ACTIVE_CAT) cur = "groups";
      setInterceptsMobilePanel(cur);
    } else {
      document.body.removeAttribute("data-ix-panel");
      root.removeAttribute("data-ix-panel");
    }

    const mode = mobile ? "mobile" : compact ? "compact" : "desktop";
    if (mode !== _ixLastUiMode) {
      _ixLastUiMode = mode;
      if (typeof renderGroups === "function" && STATE && STATE.catalog) {
        renderGroups(STATE.catalog);
      }
    }
  }

  applyInterceptsMobileUi();
  IX_MOBILE_MQ_PHONE.addEventListener("change", applyInterceptsMobileUi);
  IX_COMPACT_MQ.addEventListener("change", applyInterceptsMobileUi);
  IX_DRAWER_MQ.addEventListener("change", applyGroupsDrawerMode);

  const ixDock = document.getElementById("ix-mobile-dock");
  if (ixDock) {
    ixDock.addEventListener("click", function (ev) {
      const btn = ev.target.closest("[data-ix-panel]");
      if (!btn) return;
      setInterceptsMobilePanel(btn.getAttribute("data-ix-panel"));
    });
  }
  const ixTgBack = document.getElementById("ix-tg-back-btn");
  if (ixTgBack) {
    ixTgBack.addEventListener("click", function () {
      if (document.body.classList.contains("groups-drawer-mode")) {
        setIxSidebarView("chats");
        ixExpandGroupsDrawer();
        return;
      }
      if (window.EavcMobileNav && typeof window.EavcMobileNav.goBack === "function") {
        window.EavcMobileNav.goBack();
      } else if (typeof window.setInterceptsMobilePanel === "function") {
        window.setInterceptsMobilePanel("groups");
      }
    });
  }
  const ixOpenGroupsBtn = document.getElementById("ix-open-groups-btn");
  if (ixOpenGroupsBtn) {
    ixOpenGroupsBtn.addEventListener("click", function () {
      // Всегда к списку чатов/групп, не к списку позывных.
      setIxSidebarView("chats");
      ixExpandGroupsDrawer();
    });
  }
  initIxMessengerSidebar();
  initInterceptsGroupsSearchControls();
  clearAiProofreadPanel();
  updateAiProofreadButtonState();
  try {
    await loadState();
    await openInterceptDeepLinkIfNeeded();
  } catch (e) {
    setText("intercepts-status", `Ошибка: ${e.message || e}`);
  }

  const shiftSel = $("shift-select");
  if (shiftSel) {
    SHIFT_SELECT_PREV_VALUE = String(shiftSel.value || "");
    shiftSel.addEventListener("focus", () => {
      SHIFT_SELECT_PREV_VALUE = String(shiftSel.value || "");
    });
  }

  window.addEventListener("beforeunload", (e) => {
    if (!hasPendingInterceptChanges()) return;
    e.preventDefault();
    e.returnValue = "";
  });

  $("shift-select").addEventListener("change", async () => {
    const sel = $("shift-select");
    const nextVal = String((sel && sel.value) || "");
    if (hasPendingInterceptChanges()) {
      const ok = window.confirm(
        "Есть несохранённый текст в бланке или в поле ввода. Сменить смену? Несохранённые фрагменты будут потеряны."
      );
      if (!ok) {
        if (sel) sel.value = SHIFT_SELECT_PREV_VALUE;
        return;
      }
    }
    SHIFT_SELECT_PREV_VALUE = nextVal;
    const sid = Number(nextVal || 0);
    ACTIVE_ITEM_ID = 0;
    ACTIVE_CATALOG_ID = 0;
    ACTIVE_CAT = null;
    stopPolling();
    if ($("typing-indicator")) $("typing-indicator").textContent = "";
    $("intercept-text").value = "";
    const inpShift = $("intercept-input");
    if (inpShift) inpShift.value = "";
    clearAiProofreadPanel();
    // Сбрасываем переключатель редактирования при переключении смены
    BLANK_EDIT_ENABLED = false;
    const toggle = $("edit-blank-toggle");
    if (toggle) toggle.checked = false;
    updateBlankEditState();
    setText("editor-subtitle", "Выбери группу слева");
    syncIxChatHeader();
    await loadState(sid || null, { explicitPick: true });
  });

  $("start-new-btn").addEventListener("click", startNewShift);
  $("export-intercepts-btn").addEventListener("click", exportDocx);
  document.querySelectorAll(".wp-add-group-btn").forEach((btn) => {
    btn.addEventListener("click", addGroup);
  });
  const addGroupForm = $("add-group-form");
  if (addGroupForm) addGroupForm.addEventListener("submit", submitAddGroupFromModal);
  const addGroupFreqRows = $("add-group-freq-rows");
  if (addGroupFreqRows) {
    addGroupFreqRows.addEventListener("click", (ev) => {
      const rm = ev.target && ev.target.closest && ev.target.closest(".add-group-freq-remove");
      if (rm && addGroupFreqRows.contains(rm)) removeFrequencyRow(rm);
    });
  }
  const addGroupFreqAddBtn = $("add-group-freq-add-btn");
  if (addGroupFreqAddBtn) addGroupFreqAddBtn.addEventListener("click", () => addFrequencyRow("add-group-freq-rows"));

  const unitManageFreqRows = $("unit-manage-freq-rows");
  if (unitManageFreqRows) {
    unitManageFreqRows.addEventListener("click", (ev) => {
      const rm = ev.target && ev.target.closest && ev.target.closest(".add-group-freq-remove");
      if (rm && unitManageFreqRows.contains(rm)) removeFrequencyRow(rm);
    });
  }
  const unitManageFreqAddBtn = $("unit-manage-freq-add-btn");
  if (unitManageFreqAddBtn) unitManageFreqAddBtn.addEventListener("click", () => addFrequencyRow("unit-manage-freq-rows"));
  const unitManageRenameBtn = $("unit-manage-rename-btn");
  if (unitManageRenameBtn) unitManageRenameBtn.addEventListener("click", () => submitUnitManageRename());
  const unitManageAddCatalogBtn = $("unit-manage-add-catalog-btn");
  if (unitManageAddCatalogBtn) unitManageAddCatalogBtn.addEventListener("click", () => submitUnitManageAddFrequencies());
  const unitManageDeleteBtn = $("unit-manage-delete-btn");
  if (unitManageDeleteBtn) unitManageDeleteBtn.addEventListener("click", () => submitUnitManageDelete());

  const layout = document.querySelector(".sessions-layout");
  const pageMode = layout ? String(layout.getAttribute("data-page-mode") || "") : "";
  const isAudioPage = pageMode === "audio";
  const collapseAllBtn = $("groups-collapse-all-btn");
  const expandAllBtn = $("groups-expand-all-btn");
  const panelToggleBtn = $("groups-panel-toggle-btn");
  const groupsTabBtn = $("groups-drawer-toggle");
  if (isAudioPage && panelToggleBtn) {
    const AUDIO_GROUPS_COLLAPSED_KEY = "intercept-audio-groups-collapsed";
    const relayoutAudioWaveform = () => {
      if (!AUDIO_WAVE_BUFFER) return;
      requestAnimationFrame(() => {
        drawWaveform(AUDIO_WAVE_BUFFER);
      });
    };
    const setCollapsed = (v, persist = true) => {
      document.body.classList.toggle("groups-panel-collapsed", !!v);
      panelToggleBtn.innerHTML = v
        ? "<i class='bi bi-layout-sidebar-inset-reverse me-1'></i>Развернуть список"
        : "<i class='bi bi-layout-sidebar-inset me-1'></i>Свернуть список";
      if (persist) {
        try {
          localStorage.setItem(AUDIO_GROUPS_COLLAPSED_KEY, v ? "1" : "0");
        } catch (_) { }
      }
      relayoutAudioWaveform();
    };
    try {
      const saved = localStorage.getItem(AUDIO_GROUPS_COLLAPSED_KEY);
      setCollapsed(saved !== "0", false);
    } catch (_) {
      setCollapsed(true, false);
    }
    panelToggleBtn.addEventListener("click", () => {
      const now = document.body.classList.contains("groups-panel-collapsed");
      setCollapsed(!now);
    });
    if (groupsTabBtn) {
      groupsTabBtn.addEventListener("click", () => setCollapsed(false));
    }
  }
  if (collapseAllBtn) {
    collapseAllBtn.addEventListener("click", () => {
      const units = new Set();
      const cat = (STATE && STATE.catalog) ? STATE.catalog : [];
      for (const c of cat || []) {
        const key = _unitKey(c.unit_name || "") || "—";
        units.add(key);
      }
      COLLAPSED_UNITS = new Set(units);
      EXPANDED_UNITS = new Set();
      if (STATE && STATE.catalog) renderGroups(STATE.catalog);
    });
  }
  if (expandAllBtn) {
    expandAllBtn.addEventListener("click", () => {
      const units = new Set();
      const cat = (STATE && STATE.catalog) ? STATE.catalog : [];
      for (const c of cat || []) {
        const key = _unitKey(c.unit_name || "") || "—";
        units.add(key);
      }
      EXPANDED_UNITS = new Set(units);
      COLLAPSED_UNITS = new Set();
      if (STATE && STATE.catalog) renderGroups(STATE.catalog);
    });
  }
  if ($("manual-save-btn")) {
    $("manual-save-btn").addEventListener("click", () =>
      saveNow({ sync: true }).catch((e) => {
        setText("intercepts-status", `Ошибка: ${e.message || e}`);
      })
    );
  }
  if ($("ai-proofread-btn")) $("ai-proofread-btn").addEventListener("click", () => runAiProofread());
  if ($("ai-proofread-apply-btn")) $("ai-proofread-apply-btn").addEventListener("click", () => applyAiProofreadFixes());
  if ($("merge-updates-btn")) {
    $("merge-updates-btn").addEventListener("click", () =>
      saveNow({ sync: true, force: true, merge: true })
    );
  }
  if ($("cs-add-btn")) {
    $("cs-add-btn").addEventListener("click", (ev) => {
      ev.preventDefault();
      addCallsign().catch((e) => {
        setText("intercepts-status", `Ошибка: ${e.message || e}`);
      });
    });
  }
  if ($("cs-label")) $("cs-label").addEventListener("input", updateAddCallsignButton);
  if ($("cs-code")) $("cs-code").addEventListener("input", updateAddCallsignButton);
  if ($("open-callsigns-modal-btn")) {
    $("open-callsigns-modal-btn").addEventListener("click", () => {
      if (_ixIsMessengerUi() && typeof setIxSidebarView === "function") {
        setIxSidebarView("callsigns");
        return;
      }
      openCallsignCardsModal("");
    });
  }
  initCorrIdSuggestToggle();

  const interceptText = $("intercept-text");
  if (interceptText) {
    let lastBlankDblAt = 0;
    const handleBlankDoubleClick = () => {
      const now = Date.now();
      if (now - lastBlankDblAt < 180) return;
      lastBlankDblAt = now;
      // Даем браузеру завершить выделение текста после dblclick
      window.setTimeout(() => {
        const code = _extractCallsignCodeFromSelection(interceptText);
        if (code && openCallsignSettingsByCode(code)) return;
        openCallsignCardsModal(code || "");
      }, 20);
    };
    interceptText.addEventListener("dblclick", handleBlankDoubleClick);
    interceptText.addEventListener("mouseup", (ev) => {
      if (ev && ev.detail === 2) handleBlankDoubleClick();
    });
    interceptText.addEventListener("contextmenu", (ev) => {
      const code = _extractCallsignCodeFromSelection(interceptText);
      if (!code) return;
      ev.preventDefault();
      if (openCallsignSettingsByCode(code)) return;
      openCallsignCardsModal(code || "");
    });
  }
  const interceptPreview = $("intercept-preview");
  if (interceptPreview) {
    interceptPreview.addEventListener("dblclick", (ev) => {
      let preferred = "";
      const idEl = ev.target && ev.target.closest ? ev.target.closest(".ip-id") : null;
      if (idEl && idEl.dataset) preferred = String(idEl.dataset.code || "").trim();
      if (preferred && openCallsignSettingsByCode(preferred)) return;
      openCallsignCardsModal(preferred);
    });
    interceptPreview.addEventListener("contextmenu", (ev) => {
      const idEl = ev.target && ev.target.closest ? ev.target.closest(".ip-id") : null;
      if (!idEl || !idEl.dataset) return;
      const preferred = String(idEl.dataset.code || "").trim();
      if (!preferred) return;
      ev.preventDefault();
      if (openCallsignSettingsByCode(preferred)) return;
      openCallsignCardsModal(preferred);
    });
  }

  // Обработчик переключателя редактирования бланка
  const editBlankToggle = $("edit-blank-toggle");
  if (editBlankToggle) {
    // Инициализируем переключатель в выключенном состоянии
    editBlankToggle.checked = false;
    BLANK_EDIT_ENABLED = false;
    editBlankToggle.addEventListener("change", (ev) => {
      BLANK_EDIT_ENABLED = ev.target.checked;
      BLANK_VIEW_MODE = "plain";
      updateBlankEditState();
      updateBlankViewMode();
      updateBlankDirtyUi();
      if (BLANK_EDIT_ENABLED) {
        // При включении редактирования — фокус в textarea
        try { $("intercept-text")?.focus(); } catch (_) { }
      }
    });
  }

  // Кнопка переключения вида удалена: всегда plain.

  const groupsDrawerToggle = $("groups-drawer-toggle");
  if (groupsDrawerToggle) {
    groupsDrawerToggle.addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (document.body.classList.contains("groups-drawer-collapsed")) {
        setIxSidebarView("chats");
        ixExpandGroupsDrawer();
        return;
      }
      // Панель открыта на позывных/профиле — «Чаты» возвращает к группам, не сворачивает.
      if (IX_SIDEBAR_VIEW === "callsigns" || IX_CALLSIGN_PROFILE_CODE) {
        setIxSidebarView("chats");
        return;
      }
      ixCollapseGroupsDrawer();
    });
  }

  document.addEventListener("click", (ev) => {
    if (!document.body.classList.contains("groups-drawer-mode")) return;
    if (ixViewportIsNarrow()) return;
    if (document.body.classList.contains("groups-drawer-collapsed")) return;
    const panel = document.querySelector(".intercepts-groups-panel");
    const toggle = $("groups-drawer-toggle");
    const openBtn = document.getElementById("ix-open-groups-btn");
    const panelResizer = document.getElementById("ix-drawer-panel-resizer");
    const blankFloat = document.getElementById("ix-blank-float");
    const target = ev.target;
    if (!panel || !(target instanceof Node)) return;
    if (panel.contains(target) || (toggle && toggle.contains(target))) return;
    if (openBtn && openBtn.contains(target)) return;
    if (panelResizer && panelResizer.contains(target)) return;
    if (blankFloat && blankFloat.contains(target)) return;
    ixCollapseGroupsDrawer();
  });

  // ~50% окна: только бланк — сдвиг (слева) и ширина (справа); список чатов отдельно
  function initDrawerPanelWidthResizer() {
    const PANEL_KEY = "intercept-drawer-panel-width-px";
    const OFFSET_KEY = "intercept-blank-offset-x-px";
    const WIDTH_KEY = "intercept-blank-width-px";
    const MIN_PANEL = 220;
    const MIN_BLANK_W = 200;
    const MAX_RATIO = 0.78;

    function tabInsetPx() {
      const tab = parseFloat(
        getComputedStyle(document.body).getPropertyValue("--ix-drawer-tab-inset")
      );
      return Number.isFinite(tab) && tab > 0 ? tab : 56;
    }

    function maxPanelWidth() {
      return Math.max(MIN_PANEL, Math.round(window.innerWidth * MAX_RATIO));
    }

    function blankHost() {
      return document.querySelector(".md3-intercepts.ix-messenger-ui .tg-chat__body");
    }

    function blankBox() {
      return document.getElementById("ix-blank-float");
    }

    function hostInnerWidth() {
      const host = blankHost();
      if (!host) return window.innerWidth;
      const s = getComputedStyle(host);
      const pl = parseFloat(s.paddingLeft) || 0;
      const pr = parseFloat(s.paddingRight) || 0;
      return Math.max(MIN_BLANK_W, host.clientWidth - pl - pr);
    }

    function applyPanelWidth(px) {
      const w = Math.max(MIN_PANEL, Math.min(maxPanelWidth(), Math.round(px)));
      document.body.style.setProperty("--ix-drawer-panel-w", w + "px");
      return w;
    }

    function applyBlankOffset(px) {
      const maxOff = Math.max(0, hostInnerWidth() - MIN_BLANK_W);
      const x = Math.max(0, Math.min(maxOff, Math.round(px)));
      document.body.style.setProperty("--ix-blank-offset-x", x + "px");
      return x;
    }

    function applyBlankWidth(px) {
      const box = blankBox();
      const hostW = hostInnerWidth();
      const drawer = document.body.classList.contains("groups-drawer-mode");
      const off = drawer
        ? (box
          ? parseFloat(getComputedStyle(box).marginLeft) || 0
          : parseFloat(getComputedStyle(document.body).getPropertyValue("--ix-blank-offset-x")) || 0)
        : 0;
      const maxW = Math.max(MIN_BLANK_W, hostW - off);
      const w = Math.max(MIN_BLANK_W, Math.min(maxW, Math.round(px)));
      document.body.style.setProperty("--ix-blank-width", w + "px");
      return w;
    }

    function loadSavedSizes() {
      const drawer = document.body.classList.contains("groups-drawer-mode");
      try {
        if (drawer) {
          const pw = parseInt(localStorage.getItem(PANEL_KEY), 10);
          if (Number.isFinite(pw) && pw >= MIN_PANEL) applyPanelWidth(pw);
          const ox = parseInt(localStorage.getItem(OFFSET_KEY), 10);
          if (Number.isFinite(ox) && ox >= 0) applyBlankOffset(ox);
        } else {
          document.body.style.removeProperty("--ix-blank-offset-x");
        }
        const bw = parseInt(localStorage.getItem(WIDTH_KEY), 10);
        if (Number.isFinite(bw) && bw >= MIN_BLANK_W) {
          applyBlankWidth(bw);
        } else if (!drawer) {
          document.body.style.removeProperty("--ix-blank-width");
        }
      } catch (_) { }
    }

    loadSavedSizes();
    IX_DRAWER_MQ.addEventListener("change", loadSavedSizes);
    window.addEventListener("resize", () => {
      const box = blankBox();
      if (!box) return;
      const w = box.getBoundingClientRect().width;
      if (Number.isFinite(w)) applyBlankWidth(w);
      if (document.body.classList.contains("groups-drawer-mode")) {
        const x = parseFloat(getComputedStyle(box).marginLeft) || 0;
        applyBlankOffset(x);
      }
    });

    const panel = document.querySelector(".md3-intercepts.ix-messenger-ui .intercepts-groups-panel");
    const edgeResizer = document.getElementById("ix-blank-edge-resizer");
    const widthResizer = document.getElementById("ix-blank-width-resizer");
    const panelResizer = document.getElementById("ix-drawer-panel-resizer");
    const box = blankBox();
    if (!box) return;

    function bindPointerDrag(handle, mode) {
      if (!handle) return;

      function pointerDown(clientX, ev) {
        if ((mode === "panel" || mode === "offset") && !document.body.classList.contains("groups-drawer-mode")) {
          return;
        }
        if (ev) {
          ev.preventDefault();
          ev.stopPropagation();
        }

        const startX = clientX;
        const startOffset = parseFloat(getComputedStyle(box).marginLeft) || 0;
        const startWidth = box.getBoundingClientRect().width;
        const startPanelW = panel ? panel.getBoundingClientRect().width : MIN_PANEL;

        function pointerMove(cx) {
          const dx = cx - startX;
          if (mode === "offset") {
            applyBlankOffset(startOffset + dx);
          } else if (mode === "width") {
            applyBlankWidth(startWidth + dx);
          } else if (mode === "panel" && panel) {
            applyPanelWidth(startPanelW + dx);
          }
        }

        function pointerUp() {
          document.removeEventListener("mousemove", onMouseMove);
          document.removeEventListener("mouseup", onMouseUp);
          document.removeEventListener("touchmove", onTouchMove);
          document.removeEventListener("touchend", onTouchEnd);
          document.removeEventListener("touchcancel", onTouchEnd);
          document.body.classList.remove("ix-drawer-resizing");
          document.body.style.cursor = "";
          document.body.style.userSelect = "";
          try {
            if (mode === "offset") {
              localStorage.setItem(OFFSET_KEY, String(Math.round(parseFloat(getComputedStyle(box).marginLeft) || 0)));
            } else if (mode === "width") {
              localStorage.setItem(WIDTH_KEY, String(Math.round(box.getBoundingClientRect().width)));
            } else if (mode === "panel" && panel) {
              const w = panel.getBoundingClientRect().width;
              if (Number.isFinite(w) && w >= MIN_PANEL) {
                localStorage.setItem(PANEL_KEY, String(Math.round(w)));
              }
            }
          } catch (_) { }
        }

        function onMouseMove(ev) {
          pointerMove(ev.clientX);
        }

        function onMouseUp() {
          pointerUp();
        }

        function onTouchMove(ev) {
          if (!ev.touches || !ev.touches[0]) return;
          ev.preventDefault();
          pointerMove(ev.touches[0].clientX);
        }

        function onTouchEnd() {
          pointerUp();
        }

        document.body.classList.add("ix-drawer-resizing");
        document.body.style.cursor = "ew-resize";
        document.body.style.userSelect = "none";
        document.addEventListener("mousemove", onMouseMove);
        document.addEventListener("mouseup", onMouseUp);
        document.addEventListener("touchmove", onTouchMove, { passive: false });
        document.addEventListener("touchend", onTouchEnd);
        document.addEventListener("touchcancel", onTouchEnd);
      }

      handle.addEventListener("mousedown", (ev) => pointerDown(ev.clientX, ev));
      handle.addEventListener(
        "touchstart",
        (ev) => {
          if (!ev.touches || !ev.touches[0]) return;
          pointerDown(ev.touches[0].clientX, ev);
        },
        { passive: false }
      );
    }

    bindPointerDrag(edgeResizer, "offset");
    bindPointerDrag(widthResizer, "width");
    bindPointerDrag(panelResizer, "panel");
  }

  // Высота блока подразделений: тянуть за полоску вниз/вверх
  function initGroupsListResizer() {
    const STORAGE_KEY = "intercept-groups-list-height";
    const MIN_H = 120;
    const MAX_H = 900;

    function applySavedHeight() {
      try {
        const saved = localStorage.getItem(STORAGE_KEY);
        const px = saved ? parseInt(saved, 10) : NaN;
        if (!Number.isFinite(px) || px < MIN_H) return;
        document.querySelectorAll(".groups-list-resizable").forEach((el) => {
          el.style.setProperty("--groups-list-height", px + "px");
        });
      } catch (_) { }
    }

    applySavedHeight();

    document.querySelectorAll(".groups-list-resizer").forEach((resizerEl) => {
      const container = resizerEl.closest(".groups-list-resizable");
      const scrollEl = container ? container.querySelector(".groups-list-scroll") : null;
      if (!container || !scrollEl) return;

      resizerEl.addEventListener("mousedown", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const startY = e.clientY;
        const startHeight = scrollEl.getBoundingClientRect().height;

        function move(ev) {
          const delta = ev.clientY - startY;
          let h = Math.round(startHeight + delta);
          h = Math.max(MIN_H, Math.min(MAX_H, h));
          container.style.setProperty("--groups-list-height", h + "px");
        }

        function up() {
          document.removeEventListener("mousemove", move);
          document.removeEventListener("mouseup", up);
          document.body.style.cursor = "";
          document.body.style.userSelect = "";
          try {
            const h = scrollEl.getBoundingClientRect().height;
            if (Number.isFinite(h) && h >= MIN_H) localStorage.setItem(STORAGE_KEY, String(Math.round(h)));
          } catch (_) { }
        }

        document.body.style.cursor = "ns-resize";
        document.body.style.userSelect = "none";
        document.addEventListener("mousemove", move);
        document.addEventListener("mouseup", up);
      });
    });
  }

  // Инициализация ползунка для изменения ширины бланка
  function initTextResizer() {
    const isMessenger = _ixIsMessengerUi();
    const resizers = [
      $("intercept-text-resizer"),
      $("intercept-preview-resizer"),
      isMessenger ? $("ix-blank-height-splitter") : null,
    ].filter(Boolean);
    const textarea = $("intercept-text");
    const wrapper = $("intercept-text-wrapper");
    const preview = $("intercept-preview");
    if (!resizers.length || !textarea || !wrapper) return;

    const blankShell = wrapper.closest(".ix-blank-shell");
    const chatBody = wrapper.closest(".tg-chat__body");
    const chatStack = document.getElementById("ix-chat-stack");
    const minWidth = 300;
    const minHeight = isMessenger ? 180 : 220;

    function clampWidth(w) {
      return Math.max(minWidth, Math.min(window.innerWidth - 100, w));
    }

    function messengerBlankMaxHeight() {
      const stack = chatStack || (blankShell && blankShell.closest(".ix-chat-stack"));
      if (!stack) return window.innerHeight - 160;
      const composer = stack.querySelector(".tg-composer");
      const splitter = stack.querySelector(".ix-blank-height-splitter");
      const reserved = (composer ? composer.offsetHeight : 0) + (splitter ? splitter.offsetHeight : 12) + 6;
      return Math.max(minHeight, stack.clientHeight - reserved);
    }

    function clampHeight(h) {
      const maxHeight = isMessenger ? messengerBlankMaxHeight() : window.innerHeight - 160;
      return Math.max(minHeight, Math.min(maxHeight, h));
    }

    function clearMessengerBlankCustomHeight() {
      if (!chatBody) return;
      chatBody.classList.remove("ix-blank-height-custom");
      chatBody.style.height = "";
      chatBody.style.flex = "";
      document.documentElement.style.removeProperty("--ix-blank-shell-height");
      if (blankShell) {
        blankShell.style.height = "";
        blankShell.style.flex = "";
      }
    }

    function applySize(width, height) {
      if (isMessenger && chatBody) {
        textarea.style.width = "";
        wrapper.style.width = "";
        if (preview) preview.style.width = "";
        if (Number.isFinite(height)) {
          const h = clampHeight(height);
          chatBody.classList.add("ix-blank-height-custom");
          chatBody.style.height = h + "px";
          chatBody.style.flex = "0 0 " + h + "px";
          document.documentElement.style.setProperty("--ix-blank-shell-height", h + "px");
          if (blankShell) {
            blankShell.style.height = "100%";
            blankShell.style.flex = "1 1 auto";
          }
          wrapper.style.height = "";
          textarea.style.height = "100%";
          if (preview) preview.style.height = "100%";
        } else {
          clearMessengerBlankCustomHeight();
        }
        return;
      }
      if (Number.isFinite(width)) {
        const w = clampWidth(width);
        textarea.style.width = w + "px";
        wrapper.style.width = w + "px";
        if (preview) preview.style.width = w + "px";
      }
      if (Number.isFinite(height)) {
        const h = clampHeight(height);
        textarea.style.height = h + "px";
        wrapper.style.height = h + "px";
        if (preview) preview.style.height = h + "px";
      }
    }

    // Загружаем сохранённые размеры
    function loadSavedSize() {
      try {
        const savedWidth = isMessenger ? null : localStorage.getItem("intercept-text-width");
        const savedHeight = localStorage.getItem(
          isMessenger ? "intercept-blank-shell-height" : "intercept-text-height"
        );
        const width = savedWidth ? parseInt(savedWidth, 10) : null;
        const height = savedHeight ? parseInt(savedHeight, 10) : null;
        if (Number.isFinite(width) || Number.isFinite(height)) {
          applySize(width, height);
        } else if (!isMessenger) {
          // Первый запуск: синхронизируем высоту preview с textarea
          applySize(textarea.offsetWidth, textarea.offsetHeight);
        }
      } catch (_) { }
    }

    // Сохраняем размеры
    function _sizeSource() {
      if (isMessenger && chatBody) return chatBody;
      if (preview && preview.style.display !== "none") return preview;
      return textarea;
    }

    function saveSize() {
      try {
        const src = _sizeSource();
        const w = src && src.offsetWidth ? src.offsetWidth : textarea.offsetWidth;
        const h = src && src.offsetHeight ? src.offsetHeight : textarea.offsetHeight;
        if (isMessenger) {
          if (chatBody && chatBody.classList.contains("ix-blank-height-custom")) {
            localStorage.setItem("intercept-blank-shell-height", String(h));
          } else {
            localStorage.removeItem("intercept-blank-shell-height");
          }
        } else {
          localStorage.setItem("intercept-text-width", String(w));
          localStorage.setItem("intercept-text-height", String(h));
        }
      } catch (_) { }
    }

    let isResizing = false;
    let startX = 0;
    let startY = 0;
    let startWidth = 0;
    let startHeight = 0;

    function beginResize(clientX, clientY, ev) {
      if (ev) {
        ev.preventDefault();
        ev.stopPropagation();
      }
      isResizing = true;
      startX = clientX;
      startY = clientY;
      const src = _sizeSource();
      startWidth = (src && src.offsetWidth) ? src.offsetWidth : 0;
      startHeight = (src && src.offsetHeight) ? src.offsetHeight : 0;
      if (isMessenger && chatBody && startHeight < minHeight) {
        startHeight = messengerBlankMaxHeight();
      }
      document.body.style.cursor = isMessenger ? "ns-resize" : "se-resize";
      document.body.style.userSelect = "none";
      if (isMessenger) document.documentElement.classList.add("ix-blank-resizing");
    }

    function moveResize(clientX, clientY) {
      if (!isResizing) return;
      const diffX = clientX - startX;
      const diffY = clientY - startY;
      const newWidth = isMessenger ? null : clampWidth(startWidth + diffX);
      const newHeight = clampHeight(startHeight + diffY);
      if (isMessenger && chatBody && !chatBody.classList.contains("ix-blank-height-custom") && diffY !== 0) {
        chatBody.classList.add("ix-blank-height-custom");
      }
      applySize(newWidth, newHeight);
      saveSize();
    }

    function endResize() {
      if (!isResizing) return;
      isResizing = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      document.documentElement.classList.remove("ix-blank-resizing");
    }

    resizers.forEach((resizer) => {
      resizer.addEventListener("mousedown", (e) => beginResize(e.clientX, e.clientY, e));
      resizer.addEventListener(
        "touchstart",
        (e) => {
          if (!e.touches || !e.touches[0]) return;
          beginResize(e.touches[0].clientX, e.touches[0].clientY, e);
        },
        { passive: false }
      );
      if (isMessenger && resizer.id === "ix-blank-height-splitter") {
        resizer.addEventListener("dblclick", () => {
          try {
            localStorage.removeItem("intercept-blank-shell-height");
          } catch (_) { /* ignore */ }
          clearMessengerBlankCustomHeight();
        });
      }
    });

    document.addEventListener("mousemove", (e) => {
      if (!isResizing) return;
      e.preventDefault();
      moveResize(e.clientX, e.clientY);
    });

    document.addEventListener("mouseup", endResize);

    document.addEventListener(
      "touchmove",
      (e) => {
        if (!isResizing || !e.touches || !e.touches[0]) return;
        e.preventDefault();
        moveResize(e.touches[0].clientX, e.touches[0].clientY);
      },
      { passive: false }
    );

    document.addEventListener("touchend", endResize);
    document.addEventListener("touchcancel", endResize);

    // Загружаем сохранённые размеры при инициализации
    loadSavedSize();

    // Обрабатываем изменение размера окна
    window.addEventListener("resize", () => {
      if (isMessenger) {
        if (!chatBody || !chatBody.classList.contains("ix-blank-height-custom")) return;
        let saved = NaN;
        try {
          saved = parseInt(localStorage.getItem("intercept-blank-shell-height") || "", 10);
        } catch (_) { /* ignore */ }
        const current = Number.isFinite(saved) ? saved : chatBody.offsetHeight;
        applySize(null, clampHeight(current));
        return;
      }
      const src = _sizeSource();
      const currentWidth = (src && src.offsetWidth) ? src.offsetWidth : textarea.offsetWidth;
      const currentHeight = (src && src.offsetHeight) ? src.offsetHeight : textarea.offsetHeight;
      applySize(currentWidth, currentHeight);
      saveSize();
    });
  }

  // Инициализируем ползунок при загрузке
  initTextResizer();
  initGroupsListResizer();
  initDrawerPanelWidthResizer();

  // Инициализируем аудиоперехваты
  initAudioUi();

  // Старт цепочки автоо��новления списка аудио (следующий запрос — ровно через 20 с после окончания предыдущего)
  setTimeout(function startAudioRefreshChain() {
    if (typeof getAudioFolderPath === "function" && getAudioFolderPath() && typeof refreshAudioQueue === "function") {
      refreshAudioQueue();
    }
  }, 500);

  $("intercept-text").addEventListener("input", (ev) => {
    const ta = ev && ev.target ? ev.target : $("intercept-text");
    // Не обрабатываем ввод, если бланк неактивен
    if (!ta || ta.disabled) return;
    // Нормализуем формат времени при вводе (12:17 -> 12.17)
    const v = String(ta.value || "");
    const pos = ta.selectionStart || 0;
    const normalized = normalizeTimeInText(v);
    if (normalized !== v) {
      // Сохраняем позицию курсора относительно конца текста до нормализации
      const lengthDiff = normalized.length - v.length;
      let newPos = pos;
      // Если произошли замены, корректируем позицию курсора
      // При замене ":" на "." длина не меняется, но позиция может немного сдвинуться
      if (lengthDiff !== 0) {
        newPos = Math.max(0, Math.min(normalized.length, pos + lengthDiff));
      }
      ta.value = normalized;
      try {
        ta.setSelectionRange(newPos, newPos);
      } catch (_) { }
    }
    _applyCallsignDecorationsInPlain(ta);
    clearAiProofreadPanel();
    scheduleSave();
    _autoScrollEditorIfNeeded(ta);
    updateBlankCallsignLegend();
  });
  $("intercept-text").addEventListener("blur", () => setTyping(false));
  document.addEventListener("keydown", (ev) => {
    // В браузере нельзя надёжно ловить "Ctrl+Shift" без третьей клавиши.
    // Поэтому используем Ctrl+Shift+S.
    // Подсказки (позывные): стрелки выбрать, Enter/Tab вставить
    // Важно: при открытой подсказке Enter НЕ должен превращаться в "\n-" (автотире).
    const taInput = $("intercept-input");
    const isInputFocused = taInput && document.activeElement === taInput;
    const taBlank = $("intercept-text");
    const isBlankFocused = taBlank && document.activeElement === taBlank && !taBlank.disabled;

    // Автокапитализация после точки для полей ввода
    if (isInputFocused) {
      if (_autoUppercaseAfterDot(ev, "intercept-input")) {
        // после программной вставки обновим состояние кнопки отправки
        try { updateSendButton(); } catch (_) { }
        return;
      }
    } else if (isBlankFocused) {
      if (_autoUppercaseAfterDot(ev, "intercept-text")) {
        return;
      }
    }

    // Обработка подсказок для поля ввода радиоперехвата
    if (isInputFocused && SUGGEST_INPUT.open && SUGGEST_INPUT.items.length) {
      // стрелки по подсказкам
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        const n = SUGGEST_INPUT.items.length;
        if (!n) return;
        if (ev.key === "ArrowDown") SUGGEST_INPUT.idx = Math.min(n - 1, SUGGEST_INPUT.idx + 1);
        if (ev.key === "ArrowUp") SUGGEST_INPUT.idx = Math.max(0, SUGGEST_INPUT.idx - 1);
        renderSuggestInput();
        return;
      }
      // Enter/Tab: принять подсказку (Enter не срабатывает во время IME-композиции)
      if ((ev.key === "Enter" || ev.key === "Tab") && !ev.isComposing && ev.keyCode !== 229) {
        ev.preventDefault();
        acceptSuggestInput(SUGGEST_INPUT.idx);
        return;
      }
      // Escape: закрыть
      if (ev.key === "Escape") {
        ev.preventDefault();
        setSuggestInput(false, [], "");
        return;
      }
    }

    // Обработка подсказок для основного поля бланка
    if (!isInputFocused && SUGGEST.open && SUGGEST.items.length) {
      // стрелки по подсказкам
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        const n = SUGGEST.items.length;
        if (!n) return;
        // Не делаем wrap-around, чтобы "вниз" не прыгало на первый элемент.
        if (ev.key === "ArrowDown") SUGGEST.idx = Math.min(n - 1, SUGGEST.idx + 1);
        if (ev.key === "ArrowUp") SUGGEST.idx = Math.max(0, SUGGEST.idx - 1);
        renderSuggest();
        return;
      }
      // Enter/Tab: принять подсказку (Enter не срабатывает во время IME-композиции)
      if ((ev.key === "Enter" || ev.key === "Tab") && !ev.isComposing && ev.keyCode !== 229) {
        ev.preventDefault();
        acceptSuggest(SUGGEST.idx);
        return;
      }
      // Escape: закрыть
      if (ev.key === "Escape") {
        ev.preventDefault();
        setSuggest(false, [], "");
        return;
      }
    }

    // Автопрефикс строки "-": при Enter начинаем новую строку с "-"
    // Но если оператор начинает вводить время — тире будет автоматически убрано (_fixDashIfTimeHeaderAtCursor()).
    if (ev.key === "Enter" && !ev.ctrlKey && !ev.altKey && !ev.metaKey && !ev.isComposing && ev.keyCode !== 229) {
      const ta = $("intercept-text");
      // Проверяем, что бланк активен (не disabled - это уже учитывает переключатель)
      if (ta && document.activeElement === ta && !ta.disabled) {
        // Не вмешиваемся в Enter с Shift (если нужно вставить "пустую" строку без тире)
        if (!ev.shiftKey) {
          ev.preventDefault();
          insertAtCursor("\n-");
          return;
        }
      }
      // Обработка Enter для поля ввода радиоперехвата
      if (isInputFocused) {
        // Если открыта подсказка - уже обработано выше
        if (SUGGEST_INPUT.open && SUGGEST_INPUT.items.length) {
          return;
        }
        // Не вмешиваемся в Enter с Shift (если нужно вставить "пустую" строку без тире)
        if (!ev.shiftKey) {
          ev.preventDefault();
          insertAtCursor("\n-", "intercept-input");
          return;
        }
      }
    }

    if (ev.ctrlKey && ev.shiftKey && String(ev.key || "").toLowerCase() === "s") {
      ev.preventDefault();
      saveNow({ sync: true });
    }
  });

  // обновление подсказок по движению каретки/вводу
  $("intercept-text").addEventListener("keyup", (ev) => updateSuggestFromCursor(ev));
  // По UX: одиночный клик по коду не должен открывать список позывных.
  $("intercept-text").addEventListener("blur", () => setSuggest(false, [], ""));
  $("intercept-text").addEventListener("input", () => _renderPreview());

  // Поле ввода радиоперехвата: делегирование на document, чтобы работало и на странице аудио,
  // где элемент может быть в другой части DOM
  function handleInterceptInputEvent(ev) {
    if (!ev.target || ev.target.id !== "intercept-input") return;
    const ta = ev.target;
    if (ev.type === "input") {
      // Всегда работаем с элементом, в котором печатают (ev.target), а не с getElementById
      normalizeTimeOnInput("intercept-input", ta);
      _autoScrollEditorIfNeeded(ta);
      _fixDashIfTimeHeaderAtCursor("intercept-input", ta);
      updateSuggestFromCursor(ev, "intercept-input");
      updateSendButton(ta);
    } else if (ev.type === "keyup" || ev.type === "click") {
      updateSuggestFromCursor(ev, "intercept-input");
      if (ev.type === "click") updateSendButton(ta);
    }
  }
  document.body.addEventListener("input", handleInterceptInputEvent, true);
  document.body.addEventListener("keyup", handleInterceptInputEvent, true);
  document.body.addEventListener("click", handleInterceptInputEvent, true);

  // Закрытие подсказок при уходе фокуса (focusout всплывает, blur — нет)
  document.body.addEventListener("focusout", (ev) => {
    if (ev.target.id !== "intercept-input") return;
    const next = ev.relatedTarget;
    if (next && (next.id === "cs-suggest-input" || (next.closest && next.closest("#cs-suggest-input")))) return;
    setSuggestInput(false, [], "");
  }, true);

  // При фокусе в поле ввода — обновить кнопку по значению этого поля
  document.body.addEventListener("focusin", (ev) => {
    if (ev.target.id === "intercept-input") updateSendButton(ev.target);
  }, true);

  // Функция обновления состояния кнопки отправки.
  // Кнопку не делаем disabled: в части браузеров клик по disabled не срабатывает; пустой ввод проверяем в sendInputToBlank.
  function updateSendButton(optionalInput) {
    const btn = $("send-input-btn");
    if (!btn) return;
    let input = optionalInput && optionalInput.id === "intercept-input" ? optionalInput : $("intercept-input");
    if (input && document.activeElement && document.activeElement.id === "intercept-input") {
      input = document.activeElement;
    }
    const hasText = input && (input.value || "").trim().length > 0;
    btn.disabled = false;
    btn.classList.toggle("is-empty", !hasText);
  }

  // Функция отправки текста в бланк
  async function sendInputToBlank() {
    setText("intercepts-status", "Отправка…");
    const isAudioPage = !!document.querySelector("[data-page-mode='audio']");
    // На странице аудио явно берём бланк из колонки с бланком, поле ввода — из панели аудио
    let blank = isAudioPage
      ? document.querySelector(".audio-blank-col #intercept-text") || document.querySelector("#intercept-text")
      : $("intercept-text");
    let input = isAudioPage
      ? (document.querySelector("#audio-intercepts-panel #intercept-input") || $("intercept-input"))
      : $("intercept-input");
    if (document.activeElement && document.activeElement.id === "intercept-input") {
      input = document.activeElement;
    }
    if (!input || !blank) {
      setText("intercepts-status", "Ошибка: не найдено поле ввода или бланк");
      return;
    }
    let text = (input.value || "").trim();
    if (!text) {
      setText("intercepts-status", "Введите текст перехвата");
      setTimeout(() => setText("intercepts-status", ""), 2000);
      return;
    }

    // Восстановить выбор по ACTIVE_CAT/ACTIVE_CATALOG_ID
    if (!ACTIVE_ITEM_ID) {
      await _ensureActiveItemOpen();
    }

    if (!ACTIVE_ITEM_ID) {
      let currentItem = _currentAudioItem();
      if (!currentItem && typeof AUDIO_QUEUE !== "undefined" && AUDIO_QUEUE.length) {
        currentItem = AUDIO_QUEUE[0];
      }
      if (currentItem) {
        if (!ACTIVE_SESSION_ID && typeof loadState === "function") {
          await loadState(null);
          if (!ACTIVE_SESSION_ID && STATE && (STATE.selected_session || STATE.current_session)) {
            const s = STATE.selected_session || STATE.current_session;
            ACTIVE_SESSION_ID = Number(s.id || 0);
            if (STATE.sessions && typeof renderShifts === "function") renderShifts(STATE.sessions, s);
          }
          if (!ACTIVE_SESSION_ID && STATE && STATE.sessions && STATE.sessions.length) {
            const first = STATE.sessions[0];
            ACTIVE_SESSION_ID = Number(first.id || 0);
            if (ACTIVE_SESSION_ID && typeof loadState === "function") {
              await loadState(ACTIVE_SESSION_ID);
              if (STATE.sessions && typeof renderShifts === "function") renderShifts(STATE.sessions, first);
            }
          }
        }
        try {
          await openAudioCatalog(currentItem);
        } catch (_) { }
        if (!ACTIVE_ITEM_ID && STATE && STATE.catalog && currentItem) {
          const freq = String(currentItem.frequency || "").trim();
          const grp = String(currentItem.group_code || "").trim();
          const cat = STATE.catalog.find(
            (c) => String(c.frequency || "").trim() === freq && String(c.group_code || "").trim() === grp
          );
          if (cat && ACTIVE_SESSION_ID) {
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
          }
        }
      }
    }

    if (!ACTIVE_ITEM_ID) {
      updateSendButton();
      setText("intercepts-status", "Сначала выберите активную группу (частота/группа) слева, затем отправьте текст.");
      setTimeout(() => setText("intercepts-status", ""), 5000);
      try { input.focus(); } catch (_) { }
      return;
    }

    // Активная группа выбрана: добавляем текст в бланк и сохраняем.
    text = normalizeTimeInText(text);
    let newText = blank.value || "";
    if (newText && !newText.endsWith("\n")) newText += "\n";
    const appendedText = text;
    const appendedStart = newText.length;
    newText += text;
    blank.value = newText;

    const previewBox = $("intercept-preview");
    const previewVisible = previewBox && previewBox.style.display !== "none";
    const wrap = $("intercept-text-wrapper");
    const editorVisible = wrap && wrap.style.display !== "none" && !blank.disabled;
    if (previewVisible) {
      _renderPreview();
      requestAnimationFrame(() => _scrollToBottom(previewBox));
    } else if (editorVisible) {
      requestAnimationFrame(() => {
        try { blank.scrollTop = blank.scrollHeight; } catch (_) { }
      });
    }
    if ($("audio-intercepts-panel")) {
      requestAnimationFrame(() => {
        try {
          const wrapper = $("intercept-text-wrapper");
          if (wrapper && wrapper.scrollIntoView) {
            wrapper.scrollIntoView({ behavior: "smooth", block: "end" });
          }
        } catch (_) { }
      });
    }
    if (!CAN_EDIT || ACTIVE_CLOSED) {
      setText("intercepts-status", "Текст в бланке. Нет доступа к редактированию — сохранить на сервер нельзя.");
      setTimeout(() => setText("intercepts-status", ""), 4000);
      try { input.focus(); } catch (_) { }
      return;
    }

    const sentDraft = text;
    input.value = "";
    updateSendButton();
    setText("intercepts-status", "Сохранение…");
    saveNow({ sync: true, force: true })
      .then(() => {
        if (previewVisible) requestAnimationFrame(() => _scrollToBottom(previewBox));
        else if (editorVisible) {
          requestAnimationFrame(() => {
            try { blank.scrollTop = blank.scrollHeight; } catch (_) { }
          });
        }
        let statusMsg = "Текст отправлен в бланк и сохранён";
        if (isAudioPage && ASR_UI_ENABLED) {
          maybeLearnAsrFromBlankSend(appendedText)
            .then((res) => {
              if (res && Number(res.learned || 0) > 0) {
                statusMsg = `Текст отправлен в бланк. В обучение: ${res.learned} прим.`;
              }
              setText("intercepts-status", statusMsg);
              setTimeout(() => setText("intercepts-status", ""), 3000);
            })
            .catch(() => {
              setText("intercepts-status", statusMsg);
              setTimeout(() => setText("intercepts-status", ""), 2000);
            });
        } else {
          setText("intercepts-status", statusMsg);
          setTimeout(() => setText("intercepts-status", ""), 2000);
        }
      })
      .catch((saveError) => {
        input.value = sentDraft;
        updateSendButton();
        setText(
          "intercepts-status",
          "Ошибка сохранения: " + (saveError && saveError.message ? saveError.message : String(saveError))
        );
        console.error("Ошибка сохранения после отправки перехвата:", saveError);
      });
    try { input.focus(); } catch (_) { }
  }

  // Кнопка «Отправить в бланк» — делегирование (клик по кнопке или по иконке внутри неё)
  document.body.addEventListener("click", (ev) => {
    const btn = ev.target && (ev.target.id === "send-input-btn" || (ev.target.closest && ev.target.closest("#send-input-btn")));
    if (btn) {
      ev.preventDefault();
      sendInputToBlank().catch((e) => {
        setText("intercepts-status", "Ошибка: " + (e && e.message ? e.message : String(e)));
        console.error("sendInputToBlank:", e);
      });
    }
  }, true);

  // Обновление состояния кнопки при вводе (без постоянного таймера)
  document.addEventListener("input", (ev) => {
    if (ev.target && ev.target.id === "intercept-input") updateSendButton(ev.target);
  }, true);
  document.addEventListener("focusin", (ev) => {
    if (ev.target && ev.target.id === "intercept-input") updateSendButton(ev.target);
  }, true);
  updateSendButton();

  // На странице «Аудиоперехваты» явно привязываемся к полю и кнопке внутри панели аудио
  if (document.querySelector("[data-page-mode='audio']") && $("audio-intercepts-panel")) {
    const panel = $("audio-intercepts-panel");
    const panelInput = panel.querySelector("#intercept-input");
    const panelBtn = panel.querySelector("#send-input-btn");
    if (panelBtn) {
      panelBtn.disabled = false;
      panelBtn.classList.remove("is-empty");
    }
    if (panelInput && typeof updateSendButton === "function") {
      updateSendButton(panelInput);
    }
  }

  window.updateSendButton = updateSendButton;
});

})();
