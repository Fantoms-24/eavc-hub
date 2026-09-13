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

function debounce(fn, wait = 250) {
  let t = null;
  return (...args) => {
    if (t) clearTimeout(t);
    t = setTimeout(() => fn(...args), wait);
  };
}

function setText(id, text) {
  const el = $(id);
  if (el) el.textContent = text || "";
}

function setStatus(text, isError) {
  const el = $("admin-status");
  if (!el) return;
  el.className = isError ? "alert alert-danger py-2 small mt-3" : "alert alert-success py-2 small mt-3";
  el.textContent = text || "";
  if (!text) el.className = "small wp-subtle mt-3";
}

let ALL_POSITIONS = [];
let USERS_CACHE = [];
let ROLES_FOR_ASSIGNMENT = [];
let MODAL_USER_ID = 0;
let positionsModal = null;
let POS_BY_KEY = {};
let TARGETING_LIST = [];
let USER_FILTERS = { q: "", role: "", position: "", sort: "username_asc" };
let SELECTED_USER_IDS = new Set();
let TAB_CATEGORIES_CACHE = [];
let CUSTOM_ROLE_EDIT_ID = 0;

function posKey(name) {
  return encodeURIComponent(String(name || ""));
}

function posNameFromKey(key) {
  return POS_BY_KEY[String(key || "")] || decodeURIComponent(String(key || ""));
}

function roleBadge(role) {
  const r = String(role || "operator").toLowerCase();
  if (r === "chief") return `<span class="badge text-bg-primary">chief</span>`;
  return `<span class="badge text-bg-light border">operator</span>`;
}

function getRoleData(role) {
  const r = String(role || "viewer").trim();
  const rLower = r.toLowerCase();
  const roles = {
    admin: { icon: "bi-shield-fill-check", tone: "admin", name: "Администратор" },
    moderator: { icon: "bi-person-gear", tone: "moderator", name: "Модератор" },
    search_editor: { icon: "bi-pencil-square", tone: "editor", name: "Редактор поиска" },
    viewer: { icon: "bi-eye", tone: "viewer", name: "Наблюдатель" },
    audio_viewer: { icon: "bi-volume-up", tone: "audio", name: "Аудио (просмотр)" }
  };
  if (roles[rLower]) return roles[rLower];
  const custom = (ROLES_FOR_ASSIGNMENT || []).find((x) => String(x.role || "") === r);
  if (custom) return { icon: "bi-person-badge", tone: "custom", name: custom.label || r };
  return roles.viewer;
}

function rolePillToneClass(role) {
  const tone = getRoleData(role).tone || "viewer";
  return `adm-role-pill--${tone}`;
}

function applyRolePillState(selector, role) {
  if (!selector) return;
  const roleData = getRoleData(role);
  const pill = selector.querySelector(".adm-role-pill");
  if (pill) {
    pill.className = `adm-role-pill admin-role-selector ${rolePillToneClass(role)}`;
    pill.dataset.role = role;
    const icon = pill.querySelector(".adm-role-pill__icon i");
    const label = pill.querySelector(".adm-role-pill__label");
    if (icon) icon.className = `bi ${roleData.icon}`;
    if (label) label.textContent = roleData.name;
  }
  selector.dataset.role = role;
}

function roleCard(role, userId) {
  const r = String(role || "viewer").trim();
  const roleData = getRoleData(r);
  const list = ROLES_FOR_ASSIGNMENT && ROLES_FOR_ASSIGNMENT.length ? ROLES_FOR_ASSIGNMENT : [
    { role: "viewer", label: "Наблюдатель" },
    { role: "search_editor", label: "Редактор поиска" },
    { role: "moderator", label: "Модератор" },
    { role: "admin", label: "Администратор" }
  ];
  const optionsHtml = list.map((x) => {
    const d = getRoleData(x.role);
    const active = x.role === r ? " adm-role-menu__option--active" : "";
    return `<button type="button" class="admin-role-option adm-role-menu__option${active}" data-role="${escapeHtml(x.role)}">
      <span class="adm-role-menu__icon adm-role-menu__icon--${d.tone}"><i class="bi ${d.icon}" aria-hidden="true"></i></span>
      <span class="adm-role-menu__label">${escapeHtml(x.label || x.role)}</span>
    </button>`;
  }).join("");
  return `
    <div class="admin-role-selector position-relative" data-user-id="${userId}" data-role="${escapeHtml(r)}">
      <button type="button" class="adm-role-pill ${rolePillToneClass(r)}" aria-haspopup="listbox" aria-expanded="false">
        <span class="adm-role-pill__icon"><i class="bi ${roleData.icon}" aria-hidden="true"></i></span>
        <span class="adm-role-pill__label">${escapeHtml(roleData.name)}</span>
        <i class="bi bi-chevron-down adm-role-pill__caret" aria-hidden="true"></i>
      </button>
      <div class="admin-role-dropdown adm-role-menu" role="listbox" hidden>
        ${optionsHtml}
      </div>
    </div>
  `;
}

function positionsLabel(positions) {
  const ps = positions || [];
  if (!ps.length) return { text: "Нет доступа", tone: "empty" };
  if (ps.length === 1) return { text: ps[0].name, tone: "active" };
  return { text: `${ps.length} позиции`, tone: "active" };
}

