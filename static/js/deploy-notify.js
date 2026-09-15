/**
 * Опрос сервера на предмет нового deploy-revision; при смене показываем диалог «Обновить страницу?».
 * На HUB — скачивание обновления пакета с прогрессом % и тостом об успехе.
 * На SERVER (admin) — тост, какой HUB успешно обновился.
 */
(function () {
  const LS_ACK = "wp_deploy_banner_ack_rev";
  const LS_HUB_UPDATE_ACK = "wp_hub_update_banner_ack_rev";
  const LS_HUB_EXPECT = "wp_hub_update_expect_rev";
  const LS_HUB_REPORTS_ACK = "wp_hub_reports_ack_ids";
  const POLL_MS = 120_000;
  const HUB_REPORTS_POLL_MS = 45_000;

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  let polling = false;
  let modalShowing = false;
  let hubReportsPolling = false;

  function showAppToast(message, variant) {
    const toastEl = document.getElementById("app-toast");
    const bodyEl = document.getElementById("app-toast-body");
    if (!toastEl || !bodyEl) {
      try { window.alert(String(message || "")); } catch (_e) {}
      return;
    }
    bodyEl.textContent = String(message || "");
    toastEl.classList.remove("text-bg-success", "text-bg-danger", "text-bg-warning", "text-bg-primary", "text-bg-dark");
    const map = { success: "text-bg-success", danger: "text-bg-danger", warning: "text-bg-warning", primary: "text-bg-primary" };
    toastEl.classList.add(map[variant] || "text-bg-dark");
    if (typeof bootstrap !== "undefined" && bootstrap.Toast) {
      bootstrap.Toast.getOrCreateInstance(toastEl, { delay: 7000 }).show();
    } else {
      toastEl.classList.add("show");
      setTimeout(() => toastEl.classList.remove("show"), 7000);
    }
  }

  function getAck() {
    try { return String(localStorage.getItem(LS_ACK) || "").trim(); } catch (_e) { return ""; }
  }
  function setAck(rev) {
    try { localStorage.setItem(LS_ACK, String(rev || "").trim()); } catch (_e) {}
  }
  function getHubUpdateAck() {
    try { return String(localStorage.getItem(LS_HUB_UPDATE_ACK) || "").trim(); } catch (_e) { return ""; }
  }
  function setHubUpdateAck(rev) {
    try { localStorage.setItem(LS_HUB_UPDATE_ACK, String(rev || "").trim()); } catch (_e) {}
  }
  function getExpectRev() {
    try { return String(localStorage.getItem(LS_HUB_EXPECT) || "").trim(); } catch (_e) { return ""; }
  }
  function setExpectRev(rev) {
    try { localStorage.setItem(LS_HUB_EXPECT, String(rev || "").trim()); } catch (_e) {}
  }
  function clearExpectRev() {
    try { localStorage.removeItem(LS_HUB_EXPECT); } catch (_e) {}
  }
  function getReportsAck() {
    try {
      const raw = JSON.parse(localStorage.getItem(LS_HUB_REPORTS_ACK) || "[]");
      return Array.isArray(raw) ? raw.map(String) : [];
    } catch (_e) { return []; }
  }
  function setReportsAck(ids) {
    try { localStorage.setItem(LS_HUB_REPORTS_ACK, JSON.stringify(ids.slice(0, 100))); } catch (_e) {}
  }

  function hasUnsavedInput() {
    return Boolean(document.querySelector("[data-wp-update-dirty='1']"));
  }

  function watchUnsavedInput() {
    document.addEventListener("input", (event) => {
      const el = event.target;
      if (el && /^(INPUT|TEXTAREA|SELECT)$/i.test(el.tagName || "")) {
        el.dataset.wpUpdateDirty = "1";
      }
    }, true);
  }

  async function fetchHubUpdate() {
    const res = await fetch("/api/hub-update/manifest", {
      credentials: "same-origin",
      method: "GET",
      cache: "no-cache",
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false || !data.available) return null;
    return data.release || null;
  }

  async function fetchHubUpdateStatus() {
    const res = await fetch("/api/hub-update/status", {
      credentials: "same-origin",
      method: "GET",
      cache: "no-cache",
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) return {};
    return (data.status && typeof data.status === "object") ? data.status : {};
  }

  function formatBytes(n) {
    const v = Number(n) || 0;
    if (v < 1024) return v + " Б";
    if (v < 1024 * 1024) return (v / 1024).toFixed(1) + " КБ";
    return (v / (1024 * 1024)).toFixed(1) + " МБ";
  }

  function showHubUpdateModal(release) {
    const revision = String(release && release.revision || "").trim();
    if (modalShowing || !revision) return;
    modalShowing = true;
    const wrap = document.createElement("div");
    wrap.innerHTML = `
<div class="modal fade" id="wp-hub-update-modal" tabindex="-1" aria-labelledby="wp-hub-update-title" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered"><div class="modal-content">
    <div class="modal-header"><h5 class="modal-title" id="wp-hub-update-title">Доступно обновление HUB</h5>
      <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Закрыть"></button></div>
    <div class="modal-body">
      <p class="mb-1"><strong>${esc((release && release.title) || "Новое обновление")}</strong></p>
      ${(release && release.notes) ? ("<p>" + esc(release.notes) + "</p>") : ""}
      <p class="small text-muted mb-0">Версия: ${esc(revision)}. Перед обновлением сохраните незавершённые записи. HUB перезапустится, данные и настройки сохранятся.</p>
      <div class="mt-3" data-wp-hub-update-progress-wrap style="display:none">
        <div class="d-flex justify-content-between small mb-1">
          <span data-wp-hub-update-progress-label>Загрузка…</span>
          <span data-wp-hub-update-progress-pct>0%</span>
        </div>
        <div class="progress" style="height: 1.25rem" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
          <div class="progress-bar progress-bar-striped progress-bar-animated" style="width:0%" data-wp-hub-update-progress>0%</div>
        </div>
      </div>
      <div class="small text-danger mt-2" data-wp-hub-update-error></div>
    </div>
    <div class="modal-footer flex-wrap gap-2">
      <button type="button" class="btn btn-outline-secondary" data-wp-hub-update-later>Позже</button>
      <button type="button" class="btn btn-primary" data-wp-hub-update-apply>Скачать и перезапустить HUB</button>
    </div>
  </div></div>
</div>`;
    document.body.appendChild(wrap.firstElementChild);
    const el = document.getElementById("wp-hub-update-modal");
    const modal = typeof bootstrap !== "undefined" ? new bootstrap.Modal(el) : null;
    if (!modal) { modalShowing = false; el && el.remove(); return; }
    el.addEventListener("hidden.bs.modal", () => { modalShowing = false; el && el.remove(); }, { once: true });
    const laterEl = el.querySelector("[data-wp-hub-update-later]");
    if (laterEl) laterEl.addEventListener("click", () => {
      setHubUpdateAck(revision); modal.hide();
    });
    const applyEl = el.querySelector("[data-wp-hub-update-apply]");
    if (applyEl) applyEl.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      const laterBtn = el.querySelector("[data-wp-hub-update-later]");
      const error = el.querySelector("[data-wp-hub-update-error]");
      const progWrap = el.querySelector("[data-wp-hub-update-progress-wrap]");
      const progBar = el.querySelector("[data-wp-hub-update-progress]");
      const progPct = el.querySelector("[data-wp-hub-update-progress-pct]");
      const progLabel = el.querySelector("[data-wp-hub-update-progress-label]");
      const progRoot = el.querySelector(".progress");
      if (hasUnsavedInput()) {
        error.className = "small text-danger mt-2";
        error.textContent = "Есть несохранённые поля. Сохраните изменения, обновите страницу и повторите.";
        return;
      }
      let stopPoll = false;
      const setProgress = (pct, label) => {
        const p = Math.max(0, Math.min(100, Math.round(Number(pct) || 0)));
        if (progWrap) progWrap.style.display = "block";
        if (progBar) {
          progBar.style.width = p + "%";
          progBar.textContent = p + "%";
        }
        if (progPct) progPct.textContent = p + "%";
        if (progLabel) progLabel.textContent = label || "Загрузка…";
        if (progRoot) progRoot.setAttribute("aria-valuenow", String(p));
      };
      const pollProgress = async () => {
        while (!stopPoll) {
          try {
            const st = await fetchHubUpdateStatus();
            const state = String(st.state || "");
            const pct = Number(st.percent);
            if (state === "downloading" && Number.isFinite(pct)) {
              const recv = st.bytes_received;
              const total = st.bytes_total;
              const extra = (recv && total) ? (" (" + formatBytes(recv) + " / " + formatBytes(total) + ")") : "";
              setProgress(pct, "Скачивание пакета" + extra);
            } else if (state === "verifying") {
              setProgress(100, "Проверка контрольной суммы…");
            } else if (state === "checkpointing") {
              setProgress(100, "Фиксация баз данных…");
            } else if (state === "queued" || state === "waiting" || state === "installing" || state === "health_check") {
              setProgress(100, "Установка и перезапуск HUB…");
            } else if (state === "failed") {
              setProgress(pct || 0, "Ошибка обновления");
            }
          } catch (_e) {}
          await new Promise((r) => setTimeout(r, 450));
        }
      };
      try {
        button.disabled = true;
        if (laterBtn) laterBtn.disabled = true;
        error.className = "small text-muted mt-2";
        error.textContent = "Идёт загрузка обновления…";
        setProgress(0, "Подготовка…");
        pollProgress();
        setExpectRev(revision);
        const response = await fetch("/api/hub-update/apply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ revision }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.ok === false) throw new Error(data.error || ("HTTP " + response.status));
        setHubUpdateAck(revision);
        setProgress(100, "Пакет готов. HUB перезапускается…");
        error.className = "small text-success mt-2";
        error.textContent = "Обновление принято. Страница обновится после перезапуска HUB…";
        setTimeout(() => window.location.reload(), 10000);
      } catch (err) {
        stopPoll = true;
        clearExpectRev();
        error.className = "small text-danger mt-2";
        error.textContent = "Не удалось начать обновление: " + (err.message || err);
        button.disabled = false;
        if (laterBtn) laterBtn.disabled = false;
      } finally {
        setTimeout(() => { stopPoll = true; }, 12000);
      }
    });
    modal.show();
  }

  async function maybeShowHubUpdateSuccess() {
    const expect = getExpectRev();
    if (!expect) return;
    try {
      const st = await fetchHubUpdateStatus();
      const state = String(st.state || "");
      const rev = String(st.revision || "").trim() || expect;
      const manifestRes = await fetch("/api/hub-update/manifest", {
        credentials: "same-origin", method: "GET", cache: "no-cache",
      });
      const manifest = await manifestRes.json().catch(() => ({}));
      const installed = String(manifest.installed_revision || "").trim();
      const ok =
        (state === "completed" && (rev === expect || !st.revision)) ||
        installed === expect;
      if (!ok) {
        if (state === "failed" || state === "rolled_back") {
          clearExpectRev();
          showAppToast("Обновление HUB не удалось: " + (st.error || state), "danger");
        }
        return;
      }
      clearExpectRev();
      setHubUpdateAck(expect);
      showAppToast("HUB успешно обновлён до версии " + expect, "success");
      try {
        await fetch("/api/hub-update/notify-server", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ revision: expect }),
        });
      } catch (_e) {}
    } catch (_e) {}
  }

  async function fetchAnnounce() {
    const res = await fetch("/api/client/deploy-announce", {
      credentials: "same-origin",
      method: "GET",
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) return null;
    return data;
  }

  function showModal(revision, message) {
    if (modalShowing || typeof revision !== "string" || !revision) return;
    modalShowing = true;
    const msg =
      message && String(message).trim()
        ? ("<p>" + esc(message) + "</p>")
        : "<p>Выложено обновление веб-портала. Обновите страницу (кэш сбросится по Ctrl+F5 при необходимости).</p>";
    const wrap = document.createElement("div");
    wrap.innerHTML = `
<div class="modal fade" id="wp-deploy-announce-modal" tabindex="-1" aria-labelledby="wp-deploy-announce-title" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title" id="wp-deploy-announce-title">Доступно обновление</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Закрыть"></button>
      </div>
      <div class="modal-body">
        ${msg}
        <p class="small text-muted mb-0 wp-mono">revision: ${esc(revision)}</p>
      </div>
      <div class="modal-footer flex-wrap gap-2">
        <button type="button" class="btn btn-outline-secondary" data-wp-deploy-later="">Позже</button>
        <button type="button" class="btn btn-primary" data-wp-deploy-reload="">Обновить страницу</button>
      </div>
    </div>
  </div>
</div>`;
    document.body.appendChild(wrap.firstElementChild);
    const el = document.getElementById("wp-deploy-announce-modal");
    const modal = typeof bootstrap !== "undefined" ? new bootstrap.Modal(el) : null;
    if (!modal) {
      modalShowing = false;
      if (el && el.parentNode) el.parentNode.removeChild(el);
      return;
    }
    el.addEventListener(
      "hidden.bs.modal",
      () => {
        modalShowing = false;
        if (el && el.parentNode) el.parentNode.removeChild(el);
      },
      { once: true }
    );
    const later = el.querySelector("[data-wp-deploy-later]");
    if (later) later.addEventListener("click", () => {
      setAck(revision);
      modal.hide();
    });
    const reload = el.querySelector("[data-wp-deploy-reload]");
    if (reload) reload.addEventListener("click", () => {
      setAck(revision);
      modal.hide();
      window.location.reload();
    });
    modal.show();
  }

  async function pollHubReportsOnce() {
    if (hubReportsPolling || document.hidden) return;
    hubReportsPolling = true;
    try {
      const res = await fetch("/api/admin/updates/hub-reports?limit=20", {
        credentials: "same-origin",
        method: "GET",
        cache: "no-cache",
      });
      if (res.status === 403 || res.status === 409) return;
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) return;
      const reports = Array.isArray(data.reports) ? data.reports : [];
      if (!reports.length) return;
      const ack = new Set(getReportsAck());
      const fresh = reports.filter((r) => r && r.id && !ack.has(String(r.id)));
      if (!fresh.length) {
        if (!ack.size) setReportsAck(reports.map((r) => String(r.id)));
        return;
      }
      fresh.slice(0, 3).forEach((r) => {
        const name = String(r.hub_name || r.hub_id || "HUB").trim();
        const rev = String(r.revision || "").trim();
        showAppToast("HUB «" + name + "» успешно обновился до " + rev, "success");
        ack.add(String(r.id));
      });
      setReportsAck(Array.from(ack));
    } catch (_e) {
    } finally {
      hubReportsPolling = false;
    }
  }

  async function pollOnce() {
    if (polling || document.hidden) return;
    polling = true;
    try {
      const update = await fetchHubUpdate();
      if (update && String(update.revision || "").trim() !== getHubUpdateAck()) {
        showHubUpdateModal(update);
        return;
      }
      const data = await fetchAnnounce();
      if (!data) return;
      const rev = String(data.revision || "").trim();
      if (!rev) return;
      if (rev === getAck()) return;
      showModal(rev, data.message || "");
    } catch (_e) {
    } finally {
      polling = false;
    }
  }

  function start() {
    if (!document.body || document.body.getAttribute("data-wp-deploy-poll") !== "1") return;
    watchUnsavedInput();
    maybeShowHubUpdateSuccess();
    pollOnce();
    setInterval(pollOnce, POLL_MS);
    pollHubReportsOnce();
    setInterval(pollHubReportsOnce, HUB_REPORTS_POLL_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
