(function () {
  "use strict";

function _tgSetMsg(text, kind) {
  const el = $("tg-admin-msg");
  if (!el) return;
  el.textContent = text || "";
  el.className =
    "small mt-2" +
    (kind === "ok" ? " text-success" : kind === "err" ? " text-danger" : "");
}

function _tgApplyStatus(data) {
  const cfg = (data && data.config) || {};
  const en = $("tg-enabled-cb");
  const apiId = $("tg-api-id");
  const apiHash = $("tg-api-hash");
  const target = $("tg-target");
  const sess = $("tg-session-name");
  if (en) en.checked = !!cfg.enabled;
  if (apiId) apiId.value = cfg.api_id ? String(cfg.api_id) : "";
  if (apiHash) apiHash.value = cfg.api_hash || "";
  if (target) target.value = cfg.target || "";
  if (sess) sess.value = cfg.session_name || "tg_user";
  const line = $("tg-status-line");
  if (line) {
    const parts = [];
    parts.push(cfg.enabled ? "включено" : "выключено");
    parts.push(data && data.session_exists ? "сессия есть" : "сессии нет");
    if (data && data.sender_ready) parts.push("отправитель готов");
    else if (data && data.sender_error) parts.push("отправитель: " + data.sender_error);
    if (data && data.login_pending) parts.push("ожидается код");
    line.textContent = "Статус: " + parts.join(" · ");
  }
}

async function loadTelegramPanel() {
  try {
    const data = await apiGet("/api/admin/telegram");
    _tgApplyStatus(data);
  } catch (e) {
    _tgSetMsg(`Ошибка загрузки: ${e.message || e}`, "err");
  }
}

async function saveTelegramSettings() {
  try {
    _tgSetMsg("Сохранение…");
    const data = await apiPost("/api/admin/telegram", {
      enabled: !!($("tg-enabled-cb") && $("tg-enabled-cb").checked),
      api_id: Number(($("tg-api-id") && $("tg-api-id").value) || 0),
      api_hash: ($("tg-api-hash") && $("tg-api-hash").value) || "",
      target: ($("tg-target") && $("tg-target").value) || "",
      session_name: ($("tg-session-name") && $("tg-session-name").value) || "tg_user",
    });
    _tgApplyStatus(data);
    _tgSetMsg("Настройки сохранены", "ok");
  } catch (e) {
    _tgSetMsg(`Ошибка: ${e.message || e}`, "err");
  }
}

async function telegramSendCode() {
  try {
    _tgSetMsg("Отправка кода…");
    const phone = ($("tg-phone") && $("tg-phone").value) || "";
    const data = await apiPost("/api/admin/telegram/login/send-code", { phone });
    if (!data || data.ok === false) {
      _tgSetMsg((data && data.error) || "Не удалось отправить код", "err");
      return;
    }
    _tgSetMsg(data.message || "Код отправлен — смотрите Telegram", "ok");
    await loadTelegramPanel();
  } catch (e) {
    _tgSetMsg(`Ошибка: ${e.message || e}`, "err");
  }
}

async function telegramConfirmLogin() {
  try {
    _tgSetMsg("Подтверждение входа…");
    const data = await apiPost("/api/admin/telegram/login/confirm", {
      code: ($("tg-code") && $("tg-code").value) || "",
      password: ($("tg-password") && $("tg-password").value) || "",
    });
    if (!data || data.ok === false) {
      _tgSetMsg((data && data.error) || "Вход не удался", "err");
      return;
    }
    if (data.status) _tgApplyStatus(data.status);
    else await loadTelegramPanel();
    _tgSetMsg(data.message || "Вход выполнен", "ok");
  } catch (e) {
    _tgSetMsg(`Ошибка: ${e.message || e}`, "err");
  }
}

async function telegramLogout() {
  if (!confirm("Удалить сессию Telegram на этом HUB?")) return;
  try {
    const data = await apiPost("/api/admin/telegram/logout", {});
    if (data && data.status) _tgApplyStatus(data.status);
    else await loadTelegramPanel();
    _tgSetMsg("Сессия удалена", "ok");
  } catch (e) {
    _tgSetMsg(`Ошибка: ${e.message || e}`, "err");
  }
}

async function telegramTestSend() {
  try {
    _tgSetMsg("Отправка теста…");
    const data = await apiPost("/api/admin/telegram/test", {});
    if (!data || data.ok === false) {
      _tgSetMsg((data && data.error) || "Не удалось отправить", "err");
      return;
    }
    _tgSetMsg(`Тест отправлен → ${data.target || ""}`, "ok");
  } catch (e) {
    _tgSetMsg(`Ошибка: ${e.message || e}`, "err");
  }
}

function startTelegramTabLoad() {
  const tab = document.querySelector("#admin-telegram-tab");
  if (tab) {
    tab.addEventListener("shown.bs.tab", () => loadTelegramPanel());
  }
  const pane = document.querySelector("#admin-telegram-pane");
  if (pane && pane.classList.contains("active")) loadTelegramPanel();
  $("tg-save-btn")?.addEventListener("click", () => saveTelegramSettings());
  $("tg-send-code-btn")?.addEventListener("click", () => telegramSendCode());
  $("tg-confirm-btn")?.addEventListener("click", () => telegramConfirmLogin());
  $("tg-logout-btn")?.addEventListener("click", () => telegramLogout());
  $("tg-test-btn")?.addEventListener("click", () => telegramTestSend());
  $("tg-refresh-btn")?.addEventListener("click", () => loadTelegramPanel());
}

  function init() {
    startTelegramTabLoad();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
