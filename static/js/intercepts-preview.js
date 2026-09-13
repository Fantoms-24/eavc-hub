(function () {
  "use strict";

function _callsignByCode(code) {
  const c = _normalizeCallsignCode(code);
  if (!c) return null;
  const all = Array.isArray(ALL_CALLSIGNS) ? ALL_CALLSIGNS : [];
  const matches = all.filter((x) => _normalizeCallsignCode(x && x.code) === c);
  if (!matches.length) return null;
  if (ACTIVE_CAT) {
    const af = String(ACTIVE_CAT.frequency || "").trim();
    const ag = String(ACTIVE_CAT.group_code || "").trim();
    // Активная частота+группа: только запись этой пары, без чужой группы.
    if (af && ag) {
      return (
        matches.find(
          (x) =>
            String(x.frequency || "").trim() === af &&
            String(x.group_code || "").trim() === ag
        ) || null
      );
    }
  }
  return matches[0];
}

function _callsignInsertText(code) {
  const c = String(code || "").trim();
  if (!c) return "";
  return `(${c})`;
}

function insertCallsignAtCursor(code, textareaId = "intercept-text") {
  const text = _callsignInsertText(code);
  if (!text) return;
  insertAtCursor(text, textareaId);
}

function _hashInt(s) {
  // small deterministic hash (for coloring)
  const str = String(s || "");
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0);
}

function _hslToRgb(h, s, l) {
  // h: 0..360, s/l: 0..100 -> [r,g,b] 0..255
  let hh = ((Number(h) || 0) % 360 + 360) % 360;
  let ss = Math.max(0, Math.min(100, Number(s) || 0)) / 100;
  let ll = Math.max(0, Math.min(100, Number(l) || 0)) / 100;

  const c = (1 - Math.abs(2 * ll - 1)) * ss;
  const x = c * (1 - Math.abs(((hh / 60) % 2) - 1));
  const m = ll - c / 2;

  let r1 = 0, g1 = 0, b1 = 0;
  if (hh < 60) { r1 = c; g1 = x; b1 = 0; }
  else if (hh < 120) { r1 = x; g1 = c; b1 = 0; }
  else if (hh < 180) { r1 = 0; g1 = c; b1 = x; }
  else if (hh < 240) { r1 = 0; g1 = x; b1 = c; }
  else if (hh < 300) { r1 = x; g1 = 0; b1 = c; }
  else { r1 = c; g1 = 0; b1 = x; }

  const r = Math.round((r1 + m) * 255);
  const g = Math.round((g1 + m) * 255);
  const b = Math.round((b1 + m) * 255);
  return [r, g, b];
}

function _normalizeCorrespondentId(raw) {
  const s = String(raw ?? "").trim();
  if (!s) return "";
  const m = s.match(/^FR[_-]?(.+)$/i);
  if (m) return String(m[1] || "").trim();
  return s;
}

function _correspondentIdFromItem(item) {
  if (!item) return "";
  const raw = item.correspondent_id != null
    ? item.correspondent_id
    : (item.id != null ? item.id : "");
  return _normalizeCorrespondentId(raw);
}

function _correspondentIdFromSegment(seg) {
  if (!seg) return "";
  return _correspondentIdFromItem(seg.item || seg);
}


function _colorForCode(code) {
  const c = String(code || "").trim();
  const h = _hashInt(c);
  const hue = h % 360;
  // Разводим насыщенность/яркость по битам хеша — иначе разные ID часто
  // попадают в один hue (% 360) и выглядят одинаково на дорожке.
  const satBg = 58 + ((h >>> 8) & 0x7f) % 30;
  const lightBg = 86 + ((h >>> 16) & 0x3f) % 9;
  const satLine = 55 + ((h >>> 22) & 0x3f) % 25;
  const lightLine = 34 + ((h >>> 28) & 0x3f) % 20;
  const [br, bg, bb] = _hslToRgb(hue, satBg, lightBg);
  const [lr, lg, lb] = _hslToRgb(hue, satLine, lightLine);
  const toHex = (r, g, b) => "#" + [r, g, b].map((x) => Math.round(x).toString(16).padStart(2, "0")).join("");
  return {
    bg: `rgb(${br}, ${bg}, ${bb})`,
    border: `rgb(${lr}, ${lg}, ${lb})`,
    borderHex: toHex(lr, lg, lb),
    text: "#111827",
    line: `rgba(${lr}, ${lg}, ${lb}, 0.55)`,
  };
}


function _contentSig(updatedAt, content) {
  const c = String(content || "");
  const head = c.slice(0, 64);
  const tail = c.slice(-64);
  return `${String(updatedAt || "")}|${c.length}|${head}|${tail}`;
}

function _appendTextWithIdBadges(container, msgText) {
  const s = String(msgText || "");
  const re = /\((\d{1,10})\)/g;
  // Не выделяем цветом ID в самом конце строки (частый кейс: "... (123)")
  // Оставляем его обычным текстом.
  const endMatch = s.match(/\((\d{1,10})\)\s*$/);
  const endStart = endMatch ? (s.lastIndexOf(endMatch[0])) : -1;

  let last = 0;
  let m;
  while ((m = re.exec(s)) !== null) {
    const start = m.index;
    const end = start + m[0].length;
    if (start > last) container.appendChild(document.createTextNode(s.slice(last, start)));
    const code = String(m[1] || "");

    // Если это самый последний "(ID)" в конце строки — выводим как обычный текст без бейджа/клика.
    if (endStart !== -1 && start === endStart) {
      container.appendChild(document.createTextNode(s.slice(start, end)));
      last = end;
      continue;
    }

    const wrap = document.createElement("span");
    wrap.className = "ip-id-row";

    const span = document.createElement("span");
    span.className = "ip-id";
    span.dataset.code = code;
    span.textContent = `(${code})`;
    const col = _colorForCode(code);
    span.style.background = col.bg;
    span.style.borderColor = col.border;
    span.style.color = col.text;
    if (PREVIEW_HIGHLIGHT_CODE && code === PREVIEW_HIGHLIGHT_CODE) {
      span.classList.add("ip-active");
    }
    span.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      PREVIEW_HIGHLIGHT_CODE = (PREVIEW_HIGHLIGHT_CODE === code) ? "" : code;
      _renderPreview();
    });
    wrap.appendChild(span);

    const cs = _callsignByCode(code);
    const csLabel = String((cs && cs.label) || "").trim() || "н/у";
    const csTag = String((cs && cs.tag) || "").trim();
    const chip = document.createElement("span");
    chip.className = "ip-callsign-chip";
    if (csTag) {
      chip.textContent = `${csLabel} • ${csTag}`;
    } else {
      chip.textContent = csLabel;
    }
    chip.title = csLabel === "н/у"
      ? "Позывной не указан"
      : (cs && cs.tag_desc ? `${csLabel}\n${String(cs.tag_desc).trim()}` : csLabel);
    wrap.appendChild(chip);

    container.appendChild(wrap);
    const knownLabel = String((cs && cs.label) || "").trim().toLowerCase();
    const tail = s.slice(end);
    const tailMatch = tail.match(/^(\s*-\s*)([^\n\r()]+)/);
    if (knownLabel && tailMatch) {
      const sep = String(tailMatch[1] || "");
      const rawLabel = String(tailMatch[2] || "");
      const cmp = rawLabel.trim().toLowerCase();
      if (cmp.startsWith(knownLabel)) {
        container.appendChild(document.createTextNode(sep));
        const strong = document.createElement("strong");
        strong.className = "ip-callsign-label-strong";
        strong.textContent = rawLabel.trim();
        container.appendChild(strong);
        last = end + tailMatch[0].length;
        continue;
      }
    }
    last = end;
  }
  if (last < s.length) container.appendChild(document.createTextNode(s.slice(last)));
}

