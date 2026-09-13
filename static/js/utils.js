/**
 * Общие утилиты для страниц (DOM, тосты, модалки, тег позывного).
 * Требует: api.js (apiPost), Bootstrap (для Modal/Toast).
 */
function $(id) {
  return document.getElementById(id);
}

function setText(id, text) {
  const el = $(id);
  if (el) el.textContent = text || "";
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function debounce(fn, wait) {
  wait = Number(wait) || 250;
  let t = null;
  return function (...args) {
    if (t) clearTimeout(t);
    t = setTimeout(() => fn.apply(this, args), wait);
  };
}

function showToast(message, variant) {
  const toastEl = $("app-toast");
  const bodyEl = $("app-toast-body");
  if (!toastEl || !bodyEl || !window.bootstrap) return;
  if (bodyEl) bodyEl.textContent = message || "";
  toastEl.classList.remove("text-bg-success", "text-bg-danger", "text-bg-warning", "text-bg-info");
  if (variant) toastEl.classList.add("text-bg-" + variant);
  const toast = window.bootstrap.Toast.getOrCreateInstance(toastEl, { delay: 2500 });
  toast.show();
}

function getModal(elOrId) {
  const el = typeof elOrId === "string" ? $(elOrId) : elOrId;
  if (!el || !window.bootstrap || !window.bootstrap.Modal) return null;
  return window.bootstrap.Modal.getOrCreateInstance(el);
}

function showModal(elOrId) {
  const modal = getModal(elOrId);
  if (modal) modal.show();
}

// ---- Единый модал «Тег позывного» (Анализ + Перехваты) ----
let _callsignTagCurrent = null;

function openCallsignTagModal(callsign, onSaved) {
  if (!callsign || !Number(callsign.id)) return;
  const modalEl = $("callsignTagModal");
  const tagEl = $("cs-tag-input");
  const descEl = $("cs-tag-desc");
  const useColorEl = $("cs-tag-use-color");
  const colorEl = $("cs-tag-color");
  if (!modalEl || !tagEl || !descEl) return;

  _callsignTagCurrent = { id: Number(callsign.id), onSaved: typeof onSaved === "function" ? onSaved : null };

  tagEl.value = String(callsign.tag || "").trim();
  descEl.value = String(callsign.tag_desc || "").trim();
  const curColor = String(callsign.tag_color || "").trim();
  if (curColor && /^#[0-9a-fA-F]{6}$/.test(curColor)) {
    if (useColorEl) useColorEl.checked = true;
    if (colorEl) colorEl.value = curColor;
  } else {
    if (useColorEl) useColorEl.checked = false;
    if (colorEl) colorEl.value = "#f59e0b";
  }
  if (colorEl) colorEl.disabled = !(useColorEl && useColorEl.checked);
  if (useColorEl && colorEl) {
    useColorEl.onchange = function () { colorEl.disabled = !useColorEl.checked; };
  }

  const modal = getModal(modalEl);
  if (modal) modal.show();
}

function _callsignTagSave() {
  const cur = _callsignTagCurrent;
  if (!cur || typeof window.apiPost !== "function") return;
  const tagEl = $("cs-tag-input");
  const descEl = $("cs-tag-desc");
  const useColorEl = $("cs-tag-use-color");
  const colorEl = $("cs-tag-color");
  const tag = tagEl ? String(tagEl.value || "").trim() : "";
  const tag_desc = descEl ? String(descEl.value || "").trim() : "";
  const tag_color = (useColorEl && useColorEl.checked && colorEl) ? String(colorEl.value || "").trim() : "";

  window.apiPost("/api/analysis/callsign-tag", {
    callsign_id: cur.id,
    tag,
    tag_desc,
    tag_color,
  }).then(() => {
    const modalEl = $("callsignTagModal");
    if (modalEl && window.bootstrap && window.bootstrap.Modal) {
      const m = window.bootstrap.Modal.getInstance(modalEl);
      if (m) m.hide();
    }
    if (cur.onSaved) cur.onSaved();
    _callsignTagCurrent = null;
  }).catch((e) => {
    if (typeof window.showToast === "function") window.showToast("Ошибка: " + (e.message || e), "danger");
    else if (typeof window.alert === "function") window.alert("Ошибка: " + (e.message || e));
  });
}

document.addEventListener("DOMContentLoaded", function () {
  const saveBtn = $("cs-tag-save");
  if (saveBtn) saveBtn.addEventListener("click", _callsignTagSave);
});
