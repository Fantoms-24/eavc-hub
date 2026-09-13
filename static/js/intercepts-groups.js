(function () {
  "use strict";

function parseAddGroupCodes(s) {
  return String(s || "")
    .split(/[,;，；]/)
    .map((x) => x.trim())
    .filter(Boolean);
}

function resetFrequencyRows(containerId) {
  const container = $(containerId);
  if (!container) return;
  const rows = container.querySelectorAll(".add-group-freq-row");
  rows.forEach((r, i) => {
    if (i > 0) r.remove();
  });
  const first = container.querySelector(".add-group-freq-row");
  if (first) {
    const fi = first.querySelector(".add-group-freq-input");
    const gi = first.querySelector(".add-group-grp-input");
    if (fi) fi.value = "";
    if (gi) gi.value = "";
  }
  syncFrequencyRowRemoveButtons(containerId);
}

function syncFrequencyRowRemoveButtons(containerId) {
  const container = $(containerId);
  if (!container) return;
  const rows = container.querySelectorAll(".add-group-freq-row");
  const multi = rows.length > 1;
  rows.forEach((row) => {
    const btn = row.querySelector(".add-group-freq-remove");
    if (btn) btn.disabled = !multi;
  });
}

function addFrequencyRow(containerId) {
  const container = $(containerId);
  const first = container && container.querySelector(".add-group-freq-row");
  if (!container || !first) return;
  const row = first.cloneNode(true);
  const fi = row.querySelector(".add-group-freq-input");
  const gi = row.querySelector(".add-group-grp-input");
  if (fi) fi.value = "";
  if (gi) gi.value = "";
  container.appendChild(row);
  syncFrequencyRowRemoveButtons(containerId);
}

function removeFrequencyRow(btn) {
  const row = btn && btn.closest(".add-group-freq-row");
  const container = row && row.parentElement;
  if (!row || !container || !container.id) return;
  if (container.querySelectorAll(".add-group-freq-row").length <= 1) return;
  row.remove();
  syncFrequencyRowRemoveButtons(container.id);
}

function collectFreqGroupPairsFromContainer(containerId) {
  const container = $(containerId);
  const pairs = [];
  let rowInvalid = false;
  if (container) {
    const rowList = container.querySelectorAll(".add-group-freq-row");
    for (let r = 0; r < rowList.length; r++) {
      const row = rowList[r];
      const fi = row.querySelector(".add-group-freq-input");
      const gi = row.querySelector(".add-group-grp-input");
      const freq = String((fi && fi.value) || "").trim();
      const codes = parseAddGroupCodes(gi && gi.value);
      if (!freq && codes.length === 0) continue;
      if (!freq || codes.length === 0) {
        rowInvalid = true;
        break;
      }
      for (let c = 0; c < codes.length; c++) {
        pairs.push({ frequency: freq, group_code: codes[c] });
      }
    }
  }
  return { pairs, rowInvalid };
}

/** Контекст модалки «Подразделение» (настройки) */
let UNIT_MANAGE_CTX = { unitKey: "", unitName: "" };

function openAddGroupModal() {
  const modalEl = $("addGroupModal");
  const form = $("add-group-form");
  if (form) form.reset();
  resetFrequencyRows("add-group-freq-rows");
  if (!modalEl || !window.bootstrap || !window.bootstrap.Modal) return;
  const modal = window.bootstrap.Modal.getOrCreateInstance(modalEl);
  const onShown = () => {
    const u = $("add-group-unit");
    if (u) {
      u.focus();
      u.select();
    }
    modalEl.removeEventListener("shown.bs.modal", onShown);
  };
  modalEl.addEventListener("shown.bs.modal", onShown);
  modal.show();
}

async function submitAddGroupFromModal(ev) {
  ev.preventDefault();
  const form = $("add-group-form");
  const unit = String(($("add-group-unit") && $("add-group-unit").value) || "").trim();
  const location = String(($("add-group-location") && $("add-group-location").value) || "").trim();
  if (!unit) {
    if (form && form.checkValidity) form.reportValidity();
    return;
  }
  const { pairs, rowInvalid } = collectFreqGroupPairsFromContainer("add-group-freq-rows");
  if (rowInvalid) {
    setText("intercepts-status", "В каждой заполненной строке укажите частоту и хотя бы один код группы (или удалите лишнюю строку).");
    return;
  }
  if (pairs.length === 0) {
    setText("intercepts-status", "Добавьте хотя бы одну частоту и код группы (несколько групп — через запятую).");
    return;
  }
  const modalEl = $("addGroupModal");
  if (modalEl && window.bootstrap && window.bootstrap.Modal) {
    const inst = window.bootstrap.Modal.getInstance(modalEl);
    if (inst) inst.hide();
  }
  setText("intercepts-status", pairs.length > 1 ? `Добавляю записи (${pairs.length})…` : "Добавляю группу…");
  let ok = 0;
  const errs = [];
  try {
    for (let i = 0; i < pairs.length; i++) {
      const p = pairs[i];
      try {
        await apiPost("/api/intercepts/catalog", {
          unit_name: unit,
          frequency: p.frequency,
          group_code: p.group_code,
          location: location,
        });
        ok++;
      } catch (e) {
        errs.push(`${p.frequency} / ${p.group_code}: ${e && e.message ? e.message : e}`);
      }
    }
    await loadState();
    if (errs.length === 0) {
      setText("intercepts-status", ok > 1 ? `Добавлено записей: ${ok}.` : "Группа добавлена.");
    } else {
      setText(
        "intercepts-status",
        `Добавлено ${ok} из ${pairs.length}. ${errs.slice(0, 4).join("; ")}${errs.length > 4 ? "…" : ""}`
      );
    }
  } catch (e) {
    setText("intercepts-status", `Ошибка: ${e.message || e}`);
  }
}

async function addGroup() {
  if (!CAN_START) return;
  openAddGroupModal();
}

function openUnitManageModal(unitKey, unitName) {
  if (!CAN_START) return;
  UNIT_MANAGE_CTX = { unitKey: String(unitKey || ""), unitName: String(unitName || "").trim() };
  const nameEl = $("unit-manage-name");
  if (nameEl) nameEl.value = UNIT_MANAGE_CTX.unitName;
  const delConf = $("unit-manage-delete-confirm");
  if (delConf) delConf.value = "";
  const locEl = $("unit-manage-location");
  if (locEl) locEl.value = "";
  resetFrequencyRows("unit-manage-freq-rows");
  const modalEl = $("unitManageModal");
  if (!modalEl || !window.bootstrap || !window.bootstrap.Modal) return;
  window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
  const onShown = () => {
    if (nameEl) nameEl.focus();
    modalEl.removeEventListener("shown.bs.modal", onShown);
  };
  modalEl.addEventListener("shown.bs.modal", onShown);
}

async function submitUnitManageRename() {
  const nameEl = $("unit-manage-name");
  const newName = nameEl ? String(nameEl.value || "").trim() : "";
  const oldName = String(UNIT_MANAGE_CTX.unitName || "").trim();
  if (!newName || newName === oldName) {
    setText("intercepts-status", "Укажите новое название, отличное от текущего.");
    return;
  }
  setText("intercepts-status", "Переименовываю подразделение…");
  try {
    await apiPost("/api/intercepts/catalog/rename-unit", { old_name: oldName, new_name: newName });
    UNIT_MANAGE_CTX.unitName = newName;
    if (nameEl) nameEl.value = newName;
    await loadState(ACTIVE_SESSION_ID || null);
    setText("intercepts-status", "Название обновлено.");
  } catch (e) {
    setText("intercepts-status", `Ошибка: ${e.message || e}`);
  }
}

async function submitUnitManageAddFrequencies() {
  const unit = String(UNIT_MANAGE_CTX.unitName || "").trim();
  const location = String(($("unit-manage-location") && $("unit-manage-location").value) || "").trim();
  if (!unit) {
    setText("intercepts-status", "Не выбрано подразделение.");
    return;
  }
  const { pairs, rowInvalid } = collectFreqGroupPairsFromContainer("unit-manage-freq-rows");
  if (rowInvalid) {
    setText("intercepts-status", "В каждой строке укажите частоту и хотя бы один код группы (или удалите пустую строку).");
    return;
  }
  if (pairs.length === 0) {
    setText("intercepts-status", "Добавьте строки с частотой и кодами групп (несколько групп — через запятую).");
    return;
  }
  setText("intercepts-status", pairs.length > 1 ? `Добавляю записи (${pairs.length})…` : "Добавляю…");
  let ok = 0;
  const errs = [];
  try {
    for (let i = 0; i < pairs.length; i++) {
      const p = pairs[i];
      try {
        await apiPost("/api/intercepts/catalog", {
          unit_name: unit,
          frequency: p.frequency,
          group_code: p.group_code,
          location: location,
        });
        ok++;
      } catch (e) {
        errs.push(`${p.frequency} / ${p.group_code}: ${e && e.message ? e.message : e}`);
      }
    }
    await loadState(ACTIVE_SESSION_ID || null);
    resetFrequencyRows("unit-manage-freq-rows");
    if (errs.length === 0) {
      setText("intercepts-status", ok > 1 ? `Добавлено записей: ${ok}.` : "Запись добавлена.");
    } else {
      setText(
        "intercepts-status",
        `Добавлено ${ok} из ${pairs.length}. ${errs.slice(0, 3).join("; ")}${errs.length > 3 ? "…" : ""}`
      );
    }
  } catch (e) {
    setText("intercepts-status", `Ошибка: ${e.message || e}`);
  }
}

async function submitUnitManageDelete() {
  const unit = String(UNIT_MANAGE_CTX.unitName || "").trim();
  const confEl = $("unit-manage-delete-confirm");
  const typed = confEl ? String(confEl.value || "").trim() : "";
  if (!unit) {
    setText("intercepts-status", "Не выбрано подразделение.");
    return;
  }
  if (typed !== unit) {
    setText("intercepts-status", "Введите в поле подтверждения точное текущее название подразделения (как в каталоге).");
    return;
  }
  setText("intercepts-status", "Удаляю подразделение…");
  try {
    await apiPost("/api/intercepts/catalog/delete-unit", { unit_name: unit });
    const modalEl = $("unitManageModal");
    if (modalEl && window.bootstrap && window.bootstrap.Modal) {
      const inst = window.bootstrap.Modal.getInstance(modalEl);
      if (inst) inst.hide();
    }
    if (ACTIVE_CAT && _unitKey(ACTIVE_CAT.unit_name) === _unitKey(unit)) {
      ACTIVE_ITEM_ID = 0;
      ACTIVE_CATALOG_ID = 0;
      ACTIVE_CAT = null;
      const ta = $("intercept-text");
      if (ta) ta.value = "";
      setText("editor-subtitle", "Выбери группу слева");
      syncIxChatHeader();
    }
    await loadState(ACTIVE_SESSION_ID || null);
    setText("intercepts-status", "Подразделение удалено.");
  } catch (e) {
    setText("intercepts-status", `Ошибка: ${e.message || e}`);
  }
}


  window.openAddGroupModal = openAddGroupModal;
  window.openUnitManageModal = openUnitManageModal;
  window.addGroup = addGroup;
  window.addFrequencyRow = addFrequencyRow;
  window.removeFrequencyRow = removeFrequencyRow;
  window.submitAddGroupFromModal = submitAddGroupFromModal;
  window.submitUnitManageRename = submitUnitManageRename;
  window.submitUnitManageAddFrequencies = submitUnitManageAddFrequencies;
  window.submitUnitManageDelete = submitUnitManageDelete;
})();
