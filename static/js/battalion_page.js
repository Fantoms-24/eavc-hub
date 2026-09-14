function _esc(s) {
  var t = s == null || s === undefined ? "" : String(s);
  return t
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
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

/** Как на карточке подразделения: баннер / тон из профиля родителя. */
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

async function _openFreqModal(k, f, g) {
  const modalEl = document.getElementById("up-freq-modal");
  const body = document.getElementById("up-freq-modal-body");
  const t = document.getElementById("up-freq-modal-title");
  if (t) t.textContent = `${_esc(f)} / G ${_esc(g)}`;
  if (body) body.innerHTML = '<p class="text-muted">Загрузка…</p>';
  if (modalEl && window.bootstrap) {
    window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
  }
  try {
    const r = await fetch(
      `/api/online-search/battalion-freq-detail?k=${encodeURIComponent(k)}&f=${encodeURIComponent(
        f
      )}&g=${encodeURIComponent(g)}`,
      { credentials: "same-origin" }
    );
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.error || r.status);
    const ids1 = (d.id_seanses || []).map((x) => _esc(x)).join(", ") || "—";
    const ids2 = (d.id_online_search || []).map((x) => _esc(x)).join(", ") || "—";
    const cs = d.callsigns || [];
    let csH = "";
    for (const c of cs) {
      csH += `<div class="mb-1 small"><strong>${_esc(c.label || "—")}</strong> <span class="text-muted">(${
        _esc(c.code || "")
      })</span></div>`;
    }
    if (!csH) csH = '<p class="text-muted small mb-0">Позывные в справочнике не найдены.</p>';
    if (body) {
      body.innerHTML = `
        <p class="small"><span class="text-secondary">Сеансы (первая / последняя дата):</span><br />
        <strong>${_esc(d.seanses_first || "—")}</strong> — <strong>${_esc(d.seanses_last || "—")}</strong></p>
        <h3 class="h6 mt-3">ID в сеансах</h3>
        <p class="small font-monospace text-break">${ids1}</p>
        <h3 class="h6">ID в online_search</h3>
        <p class="small font-monospace text-break">${ids2}</p>
        <h3 class="h6">Позывные (справочник)</h3>
        ${csH}`;
    }
  } catch (e) {
    if (body) body.innerHTML = `<p class="text-danger small">${_esc(e.message || e)}</p>`;
  }
}

function _addFreqBtn(container, k, f, g, sub) {
  if (!container) return;
  const b = document.createElement("button");
  b.type = "button";
  b.className = "border-0";
  b.innerHTML = `<span class="up-freq__signal" aria-hidden="true"><i class="bi bi-broadcast"></i></span>
    <span class="up-freq__copy"><span class="up-freq__frequency"><span class="up-freq__value">${_esc(f)}</span><span class="up-freq__unit">MHz</span></span>
    <span class="up-freq__g">Группа G ${_esc(g)}</span></span>
    <span class="up-freq__sessions">${_esc(sub || "Открыть")}</span>
    <i class="bi bi-arrow-up-right up-freq__arrow" aria-hidden="true"></i>`;
  b.addEventListener("click", () => {
    void _openFreqModal(k, f, g);
  });
  container.appendChild(b);
}

function _freqSortKey(f) {
  const n = parseFloat(String(f == null ? "" : f).replace(",", "."));
  return Number.isFinite(n) ? n : Number.POSITIVE_INFINITY;
}

function _ruGroupsWord(n) {
  var nn = Number(n);
  var m100 = nn % 100;
  var k10 = nn % 10;
  if (m100 > 10 && m100 < 20) return "групп";
  if (k10 === 1) return "группа";
  if (k10 >= 2 && k10 <= 4) return "группы";
  return "групп";
}

function _ruPairsWord(n) {
  var nn = Number(n);
  var m100 = nn % 100;
  var k10 = nn % 10;
  if (m100 > 10 && m100 < 20) return "пар";
  if (k10 === 1) return "пара";
  if (k10 >= 2 && k10 <= 4) return "пары";
  return "пар";
}

function _formatBnDate(value) {
  var raw = String(value || "").trim();
  var match = raw.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? match[3] + "." + match[2] + "." + match[1] : raw || "—";
}

