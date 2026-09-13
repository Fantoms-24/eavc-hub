(function () {
  "use strict";

const TAB_ICON_MAP = {
  tab_intercepts: "bi-chat-dots",
  tab_audio_intercepts: "bi-mic",
  tab_aviation: "bi-airplane",
  tab_sessions: "bi-collection-play",
  tab_analysis: "bi-graph-up",
  tab_search_online: "bi-search",
  tab_instructions: "bi-book",
  tab_admin: "bi-shield-lock",
};

function tabIcon(id) {
  return TAB_ICON_MAP[String(id || "")] || "bi-grid";
}

function isTabPerm(perm) {
  return String(perm || "").startsWith("tab_");
}

function hideCustomRoleCreateCollapse() {
  const collapseEl = $("adm-create-role-collapse");
  if (!collapseEl || !window.bootstrap) return;
  const inst = bootstrap.Collapse.getInstance(collapseEl) || bootstrap.Collapse.getOrCreateInstance(collapseEl, { toggle: false });
  inst.hide();
}

function renderCustomRoleCheckboxes(containerId, selectedIds) {
  const box = $(containerId);
  if (!box || !TAB_CATEGORIES_CACHE.length) return;
  const sel = new Set((selectedIds || []).map(String));
  box.innerHTML = `<div class="adm-tab-grid">${TAB_CATEGORIES_CACHE.map((c) => {
    const checked = sel.has(c.id);
    return `<label class="adm-tab-toggle">
      <input type="checkbox" class="adm-tab-toggle__input custom-role-tab-cb" value="${escapeHtml(c.id)}" ${checked ? "checked" : ""} />
      <span class="adm-tab-toggle__card">
        <span class="adm-tab-toggle__icon"><i class="bi ${tabIcon(c.id)}" aria-hidden="true"></i></span>
        <span class="adm-tab-toggle__label">${escapeHtml(c.label)}</span>
        <span class="adm-tab-toggle__check" aria-hidden="true"><i class="bi bi-check-lg"></i></span>
      </span>
    </label>`;
  }).join("")}</div>`;
}

function renderPermChips(permissions) {
  return (permissions || []).map((p) => {
    const perm = p.perm || p;
    const label = p.label || perm;
    const tab = isTabPerm(perm);
    const cls = tab ? "adm-perm-chip adm-perm-chip--tab" : "adm-perm-chip adm-perm-chip--sys";
    const icon = tab ? tabIcon(perm) : "bi-key";
    return `<span class="${cls}"><i class="bi ${icon}" aria-hidden="true"></i>${escapeHtml(label)}</span>`;
  }).join("");
}

function renderCustomRoleTabChips(permissionIds) {
  const ids = permissionIds || [];
  if (!ids.length) return '<span class="adm-perm-empty">Нет разделов</span>';
  return ids.map((pid) => {
    const c = TAB_CATEGORIES_CACHE.find((x) => x.id === pid);
    const label = c ? c.label : pid;
    const icon = c ? tabIcon(c.id) : "bi-grid";
    return `<span class="adm-perm-chip adm-perm-chip--tab"><i class="bi ${icon}" aria-hidden="true"></i>${escapeHtml(label)}</span>`;
  }).join("");
}

function renderRefRoleCell(roleRow) {
  const isBuiltin = roleRow.builtin !== false;
  const data = isBuiltin ? getRoleData(roleRow.role) : { icon: "bi-person-badge", tone: "custom", name: roleRow.label || roleRow.role };
  const badge = isBuiltin
    ? '<span class="adm-ref-role__badge">Встроенная</span>'
    : '<span class="adm-ref-role__badge adm-ref-role__badge--custom">Кастомная</span>';
  return `<div class="adm-ref-role adm-ref-role--${data.tone}">
    <span class="adm-ref-role__icon"><i class="bi ${data.icon}" aria-hidden="true"></i></span>
    <span class="adm-ref-role__label">${escapeHtml(roleRow.label || roleRow.role)}</span>
    ${badge}
  </div>`;
}

function getSelectedTabIds(containerId) {
  const box = $(containerId);
  if (!box) return [];
  return Array.from(box.querySelectorAll(".custom-role-tab-cb:checked")).map((cb) => cb.value);
}

let CUSTOM_ROLES_CACHE = [];

async function createCustomRole() {
  const nameEl = $("custom-role-name");
  const name = (nameEl && nameEl.value || "").trim();
  if (!name) {
    setStatus("Введите название роли", true);
    return;
  }
  const perms = getSelectedTabIds("custom-role-checkboxes");
  try {
    await apiPost("/api/admin/roles", { name, permissions: perms });
    setStatus("Роль создана", false);
    hideCustomRoleCreateCollapse();
    if (nameEl) nameEl.value = "";
    renderCustomRoleCheckboxes("custom-role-checkboxes", []);
    await loadRoles();
    await reload();
  } catch (e) {
    setStatus("Ошибка: " + (e.message || e), true);
  }
}

function cancelCustomRoleForm() {
  hideCustomRoleCreateCollapse();
  const nameEl = $("custom-role-name");
  if (nameEl) nameEl.value = "";
  renderCustomRoleCheckboxes("custom-role-checkboxes", []);
}

function openEditCustomRoleModal(id) {
  const cr = CUSTOM_ROLES_CACHE.find((r) => r.id === id);
  if (!cr) return;
  CUSTOM_ROLE_EDIT_ID = id;
  const nameEl = $("custom-role-edit-name");
  if (nameEl) nameEl.value = cr.name || "";
  renderCustomRoleCheckboxes("custom-role-edit-checkboxes", cr.permissions || []);
  const modalEl = document.getElementById("customRoleEditModal");
  if (modalEl) new bootstrap.Modal(modalEl).show();
}

async function saveEditCustomRole() {
  const nameEl = $("custom-role-edit-name");
  const name = (nameEl && nameEl.value || "").trim();
  if (!name) {
    setStatus("Введите название роли", true);
    return;
  }
  const perms = getSelectedTabIds("custom-role-edit-checkboxes");
  try {
    const res = await fetch("/api/admin/roles/" + CUSTOM_ROLE_EDIT_ID, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, permissions: perms }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) throw new Error(data.error || "Ошибка сохранения");
    setStatus("Роль обновлена", false);
    const modalEl = document.getElementById("customRoleEditModal");
    if (modalEl) bootstrap.Modal.getInstance(modalEl).hide();
    await loadRoles();
    await reload();
  } catch (e) {
    setStatus("Ошибка: " + (e.message || e), true);
  }
}

async function deleteCustomRole(id) {
  if (!confirm("Удалить эту роль? Пользователям с этой ролью будет назначена роль «Наблюдатель».")) return;
  try {
    const res = await fetch("/api/admin/roles/" + id, { method: "DELETE" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) throw new Error(data.error || "Ошибка удаления");
    setStatus("Роль удалена", false);
    await loadRoles();
    await reload();
  } catch (e) {
    setStatus("Ошибка: " + (e.message || e), true);
  }
}

async function loadRoles() {
  const loading = $("roles-reference-loading");
  const content = $("roles-reference-content");
  const body = $("roles-reference-body");
  const allPermsEl = $("roles-all-perms-list");
  const customTbody = $("custom-roles-tbody");
  const customCountEl = $("custom-roles-count");
  try {
    if (loading) loading.style.display = "";
    if (content) content.style.display = "none";
    const data = await apiGet("/api/admin/roles");
    const roles = data.roles || [];
    const customRoles = data.custom_roles || [];
    CUSTOM_ROLES_CACHE = customRoles;
    TAB_CATEGORIES_CACHE = data.tab_categories || [];
    const allPerms = data.all_permissions || [];
    if (customCountEl) {
      const n = customRoles.length;
      const m10 = n % 10;
      const m100 = n % 100;
      let label = `${n} ролей`;
      if (m10 === 1 && m100 !== 11) label = `${n} роль`;
      else if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) label = `${n} роли`;
      customCountEl.textContent = label;
    }
    if (body) {
      body.innerHTML = roles
        .map(
          (r) =>
            `<tr>
              <td>${renderRefRoleCell(r)}</td>
              <td><div class="adm-perm-chips">${renderPermChips(r.permissions || []) || '<span class="adm-perm-empty">—</span>'}</div></td>
            </tr>`
        )
        .join("");
    }
    if (allPermsEl) {
      allPermsEl.innerHTML = (allPerms || []).map((p) => {
        const perm = p.perm || p;
        const label = p.label || perm;
        const tab = isTabPerm(perm);
        const cls = tab ? "adm-perm-chip adm-perm-chip--tab adm-perm-chip--legend" : "adm-perm-chip adm-perm-chip--sys adm-perm-chip--legend";
        const icon = tab ? tabIcon(perm) : "bi-key";
        return `<span class="${cls}" title="${escapeHtml(perm)}"><i class="bi ${icon}" aria-hidden="true"></i>${escapeHtml(label)}</span>`;
      }).join("");
    }
    if (customTbody) {
      customTbody.innerHTML = customRoles.length === 0
        ? `<tr><td colspan="3"><div class="adm-roles-empty"><i class="bi bi-shield-plus" aria-hidden="true"></i><span>Нет кастомных ролей. Нажмите «Создать роль».</span></div></td></tr>`
        : customRoles.map((cr) => `<tr>
              <td>
                <div class="adm-custom-role-name">
                  <span class="adm-custom-role-name__icon"><i class="bi bi-person-badge" aria-hidden="true"></i></span>
                  <span class="adm-custom-role-name__label">${escapeHtml(cr.name)}</span>
                </div>
              </td>
              <td><div class="adm-perm-chips">${renderCustomRoleTabChips(cr.permissions || [])}</div></td>
              <td class="text-end">
                <div class="adm-row-actions">
                  <button type="button" class="adm-icon-btn" title="Изменить" aria-label="Изменить" onclick="openEditCustomRoleModal(${cr.id})">
                    <i class="bi bi-pencil" aria-hidden="true"></i>
                  </button>
                  <button type="button" class="adm-icon-btn adm-icon-btn--danger" title="Удалить" aria-label="Удалить" onclick="deleteCustomRole(${cr.id})">
                    <i class="bi bi-trash" aria-hidden="true"></i>
                  </button>
                </div>
              </td>
            </tr>`).join("");
    }
    renderCustomRoleCheckboxes("custom-role-checkboxes", []);
    if (loading) loading.style.display = "none";
    if (content) content.style.display = "";
  } catch (e) {
    if (loading) {
      loading.innerHTML = "<span class=\"text-danger\">Ошибка: " + escapeHtml(e.message || String(e)) + "</span>";
      loading.style.display = "";
    }
    if (content) content.style.display = "none";
  }
}

function startRolesTabLoad() {
  const rolesTab = document.querySelector("#admin-roles-tab");
  if (!rolesTab) return;
  rolesTab.addEventListener("shown.bs.tab", () => {
    loadRoles();
  });
  // Если вкладка «Роли» уже активна при загрузке страницы (напрямую по якорю и т.д.) — загружаем сразу
  const rolesPane = document.querySelector("#admin-roles-pane");
  if (rolesPane && rolesPane.classList.contains("active")) {
    loadRoles();
  }
}

  function init() {
    const createRoleCollapse = document.getElementById("adm-create-role-collapse");
    if (createRoleCollapse) {
      createRoleCollapse.addEventListener("shown.bs.collapse", () => {
        renderCustomRoleCheckboxes("custom-role-checkboxes", []);
        const nameEl = document.getElementById("custom-role-name");
        if (nameEl) nameEl.focus();
      });
    }
    document.getElementById("custom-role-save-btn")?.addEventListener("click", createCustomRole);
    document.getElementById("custom-role-cancel-btn")?.addEventListener("click", cancelCustomRoleForm);
    document.getElementById("custom-role-edit-save")?.addEventListener("click", saveEditCustomRole);
    startRolesTabLoad();
  }

  window.openEditCustomRoleModal = openEditCustomRoleModal;
  window.deleteCustomRole = deleteCustomRole;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
