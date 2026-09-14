(function () {
  "use strict";

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }

  function number(value) {
    return Number(value || 0).toLocaleString("ru-RU");
  }

  function formatUnitName(value) {
    return String(value || "")
      .replace(/^__manual_group__:/i, "")
      .replace(/омбр/giu, "ОМБр")
      .replace(/мсб/giu, "МСБ")
      .replace(/мб/giu, "МБ")
      .replace(/бр/giu, "Бр")
      .trim();
  }

  function pluralUnits(n) {
    var abs = Math.abs(Number(n) || 0);
    var mod10 = abs % 10;
    var mod100 = abs % 100;
    if (mod100 >= 11 && mod100 <= 19) return abs + " подразделений";
    if (mod10 === 1) return abs + " подразделение";
    if (mod10 >= 2 && mod10 <= 4) return abs + " подразделения";
    return abs + " подразделений";
  }

  function pluralRecords(n) {
    var val = Number(n) || 0;
    var formatted = number(val);
    var abs = Math.abs(val);
    var mod10 = abs % 10;
    var mod100 = abs % 100;
    if (mod100 >= 11 && mod100 <= 19) return formatted + " записей";
    if (mod10 === 1) return formatted + " запись";
    if (mod10 >= 2 && mod10 <= 4) return formatted + " записи";
    return formatted + " записей";
  }

  function shortChildName(value, fallback) {
    var raw = "";
    var vStr = String(value || "").trim();
    var fStr = String(fallback || "").trim();
    if (vStr && vStr !== "__none__" && vStr !== "Записи") {
      raw = vStr;
    } else if (fStr && fStr !== "Записи") {
      raw = fStr;
    } else if (vStr) {
      raw = vStr;
    } else {
      raw = "Подразделение";
    }
    var text = formatUnitName(raw);
    if (!text || text === "Записи") return "Подразделение";
    var match = text.match(/(?:^|\s)(\d+)\s*(МСБ|МБ|ШБ|БАТ|ББПС|БМП|БОН|ДШБ)(?:\s|$)/iu);
    if (match) {
      return match[1] + " " + match[2].toUpperCase();
    }
    return text;
  }

  function childSubtitle(name, key) {
    var full = (String(key || "") + " " + String(name || "")).toLowerCase();
    var ordinal = String(name || "").match(/^\d+/);
    if (ordinal) {
      if (full.indexOf("шб") !== -1) return ordinal[0] + "-й штурмовой батальон";
      if (full.indexOf("дшб") !== -1) return ordinal[0] + "-й десантно-штурмовой батальон";
      if (full.indexOf("ббпс") !== -1) return ordinal[0] + "-й батальон БПЛА";
      if (full.indexOf("бон") !== -1) return ordinal[0] + "-й батальон опер. назначения";
      if (full.indexOf("бмп") !== -1) return ordinal[0] + "-й батальон морской пехоты";
      if (full.indexOf("мсб") !== -1 || full.indexOf("мб") !== -1) return ordinal[0] + "-й мотострелковый батальон";
      return ordinal[0] + "-е подразделение";
    }
    if (full.indexOf("взвод связи") !== -1) return "Взвод связи";
    if (full.indexOf("развед") !== -1) return "Разведывательное подразделение";
    if (full.indexOf("сухопутн") !== -1) return "Сухопутные войска";
    if (full.indexOf("морск") !== -1) return "Морская пехота";
    return "Формирование";
  }

  function unitSubtitle(name) {
    var normalized = String(name || "").toLowerCase();
    if (normalized.indexOf("омбр") !== -1) return "Отдельная морская бригада";
    if (normalized.indexOf("ошп") !== -1) return "Отдельный штурмовой полк";
    if (normalized.indexOf("ошбр") !== -1) return "Отдельная штурмовая бригада";
    if (normalized.indexOf("мсб") !== -1 || normalized.indexOf("мб") !== -1) return "Мотострелковый батальон";
    if (normalized.indexOf("шб") !== -1) return "Штурмовой батальон";
    if (normalized.indexOf("дшб") !== -1) return "Десантно-штурмовой батальон";
    if (normalized.indexOf("ббпс") !== -1) return "Батальон БПЛА";
    return "Объединённое подразделение";
  }

  function parseDate(value) {
    var match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
    return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : null;
  }

  function shortDate(value) {
    var date = parseDate(value);
    if (!date) return "—";
    var months = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
    return date.getDate() + " " + months[date.getMonth()];
  }

  function weekDay(value) {
    var date = parseDate(value);
    return date ? ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"][date.getDay()] : "";
  }

  function dateTime(value) {
    var text = String(value || "").trim();
    if (!text) return "Дата не указана";
    var parts = text.split(/[T ]/);
    return shortDate(parts[0]) + (parts[1] ? " " + parts[1].slice(0, 5) : "");
  }

  function setText(id, value) {
    var element = document.getElementById(id);
    if (element) element.textContent = value;
  }

  function callLabel(call) {
    if (!call) return "Позывной";
    var label = String(call.label || "Позывной");
    var id = String(call.correspondent_id || call.id || "").trim();
    return id && id !== label ? label + " (" + id + ")" : label;
  }

  function smoothPath(points) {
    if (!points.length) return "";
    var path = "M " + points[0].x + " " + points[0].y;
    for (var index = 1; index < points.length; index += 1) {
      var previous = points[index - 1];
      var current = points[index];
      var middle = (previous.x + current.x) / 2;
      path += " C " + middle + " " + previous.y + ", " + middle + " " + current.y + ", " + current.x + " " + current.y;
    }
    return path;
  }

  function renderHero(data, profile) {
    var hero = profile && profile.hero && typeof profile.hero === "object" ? profile.hero : {};
    var label = String(hero.title || formatUnitName(data.parent_label || (profile && profile.parent_label) || data.parent_key));
    setText("up-ph-title", label || "Подразделение");
    setText("up-ph-sub", hero.subtitle || unitSubtitle(label));
    setText("up2-crumb", label || "Подразделение");
    setText("udash-summary-sessions", number(data.summary && data.summary.sessions));
    setText("udash-summary-correspondents", number(data.summary && (data.summary.correspondents || data.summary.callsigns)));
    setText("udash-summary-callsigns", number(data.summary && data.summary.callsigns));
    var period = data.period || {};
    var periodDays = Number(period.days || 7);
    var sessionsLabel = document.getElementById("udash-summary-sessions-label");
    var correspondentsLabel = document.getElementById("udash-summary-correspondents-label");
    if (sessionsLabel) sessionsLabel.innerHTML = "сеансов<br>за " + periodDays + " дней";
    if (correspondentsLabel) correspondentsLabel.innerHTML = "корреспондентов<br>за " + periodDays + " дней";
    setText("udash-period", shortDate(period.start) + " – " + shortDate(period.end));
    setText("udash-updated", "Обновлено " + dateTime(data.last_updated || period.end));

    var status = document.getElementById("ud-unit-status");
    if (status) {
      var statusText = String(hero.status || "Онлайн");
      var statusLabel = status.querySelector("span");
      if (statusLabel) statusLabel.textContent = statusText;
      status.classList.toggle("is-offline", statusText !== "Онлайн");
    }
    var tagsRoot = document.getElementById("ud-unit-tags");
    if (tagsRoot) {
      var tags = Array.isArray(hero.tags) && hero.tags.length ? hero.tags : ["Сухопутные войска", "Морская пехота", "В/ч неизвестна"];
      tagsRoot.innerHTML = tags.slice(0, 5).map(function (tag) { return "<span>" + esc(tag) + "</span>"; }).join("");
    }
  }

  function renderChart(days) {
    var root = document.getElementById("udash-chart");
    if (!root) return;
    days = Array.isArray(days) ? days : [];
    if (!days.length) {
      root.innerHTML = '<div class="ud-empty">За выбранный период данных нет.</div>';
      return;
    }

    var width = Math.max(480, Math.round(root.clientWidth - 20));
    var height = Math.max(145, Math.round(root.clientHeight - 11));
    var left = 38;
    var right = 16;
    var top = 12;
    var bottom = 39;
    var plotWidth = width - left - right;
    var plotHeight = height - top - bottom;
    var values = [];
    days.forEach(function (item) {
      values.push(Number(item.sessions || 0), Number(item.correspondents || 0));
    });
    var rawMax = Math.max.apply(null, values.concat([1]));
    var step = Math.max(1, Math.ceil(rawMax / 4 / 5) * 5);
    var max = step * 4;
    var x = function (index) { return left + (plotWidth * index / Math.max(days.length - 1, 1)); };
    var y = function (value) { return top + plotHeight - (Number(value || 0) / max * plotHeight); };
    var sessionPoints = days.map(function (item, index) { return { x: x(index), y: y(item.sessions) }; });
    var correspondentPoints = days.map(function (item, index) { return { x: x(index), y: y(item.correspondents) }; });
    var sessionLine = smoothPath(sessionPoints);
    var correspondentLine = smoothPath(correspondentPoints);
    var grid = "";
    for (var tick = 0; tick <= 4; tick += 1) {
      var value = step * (4 - tick);
      var gy = top + plotHeight * tick / 4;
      grid += '<line class="ud-chart-grid" x1="' + left + '" y1="' + gy + '" x2="' + (width - right) + '" y2="' + gy + '"/>';
      grid += '<text class="ud-chart-label" x="' + (left - 8) + '" y="' + (gy + 3) + '" text-anchor="end">' + value + '</text>';
    }
    var labelEvery = days.length <= 7 ? 1 : (days.length <= 14 ? 2 : 5);
    days.forEach(function (item, index) {
      var gx = x(index);
      if (index % labelEvery === 0 || index === days.length - 1) {
        grid += '<line class="ud-chart-grid" x1="' + gx + '" y1="' + top + '" x2="' + gx + '" y2="' + (top + plotHeight) + '" opacity=".7"/>';
        grid += '<text class="ud-chart-label" x="' + gx + '" y="' + (height - 22) + '" text-anchor="middle">' + esc(shortDate(item.date)) + '</text>';
        grid += '<text class="ud-chart-label" x="' + gx + '" y="' + (height - 11) + '" text-anchor="middle">' + esc(weekDay(item.date)) + '</text>';
      }
    });
    var sessionDots = sessionPoints.map(function (point, index) { return '<circle data-chart-index="' + index + '" class="ud-chart-dot-blue" cx="' + point.x + '" cy="' + point.y + '" r="3.5"/>'; }).join("");
    var correspondentDots = correspondentPoints.map(function (point, index) { return '<circle data-chart-index="' + index + '" class="ud-chart-dot-cyan" cx="' + point.x + '" cy="' + point.y + '" r="3.5"/>'; }).join("");
    var hitAreas = days.map(function (_item, index) {
      var startX = index === 0 ? left : (x(index - 1) + x(index)) / 2;
      var endX = index === days.length - 1 ? width - right : (x(index) + x(index + 1)) / 2;
      return '<rect data-chart-index="' + index + '" class="ud-chart-hit" x="' + startX + '" y="' + top + '" width="' + (endX - startX) + '" height="' + plotHeight + '"/>';
    }).join("");
    var base = top + plotHeight;
    var sessionArea = sessionLine + " L " + sessionPoints[sessionPoints.length - 1].x + " " + base + " L " + sessionPoints[0].x + " " + base + " Z";
    var correspondentArea = correspondentLine + " L " + correspondentPoints[correspondentPoints.length - 1].x + " " + base + " L " + correspondentPoints[0].x + " " + base + " Z";
    var last = days[days.length - 1];
    root.innerHTML = '<svg viewBox="0 0 ' + width + " " + height + '" preserveAspectRatio="none" aria-label="График активности радиосети">' +
      '<defs><linearGradient id="ud-blue-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2d83ff" stop-opacity=".31"/><stop offset="1" stop-color="#2d83ff" stop-opacity=".03"/></linearGradient><linearGradient id="ud-cyan-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#10c9c1" stop-opacity=".26"/><stop offset="1" stop-color="#10c9c1" stop-opacity=".03"/></linearGradient></defs>' +
      grid + '<path class="ud-chart-area-blue" d="' + sessionArea + '"/><path class="ud-chart-area-cyan" d="' + correspondentArea + '"/>' +
      '<path class="ud-chart-line-blue" d="' + sessionLine + '"/><path class="ud-chart-line-cyan" d="' + correspondentLine + '"/>' +
      '<line id="ud-chart-guide" class="ud-chart-guide" style="display:none" x1="' + sessionPoints[sessionPoints.length - 1].x + '" y1="' + top + '" x2="' + sessionPoints[sessionPoints.length - 1].x + '" y2="' + base + '"/>' +
      sessionDots + correspondentDots + hitAreas + '</svg>' +
      '<div class="ud-chart-tip" id="ud-chart-tip" hidden><b id="ud-chart-tip-date">' + esc(shortDate(last.date)) + " " + esc(String(last.date || "").slice(0, 4)) + '</b><span><i class="blue"></i>Сеансы: <strong id="ud-chart-tip-sessions">' + number(last.sessions) + '</strong></span><br><span><i class="cyan"></i>Корреспонденты: <strong id="ud-chart-tip-correspondents">' + number(last.correspondents) + '</strong></span></div>' +
      '<div class="ud-chart-legend"><span>Сеансы</span><span>Корреспонденты</span></div>';

    var selectedIndex = -1;
    function selectPoint(index) {
      var item = days[index];
      if (!item || selectedIndex === index) return;
      selectedIndex = index;
      setText("ud-chart-tip-date", shortDate(item.date) + " " + String(item.date || "").slice(0, 4));
      setText("ud-chart-tip-sessions", number(item.sessions));
      setText("ud-chart-tip-correspondents", number(item.correspondents));
      var guide = document.getElementById("ud-chart-guide");
      if (guide) {
        guide.style.display = "";
        guide.setAttribute("x1", x(index));
        guide.setAttribute("x2", x(index));
      }
      var tip = document.getElementById("ud-chart-tip");
      if (tip) {
        tip.hidden = false;
        var percent = 6 + (88 * index / Math.max(days.length - 1, 1));
        tip.style.left = percent + "%";
        tip.style.transform = index > days.length / 2 ? "translateX(-100%)" : "translateX(0)";
      }
    }

    function pointFromEvent(event) {
      var target = event.target && event.target.closest ? event.target.closest("[data-chart-index]") : null;
      if (target) selectPoint(Number(target.getAttribute("data-chart-index")));
    }

    root.onpointermove = pointFromEvent;
    root.onclick = pointFromEvent;
    root.onpointerleave = function () {
      selectedIndex = -1;
      var guide = document.getElementById("ud-chart-guide");
      var tip = document.getElementById("ud-chart-tip");
      if (guide) guide.style.display = "none";
      if (tip) tip.hidden = true;
    };
  }

  function renderStructure(data, profile) {
    var root = document.getElementById("udash-structure");
    if (!root) return;
    var children = (data.children || (profile && profile.children) || []).slice().sort(function (left, right) {
      return shortChildName(left.unit_key, left.label).localeCompare(shortChildName(right.unit_key, right.label), "ru", { numeric: true });
    });
    var total = children.length;
    var parent = formatUnitName(data.parent_label || (profile && profile.parent_label) || data.parent_key);

    var layoutModifier = total <= 1 ? "ud-structure--single" : (total === 2 ? "ud-structure--pair" : "ud-structure--multi");
    root.className = "ud-structure " + layoutModifier + (root.classList.contains("is-expanded") ? " is-expanded" : "");

    var childHtml = children.map(function (child, index) {
      var key = String(child.unit_key || "");
      var name = shortChildName(key, child.label);
      var sub = childSubtitle(name, key);
      var fullName = formatUnitName(key || child.label || name);
      var isExtra = index >= 3;
      return '<a class="ud-structure-child' + (isExtra ? ' ud-structure-child--extra' : '') + '" href="/search-online/battalion?k=' + encodeURIComponent(key) + '" title="' + esc(fullName) + '">' +
        '<div class="ud-structure-child__head">' +
          '<span class="ud-structure-child__badge"><i class="bi bi-shield-shaded"></i></span>' +
          '<i class="bi bi-arrow-up-right ud-structure-child__arrow"></i>' +
        '</div>' +
        '<strong class="ud-structure-child__name">' + esc(name) + '</strong>' +
        '<small class="ud-structure-child__sub">' + esc(sub) + '</small>' +
        (fullName && fullName !== name ? '<em class="ud-structure-full">' + esc(fullName) + '</em>' : '') +
        '<span class="ud-structure-child__count"><i class="bi bi-people"></i> ' + esc(pluralRecords(child.row_count)) + '</span>' +
      '</a>';
    }).join("");

    var moreBarHtml = "";
    if (total > 3) {
      var extraCount = total - 3;
      moreBarHtml = '<button type="button" class="ud-structure-more-bar" id="udash-more-bar">' +
        '<span><i class="bi bi-diagram-3-fill"></i> Ещё ' + esc(pluralUnits(extraCount)) + ' в составе</span>' +
        '<span class="ud-structure-more-action">Показать все (' + total + ') <i class="bi bi-chevron-down"></i></span>' +
      '</button>';
    }

    root.innerHTML = '<div class="ud-structure-parent">' +
        '<div class="ud-structure-emblem"><i class="bi bi-shield-shaded"></i></div>' +
        '<div>' +
          '<strong>' + esc(parent) + '</strong>' +
          '<small>' + esc(unitSubtitle(parent)) + '</small>' +
          '<span class="ud-structure-count">' + esc(pluralUnits(total)) + '</span>' +
        '</div>' +
      '</div>' +
      '<div class="ud-structure-children">' + (childHtml || '<div class="ud-structure-empty text-muted">Нет привязанных подразделений</div>') + '</div>' +
      moreBarHtml;

    var expand = document.getElementById("udash-expand-structure");
    function updateExpandBtn() {
      var isExp = root.classList.contains("is-expanded");
      if (expand) {
        if (isExp) {
          expand.textContent = "Свернуть";
        } else {
          expand.textContent = total > 3 ? "Развернуть все (" + total + ")" : "Развернуть все";
        }
      }
    }
    updateExpandBtn();

    if (expand) {
      expand.onclick = function () {
        root.classList.toggle("is-expanded");
        updateExpandBtn();
      };
    }

    var moreBar = document.getElementById("udash-more-bar");
    if (moreBar) {
      moreBar.onclick = function () {
        root.classList.add("is-expanded");
        updateExpandBtn();
      };
    }
  }

  function detailMeta(call) {
    var intercept = call && call.last_intercept;
    if (!intercept) return '<div><i class="bi bi-info-circle"></i>Сообщений в перехватах не найдено</div>';
    return '<div><i class="bi bi-calendar3"></i>' + esc(dateTime(intercept.updated_at)) + '</div>' +
      '<div><i class="bi bi-soundwave"></i>Частота: ' + esc(intercept.frequency || call.frequency || "—") + ' МГц</div>' +
      '<div><i class="bi bi-people"></i>Группа: ' + esc(intercept.group || call.group || "—") + '</div>';
  }

  function showCallDetail(call) {
    if (!call) return;
    setText("udash-call-title", callLabel(call));
    setText("udash-call-sessions", number(call.sessions));
    setText("udash-call-correspondent-id", call.correspondent_id || call.id || "—");
    setText("udash-call-text", call.last_intercept && call.last_intercept.content ? call.last_intercept.content : "Для этого позывного последнее сообщение не найдено.");
    var meta = document.getElementById("udash-call-meta");
    if (meta) meta.innerHTML = detailMeta(call);
    document.querySelectorAll(".ud-call-row").forEach(function (row) {
      row.classList.toggle("is-selected", row.getAttribute("data-call-id") === String(call.id));
    });
  }

  function renderCalls(callsigns, periodDays) {
    var root = document.getElementById("udash-calls");
    var allButton = document.getElementById("udash-all-calls");
    if (!root) return;
    callsigns = Array.isArray(callsigns) ? callsigns.slice().sort(function (left, right) {
      return Number(right.sessions || 0) - Number(left.sessions || 0) || String(left.label || left.id).localeCompare(String(right.label || right.id), "ru");
    }) : [];
    if (!callsigns.length) {
      root.innerHTML = '<div class="ud-empty">Активные позывные не найдены.</div>';
      return;
    }
    var expanded = false;
    function draw() {
      var visible = expanded ? callsigns : callsigns.slice(0, 10);
      var maxSessions = Math.max.apply(null, callsigns.map(function (item) { return Number(item.sessions || 0); }).concat([1]));
      root.innerHTML = '<div class="ud-call-head"><span>#</span><span>Позывной</span><span>Сеансов за ' + periodDays + ' дней</span><span>ID корреспондента</span></div>' + visible.map(function (item, index) {
        var sessions = Number(item.sessions || 0);
        return '<div class="ud-call-row" role="button" tabindex="0" data-call-id="' + esc(item.id) + '"><span>' + (index + 1) + '</span><strong>' + esc(item.label || item.id) + '</strong>' +
          '<span class="ud-bar-cell"><span class="ud-meter"><i style="width:' + Math.max(5, Math.round(sessions / maxSessions * 100)) + '%"></i></span><b>' + number(sessions) + '</b></span>' +
          '<span class="ud-correspondent-id">' + esc(item.correspondent_id || item.id || "—") + '</span></div>';
      }).join("");
      if (allButton) allButton.textContent = expanded ? "Топ-10" : "Все позывные";
    }
    function select(event) {
      var row = event.target.closest(".ud-call-row");
      if (!row) return;
      var call = callsigns.filter(function (item) { return String(item.id) === row.getAttribute("data-call-id"); })[0];
      showCallDetail(call);
    }
    root.onclick = select;
    root.onkeydown = function (event) {
      if (event.key === "Enter" || event.key === " ") select(event);
    };
    if (allButton) allButton.onclick = function () { expanded = !expanded; draw(); showCallDetail(callsigns[0]); };
    var close = document.getElementById("udash-call-close");
    if (close) close.onclick = function () {
      setText("udash-call-title", "Позывной");
      setText("udash-call-sessions", "0");
      setText("udash-call-correspondent-id", "—");
      setText("udash-call-text", "Выберите позывной в таблице слева.");
      var meta = document.getElementById("udash-call-meta");
      if (meta) meta.innerHTML = "";
      document.querySelectorAll(".ud-call-row").forEach(function (row) { row.classList.remove("is-selected"); });
    };
    draw();
    showCallDetail(callsigns[0]);
  }

  function renderFrequencies(frequencies) {
    var root = document.getElementById("udash-frequencies");
    if (!root) return;
    frequencies = Array.isArray(frequencies) ? frequencies.slice().sort(function (left, right) {
      return Number.parseFloat(left.frequency) - Number.parseFloat(right.frequency);
    }).slice(0, 10) : [];
    if (!frequencies.length) {
      root.innerHTML = '<div class="ud-empty">Частоты не найдены.</div>';
      return;
    }
    var max = Math.max.apply(null, frequencies.map(function (item) { return Number(item.sessions || 0); }).concat([1]));
    root.innerHTML = '<div class="ud-freq-head"><span>Частота, МГц</span><span>Рабочая группа</span><span>Сеансов</span><span></span></div>' + frequencies.map(function (item) {
      var sessions = Number(item.sessions || 0);
      return '<div class="ud-freq-row"><strong>' + esc(item.frequency) + '</strong><span>Группа ' + esc(item.group) + '</span><b>' + number(sessions) + '</b><span class="ud-meter"><i style="width:' + Math.max(5, Math.round(sessions / max * 100)) + '%"></i></span></div>';
    }).join("");
  }

  function render(data, profile) {
    var periodDays = Number(data.period && data.period.days || 7);
    renderHero(data, profile);
    renderChart(data.days);
    renderStructure(data, profile);
    renderCalls(data.callsigns, periodDays);
    renderFrequencies(data.frequencies);
    setText("udash-call-sessions-label", "Сеансов за " + periodDays + " дней");
  }

  var parentKey = window.__UP_PARENT_P__;
  if (!parentKey) return;
  var profile = null;
  var dashboardData = null;
  var requestController = null;
  var profilePromise = window.__UP_PROFILE_PROMISE__ || fetch("/api/online-search/unit-parent?p=" + encodeURIComponent(parentKey), { credentials: "same-origin" })
    .then(function (response) { return response.json().then(function (data) { return { response: response, data: data }; }); });
  window.__UP_PROFILE_PROMISE__ = profilePromise;

  profilePromise.then(function (result) {
    profile = result && result.data && result.data.ok ? result.data : null;
    if (dashboardData) renderHero(dashboardData, profile);
  }).catch(function () { profile = null; });

  function setBusy(busy) {
    var workspace = document.getElementById("up-dashboard");
    if (workspace) workspace.setAttribute("aria-busy", busy ? "true" : "false");
  }

  function loadDashboard(days) {
    if (requestController) requestController.abort();
    requestController = new AbortController();
    setBusy(true);
    return fetch("/api/online-search/unit-dashboard?p=" + encodeURIComponent(parentKey) + "&days=" + days, {
      credentials: "same-origin",
      signal: requestController.signal
    }).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    }).then(function (data) {
      if (!data || !data.ok) throw new Error((data && data.error) || "Не удалось загрузить аналитику");
      dashboardData = data;
      render(data, profile);
      document.querySelectorAll("#udash-period-select, #udash-frequency-period-select").forEach(function (select) {
        select.value = String(days);
      });
    }).catch(function (error) {
      if (error && error.name === "AbortError") return;
      var chart = document.getElementById("udash-chart");
      if (chart) chart.innerHTML = '<div class="ud-empty">Не удалось загрузить аналитику подразделения.</div>';
    }).finally(function () { setBusy(false); });
  }

  document.querySelectorAll("#udash-period-select, #udash-frequency-period-select").forEach(function (select) {
    select.addEventListener("change", function () { loadDashboard(Number(select.value || 7)); });
  });
  window.addEventListener("unit-profile-updated", function (event) {
    if (!event.detail) return;
    profile = { ...(profile || {}), hero: event.detail.hero || null, parent_label: event.detail.defaultTitle || (profile && profile.parent_label) };
    if (dashboardData) renderHero(dashboardData, profile);
  });
  loadDashboard(7);
})();
