// Targeting/Notifications system — v2 inbox panel
let ALL_TARGETING = [];
let TARGETING_MODAL = null;
let TARGETING_SELECTED_ID = null;
let TARGETING_FILTER = "all";
let TARGETING_MOBILE_DETAIL = false;

async function apiGet(url) {
  const res = await fetch(url, { method: "GET" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function apiPost(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function $(id) {
  return document.getElementById(id);
}

function escapeHtml(text) {
  if (!text) return "";
  const div = document.createElement("div");
  div.textContent = String(text);
  return div.innerHTML;
}

function formatDate(dateStr) {
  if (!dateStr) return "";
  try {
    const d = new Date(dateStr);
    return d.toLocaleString("ru-RU", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return dateStr;
  }
}

function formatRelativeTime(dateStr) {
  if (!dateStr) return "";
  try {
    const d = new Date(dateStr);
    const diffMs = Date.now() - d.getTime();
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return "только что";
    if (mins < 60) return `${mins} мин назад`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours} ч назад`;
    const days = Math.floor(hours / 24);
    if (days < 7) return `${days} д назад`;
    return formatDate(dateStr);
  } catch {
    return formatDate(dateStr);
  }
}

function getTargetingTypeTag(targetType, targetPosition, targetUserIds) {
  if (targetType === "all") {
    return '<span class="tg-tag tg-tag--all"><i class="bi bi-people-fill" aria-hidden="true"></i>Все пользователи</span>';
  }
  if (targetType === "position") {
    return `<span class="tg-tag tg-tag--position"><i class="bi bi-geo-alt-fill" aria-hidden="true"></i>${escapeHtml(targetPosition || "Позиция")}</span>`;
  }
  if (targetType === "users") {
    const count = targetUserIds?.length || 0;
    return `<span class="tg-tag tg-tag--users"><i class="bi bi-person-check-fill" aria-hidden="true"></i>${count} пользователей</span>`;
  }
  return "";
}

function getFilteredTargeting() {
  if (TARGETING_FILTER === "unread") {
    return ALL_TARGETING.filter((t) => !t.is_read);
  }
  return ALL_TARGETING;
}

function getUnreadCount() {
  return ALL_TARGETING.filter((t) => !t.is_read).length;
}

function pickDefaultTargetingId(items) {
  if (!items.length) return null;
  const unread = items.find((t) => !t.is_read);
  return (unread || items[0]).id;
}

function renderTargetingStats() {
  const unreadEl = $("targeting-stat-unread");
  const totalEl = $("targeting-stat-total");
  const unread = getUnreadCount();
  if (unreadEl) {
    unreadEl.textContent = unread ? `${unread} новых` : "Нет новых";
    unreadEl.classList.toggle("tg-stat--new", unread > 0);
  }
  if (totalEl) totalEl.textContent = `${ALL_TARGETING.length} всего`;
}

function renderTargetingFilters() {
  document.querySelectorAll("[data-tg-filter]").forEach((btn) => {
    const val = btn.getAttribute("data-tg-filter");
    const active = val === TARGETING_FILTER;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
}

function renderTargetingListPane() {
  const list = $("targeting-list-pane");
  if (!list) return;

  const items = getFilteredTargeting();
  if (!items.length) {
    const label =
      TARGETING_FILTER === "unread"
        ? "Нет непрочитанных нацеливаний"
        : "Нет нацеливаний";
    list.innerHTML = `<div class="tg-empty"><div class="tg-empty__icon"><i class="bi bi-inbox" aria-hidden="true"></i></div><strong>${label}</strong><span>Новые указания появятся здесь автоматически</span></div>`;
    TARGETING_SELECTED_ID = null;
    return;
  }

  if (!items.some((t) => t.id === TARGETING_SELECTED_ID)) {
    TARGETING_SELECTED_ID = pickDefaultTargetingId(items);
  }

  list.innerHTML = items
    .map((t) => {
      const isRead = !!t.is_read;
      const isActive = t.id === TARGETING_SELECTED_ID;
      const preview = String(t.message || "").replace(/\s+/g, " ").trim();
      const rel = formatRelativeTime(t.created_at);
      return `
        <button type="button" class="tg-item${isRead ? " tg-item--read" : " tg-item--unread"}${isActive ? " tg-item--active" : ""}"
          data-targeting-id="${t.id}" aria-current="${isActive ? "true" : "false"}">
          <span class="tg-item__accent" aria-hidden="true"></span>
          <span class="tg-item__inner">
            <span class="tg-item__main">
              <h4 class="tg-item__title">${escapeHtml(t.title || "Без заголовка")}</h4>
              <p class="tg-item__preview">${escapeHtml(preview)}</p>
              <div class="tg-item__meta"><i class="bi bi-clock" aria-hidden="true"></i>${escapeHtml(rel)}</div>
            </span>
            <span class="tg-item__badge">Новое</span>
            <i class="bi bi-chevron-right tg-item__chev" aria-hidden="true"></i>
          </span>
        </button>`;
    })
    .join("");

  list.querySelectorAll("[data-targeting-id]").forEach((btn) => {
    btn.addEventListener("click", () => {
      TARGETING_SELECTED_ID = Number(btn.getAttribute("data-targeting-id"));
      TARGETING_MOBILE_DETAIL = true;
      renderTargetingPanel();
    });
  });
}

function renderTargetingDetailPane() {
  const detail = $("targeting-detail-pane");
  if (!detail) return;

  const item = ALL_TARGETING.find((t) => t.id === TARGETING_SELECTED_ID);
  if (!item) {
    detail.innerHTML = `<div class="tg-empty"><div class="tg-empty__icon"><i class="bi bi-file-earmark-text" aria-hidden="true"></i></div><strong>Выберите нацеливание</strong><span>Краткий обзор — в списке слева</span></div>`;
    detail.classList.remove("tg-panel__detail--mobile-open", "tg-inbox__detail--mobile-open");
    return;
  }

  const isRead = !!item.is_read;
  const typeTag = getTargetingTypeTag(item.target_type, item.target_position, item.target_user_ids);

  detail.innerHTML = `
    <article class="tg-detail" aria-labelledby="tg-detail-title">
      <header class="tg-detail__head">
        <p class="tg-detail__kicker">Оперативное указание</p>
        <h3 class="tg-detail__title" id="tg-detail-title">${escapeHtml(item.title || "")}</h3>
        <div class="tg-detail__meta">
          <span><i class="bi bi-person-circle" aria-hidden="true"></i>${escapeHtml(item.created_by || "—")}</span>
          <span><i class="bi bi-clock" aria-hidden="true"></i>${formatDate(item.created_at)}</span>
          ${
            item.expires_at
              ? `<span><i class="bi bi-hourglass-split" aria-hidden="true"></i>до ${formatDate(item.expires_at)}</span>`
              : ""
          }
        </div>
        <div class="tg-detail__tags">${typeTag}</div>
      </header>
      <div class="tg-detail__body">
        <div class="tg-detail__doc">
          <p class="tg-detail__message">${escapeHtml(item.message || "")}</p>
        </div>
      </div>
      ${
        !isRead
          ? `<footer class="tg-detail__foot">
              <span class="small text-muted">Подтвердите ознакомление</span>
              <button type="button" class="btn btn-primary btn-sm" data-tg-mark-read="${item.id}">
                <i class="bi bi-check2-circle me-1" aria-hidden="true"></i>Прочитано
              </button>
            </footer>`
          : `<footer class="tg-detail__foot">
              <span class="tg-detail__read-badge"><i class="bi bi-check2-circle" aria-hidden="true"></i>Ознакомлены</span>
            </footer>`
      }
    </article>`;

  detail.classList.toggle("tg-panel__detail--mobile-open", TARGETING_MOBILE_DETAIL);
  detail.classList.toggle("tg-inbox__detail--mobile-open", TARGETING_MOBILE_DETAIL);

  const markBtn = detail.querySelector("[data-tg-mark-read]");
  if (markBtn) {
    markBtn.addEventListener("click", () => markTargetingReadById(Number(markBtn.getAttribute("data-tg-mark-read"))));
  }
}

function renderTargetingLoadingSkeleton() {
  const list = $("targeting-list-pane");
  const detail = $("targeting-detail-pane");
  const skeletonRows = Array.from({ length: 4 })
    .map(
      () => `<div class="tg-skeleton__row">
        <span class="tg-skeleton__dot" aria-hidden="true"></span>
        <div class="tg-skeleton__lines">
          <span class="tg-skeleton__line tg-skeleton__line--title"></span>
          <span class="tg-skeleton__line"></span>
          <span class="tg-skeleton__line tg-skeleton__line--short"></span>
        </div>
      </div>`
    )
    .join("");

  if (list) {
    list.innerHTML = `<div class="tg-skeleton" aria-busy="true" aria-label="Загрузка нацеливаний">${skeletonRows}</div>`;
  }
  if (detail) {
    detail.innerHTML = `<div class="tg-skeleton tg-skeleton__detail" aria-hidden="true">
      <span class="tg-skeleton__line tg-skeleton__line--title mb-3 d-block"></span>
      <span class="tg-skeleton__line d-block mb-2"></span>
      <span class="tg-skeleton__line d-block mb-2"></span>
      <span class="tg-skeleton__line tg-skeleton__line--short d-block"></span>
    </div>`;
  }
  if ($("targeting-stat-unread")) $("targeting-stat-unread").textContent = "…";
  if ($("targeting-stat-total")) $("targeting-stat-total").textContent = "…";
}

function renderTargetingShellLayout() {
  const shell = $("targeting-panel-shell");
  const foot = $("targeting-mobile-foot");
  if (shell) {
    shell.classList.toggle("tg-panel__shell--mobile-detail", TARGETING_MOBILE_DETAIL);
    shell.classList.toggle("tg-inbox__body--mobile-detail", TARGETING_MOBILE_DETAIL);
  }
  if (foot) {
    foot.hidden = !TARGETING_MOBILE_DETAIL;
  }
}

function renderTargetingPanel() {
  renderTargetingStats();
  renderTargetingFilters();
  renderTargetingListPane();
  renderTargetingDetailPane();
  renderTargetingShellLayout();
}

function bindTargetingPanelEvents() {
  document.querySelectorAll("[data-tg-filter]").forEach((btn) => {
    if (btn.dataset.tgBound) return;
    btn.dataset.tgBound = "1";
    btn.addEventListener("click", () => {
      TARGETING_FILTER = btn.getAttribute("data-tg-filter") || "all";
      TARGETING_MOBILE_DETAIL = false;
      renderTargetingPanel();
    });
  });

  const backBtn = $("targeting-mobile-back");
  if (backBtn && !backBtn.dataset.tgBound) {
    backBtn.dataset.tgBound = "1";
    backBtn.addEventListener("click", () => {
      TARGETING_MOBILE_DETAIL = false;
      renderTargetingShellLayout();
      const pane = $("targeting-detail-pane");
      pane?.classList.remove("tg-panel__detail--mobile-open", "tg-inbox__detail--mobile-open");
    });
  }
}

async function loadTargeting() {
  try {
    const data = await apiGet("/api/targeting");
    const targeting = data.targeting || [];
    const badge = $("targeting-badge");
    if (badge) {
      if (targeting.length > 0) {
        badge.textContent = targeting.length;
        badge.hidden = false;
        badge.style.display = "";
      } else {
        badge.hidden = true;
        badge.style.display = "none";
      }
    }
  } catch (e) {
    console.error("Failed to load targeting:", e);
  }
}

async function showTargetingModal() {
  if (!TARGETING_MODAL) {
    const modalEl = $("targetingModal");
    if (!modalEl) return;
    TARGETING_MODAL = new bootstrap.Modal(modalEl);
    bindTargetingPanelEvents();
  }

  TARGETING_FILTER = "all";
  TARGETING_SELECTED_ID = null;
  TARGETING_MOBILE_DETAIL = false;
  renderTargetingLoadingSkeleton();
  renderTargetingShellLayout();
  TARGETING_MODAL.show();

  try {
    const data = await apiGet("/api/targeting/all");
    ALL_TARGETING = data.targeting || [];
  } catch (e) {
    console.error("Failed to load all targeting:", e);
    ALL_TARGETING = [];
  }

  TARGETING_FILTER = getUnreadCount() ? "unread" : "all";
  TARGETING_SELECTED_ID = pickDefaultTargetingId(getFilteredTargeting());
  renderTargetingPanel();
}

async function markTargetingReadById(targetingId) {
  try {
    await apiPost("/api/targeting/read", { targeting_id: targetingId });
    const item = ALL_TARGETING.find((t) => t.id === targetingId);
    if (item) item.is_read = true;
    await loadTargeting();
    renderTargetingPanel();
  } catch (e) {
    console.error("Failed to mark targeting as read:", e);
  }
}

async function markTargetingRead() {
  await loadTargeting();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", scheduleTargetingBootstrap);
} else {
  scheduleTargetingBootstrap();
}

function scheduleTargetingBootstrap() {
  const run = () => loadTargeting();
  if (typeof requestIdleCallback === "function") {
    requestIdleCallback(run, { timeout: 4000 });
  } else {
    setTimeout(run, 2500);
  }
}

const TARGETING_POLL_MS = 45000;
setInterval(() => {
  if (document.hidden) return;
  loadTargeting();
}, TARGETING_POLL_MS);
