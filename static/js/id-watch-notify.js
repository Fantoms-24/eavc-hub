/**
 * Оповещения об отслеживаемых ID: полноэкранное окно до закрытия.
 * На странице перехватов откладываются, пока в «Ввод радиоперехвата» есть черновик.
 */
(function () {
  const LS_ACK = "wp_id_watch_alert_ack_seq";
  const POLL_MS = 2500;
  const CSS_HREF = "/static/css/id-watch-alert.css?v=5";

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function getAckSeq() {
    try {
      return parseInt(String(localStorage.getItem(LS_ACK) || "0"), 10) || 0;
    } catch (_e) {
      return 0;
    }
  }

  function setAckSeq(seq) {
    try {
      localStorage.setItem(LS_ACK, String(Math.max(0, parseInt(seq, 10) || 0)));
    } catch (_e) {
      // ignore
    }
  }

  const alertQueue = [];
  const queuedSeq = new Set();
  let overlayOpen = false;
  let polling = false;
  let currentAlert = null;

  function getInterceptInputs() {
    return Array.from(document.querySelectorAll("#intercept-input"));
  }

  function isInterceptInputVisible(input) {
    if (!input || input.hidden) return false;
    try {
      const style = window.getComputedStyle(input);
      if (style.display === "none" || style.visibility === "hidden") return false;
    } catch (_e) {
      return false;
    }
    return input.getClientRects().length > 0;
  }

  /** Черновик в поле «Ввод радиоперехвата» — не прерываем работу оператора. */
  function shouldDeferForInterceptInput() {
    for (const input of getInterceptInputs()) {
      if (!isInterceptInputVisible(input)) continue;
      if (String(input.value || "").trim()) return true;
    }
    return false;
  }

  function ensureStyles() {
    if (document.getElementById("wp-id-watch-alert-css")) return;
    const link = document.createElement("link");
    link.id = "wp-id-watch-alert-css";
    link.rel = "stylesheet";
    link.href = CSS_HREF;
    document.head.appendChild(link);
  }

  function ensureOverlay() {
    if (document.getElementById("wp-id-watch-overlay")) return;
    const wrap = document.createElement("div");
    wrap.innerHTML = `
<div id="wp-id-watch-overlay" class="wp-id-watch-overlay" hidden>
  <div class="wp-id-watch-modal" role="alertdialog" aria-modal="true" aria-labelledby="wp-id-watch-title">
    <div class="wp-id-watch-modal__head">
      <div class="wp-id-watch-modal__icon" aria-hidden="true">🚨</div>
      <h2 class="wp-id-watch-modal__title" id="wp-id-watch-title">Отслеживаемый ID в эфире</h2>
    </div>
    <div class="wp-id-watch-modal__body" id="wp-id-watch-body"></div>
    <div class="wp-id-watch-modal__foot">
      <button type="button" class="btn btn-danger wp-id-watch-modal__btn" id="wp-id-watch-dismiss">
        Закрыть оповещение
      </button>
    </div>
  </div>
</div>`;
    document.body.appendChild(wrap.firstElementChild);
    document.getElementById("wp-id-watch-dismiss")?.addEventListener("click", dismissCurrentAlert);
  }

  function lockBodyScroll() {
    document.documentElement.classList.add("wp-id-watch-open");
    document.body.classList.add("wp-id-watch-open");
  }

  function unlockBodyScroll() {
    document.documentElement.classList.remove("wp-id-watch-open");
    document.body.classList.remove("wp-id-watch-open");
  }

  function formatBody(alert) {
    const cid = esc(alert.correspondent_id || "—");
    const freq = esc(alert.frequency || "—");
    const grp = esc(alert.group_ || alert.group || "—");
    const unit = esc(alert.unit_name || "—");
    const dt = esc(alert.date_time || "—");
    return (
      `<div class="wp-id-watch-modal__row"><span class="wp-id-watch-modal__label">ID:</span>` +
      `<strong class="wp-mono">${cid}</strong></div>` +
      `<div class="wp-id-watch-modal__row"><span class="wp-id-watch-modal__label">Частота:</span>` +
      `<span class="wp-mono">${freq}</span></div>` +
      `<div class="wp-id-watch-modal__row"><span class="wp-id-watch-modal__label">Группа:</span>` +
      `<span class="wp-mono">${grp}</span></div>` +
      `<div class="wp-id-watch-modal__row"><span class="wp-id-watch-modal__label">Подразделение:</span>` +
      `${unit}</div>` +
      `<div class="wp-id-watch-modal__row"><span class="wp-id-watch-modal__label">Выход:</span>` +
      `<span class="wp-mono">${dt}</span></div>`
    );
  }

  function enqueueAlerts(alerts) {
    const sorted = (alerts || []).slice().sort(
      (a, b) => (parseInt(a.seq, 10) || 0) - (parseInt(b.seq, 10) || 0)
    );
    for (const alert of sorted) {
      const seq = parseInt(alert.seq, 10) || 0;
      if (!seq || queuedSeq.has(seq)) continue;
      queuedSeq.add(seq);
      alertQueue.push(alert);
    }
  }

  function showNextAlert() {
    if (overlayOpen || shouldDeferForInterceptInput()) return;
    const alert = alertQueue.shift();
    if (!alert) return;
    currentAlert = alert;
    ensureOverlay();
    const overlay = document.getElementById("wp-id-watch-overlay");
    const body = document.getElementById("wp-id-watch-body");
    if (!overlay || !body) return;
    body.innerHTML = formatBody(alert);
    overlay.hidden = false;
    overlayOpen = true;
    lockBodyScroll();
    try {
      if (typeof Notification !== "undefined" && Notification.permission === "granted") {
        new Notification(`ID ${alert.correspondent_id} в эфире`, {
          body: `${alert.frequency || ""} · ${alert.group_ || ""} · ${alert.unit_name || ""} · ${alert.date_time || ""}`,
          tag: `id-watch-${alert.seq}`,
          silent: true,
        });
      }
    } catch (_e) {
      // ignore
    }
  }

  function tryShowPendingAlerts() {
    if (!overlayOpen) showNextAlert();
  }

  function dismissCurrentAlert() {
    const overlay = document.getElementById("wp-id-watch-overlay");
    if (overlay) overlay.hidden = true;
    overlayOpen = false;
    unlockBodyScroll();
    if (currentAlert && currentAlert.seq) {
      setAckSeq(currentAlert.seq);
      queuedSeq.delete(parseInt(currentAlert.seq, 10) || 0);
    }
    currentAlert = null;
    tryShowPendingAlerts();
  }

  async function pollOnce() {
    if (polling) return;
    polling = true;
    try {
      const since = getAckSeq();
      const res = await fetch(
        `/api/sessions/id-watch/alerts?since=${encodeURIComponent(String(since))}`,
        { credentials: "same-origin", method: "GET", cache: "no-store" }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) return;
      const alerts = Array.isArray(data.alerts) ? data.alerts : [];
      if (!alerts.length) return;
      enqueueAlerts(alerts);
      tryShowPendingAlerts();
    } catch (_e) {
      // ignore network errors
    } finally {
      polling = false;
    }
  }

  function requestNotificationPermissionOnce() {
    try {
      if (typeof Notification === "undefined") return;
      if (Notification.permission !== "default") return;
      Notification.requestPermission().catch(() => {});
    } catch (_e) {
      // ignore
    }
  }

  function bindInterceptInputDeferHooks() {
    document.body.addEventListener(
      "click",
      (ev) => {
        if (!ev.target?.closest?.("#send-input-btn")) return;
        queueMicrotask(() => tryShowPendingAlerts());
        setTimeout(() => tryShowPendingAlerts(), 60);
      },
      true
    );
    document.addEventListener(
      "input",
      (ev) => {
        if (ev.target?.id !== "intercept-input") return;
        if (!shouldDeferForInterceptInput()) tryShowPendingAlerts();
      },
      true
    );
  }

  function start() {
    if (!document.body || !document.body.getAttribute("data-wp-id-watch-poll")) return;
    ensureStyles();
    ensureOverlay();
    bindInterceptInputDeferHooks();
    requestNotificationPermissionOnce();
    pollOnce();
    setInterval(pollOnce, POLL_MS);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) pollOnce();
    });
    window.addEventListener("focus", () => pollOnce());
  }

  window.wpIdWatchPollNow = pollOnce;
  window.wpIdWatchTryShow = tryShowPendingAlerts;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
