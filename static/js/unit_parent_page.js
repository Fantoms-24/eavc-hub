function _esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function apiPostJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
    credentials: "same-origin",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return data;
}

async function apiUploadFile(url, formData) {
  const res = await fetch(url, { method: "POST", body: formData, credentials: "same-origin" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return data;
}

function _setPatch(el, url) {
  if (!el) return;
  el.textContent = "";
  if (url) {
    const im = document.createElement("img");
    im.src = url;
    im.alt = "";
    im.loading = "eager";
    im.className = "w-100 h-100";
    im.style.objectFit = "cover";
    im.addEventListener("error", () => {
      im.remove();
      el.innerHTML = '<i class="bi bi-shield-shaded" aria-hidden="true"></i>';
    });
    el.appendChild(im);
  } else {
    el.innerHTML = '<i class="bi bi-shield-shaded" aria-hidden="true"></i>';
  }
}

function _statPill(label, value) {
  const d = document.createElement("div");
  d.className = "up-stat-pill";
  d.innerHTML = `<span class="up-stat-pill__k">${_esc(label)}</span><span class="up-stat-pill__v">${_esc(value)}</span>`;
  return d;
}

function _setCrumb(key) {
  const el = document.getElementById("up2-crumb");
  if (!el) return;
  const k = String(key || "").trim();
  if (!k) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.textContent = k;
  el.hidden = false;
  el.title = k;
}

function _renderDescriptionBlock(el, history, canEdit) {
  if (!el) return;
  const h = String(history || "").trim();
  if (h) {
    el.textContent = h;
  } else {
    el.textContent = canEdit
      ? "Описание пусто — откройте настройки (шестерёнка): эмблема, оформление шапки и текст на карточку подразделения."
      : "Описание пока не заполнено. Его можно добавить в деталях любого варианта (кнопка в поиске онлайн).";
  }
}

function _renderTimeline(listEl, hasHistory) {
  if (!listEl) return;
  listEl.innerHTML = "";
  const li = document.createElement("li");
  if (hasHistory) {
    li.innerHTML = `<div class="up-tl__date">Справка</div><div class="up-tl__title">Описание на карточке</div><div class="up-tl__sub">текст в профиле подразделения</div>`;
  } else {
    li.innerHTML = `<div class="up-tl__date">—</div><div class="up-tl__title">Нет вех</div><div class="up-tl__sub">добавьте описание в настройках (иконка шестерёнки) или в деталях варианта</div>`;
  }
  listEl.appendChild(li);
}

/** Применяет кастомную шапку: hero = null | { mode, tint, banner, banner_url } */
function applyHero(hero) {
  const root = document.getElementById("up-hero");
  const bg = document.getElementById("up-hero-bg");
  const tint = document.getElementById("up-hero-tint");
  const scrim = document.getElementById("up-hero-scrim");
  const aurora = document.getElementById("up-hero-aurora");
  if (!root || !bg || !tint || !scrim) return;
  root.classList.remove("up-hero--custom", "up-hero--tint", "up-hero--banner");
  root.style.removeProperty("--up-hero-tint");
  bg.style.backgroundImage = "";
  tint.hidden = true;
  scrim.hidden = true;
  if (aurora) aurora.style.removeProperty("opacity");
  if (!hero || !hero.mode || hero.mode === "default") {
    return;
  }
  root.classList.add("up-hero--custom");
  if (hero.mode === "tint" && hero.tint) {
    root.classList.add("up-hero--tint");
    root.style.setProperty("--up-hero-tint", String(hero.tint));
    tint.hidden = false;
    if (aurora) aurora.style.opacity = "0.2";
  } else if (hero.mode === "banner") {
    const url = hero.banner_url || "";
    if (url) {
      root.classList.add("up-hero--banner");
      bg.style.backgroundImage = `url(${JSON.stringify(url)})`;
      scrim.hidden = false;
      if (aurora) aurora.style.opacity = "0.12";
    }
  }
}

function _fillHeroForm(hero) {
  const d = document.getElementById("up-hm-def");
  const t = document.getElementById("up-hm-tint");
  const b = document.getElementById("up-hm-ban");
  const c = document.getElementById("up-set-hero-tint");
  if (d) d.checked = !hero || !hero.mode || hero.mode === "default";
  if (t) t.checked = hero && hero.mode === "tint";
  if (b) b.checked = hero && hero.mode === "banner";
  if (c && hero && hero.tint) c.value = String(hero.tint);
  else if (c) c.value = "#1d4ed8";
  _syncHeroFormVisibility();
}

function _syncHeroFormVisibility() {
  const t = document.getElementById("up-hero-tint-wrap");
  const b = document.getElementById("up-hero-banner-wrap");
  const m = document.querySelector('input[name="up-hero-mode"]:checked')?.value;
  if (t) t.style.display = m === "tint" ? "" : "none";
  if (b) b.style.display = m === "banner" ? "" : "none";
}

function _readHeroForSave(state) {
  const m = document.querySelector('input[name="up-hero-mode"]:checked')?.value || "default";
  if (m === "default") return { mode: "default" };
  if (m === "tint") {
    const col = document.getElementById("up-set-hero-tint");
    return { mode: "tint", tint: (col && col.value) || "#1d4ed8" };
  }
  if (m === "banner") {
    const fn = state.hero && state.hero.banner;
    if (!fn) {
      return null;
    }
    return { mode: "banner", banner: fn };
  }
  return { mode: "default" };
}

function _wireSettings(state) {
  if (!window.__UP_CAN_EDIT__) return;
  const btn = document.getElementById("up-btn-settings");
  const modalEl = document.getElementById("up-settings-modal");
  const ta = document.getElementById("up-set-history");
  const avInp = document.getElementById("up-set-avatar");
  const hBanner = document.getElementById("up-set-hero-banner");
  const save = document.getElementById("up-set-save");
  const avWrap = document.getElementById("up-set-av-wrap");
  const resHero = document.getElementById("up-set-hero-reset");
  if (!btn || !modalEl || !ta || !save || !avWrap) return;
  if (!window.bootstrap) return;
  const modal = window.bootstrap.Modal.getOrCreateInstance(modalEl);
  const phHist = document.getElementById("up-ph-history");
  const listEl = document.getElementById("up-ph-tl");
  const canEdit = true;

  document.querySelectorAll('input[name="up-hero-mode"]').forEach((el) => {
    el.addEventListener("change", _syncHeroFormVisibility);
  });
  if (resHero) {
    resHero.addEventListener("click", (ev) => {
      ev.preventDefault();
      const def = document.getElementById("up-hm-def");
      if (def) def.checked = true;
      _fillHeroForm(null);
      state.hero = { mode: "default" };
      applyHero(null);
    });
  }
  if (hBanner) {
    hBanner.addEventListener("change", async (ev) => {
      const f = ev.target?.files && ev.target.files[0];
      if (!f) return;
      const fd = new FormData();
      fd.append("unit_key", state.parentKey);
      fd.append("file", f);
      try {
        const data = await apiUploadFile("/api/online-search/unit-hero-banner", fd);
        if (data.banner) {
          state.hero = {
            mode: "banner",
            banner: data.banner,
            banner_url: data.banner_url,
          };
        }
        if (data.banner_url) applyHero(state.hero);
        const ban = document.getElementById("up-hm-ban");
        if (ban) ban.checked = true;
        _syncHeroFormVisibility();
        hBanner.value = "";
      } catch (e) {
        window.alert(String(e.message || e));
      }
    });
  }

  btn.addEventListener("click", () => {
    ta.value = String(state.history || "");
    _setPatch(avWrap, state.avatarUrl);
    if (avInp) avInp.value = "";
    if (hBanner) hBanner.value = "";
    _fillHeroForm(state.hero);
    applyHero(state.hero);
    modal.show();
  });
  if (avInp) {
    avInp.addEventListener("change", async (ev) => {
      const f = ev.target?.files && ev.target.files[0];
      if (!f) return;
      const fd = new FormData();
      fd.append("unit_key", state.parentKey);
      fd.append("file", f);
      try {
        const data = await apiUploadFile("/api/online-search/unit-avatar", fd);
        if (data.avatar_url) {
          state.avatarUrl = data.avatar_url;
          _setPatch(avWrap, state.avatarUrl);
          _setPatch(document.getElementById("up-ph-patch"), state.avatarUrl);
        }
      } catch (e) {
        window.alert(String(e.message || e));
      }
    });
  }
  save.addEventListener("click", async () => {
    const history = String(ta.value || "");
    let heroToSave = { mode: "default" };
    if (document.getElementById("up-hm-def")) {
      const hr = _readHeroForSave(state);
      if (hr === null) {
        window.alert("Для баннера сначала загрузите фоновое фото (или смените режим).");
        return;
      }
      heroToSave = hr;
    }
    try {
      await apiPostJson("/api/online-search/unit-profile", {
        unit_key: state.parentKey,
        history,
        hero: heroToSave,
      });
      state.history = history;
      if (heroToSave && heroToSave.mode && heroToSave.mode !== "default") {
        state.hero = { ...state.hero, ...heroToSave };
        if (state.hero.mode === "tint" && !state.hero.tint) {
          state.hero.tint = document.getElementById("up-set-hero-tint")?.value || "#1d4ed8";
        }
        if (state.hero.mode === "banner" && !state.hero.banner_url && state.hero.banner) {
          const path = state.hero.banner;
          const base = window.location.origin || "";
          state.hero.banner_url = `${base}/api/online-search/unit-hero/${path}`;
        }
        applyHero(state.hero);
      } else {
        state.hero = null;
        applyHero(null);
      }
      const has = String(history || "").trim().length > 0;
      _renderDescriptionBlock(phHist, state.history, canEdit);
      _renderTimeline(listEl, has);
      modal.hide();
    } catch (e) {
      window.alert(String(e.message || e));
    }
  });
}

(async () => {
  const p = window.__UP_PARENT_P__;
  const canEdit = !!window.__UP_CAN_EDIT__;
  const loading = document.getElementById("up-parent-loading");
  const err = document.getElementById("up-parent-err");
  const body = document.getElementById("up-parent-body");
  if (!p) {
    if (loading) loading.classList.add("d-none");
    if (err) {
      err.classList.remove("d-none");
      err.textContent = "Не указан параметр p (код подразделения).";
    }
    return;
  }
  try {
    const r = await fetch(`/api/online-search/unit-parent?p=${encodeURIComponent(p)}`, {
      credentials: "same-origin",
    });
    const data = await r.json();
    if (!r.ok || !data.ok) throw new Error(data.error || r.status);

    if (loading) loading.classList.add("d-none");
    if (body) body.classList.remove("d-none");

    const parentKey = String(data.parent_key || p);
    const state = {
      parentKey,
      history: data.history || "",
      avatarUrl: data.avatar_url || "",
      hero: data.hero && typeof data.hero === "object" ? { ...data.hero } : null,
    };

    _setCrumb(parentKey);

    const title = document.getElementById("up-ph-title");
    if (title) title.textContent = data.parent_label || "—";
    const meta = document.getElementById("up-ph-meta");
    if (meta) {
      meta.innerHTML = "";
      meta.appendChild(_statPill("Всего записей", String(data.row_count ?? "—")));
      const ch = data.children || [];
      meta.appendChild(_statPill("Вариантов", String(ch.length)));
    }
    const hist = document.getElementById("up-ph-history");
    _renderDescriptionBlock(hist, state.history, canEdit);
    const tl = document.getElementById("up-ph-tl");
    _renderTimeline(tl, String(state.history || "").trim().length > 0);
    const av = state.avatarUrl;
    _setPatch(document.getElementById("up-ph-patch"), av);

    applyHero(state.hero);

    const grid = document.getElementById("up-children");
    if (grid) {
      grid.innerHTML = "";
      for (const ch of data.children || []) {
        const lab = String(ch.label || "—");
        const uk = ch.unit_key;
        const n = Number(ch.row_count || 0);
        const a = document.createElement("a");
        a.className = "up-bcard";
        a.href = `/search-online/battalion?k=${encodeURIComponent(uk)}`;
        a.setAttribute("role", "listitem");
        a.innerHTML = `<div class="up-bcard__top">
            <span class="up-bcard__n">${n} записей</span>
            <span class="up-bcard__em" aria-hidden="true"><i class="bi bi-diagram-3"></i></span>
          </div>
          <div class="up-bcard__name">${_esc(lab)}</div>
          <div class="up-bcard__meta text-truncate" title="${_esc(uk)}">${_esc(uk)}</div>
          <span class="up-bcard__go">Открыть <i class="bi bi-arrow-right-short" aria-hidden="true"></i></span>`;
        grid.appendChild(a);
      }
    }

    _wireSettings(state);
  } catch (e) {
    if (loading) loading.classList.add("d-none");
    if (err) {
      err.classList.remove("d-none");
      err.textContent = String(e.message || e);
    }
  }
})();