function positionsSelector(user) {
  const info = positionsLabel(user.positions);
  const optionsHtml = (ALL_POSITIONS || []).map((it) => {
    const checked = (user.positions || []).some((p) => p.name === it.name);
    return `<label class="adm-pos-menu__option">
      <input type="checkbox" class="form-check-input m-0" data-pos-key="${escapeHtml(it.key)}" ${checked ? "checked" : ""} />
      <span class="adm-pos-menu__label">${escapeHtml(it.name)}</span>
    </label>`;
  }).join("");
  return `
    <div class="adm-pos-selector position-relative" data-user-id="${user.id}">
      <button type="button" class="adm-pos-pill adm-pos-pill--${info.tone}" aria-haspopup="dialog" aria-expanded="false">
        <span class="adm-pos-pill__icon"><i class="bi bi-broadcast-pin" aria-hidden="true"></i></span>
        <span class="adm-pos-pill__label">${escapeHtml(info.text)}</span>
        <i class="bi bi-chevron-down adm-pos-pill__caret" aria-hidden="true"></i>
      </button>
      <div class="adm-pos-menu admin-role-dropdown" hidden>
        <div class="adm-pos-menu__head">Доступ к позициям</div>
        <div class="adm-pos-menu__list">${optionsHtml || '<div class="adm-pos-menu__empty">Позиции не созданы</div>'}</div>
        <div class="adm-pos-menu__foot">
          <button type="button" class="btn btn-primary btn-sm adm-pos-save"><i class="bi bi-check2 me-1"></i>Сохранить</button>
        </div>
      </div>
    </div>
  `;
}

async function saveUserPositions(userId, menu) {
  const assignments = {};
  menu.querySelectorAll('input[type="checkbox"][data-pos-key]').forEach((chk) => {
    if (!chk.checked) return;
    const key = chk.dataset.posKey;
    const name = posNameFromKey(key);
    if (name) assignments[name] = "operator";
  });
  await apiPost("/api/admin/users/positions-map", { user_id: userId, assignments });
  setStatus("Позиции сохранены", false);
  closeFloatingMenu(menu, menu._floatAnchor || activeFloatingMenu?.anchor);
  await reload();
}

function formatUserDate(value) {
  const raw = String(value || "").trim();
  if (!raw) return '<span class="adm-user-date adm-user-date--empty">—</span>';
  const parts = raw.split(/\s+/);
  if (parts.length >= 2) {
    return `<span class="adm-user-date"><span class="adm-user-date__day">${escapeHtml(parts[0])}</span><span class="adm-user-date__time">${escapeHtml(parts[1])}</span></span>`;
  }
  return `<span class="adm-user-date"><span class="adm-user-date__day">${escapeHtml(raw)}</span></span>`;
}

function userInitial(username, callsign) {
  const src = String(callsign || username || "?").trim();
  return escapeHtml(src.charAt(0).toUpperCase() || "?");
}

let activeFloatingMenu = null;

function rememberFloatingMenuHome(menu) {
  if (!menu || menu._floatHome) return;
  menu._floatHome = { parent: menu.parentElement, next: menu.nextSibling };
}

function restoreFloatingMenuHome(menu) {
  if (!menu || !menu._floatHome) return;
  const { parent, next } = menu._floatHome;
  if (!parent || menu.parentElement !== document.body) return;
  if (next && next.parentElement === parent) parent.insertBefore(menu, next);
  else parent.appendChild(menu);
}

function resetFloatingMenu(menu) {
  if (!menu) return;
  menu.classList.remove("adm-float-menu--floating");
  menu.style.position = "";
  menu.style.top = "";
  menu.style.left = "";
  menu.style.bottom = "";
  menu.style.right = "";
  menu.style.width = "";
  menu.style.minWidth = "";
  menu.style.maxHeight = "";
  menu.style.visibility = "";
  menu.style.zIndex = "";
  menu._floatAnchor = null;
  restoreFloatingMenuHome(menu);
}

function positionFloatingMenu(menu, anchor, opts) {
  if (!menu || !anchor) return;
  const preferAbove = !opts || opts.preferAbove !== false;
  const minWidth = Math.max(Math.round(anchor.getBoundingClientRect().width), opts?.minWidth || 220);
  const gap = 6;
  const pad = 8;

  resetFloatingMenu(menu);
  rememberFloatingMenuHome(menu);
  menu._floatAnchor = anchor;
  menu.classList.add("adm-float-menu--floating");
  menu.hidden = false;
  document.body.appendChild(menu);

  menu.style.position = "fixed";
  menu.style.zIndex = "1080";
  menu.style.visibility = "hidden";
  menu.style.left = "0";
  menu.style.top = "0";
  menu.style.width = "auto";
  menu.style.minWidth = `${minWidth}px`;
  menu.style.maxHeight = `${Math.max(160, window.innerHeight - pad * 2)}px`;

  const anchorRect = anchor.getBoundingClientRect();
  const menuRect = menu.getBoundingClientRect();
  const menuW = menuRect.width;
  const menuH = menuRect.height;

  let left = anchorRect.left;
  let top = preferAbove ? anchorRect.top - menuH - gap : anchorRect.bottom + gap;

  if (preferAbove && top < pad) {
    top = anchorRect.bottom + gap;
  } else if (!preferAbove && top + menuH > window.innerHeight - pad) {
    top = anchorRect.top - menuH - gap;
  }

  if (left + menuW > window.innerWidth - pad) {
    left = Math.max(pad, anchorRect.right - menuW);
  }
  if (left < pad) left = pad;
  if (top + menuH > window.innerHeight - pad) {
    top = Math.max(pad, window.innerHeight - pad - menuH);
  }
  if (top < pad) top = pad;

  menu.style.top = `${Math.round(top)}px`;
  menu.style.left = `${Math.round(left)}px`;
  menu.style.visibility = "";
}

