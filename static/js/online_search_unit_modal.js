/**
 * Карточка подразделения из online_search (модальное окно).
 * Используется на страницах «Поиск онлайн» и «Перехваты».
 */
(function (global) {
  function $(id) {
    return document.getElementById(id);
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function unitLabelFromKey(k) {
    return k === "__none__" ? "Без подразделения" : k;
  }

  async function apiGet(url) {
    if (typeof global.apiGet === "function") return global.apiGet(url);
    const res = await fetch(url, { method: "GET" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  async function apiPost(url, body) {
    if (typeof global.apiPost === "function") return global.apiPost(url, body);
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  async function apiUpload(url, formData) {
    if (typeof global.apiUpload === "function") return global.apiUpload(url, formData);
    const res = await fetch(url, { method: "POST", body: formData });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  function showToast(message, variant) {
    if (typeof global.showToast === "function") {
      global.showToast(message, variant);
      return;
    }
    const toastEl = $("app-toast");
    const bodyEl = $("app-toast-body");
    if (!toastEl || !bodyEl || !global.bootstrap) return;
    bodyEl.textContent = message || "";
    toastEl.classList.remove("text-bg-success", "text-bg-danger", "text-bg-warning", "text-bg-info");
    if (variant) toastEl.classList.add(`text-bg-${variant}`);
    global.bootstrap.Toast.getOrCreateInstance(toastEl, { delay: 2500 }).show();
  }

  function osTagBadge(tag, desc, color) {
    const t = String(tag || "").trim();
    if (!t) return "";
    const c = String(color || "").trim();
    const st = c
      ? ` style="--os-tag-c:${c};background:color-mix(in srgb, ${c} 18%, transparent);border-color:color-mix(in srgb, ${c} 40%, var(--md3-outline-variant))"`
      : "";
    return `<span class="os-cs-tag badge rounded-pill border"${st} title="${escapeHtml(String(desc || ""))}">${escapeHtml(t)}</span>`;
  }

  function renderUnitRichContent(richEl, uk, data, canEdit) {
    const prof = data.profile || {};
    const history = String(prof.history || "");
    const avatarUrl = prof.avatar_url || "";
    const total = data.total_in_db != null ? data.total_in_db : 0;
    const truncated = !!data.truncated;
    const groups = data.groups || [];
    const L = data.labels || {};
    const Lid = L.id_field || "ID";
    const Lcor = L.correspondent || "Корр.";
    const Ldisc = L.discovery || "Дата обнаружения";

    let groupsHtml = "";
    groups.forEach((g, gi) => {
      const freq = String(g.frequency ?? "—");
      const gid = String(g.group_id ?? "—");
      const items = g.items || [];
      const callsigns = g.callsigns || [];
      const tabBase = `osut-${String(gi)}-${String(
        Math.abs(uk.split("").reduce((a, c) => a + c.charCodeAt(0), 0))
      )}`;
      const tRecords = `${tabBase}-rec`;
      const tCalls = `${tabBase}-cs`;
      let recordsInner = "";
      for (const it of items) {
        const idv = String(it.col3 ?? "—");
        const corr = String(it.col4 ?? "—");
        const disc = String(it.discovery ?? it.col7 ?? "—");
        const cs = it.callsign;
        const oneLine = cs
          ? `<div class="os-fg-miniline"><span class="os-fg-k">${escapeHtml(Lcor)} (стр.)</span> <span class="os-fg-v font-monospace">${escapeHtml(
              String(corr)
            )}</span> <span class="os-fg-aux text-muted">→ ${escapeHtml(
              String(cs.label || "—")
            )}</span> <span class="text-muted small">(${escapeHtml(String(cs.code || ""))})</span></div>`
          : "";
        recordsInner += `<div class="os-fg-record">
          <div class="d-flex flex-wrap justify-content-between gap-2">
            <div class="os-fg-record__grid">
              <div><span class="os-fg-k">${escapeHtml(Lid)}</span> <span class="os-fg-v font-monospace">${escapeHtml(
                idv
              )}</span></div>
              <div><span class="os-fg-k">${escapeHtml(Lcor)}</span> <span class="os-fg-v font-monospace">${escapeHtml(
                corr
              )}</span></div>
              <div class="os-fg-record__full"><span class="os-fg-k">${escapeHtml(
                Ldisc
              )}</span> <span class="os-fg-v">${escapeHtml(disc)}</span></div>
            </div>
          </div>
          ${oneLine}
        </div>`;
      }
      if (!recordsInner) {
        recordsInner = '<p class="text-muted small mb-0 px-1">Нет записей online для этой пары.</p>';
      }
      let callsInner = "";
      for (const c of callsigns) {
        const tag = osTagBadge(c.tag, c.tag_desc, c.tag_color);
        callsInner += `<div class="os-cs-line list-group-item d-flex flex-wrap align-items-center justify-content-between gap-2">
          <div>
            <div class="d-flex flex-wrap align-items-center gap-2">
              <span class="fw-semibold">${escapeHtml(c.label || "—")}</span>
              ${tag}
            </div>
            <div class="small text-muted">(${escapeHtml(
              String(c.code || "")
            )})<span class="ms-1">${escapeHtml(String(c.frequency || ""))} / G ${escapeHtml(
          String(c.group_code || "")
        )}</span></div>
          </div>
          <a class="btn btn-sm btn-outline-primary" href="/analysis" target="_blank" rel="noopener" title="Открыть раздел анализ">Анализ</a>
        </div>`;
      }
      if (!callsInner) {
        callsInner =
          '<p class="text-muted small mb-0 px-1">По этой частоте/группе в справочнике позывных нет записей (перехваты).</p>';
      }
      groupsHtml += `<div class="os-fg-card">
        <div class="os-fg-card__head">
          <div class="d-flex flex-wrap align-items-baseline gap-2">
            <span class="os-fg-card__freq">${escapeHtml(freq)}</span>
            <span class="badge os-fg-card__gb">G ${escapeHtml(gid)}</span>
          </div>
          <span class="os-fg-card__meta small text-muted">${items.length} зн. online / ${callsigns.length} позывн.</span>
        </div>
        <ul class="nav nav-tabs os-fg-card__nav px-2 pt-2 gap-0" role="tablist">
          <li class="nav-item" role="presentation">
            <button class="nav-link active" type="button" data-bs-toggle="tab" data-bs-target="#${tRecords}" role="tab">Записи</button>
          </li>
          <li class="nav-item" role="presentation">
            <button class="nav-link" type="button" data-bs-toggle="tab" data-bs-target="#${tCalls}" role="tab">Позывные</button>
          </li>
        </ul>
        <div class="tab-content os-fg-card__tabbody">
          <div class="tab-pane fade show active" id="${tRecords}" role="tabpanel">
            <div class="os-fg-records py-2 px-1">${recordsInner}</div>
          </div>
          <div class="tab-pane fade" id="${tCalls}" role="tabpanel">
            <div class="os-cs-list list-group list-group-flush py-1">${callsInner}</div>
          </div>
        </div>
      </div>`;
    });

    const editBlock = canEdit
      ? `<div class="os-unit-rich__edit mt-2">
          <label class="form-label small mb-1">История подразделения</label>
          <textarea class="form-control form-control-sm" rows="4" data-unit-history placeholder="Текст истории…">${escapeHtml(history)}</textarea>
          <div class="d-flex flex-wrap gap-2 mt-2">
            <button type="button" class="btn btn-sm btn-primary" data-unit-save>Сохранить текст</button>
            <label class="btn btn-sm btn-outline-secondary mb-0">
              <i class="bi bi-image" aria-hidden="true"></i> Аватар
              <input type="file" class="d-none" data-unit-avatar accept="image/*" />
            </label>
          </div>
        </div>`
      : `<div class="os-unit-rich__history small mt-2">${history ? escapeHtml(history) : '<span class="text-muted">История не заполнена.</span>'}</div>`;

    const av = avatarUrl
      ? `<img src="${escapeHtml(avatarUrl)}" alt="" class="os-unit-rich__avatar-img" width="96" height="96" loading="lazy" />`
      : `<div class="os-unit-rich__avatar-ph" aria-hidden="true"><i class="bi bi-building"></i></div>`;

    richEl.dataset.unitKey = uk;
    richEl.innerHTML = `
      <div class="os-unit-rich__inner">
        <div class="os-unit-rich__hero">
          <div class="os-unit-rich__avatar" data-unit-avatar-wrap>${av}</div>
          <div class="os-unit-rich__meta">
            <div class="os-unit-rich__stats text-muted small">
              В базе по подразделению: <strong>${total}</strong>${truncated ? " (показаны не все строки в детализации; лимит 10 000)" : ""}
            </div>
            ${editBlock}
          </div>
        </div>
        <div class="os-unit-rich__groups-title">Частоты / группы</div>
        <div class="os-unit-rich__groups os-unit-rich__groups--cards">${
          groupsHtml || '<p class="text-muted small mb-0">Нет данных.</p>'
        }</div>
      </div>`;
  }

  async function loadUnitModalContent(richEl, uk) {
    richEl.className = "os-unit-rich os-unit-rich--modal";
    richEl.innerHTML = `<div class="os-unit-rich__loading text-muted small py-3 px-3"><span class="spinner-border spinner-border-sm me-2" role="status"></span> Загрузка карточки…</div>`;
    try {
      const data = await apiGet(`/api/online-search/unit-detail?key=${encodeURIComponent(uk)}`);
      const canEdit = $("web-perms")?.dataset?.editSearch === "1";
      renderUnitRichContent(richEl, uk, data, canEdit);
    } catch (e) {
      richEl.innerHTML = `<div class="text-danger small p-3">Ошибка: ${escapeHtml(e.message || e)}</div>`;
    }
  }

  async function openOnlineSearchUnitModal(uk) {
    const key = String(uk || "").trim();
    if (!key || key === "—") return;
    const body = $("os-unit-modal-body");
    const title = $("os-unit-modal-title");
    const modalEl = $("os-unit-modal");
    if (!body) {
      global.location.href = `/search-online/battalion?k=${encodeURIComponent(key)}`;
      return;
    }
    if (title) title.textContent = unitLabelFromKey(key);
    const rich = document.createElement("div");
    body.innerHTML = "";
    body.appendChild(rich);
    if (modalEl && global.bootstrap) {
      global.bootstrap.Modal.getOrCreateInstance(modalEl, { backdrop: true }).show();
    }
    await loadUnitModalContent(rich, key);
  }

  let _modalInit = false;
  function initOnlineSearchUnitModal() {
    if (_modalInit) return;
    const unitModal = $("os-unit-modal");
    if (!unitModal) return;
    _modalInit = true;
    unitModal.addEventListener("click", async (ev) => {
      const saveBtn = ev.target.closest("[data-unit-save]");
      if (!saveBtn) return;
      ev.preventDefault();
      const rich = saveBtn.closest(".os-unit-rich");
      const uk = rich?.dataset.unitKey;
      const ta = rich?.querySelector("[data-unit-history]");
      if (!uk || !ta) return;
      try {
        await apiPost("/api/online-search/unit-profile", {
          unit_key: uk,
          history: String(ta.value || ""),
        });
        showToast("Сохранено", "success");
      } catch (e) {
        showToast(e.message || String(e), "danger");
      }
    });
    unitModal.addEventListener("change", async (ev) => {
      const inp = ev.target.closest("input[data-unit-avatar]");
      if (!inp || !inp.files || !inp.files[0]) return;
      const rich = inp.closest(".os-unit-rich");
      const uk = rich?.dataset.unitKey;
      if (!uk) return;
      const fd = new FormData();
      fd.append("unit_key", uk);
      fd.append("file", inp.files[0]);
      inp.value = "";
      try {
        const data = await apiUpload("/api/online-search/unit-avatar", fd);
        if (data.avatar_url) {
          const wrap = rich?.querySelector("[data-unit-avatar-wrap]");
          if (wrap) {
            wrap.textContent = "";
            const im = document.createElement("img");
            im.className = "os-unit-rich__avatar-img";
            im.width = 96;
            im.height = 96;
            im.loading = "lazy";
            im.alt = "";
            im.src = String(data.avatar_url);
            wrap.appendChild(im);
          }
        }
        showToast("Аватар обновлён", "success");
      } catch (e) {
        showToast(e.message || String(e), "danger");
      }
    });
  }

  global.openOnlineSearchUnitModal = openOnlineSearchUnitModal;
  global.openUnitModal = openOnlineSearchUnitModal;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initOnlineSearchUnitModal);
  } else {
    initOnlineSearchUnitModal();
  }
})(typeof window !== "undefined" ? window : globalThis);