function _renderBattalionArchiveTable(container, k, rows) {
  if (!container) return;
  var data = (rows || []).slice().sort(function (a, b) {
    return String(b.last_seen || "").localeCompare(String(a.last_seen || ""));
  });
  container.innerHTML = "";

  var panel = document.createElement("div");
  panel.className = "up-bn-archive-table";
  var toolbar = document.createElement("div");
  toolbar.className = "up-bn-archive-toolbar";
  toolbar.innerHTML =
    '<div class="up-bn-archive-stat"><strong>' +
    String(data.length) +
    "</strong> " +
    _ruPairsWord(data.length) +
    '</div><label class="up-bn-archive-search"><i class="bi bi-search" aria-hidden="true"></i><input type="search" autocomplete="off" placeholder="Поиск по частоте, группе…" aria-label="Фильтр архива"></label>';
  panel.appendChild(toolbar);

  var header = document.createElement("div");
  header.className = "up-bn-archive-head";
  header.innerHTML = "<span>Частота</span><span>Группа</span><span>Первая фиксация</span><span>Последняя фиксация</span><span>Статус</span><span></span>";
  panel.appendChild(header);

  var list = document.createElement("div");
  list.className = "up-bn-archive-list";
  var empty = document.createElement("div");
  empty.className = "up-bn-archive-empty";
  empty.textContent = data.length ? "По фильтру ничего не найдено." : "Архив пока пуст.";

  data.forEach(function (row) {
    var f = String(row.frequency || "");
    var g = String(row.group || "");
    var button = document.createElement("button");
    button.type = "button";
    button.className = "up-bn-archive-row";
    button.dataset.search = (f + " " + g + " " + (row.first_seen || "") + " " + (row.last_seen || "")).toLowerCase();
    button.innerHTML =
      '<span class="up-bn-archive-frequency"><i aria-hidden="true"></i><strong>' +
      _esc(f) +
      '</strong><small>MHz</small></span><span class="up-bn-archive-group">G ' +
      _esc(g) +
      '</span><span class="up-bn-archive-date">' +
      _esc(_formatBnDate(row.first_seen)) +
      '</span><span class="up-bn-archive-date">' +
      _esc(_formatBnDate(row.last_seen)) +
      '</span><span><em class="up-bn-archive-status ' +
      (row.in_seanses ? "is-live" : "") +
      '"><i aria-hidden="true"></i>' +
      (row.in_seanses ? "В сеансах" : "Архив") +
      '</em></span><i class="bi bi-chevron-right up-bn-archive-go" aria-hidden="true"></i>';
    button.addEventListener("click", function () {
      void _openFreqModal(k, f, g);
    });
    list.appendChild(button);
  });
  if (!data.length) list.appendChild(empty);
  panel.appendChild(list);
  container.appendChild(panel);

  var input = toolbar.querySelector("input");
  if (input) {
    input.addEventListener("input", function () {
      var q = String(input.value || "").trim().toLowerCase();
      var visible = 0;
      list.querySelectorAll(".up-bn-archive-row").forEach(function (row) {
        var show = !q || String(row.dataset.search || "").indexOf(q) !== -1;
        row.hidden = !show;
        if (show) visible += 1;
      });
      if (data.length) {
        if (visible) empty.remove();
        else if (!empty.parentNode) list.appendChild(empty);
      }
    });
  }
}

/**
 * Современный UI архива: группировка по частоте, фильтр, сворачиваемые группы.
 */
