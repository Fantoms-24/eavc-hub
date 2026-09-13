/**
 * Опрос сервера на предмет нового deploy-revision; при смене показываем диалог «Обновить страницу?».
 */
(function () {
  const LS_ACK = "wp_deploy_banner_ack_rev";
  const LS_HUB_UPDATE_ACK = "wp_hub_update_banner_ack_rev";
  const POLL_MS = 120_000;

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  let polling = false;
  let modalShowing = false;

  function getAck() {
    try {
      return String(localStorage.getItem(LS_ACK) || "").trim();
    } catch (_e) {
      return "";
    }
  }

  function setAck(rev) {
    try {
      localStorage.setItem(LS_ACK, String(rev || "").trim());
    } catch (_e) {
      // ignore
    }
  }

  function getHubUpdateAck() {
    try {
      return String(localStorage.getItem(LS_HUB_UPDATE_ACK) || "").trim();
    } catch (_e) {
      return "";
    }
  }

  function setHubUpdateAck(rev) {
    try {
      localStorage.setItem(LS_HUB_UPDATE_ACK, String(rev || "").trim());
    } catch (_e) {
      // ignore
    }
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

  function showHubUpdateModal(release) {
    const revision = String(release?.revision || "").trim();
    if (modalShowing || !revision) return;
    modalShowing = true;
    const wrap = document.createElement("div");
    wrap.innerHTML = `
<div class="modal fade" id="wp-hub-update-modal" tabindex="-1" aria-labelledby="wp-hub-update-title" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered"><div class="modal-content">
    <div class="modal-header"><h5 class="modal-title" id="wp-hub-update-title">Доступно обновление HUB</h5>
      <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Закрыть"></button></div>
    <div class="modal-body">
      <p class="mb-1"><strong>${esc(release?.title || "Новое обновление")}</strong></p>
      ${release?.notes ? `<p>${esc(release.notes)}</p>` : ""}
      <p class="small text-muted mb-0">Версия: ${esc(revision)}. Перед обновлением сохраните незавершённые записи. HUB перезапустится, данные и настройки сохранятся.</p>
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
    if (!modal) { modalShowing = false; el?.remove(); return; }
    el.addEventListener("hidden.bs.modal", () => { modalShowing = false; el?.remove(); }, { once: true });
    el.querySelector("[data-wp-hub-update-later]")?.addEventListener("click", () => {
      setHubUpdateAck(revision); modal.hide();
    });
    el.querySelector("[data-wp-hub-update-apply]")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      const error = el.querySelector("[data-wp-hub-update-error]");
      if (hasUnsavedInput()) {
        error.textContent = "Есть несохранённые поля. Сохраните изменения, обновите страницу и повторите.";
        return;
      }
      try {
        button.disabled = true;
        error.className = "small text-muted mt-2";
        error.textContent = "Пакет скачивается и проверяется. HUB скоро перезапустится…";
        const response = await fetch("/api/hub-update/apply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ revision }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
        setHubUpdateAck(revision);
        setTimeout(() => window.location.reload(), 10000);
      } catch (err) {
        error.className = "small text-danger mt-2";
        error.textContent = `Не удалось начать обновление: ${err.message || err}`;
        button.disabled = false;
      }
    });
    modal.show();
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
        ? `<p>${esc(message)}</p>`
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
    el.querySelector("[data-wp-deploy-later]")?.addEventListener("click", () => {
      setAck(revision);
      modal.hide();
    });
    el.querySelector("[data-wp-deploy-reload]")?.addEventListener("click", () => {
      setAck(revision);
      modal.hide();
      window.location.reload();
    });
    modal.show();
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
      const ack = getAck();
      if (rev === ack) return;
      showModal(rev, data.message || "");
    } catch (_e) {
      // ignore network errors
    } finally {
      polling = false;
    }
  }

  function start() {
    if (!document.body || document.body.getAttribute("data-wp-deploy-poll") !== "1") return;
    watchUnsavedInput();
    pollOnce();
    setInterval(pollOnce, POLL_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