function floatingMenuAnchor(menu) {
  if (!menu) return null;
  if (menu._floatAnchor) return menu._floatAnchor;
  return menu.closest(".admin-role-selector, .adm-pos-selector")
    ?.querySelector(".adm-role-pill, .adm-pos-pill") || null;
}

function closeAllFloatingMenus() {
  document.querySelectorAll(".admin-role-dropdown, .adm-pos-menu").forEach((menu) => {
    menu.hidden = true;
    const trigger = floatingMenuAnchor(menu);
    resetFloatingMenu(menu);
    if (trigger) trigger.setAttribute("aria-expanded", "false");
  });
  activeFloatingMenu = null;
}

function bindFloatingMenuScrollClose() {
  const mainScroll = document.querySelector(".adm-main__scroll");
  if (!mainScroll || mainScroll.dataset.floatMenuScrollBound === "1") return;
  mainScroll.dataset.floatMenuScrollBound = "1";
  mainScroll.addEventListener("scroll", closeAllFloatingMenus, { passive: true });
  window.addEventListener("resize", closeAllFloatingMenus);
}

function openFloatingMenu(menu, anchor, opts) {
  closeAllFloatingMenus();
  positionFloatingMenu(menu, anchor, opts);
  anchor.setAttribute("aria-expanded", "true");
  activeFloatingMenu = { menu, anchor };
}

function closeFloatingMenu(menu, anchor) {
  if (!menu) return;
  menu.hidden = true;
  resetFloatingMenu(menu);
  if (anchor) anchor.setAttribute("aria-expanded", "false");
  if (activeFloatingMenu && activeFloatingMenu.menu === menu) activeFloatingMenu = null;
}

function normalizeText(value) {
  return String(value || "").trim().toLowerCase();
}

function updatePositionFilterOptions() {
  const select = $("user-position-filter");
  if (!select) return;
  const current = USER_FILTERS.position || "";
  select.innerHTML = '<option value="">Все позиции</option>' + (ALL_POSITIONS || [])
    .map((p) => `<option value="${escapeHtml(p.name || p)}">${escapeHtml(p.name || p)}</option>`)
    .join("");
  select.value = current;
}

function readUserFilterUi() {
  USER_FILTERS.q = normalizeText($("user-search")?.value || "");
  USER_FILTERS.role = normalizeText($("user-role-filter")?.value || "");
  USER_FILTERS.position = normalizeText($("user-position-filter")?.value || "");
  USER_FILTERS.sort = $("user-sort")?.value || "username_asc";
  syncRoleCardActiveState();
}

function syncUserFilterUi() {
  if ($("user-search")) $("user-search").value = USER_FILTERS.q || "";
  if ($("user-role-filter")) $("user-role-filter").value = USER_FILTERS.role || "";
  if ($("user-position-filter")) $("user-position-filter").value = USER_FILTERS.position || "";
  if ($("user-sort")) $("user-sort").value = USER_FILTERS.sort || "username_asc";
  syncRoleCardActiveState();
}

function syncRoleCardActiveState() {
  const activeRole = normalizeText(USER_FILTERS.role || "");
  document.querySelectorAll(".admin-role-card[data-role]").forEach((card) => {
    card.classList.toggle("active", !!activeRole && card.dataset.role === activeRole);
  });
}