function _renderBattalionArchive(container, k, rows) {
  if (!container) return;

  function rowSearchBlob(row) {
    var f = String(row.frequency || "");
    var g = String(row.group || "");
    var t1 = String(row.first_seen || "");
    var t2 = String(row.last_seen || "");
    var se = row.in_seanses ? "сеансы" : "архив";
    return (f + " " + g + " " + t1 + " " + t2 + " " + se).toLowerCase();
  }

  function build(blob) {
    container.innerHTML = "";
    var raws = blob || [];
    if (!raws.length) {
      container.innerHTML =
        '<div class="up-archive-panel"><div class="up-archive-empty"><i class="bi bi-inbox up-archive-empty__ic" aria-hidden="true"></i>Нет строк <code class="small">online_search</code> с этой меткой.</div></div>';
      return;
    }

    var sortedRows = raws.slice().sort(function (a, b) {
      var df = _freqSortKey(a.frequency) - _freqSortKey(b.frequency);
      if (df !== 0 && Number.isFinite(df)) return df;
      var sf = String(a.frequency || "").localeCompare(String(b.frequency || ""), undefined, {
        numeric: true,
      });
      if (sf !== 0) return sf;
      return String(b.last_seen || "").localeCompare(String(a.last_seen || ""));
    });

    var byFreq = {};
    var order = [];
    for (var i = 0; i < sortedRows.length; i += 1) {
      var row = sortedRows[i];
      var fk = String(row.frequency == null ? "" : row.frequency).trim();
      if (!Object.prototype.hasOwnProperty.call(byFreq, fk)) {
        byFreq[fk] = [];
        order.push(fk);
      }
      byFreq[fk].push(row);
    }

    order.sort(function (a, b) {
      var d = _freqSortKey(a) - _freqSortKey(b);
      if (d !== 0 && Number.isFinite(d)) return d;
      return String(a).localeCompare(String(b), undefined, { numeric: true });
    });

    var outer = document.createElement("div");
    outer.className = "up-archive-panel";

    var toolbar = document.createElement("div");
    toolbar.className = "up-archive-toolbar";

    var stat = document.createElement("div");
    stat.className = "up-archive-stat";
    stat.innerHTML =
      '<i class="bi bi-collection" aria-hidden="true"></i><span><strong>' +
      String(raws.length) +
      "</strong> " +
      _ruPairsWord(raws.length) +
      " «частота&nbsp;/&nbsp;группа»</span>";

    var searchRow = document.createElement("div");
    searchRow.className = "up-archive-search";
    searchRow.setAttribute("role", "search");
    searchRow.innerHTML =
      '<i class="bi bi-search" aria-hidden="true"></i><input type="search" autocomplete="off" spellcheck="false" placeholder="Частота, группа или дата…" aria-label="Фильтр архива"/>';
    var inp = searchRow.querySelector("input");

    var groupsRoot = document.createElement("div");
    groupsRoot.className = "up-archive-groups";

    var emptyFilter = document.createElement("div");
    emptyFilter.className = "up-archive-filter-empty";
    emptyFilter.style.display = "none";
    emptyFilter.innerHTML =
      '<i class="bi bi-funnel mx-auto"></i>По фильтру ничего не найдено — очистите поле.';
    emptyFilter.style.textAlign = "center";

    var detailsEls = [];

    function applyFilter() {
      var q = String((inp && inp.value) || "")
        .trim()
        .toLowerCase();
      var any = false;
      for (var j = 0; j < detailsEls.length; j += 1) {
        var d = detailsEls[j];
        var rowsBtns = d.querySelectorAll(".up-archive-group__panel [data-archive-row=\"1\"]");
        var grpVisible = false;
        for (var rIdx = 0; rIdx < rowsBtns.length; rIdx += 1) {
          var rr = rowsBtns[rIdx];
          var blob = rr.getAttribute("data-search") || "";
          var hit = !q || blob.indexOf(q) !== -1;
          if (hit) rr.classList.remove("d-none");
          else rr.classList.add("d-none");
          if (hit) grpVisible = true;
        }
        if (grpVisible) {
          d.classList.remove("d-none");
          any = true;
        } else d.classList.add("d-none");
      }
      var showEmpty = q && !any;
      if (showEmpty) {
        emptyFilter.style.display = "block";
        emptyFilter.classList.remove("d-none");
      } else {
        emptyFilter.style.display = "none";
      }
    }

    if (inp) inp.addEventListener("input", applyFilter);

    for (var gi = 0; gi < order.length; gi += 1) {
      var fq = order[gi];
      var list = byFreq[fq] || [];
      let grpSection = document.createElement("section");
      grpSection.className = "up-archive-group";

      var startOpen = gi < 8;

      let sum = document.createElement("button");
      sum.type = "button";
      sum.className = "up-archive-group__toggle";
      sum.setAttribute("aria-expanded", startOpen ? "true" : "false");
      if (startOpen) grpSection.classList.add("up-archive-group--open");
      var chipWord = _ruGroupsWord(list.length);
      sum.innerHTML =
        '<span class="up-archive-group__chev" aria-hidden="true"><i class="bi bi-chevron-down"></i></span>' +
        '<span class="up-archive-group__freq">' +
        '<span class="up-archive-group__hz">' +
        _esc(fq) +
        "</span>" +
        '<span class="up-archive-group__mhz">MHz</span></span>' +
        '<span class="up-archive-chip">' +
        String(list.length) +
        " " +
        chipWord +
        "</span>";

      let body = document.createElement("div");
      body.className = "up-archive-group__panel";
      if (!startOpen) body.setAttribute("hidden", "");

      sum.addEventListener("click", function (e) {
        e.preventDefault();
        var openNow = sum.getAttribute("aria-expanded") === "true";
        var next = !openNow;
        sum.setAttribute("aria-expanded", next ? "true" : "false");
        grpSection.classList.toggle("up-archive-group--open", next);
        if (next) body.removeAttribute("hidden");
        else body.setAttribute("hidden", "");
      });

      for (var li = 0; li < list.length; li += 1) {
        var prow = list[li];
        var fff = String(prow.frequency || "");
        var gg = String(prow.group || "");
        var t1 = prow.first_seen || "";
        var t2 = prow.last_seen || "";
        var inSeanses = !!prow.in_seanses;

        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "up-archive-row";
        btn.setAttribute("data-archive-row", "1");
        btn.setAttribute("data-search", rowSearchBlob(prow));

        var datesLine =
          '<span class="text-muted small">\u0441</span> <span class="up-archive-row__dates-val">' +
          _esc(t1 || "\u2014") +
          '</span>' +
          "&nbsp;&nbsp;&middot;&nbsp;&nbsp;" +
          '<span class="text-muted small">\u043f\u043e</span> <span class="up-archive-row__dates-val">' +
          _esc(t2 || "\u2014") +
          "</span>";

        btn.innerHTML =
          '<div class="up-archive-row__main">' +
          '<div class="up-archive-row__group">' +
          '<i class="bi bi-broadcast text-muted small" aria-hidden="true"></i> ' +
          '<span class="text-muted small">\u0413\u0440\u0443\u043f\u043f\u0430</span> ' +
          '<span class="up-archive-row__g">G ' +
          _esc(gg) +
          "</span></div>" +
          '<div class="up-archive-row__dates">' +
          datesLine +
          "</div></div>" +
          '<div class="up-archive-row__aside">' +
          '<span class="up-archive-badge ' +
          (inSeanses ? "up-archive-badge--live" : "up-archive-badge--archive") +
          '">' +
          (inSeanses ? "\u0412 \u0441\u0435\u0430\u043d\u0441\u0430\u0445" : "\u0410\u0440\u0445\u0438\u0432") +
          "</span>" +
          '<span class="up-archive-row__hint">\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u0435\u0435 <i class="bi bi-arrow-right-short" aria-hidden="true"></i></span>' +
          "</div>";

        (function (_f2, _g2) {
          btn.addEventListener("click", function () {
            void _openFreqModal(k, _f2, _g2);
          });
        })(fff, gg);

        body.appendChild(btn);
      }

      grpSection.appendChild(sum);
      grpSection.appendChild(body);
      groupsRoot.appendChild(grpSection);
      detailsEls.push(grpSection);
    }

    toolbar.appendChild(stat);
    toolbar.appendChild(searchRow);
    outer.appendChild(toolbar);
    outer.appendChild(emptyFilter);
    outer.appendChild(groupsRoot);
    container.appendChild(outer);
  }

  build(rows || []);
}