function _normalizeTimeLike(s) {
  const v = String(s || "").trim();
  const m = v.match(/^(\d{1,2})[.:](\d{2})$/);
  if (!m) return "";
  const hh = String(Math.max(0, Math.min(23, Number(m[1]) || 0))).padStart(2, "0");
  const mm = String(Math.max(0, Math.min(59, Number(m[2]) || 0))).padStart(2, "0");
  return `${hh}.${mm}`;
}

function _extractUniqueCallsignCodesFromText(text) {
  const src = String(text || "");
  const re = /\((\d{1,10})\)/g;
  const out = [];
  const seen = new Set();
  let m;
  while ((m = re.exec(src)) !== null) {
    const code = String(m[1] || "").trim();
    if (!code || seen.has(code)) continue;
    seen.add(code);
    out.push(code);
  }
  return out;
}

function _decorateCallsignCodesInText(text) {
  // Раньше сюда подставлялось " (код) - позывной" для plain-режима; позывной хранится
  // только в справочнике и показывается в превью (чипы), в сохраняемый текст не пишем.
  return String(text || "");
}

function _applyCallsignDecorationsInPlain(textarea) {
  const ta = textarea || $("intercept-text");
  if (!ta) return;
  if (BLANK_VIEW_MODE !== "plain") return;
  const oldText = String(ta.value || "");
  const oldPos = Number(ta.selectionStart || 0);
  const nextText = _decorateCallsignCodesInText(oldText);
  if (nextText === oldText) return;
  const oldBefore = oldText.slice(0, oldPos);
  const nextBefore = _decorateCallsignCodesInText(oldBefore);
  ta.value = nextText;
  const newPos = Math.max(0, Math.min(nextText.length, nextBefore.length));
  try {
    ta.setSelectionRange(newPos, newPos);
  } catch (_) { }
}


  window._colorForCode = _colorForCode;
  window._contentSig = _contentSig;
  window._callsignByCode = _callsignByCode;
  window.insertCallsignAtCursor = insertCallsignAtCursor;
  window._appendTextWithIdBadges = _appendTextWithIdBadges;
  window._applyCallsignDecorationsInPlain = _applyCallsignDecorationsInPlain;
  window._normalizeTimeLike = _normalizeTimeLike;
  window._extractUniqueCallsignCodesFromText = _extractUniqueCallsignCodesFromText;
  window._decorateCallsignCodesInText = _decorateCallsignCodesInText;
})();