function applyUserFilters(users) {
  const q = USER_FILTERS.q;
  const role = USER_FILTERS.role;
  const position = USER_FILTERS.position;
  let list = (users || []).slice();

  if (q) {
    list = list.filter((u) => {
      const hay = `${u.username || ""} ${u.callsign || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }
  if (role) {
    list = list.filter((u) => normalizeText(u.role) === role);
  }
  if (position) {
    list = list.filter((u) => {
      const ps = (u.positions || []).map((p) => normalizeText(p.name));
      return ps.includes(position);
    });
  }

  const sort = USER_FILTERS.sort || "username_asc";
  if (sort === "username_desc") {
    list.sort((a, b) => String(b.username || "").localeCompare(String(a.username || ""), "ru"));
  } else if (sort === "created_desc") {
    list.sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || ""), "ru"));
  } else if (sort === "created_asc") {
    list.sort((a, b) => String(a.created_at || "").localeCompare(String(b.created_at || ""), "ru"));
  } else if (sort === "role") {
    list.sort((a, b) => String(a.role || "").localeCompare(String(b.role || ""), "ru"));
  } else if (sort === "positions_desc") {
    list.sort((a, b) => (b.positions || []).length - (a.positions || []).length);
  } else {
    list.sort((a, b) => String(a.username || "").localeCompare(String(b.username || ""), "ru"));
  }
  return list;
}

function updateUsersCount(filteredCount, totalCount) {
  const el = $("users-count");
  if (!el) return;
  el.textContent = filteredCount === totalCount
    ? `${totalCount} пользователей`
    : `${filteredCount} из ${totalCount}`;
}

function updateRoleCounts(users) {
  const counts = { admin: 0, moderator: 0, search_editor: 0, viewer: 0 };
  for (const u of users || []) {
    const r = normalizeText(u.role || "viewer");
    if (counts[r] !== undefined) counts[r] += 1;
  }
  const set = (id, val) => {
    const el = $(id);
    if (el) el.textContent = String(val);
  };
  set("role-count-admin", counts.admin);
  set("role-count-moderator", counts.moderator);
  set("role-count-search_editor", counts.search_editor);
  set("role-count-viewer", counts.viewer);
}

function updateSelectedCount() {
  const el = $("users-selected-count");
  if (el) el.textContent = `${SELECTED_USER_IDS.size} выбрано`;
  const bulkBar = $("adm-users-bulk-bar");
  if (bulkBar) bulkBar.classList.toggle("adm-users-bulk--active", SELECTED_USER_IDS.size > 0);
  const selectAll = $("users-select-all");
  if (selectAll) {
    const filtered = getFilteredUsers();
    selectAll.checked = filtered.length > 0 && filtered.every((u) => SELECTED_USER_IDS.has(Number(u.id)));
  }
}

function clearSelection() {
  SELECTED_USER_IDS = new Set();
  updateSelectedCount();
}

function getFilteredUsers() {
  return applyUserFilters(USERS_CACHE || []);
}

function selectAllFiltered(checked) {
  if (!checked) {
    clearSelection();
    return;
  }
  const filtered = getFilteredUsers();
  SELECTED_USER_IDS = new Set(filtered.map((u) => Number(u.id)));
  updateSelectedCount();
  renderUsers(USERS_CACHE);
}

async function applyBulkRole() {
  const role = $("bulk-role")?.value || "";
  if (!role) {
    setStatus("Выберите роль для массового изменения", true);
    return;
  }
  const ids = Array.from(SELECTED_USER_IDS || []);
  if (!ids.length) {
    setStatus("Нет выбранных пользователей", true);
    return;
  }
  if (!confirm(`Изменить роль для ${ids.length} пользователей?`)) return;
  try {
    for (const id of ids) {
      await apiPost("/api/admin/users/role", { user_id: id, role });
    }
    setStatus(`Роль обновлена для ${ids.length} пользователей`, false);
    clearSelection();
    await reload();
  } catch (e) {
    setStatus(`Ошибка массового обновления: ${e.message || e}`, true);
  }
}

function renderUsers(users) {
  closeAllFloatingMenus();
  const tbody = $("users-table").querySelector("tbody");
  tbody.innerHTML = "";
  const total = (users || []).length;
  const filtered = applyUserFilters(users || []);
  updateUsersCount(filtered.length, total);
  updateRoleCounts(users || []);
  if (!filtered.length) {
    tbody.innerHTML = `<tr class="adm-users-empty"><td colspan="7">
      <div class="adm-users-empty__inner">
        <i class="bi bi-people" aria-hidden="true"></i>
        <p>Пользователи не найдены</p>
        <span class="small text-muted">Измените фильтры или создайте нового пользователя</span>
      </div>
    </td></tr>`;
    updateSelectedCount();
    return;
  }
  for (const u of filtered) {
    const tr = document.createElement("tr");
    tr.className = "admin-user-row";
    const callsignHtml = u.callsign
      ? `<span class="adm-user-cell__sub">${escapeHtml(u.callsign)}</span>`
      : "";
    tr.innerHTML = `
      <td class="adm-users-table__check">
        <input class="form-check-input user-select" type="checkbox" data-user-id="${u.id}" ${SELECTED_USER_IDS.has(Number(u.id)) ? "checked" : ""} aria-label="Выбрать ${escapeHtml(u.username || "")}" />
      </td>
      <td class="adm-users-table__id wp-mono">${u.id}</td>
      <td class="adm-users-table__user">
        <div class="adm-user-cell">
          <span class="adm-user-cell__avatar" aria-hidden="true">${userInitial(u.username, u.callsign)}</span>
          <span class="adm-user-cell__meta">
            <span class="adm-user-cell__login">${escapeHtml(u.username || "")}</span>
            ${callsignHtml}
          </span>
        </div>
      </td>
      <td class="adm-users-table__role">${roleCard(u.role || "viewer", u.id)}</td>
      <td class="adm-users-table__positions">${positionsSelector(u)}</td>
      <td class="adm-users-table__date">${formatUserDate(u.created_at)}</td>
      <td class="adm-users-table__actions">
        <button type="button" class="adm-icon-btn" data-action="pw" data-user-id="${u.id}" title="Сменить пароль" aria-label="Сменить пароль">
          <i class="bi bi-key" aria-hidden="true"></i>
        </button>
      </td>
    `;

    const roleSelector = tr.querySelector(".admin-role-selector");
    if (roleSelector) {
      const dropdown = roleSelector.querySelector(".admin-role-dropdown");
      const pill = roleSelector.querySelector(".adm-role-pill");

      pill.addEventListener("click", (e) => {
        e.stopPropagation();
        if (dropdown.hidden) openFloatingMenu(dropdown, pill);
        else closeFloatingMenu(dropdown, pill);
      });

      roleSelector.querySelectorAll(".admin-role-option").forEach((option) => {
        option.addEventListener("click", async (e) => {
          e.preventDefault();
          e.stopPropagation();
          const newRole = option.dataset.role;
          closeFloatingMenu(dropdown, pill);
          if (newRole !== (u.role || "viewer")) {
            await updateUserRole(u.id, newRole);
          }
        });
      });
    }

    const posSelector = tr.querySelector(".adm-pos-selector");
    if (posSelector) {
      const menu = posSelector.querySelector(".adm-pos-menu");
      const pill = posSelector.querySelector(".adm-pos-pill");
      const saveBtn = posSelector.querySelector(".adm-pos-save");

      pill.addEventListener("click", (e) => {
        e.stopPropagation();
        if (menu.hidden) openFloatingMenu(menu, pill, { preferAbove: true, minWidth: 240 });
        else closeFloatingMenu(menu, pill);
      });

      if (saveBtn) {
        saveBtn.addEventListener("click", async (e) => {
          e.stopPropagation();
          try {
            await saveUserPositions(u.id, menu);
          } catch (err) {
            setStatus(`Ошибка: ${err.message || err}`, true);
          }
        });
      }
    }

    const selectBox = tr.querySelector('input.user-select');
    if (selectBox) {
      selectBox.addEventListener("change", () => {
        const id = Number(selectBox.dataset.userId || 0);
        if (!id) return;
        if (selectBox.checked) SELECTED_USER_IDS.add(id);
        else SELECTED_USER_IDS.delete(id);
        updateSelectedCount();
      });
    }

    const btn = tr.querySelector('button[data-action="pw"]');
    btn.addEventListener("click", async () => {
      const pw = prompt("Новый пароль:");
      if (!pw) return;
      try {
        await apiPost("/api/admin/users/password", { user_id: u.id, password: pw });
        setStatus("Пароль обновлён", false);
      } catch (e) {
        setStatus(`Ошибка: ${e.message || e}`, true);
      }
    });

    tbody.appendChild(tr);
  }
  updateSelectedCount();
}

async function updateUserRole(userId, newRole) {
  try {
    await apiPost("/api/admin/users/role", { user_id: userId, role: newRole });
    setStatus("Роль обновлена", false);
    applyRolePillState(document.querySelector(`.admin-role-selector[data-user-id="${userId}"]`), newRole);
    setTimeout(() => reload(), 500);
  } catch (e) {
    setStatus(`Ошибка: ${e.message || e}`, true);
  }
}

function updateRoleDropdowns() {
  const list = ROLES_FOR_ASSIGNMENT && ROLES_FOR_ASSIGNMENT.length ? ROLES_FOR_ASSIGNMENT : [
    { role: "viewer", label: "viewer" },
    { role: "search_editor", label: "search_editor" },
    { role: "moderator", label: "moderator" },
    { role: "admin", label: "admin" }
  ];
  const opts = list.map((x) => `<option value="${escapeHtml(x.role)}">${escapeHtml(x.label || x.role)}</option>`).join("");
  const newRole = $("new-role");
  if (newRole) newRole.innerHTML = opts;
  const roleFilter = $("user-role-filter");
  if (roleFilter) {
    const cur = roleFilter.value;
    roleFilter.innerHTML = '<option value="">Все</option>' + opts;
    if (cur) roleFilter.value = cur;
  }
  const bulkRole = $("bulk-role");
  if (bulkRole) {
    bulkRole.innerHTML = '<option value="">Сменить роль…</option>' + opts;
  }
}

async function reload() {
  const [u, p] = await Promise.all([apiGet("/api/admin/users"), apiGet("/api/admin/positions")]);
  USERS_CACHE = u.users || [];
  ROLES_FOR_ASSIGNMENT = u.roles_for_assignment || [];
  const raw = p.positions || [];
  ALL_POSITIONS = raw.map((name) => ({ name: String(name || ""), key: posKey(name) }));
  POS_BY_KEY = {};
  for (const it of ALL_POSITIONS) POS_BY_KEY[it.key] = it.name;
  updatePositionFilterOptions();
  updateRoleDropdowns();
  syncUserFilterUi();
  renderUsers(USERS_CACHE);
}

async function createUser() {
  const username = ($("new-username").value || "").trim();
  const callsign = ($("new-callsign").value || "").trim();
  const role = $("new-role").value;
  const password = $("new-password").value || "";
  if (!username || !password) {
    setStatus("Нужно указать логин и пароль", true);
    return;
  }
  try {
    await apiPost("/api/admin/users", { username, callsign, role, password });
    $("new-username").value = "";
    $("new-callsign").value = "";
    $("new-password").value = "";
    setStatus("Пользователь создан", false);
    await reload();
  } catch (e) {
    setStatus(`Ошибка: ${e.message || e}`, true);
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  $("create-user-btn").addEventListener("click", createUser);
  if ($("create-position-btn")) {
    $("create-position-btn").addEventListener("click", async () => {
      const name = ($("new-position-name").value || "").trim();
      if (!name) {
        setStatus("Введите имя позиции", true);
        return;
      }
      try {
        await apiPost("/api/admin/positions", { name });
        $("new-position-name").value = "";
        setStatus("Позиция добавлена", false);
        await reload();
      } catch (e) {
        setStatus(`Ошибка: ${e.message || e}`, true);
      }
    });
  }

  const rerenderUsersDebounced = debounce(() => {
    readUserFilterUi();
    renderUsers(USERS_CACHE);
  }, 220);
  if ($("user-search")) {
    $("user-search").addEventListener("input", rerenderUsersDebounced);
  }
  if ($("user-role-filter")) {
    $("user-role-filter").addEventListener("change", () => {
      readUserFilterUi();
      renderUsers(USERS_CACHE);
    });
  }
  if ($("user-position-filter")) {
    $("user-position-filter").addEventListener("change", () => {
      readUserFilterUi();
      renderUsers(USERS_CACHE);
    });
  }
  if ($("user-sort")) {
    $("user-sort").addEventListener("change", () => {
      readUserFilterUi();
      renderUsers(USERS_CACHE);
    });
  }
  if ($("user-filter-clear")) {
    $("user-filter-clear").addEventListener("click", () => {
      USER_FILTERS = { q: "", role: "", position: "", sort: "username_asc" };
      syncUserFilterUi();
      renderUsers(USERS_CACHE);
    });
  }
  if ($("users-select-all")) {
    $("users-select-all").addEventListener("change", (e) => {
      selectAllFiltered(!!e.target.checked);
    });
  }
  if ($("bulk-role-apply")) {
    $("bulk-role-apply").addEventListener("click", applyBulkRole);
  }
  if ($("bulk-clear")) {
    $("bulk-clear").addEventListener("click", () => {
      clearSelection();
      renderUsers(USERS_CACHE);
    });
  }

  // Role KPI chips: filter list + preset role for new user
  document.querySelectorAll(".admin-role-card[data-role]").forEach((card) => {
    card.addEventListener("click", () => {
      const role = card.dataset.role || "";
      if ($("new-role")) $("new-role").value = role;
      const roleFilter = $("user-role-filter");
      if (roleFilter) {
        const nextRole = USER_FILTERS.role === role ? "" : role;
        roleFilter.value = nextRole;
        readUserFilterUi();
        renderUsers(USERS_CACHE);
      }
    });
  });

  // Close floating menus when clicking outside
  document.addEventListener("click", (e) => {
    if (
      !e.target.closest(".admin-role-selector")
      && !e.target.closest(".adm-pos-selector")
      && !e.target.closest(".adm-float-menu--floating")
    ) {
      closeAllFloatingMenus();
    }
  });

  bindFloatingMenuScrollClose();

  if ($("targeting-title")) $("targeting-title").addEventListener("input", updateTargetingPreview);
  if ($("targeting-message")) $("targeting-message").addEventListener("input", updateTargetingPreview);
  if ($("targeting-position")) $("targeting-position").addEventListener("change", updateTargetingPreview);
  const targetingUsers = $("targeting-users-checkboxes");
  if (targetingUsers) {
    targetingUsers.addEventListener("change", (e) => {
      if (e.target && e.target.matches("input[type='checkbox']")) updateTargetingPreview();
    });
  }

  try {
    const modalEl = $("positionsModal");
    if (window.bootstrap && modalEl) {
      positionsModal = new bootstrap.Modal(modalEl);
    } else {
      positionsModal = null;
    }
  } catch (_) {
    positionsModal = null;
  }
  try {
    await reload();
  } catch (e) {
    setStatus(`Ошибка загрузки пользователей: ${e.message || e}`, true);
  }
});

function openPositionsModal(userId) {
  MODAL_USER_ID = Number(userId || 0);
  const u = (USERS_CACHE || []).find((x) => Number(x.id) === MODAL_USER_ID);
  const subtitle = $("positionsModalSubtitle");
  if (subtitle) subtitle.textContent = u ? `${u.username} (${u.role})` : "";

  // текущие назначения (только факт доступа к позиции)
  const current = {};
  for (const p of (u && u.positions) ? u.positions : []) {
    current[p.name] = true;
  }

  const body = $("positionsModalBody");
  body.innerHTML = "";
  for (const it of ALL_POSITIONS || []) {
    const name = it.name;
    const key = it.key;
    const checked = Object.prototype.hasOwnProperty.call(current, name);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>
        <input class="form-check-input" type="checkbox" data-pos-key="${key}" ${checked ? "checked" : ""} />
      </td>
      <td class="wp-mono">${name}</td>
    `;
    body.appendChild(tr);
  }

  // save handler (replace to avoid stacking)
  const saveBtn = $("positionsModalSaveBtn");
  const newBtn = saveBtn.cloneNode(true);
  saveBtn.parentNode.replaceChild(newBtn, saveBtn);
  newBtn.addEventListener("click", async () => {
    const assignments = {};
    for (const tr of body.querySelectorAll("tr")) {
      const chk = tr.querySelector('input[type="checkbox"][data-pos-key]');
      if (!chk) continue;
      if (!chk.checked) continue;
      const key = chk.dataset.posKey;
      const name = posNameFromKey(key);
      assignments[name] = "operator";
    }
    try {
      await apiPost("/api/admin/users/positions-map", { user_id: MODAL_USER_ID, assignments });
      setStatus("Позиции сохранены", false);
      positionsModal.hide();
      await reload();
    } catch (e) {
      setStatus(`Ошибка: ${e.message || e}`, true);
    }
  });

  try {
    if (!positionsModal) {
      const modalEl = $("positionsModal");
      if (window.bootstrap && modalEl) {
        positionsModal = new bootstrap.Modal(modalEl);
      }
    }
    if (!positionsModal) {
      throw new Error("Modal not available");
    }
    positionsModal.show();
  } catch (e) {
    setStatus(`Ошибка открытия окна позиций: ${e.message || e}`, true);
  }
}

// Targeting functions
async function loadTargetingList() {
  try {
    const data = await apiGet("/api/admin/targeting");
    TARGETING_LIST = data.targeting || [];
    renderTargetingList();
  } catch (e) {
    setStatus(`Ошибка загрузки нацеливаний: ${e.message || e}`, true);
  }
}

function renderTargetingList() {
  const list = $("targeting-list");
  if (!list) return;

  if (TARGETING_LIST.length === 0) {
    list.innerHTML = '<div class="tg-empty py-2"><div class="tg-empty__icon"><i class="bi bi-megaphone" aria-hidden="true"></i></div><strong>Нет активных нацеливаний</strong><span>Создайте новое сообщение для Hub\'ов и позиций</span></div>';
    return;
  }

  list.innerHTML = `<div class="tg-admin-list">${TARGETING_LIST.map((t) => {
    let targetTypeLabel = "";
    if (t.target_type === "all") {
      targetTypeLabel = '<span class="tg-tag tg-tag--all"><i class="bi bi-people-fill" aria-hidden="true"></i>Все</span>';
    } else if (t.target_type === "position") {
      targetTypeLabel = `<span class="tg-tag tg-tag--position"><i class="bi bi-geo-alt-fill" aria-hidden="true"></i>${escapeHtml(t.target_position || "")}</span>`;
    } else if (t.target_type === "users") {
      const userCount = t.target_user_ids?.length || 0;
      targetTypeLabel = `<span class="tg-tag tg-tag--users"><i class="bi bi-person-check-fill" aria-hidden="true"></i>${userCount}</span>`;
    }

    const msg = String(t.message || "");
    return `
      <article class="tg-admin-item">
        <div>
          <div class="d-flex flex-wrap align-items-center gap-2 mb-1">
            <h6 class="tg-admin-item__title mb-0">${escapeHtml(t.title || "")}</h6>
            ${targetTypeLabel}
          </div>
          <p class="tg-admin-item__msg">${escapeHtml(msg.length > 140 ? `${msg.slice(0, 140)}…` : msg)}</p>
          <div class="tg-admin-item__meta">
            <i class="bi bi-person me-1" aria-hidden="true"></i>${escapeHtml(t.created_by || "")}
            · ${formatDate(t.created_at)}
            ${t.expires_at ? ` · до ${formatDate(t.expires_at)}` : ""}
          </div>
        </div>
        <button type="button" class="btn btn-sm btn-outline-danger align-self-start" onclick="deleteTargeting(${t.id})" title="Удалить">
          <i class="bi bi-trash" aria-hidden="true"></i>
        </button>
      </article>`;
  }).join("")}</div>`;
}

function showCreateTargetingModal() {
  const modalEl = $("createTargetingModal");
  if (!modalEl) return;

  const modal = new bootstrap.Modal(modalEl);

  // Очищаем форму
  $("targeting-title").value = "";
  $("targeting-message").value = "";
  $("targeting-type").value = "all";
  $("targeting-position").value = "";
  $("targeting-expires").value = "";

  // Снимаем все чекбоксы пользователей
  const checkboxes = document.querySelectorAll("#targeting-users-checkboxes input[type='checkbox']");
  for (const cb of checkboxes) {
    cb.checked = false;
  }

  updateTargetingType();
  updateTargetingPreview();
  modal.show();
}

function updateTargetingType() {
  const type = $("targeting-type")?.value || "all";
  const positionGroup = $("targeting-position-group");
  const usersGroup = $("targeting-users-group");

  if (positionGroup) positionGroup.style.display = type === "position" ? "block" : "none";
  if (usersGroup) {
    if (type === "users") {
      usersGroup.style.display = "block";
      // Всегда загружаем пользователей при выборе типа "users"
      loadUsersForTargeting();
    } else {
      usersGroup.style.display = "none";
    }
  }

  // Загружаем позиции при необходимости
  if (type === "position") {
    if (ALL_POSITIONS.length === 0) {
      loadPositions();
    }
  }
  updateTargetingPreview();
}

function getTargetingRecipientCount() {
  const type = $("targeting-type")?.value || "all";
  if (type === "users") {
    const checkboxes = document.querySelectorAll("#targeting-users-checkboxes input[type='checkbox']:checked");
    return checkboxes ? checkboxes.length : 0;
  }
  if (type === "position") {
    const position = $("targeting-position")?.value?.trim() || "";
    if (!position) return 0;
    return (USERS_CACHE || []).filter((u) =>
      (u.positions || []).some((p) => String(p.name || "") === position)
    ).length;
  }
  return (USERS_CACHE || []).length;
}

function updateTargetingPreview() {
  const title = $("targeting-title")?.value?.trim() || "";
  const message = $("targeting-message")?.value?.trim() || "";
  const previewTitle = $("targeting-preview-title");
  const previewBody = $("targeting-preview-body");
  const countEl = $("targeting-preview-count");
  if (previewTitle) previewTitle.textContent = title || "Заголовок";
  if (previewBody) previewBody.textContent = message || "Текст сообщения";
  if (countEl) {
    const count = getTargetingRecipientCount();
    countEl.textContent = `Получателей: ${count}`;
  }
}

async function loadPositions() {
  try {
    const data = await apiGet("/api/admin/positions");
    const raw = data.positions || [];
    ALL_POSITIONS = raw.map((name) => ({ name: String(name || ""), key: posKey(name) }));
    POS_BY_KEY = {};
    for (const it of ALL_POSITIONS) POS_BY_KEY[it.key] = it.name;

    const select = $("targeting-position");
    if (select) {
      select.innerHTML = '<option value="">Выберите позицию</option>' +
        ALL_POSITIONS.map(p => `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)}</option>`).join("");
    }
    updatePositionFilterOptions();
  } catch (e) {
    console.error("Failed to load positions:", e);
  }
}

async function loadUsersForTargeting() {
  const container = $("targeting-users-checkboxes");
  if (!container) {
    console.error("Container targeting-users-checkboxes not found");
    return;
  }

  // Показываем индикатор загрузки
  container.innerHTML = '<div class="text-muted small text-center py-2"><div class="spinner-border spinner-border-sm me-2" role="status"></div>Загрузка пользователей...</div>';

  try {
    const data = await apiGet("/api/admin/users");
    USERS_CACHE = data.users || [];

    if (USERS_CACHE.length === 0) {
      container.innerHTML = '<div class="text-muted small text-center py-2">Нет пользователей</div>';
    } else {
      container.innerHTML = USERS_CACHE.map(u => {
        const callsign = u.callsign || "";
        const role = u.role || "";
        const roleBadge = getRoleBadgeForTargeting(role);
        return `
          <div class="form-check">
            <input class="form-check-input" type="checkbox" value="${u.id}" id="targeting-user-${u.id}">
            <label class="form-check-label d-flex align-items-center gap-2" for="targeting-user-${u.id}">
              <div class="flex-grow-1">
                <div class="fw-semibold">${escapeHtml(u.username || "")}</div>
                ${callsign ? `<div class="small text-primary"><i class="bi bi-person-badge me-1"></i>${escapeHtml(callsign)}</div>` : ""}
              </div>
              ${roleBadge}
            </label>
          </div>
        `;
      }).join("");
    }
    updateTargetingPreview();
  } catch (e) {
    console.error("Failed to load users:", e);
    container.innerHTML = `<div class="text-danger small text-center py-2">Ошибка загрузки пользователей: ${escapeHtml(e.message || String(e))}</div>`;
  }
}

function getRoleBadgeForTargeting(role) {
  const roleData = {
    "admin": { class: "bg-danger", icon: "bi-shield-fill-check", text: "Admin" },
    "moderator": { class: "bg-warning", icon: "bi-person-gear", text: "Moderator" },
    "search_editor": { class: "bg-info", icon: "bi-pencil-square", text: "Editor" },
    "viewer": { class: "bg-secondary", icon: "bi-eye", text: "Viewer" },
  };
  const data = roleData[role] || { class: "bg-secondary", icon: "bi-person", text: role };
  return `<span class="badge ${data.class} d-flex align-items-center gap-1">
    <i class="bi ${data.icon}"></i>
    ${data.text}
  </span>`;
}

async function createTargeting() {
  const title = $("targeting-title")?.value?.trim() || "";
  const message = $("targeting-message")?.value?.trim() || "";
  const type = $("targeting-type")?.value || "all";
  const position = $("targeting-position")?.value?.trim() || "";
  const expires = $("targeting-expires")?.value || null;

  // Собираем выбранных пользователей из чекбоксов
  const selectedUserIds = [];
  if (type === "users") {
    const checkboxes = document.querySelectorAll("#targeting-users-checkboxes input[type='checkbox']:checked");
    for (const cb of checkboxes) {
      selectedUserIds.push(parseInt(cb.value));
    }
  }

  if (!title || !message) {
    setStatus("Заголовок и сообщение обязательны", true);
    return;
  }

  if (type === "position" && !position) {
    setStatus("Выберите позицию", true);
    return;
  }

  if (type === "users" && selectedUserIds.length === 0) {
    setStatus("Выберите хотя бы одного пользователя", true);
    return;
  }

  try {
    await apiPost("/api/admin/targeting", {
      title,
      message,
      target_type: type,
      target_position: type === "position" ? position : "",
      target_user_ids: type === "users" ? selectedUserIds : [],
      expires_at: expires || null,
    });

    setStatus("Нацеливание создано", false);
    const modalEl = $("createTargetingModal");
    if (modalEl) {
      const modal = bootstrap.Modal.getInstance(modalEl);
      if (modal) modal.hide();
    }
    await loadTargetingList();
  } catch (e) {
    setStatus(`Ошибка создания нацеливания: ${e.message || e}`, true);
  }
}

async function deleteTargeting(id) {
  if (!confirm("Удалить нацеливание?")) return;

  try {
    await apiPost("/api/admin/targeting/delete", { targeting_id: id });
    setStatus("Нацеливание удалено", false);
    await loadTargetingList();
  } catch (e) {
    setStatus(`Ошибка удаления нацеливания: ${e.message || e}`, true);
  }
}

function formatDate(dateStr) {
  if (!dateStr) return "";
  try {
    const d = new Date(dateStr);
    return d.toLocaleString("ru-RU");
  } catch {
    return dateStr;
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text || "";
  return div.innerHTML;
}

// ===== РОЛИ (справочник) =====

async function populateDbHealthSelect() {
  const sel = $("db-health-db-select");
  const sel2 = $("db-multi-channel-db-select");
  const selVec = $("ai-vector-index-db-select");
  if (!sel && !sel2 && !selVec) return;
  try {
    const data = await apiGet("/api/databases");
    const dbs = data.databases || [];
    const def = data.default || "main.sqlite";
    const list = dbs.length ? dbs : [def];
    const html = list
      .map((d) => {
        const v = String(d);
        return `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`;
      })
      .join("");
    if (sel) {
      sel.innerHTML = html;
      if (list.includes(def)) sel.value = def;
    }
    if (sel2) {
      sel2.innerHTML = html;
      if (list.includes(def)) sel2.value = def;
    }
    if (selVec) {
      selVec.innerHTML = html;
      if (list.includes(def)) selVec.value = def;
    }
  } catch (e) {
    console.warn("db-health: список БД", e);
  }
}

// Tab modules: admin-roles.js, admin-sync-hubs.js, admin-settings.js, admin-db-health.js,
// admin-telegram.js, admin-ai-vector.js, admin_event_log.js, admin_ai_agent.js

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    loadTargetingList();
  });
} else {
  loadTargetingList();
}