(async () => {
  const k = String((window && window.__UP_BN_K__) || "").trim();
  const loading = document.getElementById("up-bn-loading");
  const err = document.getElementById("up-bn-err");
  const body = document.getElementById("up-bn-body");
  if (!k) {
    if (loading) loading.classList.add("d-none");
    if (err) {
      err.classList.remove("d-none");
      err.textContent = "Не указан параметр k (полная строка note).";
    }
    return;
  }
  const ac = new AbortController();
  const to = setTimeout(function () {
    ac.abort();
  }, 50000);
  try {
    var r;
    try {
      r = await fetch(
        "/api/online-search/battalion-spectrum?k=" + encodeURIComponent(k),
        { credentials: "same-origin", signal: ac.signal }
      );
    } catch (fe) {
      if (fe && (fe.name === "AbortError" || fe.name === "TimeoutError")) {
        throw new Error(
          "Сервер не ответил в срок. Страница слишком тяжёлая — попробуйте обновить позже (или Ctrl+F5)."
        );
      }
      throw fe;
    }
    let data;
    try {
      data = await r.json();
    } catch (je) {
      void je;
      throw new Error(
        "Ответ не JSON. Возможно, сессия истекла: обновите страницу и войдите снова."
      );
    }
    if (!r.ok || !data.ok) throw new Error((data && data.error) || String(r.status));

    if (body) body.classList.remove("d-none");

    const title = document.getElementById("up-bn-title");
    if (title) title.textContent = k === "__none__" ? "Без подразделения" : k;
    const sub = document.getElementById("up-bn-sub");
    if (sub) sub.textContent = "Оперативный профиль и история активности";
    const activeRows = data.active_frequencies || [];
    const archiveRows = data.archive_frequencies || [];
    const totalRows = data.total_in_db == null ? 0 : data.total_in_db;
    const lastSeen = archiveRows.reduce(function (latest, row) {
      var value = String((row && row.last_seen) || "");
      return value > latest ? value : latest;
    }, "");
    const totalEl = document.getElementById("up-bn-total");
    const activeTotalEl = document.getElementById("up-bn-active-total");
    const archiveTotalEl = document.getElementById("up-bn-archive-total");
    const lastSeenEl = document.getElementById("up-bn-last-seen");
    const activeCountEl = document.getElementById("up-bn-active-count");
    const parentEl = document.getElementById("up-bn-parent");
    if (totalEl) totalEl.textContent = String(totalRows);
    if (activeTotalEl) activeTotalEl.textContent = String(activeRows.length);
    if (archiveTotalEl) archiveTotalEl.textContent = String(archiveRows.length);
    if (lastSeenEl) lastSeenEl.textContent = _formatBnDate(lastSeen);
    if (activeCountEl) activeCountEl.textContent = String(activeRows.length);
    var parentLabel = String(data.parent_label || "").trim();
    if (parentLabel === k && k.indexOf(" · ") !== -1) {
      parentLabel = k.split(" · ")[0].trim();
    }
    if (parentEl) parentEl.textContent = parentLabel || "Не определена";
    const prof = data.profile || {};
    const hist = document.getElementById("up-bn-history");
    if (hist) {
      const h = String(prof.history || "").trim();
      hist.textContent = h || "Описание не заполнено.";
    }
    const pHero = data.parent_hero;
    if (pHero && typeof pHero === "object" && pHero.mode && pHero.mode !== "default") {
      applyHero(pHero);
    } else {
      applyHero(null);
    }
    const avShow = data.parent_avatar_url || prof.avatar_url;
    _setPatch(document.getElementById("up-bn-patch"), avShow);
    const meta = document.getElementById("up-bn-meta");
    if (meta) {
      meta.innerHTML = "";
      const d0 = document.createElement("div");
      d0.className = "up-meta-line";
      d0.dataset.k = "Note";
      d0.innerHTML = `<span class="up-meta-line__dots" aria-hidden="true"></span><strong class="text-break" style="font-size:0.8rem;">${_esc(
        k
      )}</strong>`;
      meta.appendChild(d0);
    }

    const act = document.getElementById("up-bn-active");
    if (act) {
      act.innerHTML = "";
      const af = activeRows;
      if (!af.length) {
        act.innerHTML = '<span class="text-muted small">Нет активных пар (нет сеансов с привязкой unit.name = этому note).</span>';
      } else {
        for (const row of af) {
          const f = String(row.frequency || "");
          const g = String(row.group || "");
          const n = row.session_count != null ? `${row.session_count} сеанс.` : "";
          _addFreqBtn(act, k, f, g, n);
        }
      }
    }

    const ar = document.getElementById("up-bn-archive");
    if (ar) {
      _renderBattalionArchiveTable(ar, k, archiveRows);
    }
  } catch (e) {
    if (err) {
      err.classList.remove("d-none");
      err.textContent = String((e && e.message) || e);
    }
  } finally {
    clearTimeout(to);
    if (loading) loading.classList.add("d-none");
  }
})();
