


function normalizeServerUrl(u) {
  const s = String(u || "").trim();
  if (!s) return "";
  if (/^https?:\/\//i.test(s)) return s;
  return `http://${s}`;
}

function _itemCacheKey(sessionId, catalogId, cat) {
  const sid = Number(sessionId || 0);
  const cid = Number(catalogId || 0);
  if (cid > 0) return `s:${sid}|c:${cid}`;
  const f = String((cat && cat.frequency) || "").trim();
  const g = String((cat && cat.group_code) || "").trim();
  return `s:${sid}|f:${f}|g:${g}`;
}

function _itemCacheGet(key) {
  if (!key) return null;
  const v = ITEM_OPEN_CACHE.get(String(key));
  return v ? v : null;
}

function _itemCacheSet(key, payload) {
  if (!key || !payload) return;
  ITEM_OPEN_CACHE.set(String(key), payload);
  if (ITEM_OPEN_CACHE.size > ITEM_OPEN_CACHE_MAX) {
    const victims = ITEM_OPEN_CACHE.size - ITEM_OPEN_CACHE_MAX;
    const it = ITEM_OPEN_CACHE.keys();
    for (let i = 0; i < victims; i++) {
      const k = it.next();
      if (k && !k.done) ITEM_OPEN_CACHE.delete(k.value);
    }
  }
}

function _itemCacheClear() {
  ITEM_OPEN_CACHE.clear();
}


let STATE = null;
let ACTIVE_SESSION_ID = 0;
let ACTIVE_ITEM_ID = 0;
let CAN_EDIT = false;
let CAN_EXPORT = false;
let CAN_START = false;
let SAVE_TIMER = null;
let SAVE_CHAIN = Promise.resolve();
let SAVE_CHAIN_ACTIVE = false;
let LAST_SAVED = "";
let ACTIVE_CLOSED = false;
/** Значение #shift-select до смены (для отката при отказе покинуть несохранённое). */
let SHIFT_SELECT_PREV_VALUE = "";
/** Последняя применённая смена из /state (для сброса бланка при смене сессии у всех). */
let PREV_APPLIED_SELECTED_SESSION_ID = 0;
let PREV_ITEMS_MAX_UPDATED_AT = "";
let BLANK_EDIT_ENABLED = false; // Состояние переключателя редактирования бланка
let BLANK_VIEW_MODE = "plain"; // only plain mode is supported
let LOCAL_VIEW_MODE = ""; // локально выбранный режим ("pretty" | "plain")
let CALLSIGNS = [];
let ALL_CALLSIGNS = [];
let EXPANDED_UNITS = new Set(); // Состояние развернутых подразделений
let COLLAPSED_UNITS = new Set(); // Явно свернутые подразделения (чтобы не разворачивать их автоматически)
const GROUPS_SEARCH_STORAGE_KEY = "wp_intercepts_groups_search";
const IX_CATALOG_FAVORITES_MAX = 5;
const IX_CATALOG_STALE_MS = 30 * 24 * 60 * 60 * 1000;
let CATALOG_PREFS = { favorites: [], archived: [] };
let IX_MOBILE_CATALOG_LIST = "main";
let _groupsSearchDebounce = null;
let ACTIVE_CAT = null; // {unit_name, frequency, group_code}

function _ixIsMessengerUi() {
  return !!document.querySelector(".md3-intercepts.ix-messenger-ui");
}

function _tgAvatarHue(seed) {
  let h = 0;
  const s = String(seed || "");
  for (let i = 0; i < s.length; i++) h = (h + s.charCodeAt(i) * 17) % 360;
  return h;
}

function _ixHueFromSeed(seed) {
  return _tgAvatarHue(seed);
}

function syncIxChatHeader() {
  const titleEl = document.getElementById("ix-chat-title");
  const subEl = _ixIsMessengerUi()
    ? document.getElementById("ix-chat-subtitle")
    : document.getElementById("editor-subtitle");
  const avatarEl = document.getElementById("ix-chat-avatar");
  const avatarLetterEl = document.getElementById("ix-chat-avatar-letter");
  if (!titleEl) return;
  if (ACTIVE_CAT && (ACTIVE_CAT.frequency || ACTIVE_CAT.group_code)) {
    const freq = String(ACTIVE_CAT.frequency || "").trim();
    const grp = String(ACTIVE_CAT.group_code || "").trim();
    const unit = String(ACTIVE_CAT.unit_name || "").trim();
    const loc = String(ACTIVE_CAT.location || "").trim();
    if (_ixIsMessengerUi()) {
      titleEl.textContent = [freq, grp].filter(Boolean).join(" ") || unit || "Чат";
      if (subEl) {
        const parts = [unit, loc].filter(Boolean);
        subEl.textContent = parts.length ? parts.join(" · ") : "перехват";
        subEl.hidden = false;
      }
      if (avatarEl && avatarLetterEl) {
        const digits = freq.replace(/\D/g, "");
        const label = (grp || digits.slice(-2) || freq.slice(0, 2) || unit.slice(0, 2) || "?")
          .slice(0, 2)
          .toUpperCase();
        avatarLetterEl.textContent = label;
        const hue = _ixHueFromSeed(`${freq}|${grp}|${unit}`);
        avatarEl.style.background = `linear-gradient(145deg, hsl(${hue} 46% 46%) 0%, hsl(${hue} 52% 36%) 100%)`;
        avatarEl.classList.remove("tg-chat__avatar--empty");
        avatarEl.hidden = false;
      }
    } else {
      titleEl.textContent = unit || "Чат";
    }
  } else {
    titleEl.textContent = "Выберите чат";
    if (subEl && _ixIsMessengerUi()) {
      subEl.textContent = "";
      subEl.hidden = true;
    }
    if (avatarEl && avatarLetterEl) {
      avatarLetterEl.textContent = "";
      avatarEl.classList.add("tg-chat__avatar--empty");
      avatarEl.hidden = true;
      avatarEl.style.background = "";
    }
  }
}

/** Сообщения для оператора: в messenger — полоска под шапкой чата, иначе #intercepts-status. */
function setInterceptsStatus(msg) {
  const text = String(msg || "").trim();
  const legacy = $("intercepts-status");
  if (legacy) legacy.textContent = text;
  const hint = $("ix-intercepts-hint");
  if (hint) {
    hint.textContent = text;
    hint.hidden = !text;
  }
}

let ACTIVE_ASSIGNMENTS = {};
let UNIT_ORDER = [];
let DRAG_UNIT_KEY = "";
let SUGGEST = { open: false, items: [], idx: 0, prefix: "" };
let SUGGEST_INPUT = { open: false, items: [], idx: 0, prefix: "" }; // Для поля ввода радиоперехвата
const CORR_ID_SUGGEST_LS_KEY = "wp_intercept_corr_id_suggest";
let CORR_ID_SUGGEST_ENABLED = true;
let ACTIVE_CATALOG_ID = 0;
let UNIT_MENU_LISTENER_SET = false;
let POLL_TIMER = null;
let POLL_INFLIGHT = false;
let ITEM_LIVE_INFLIGHT = false;
const ITEM_POLL_MS_MIN = 250;
const ITEM_POLL_MS_MAX = 2500;
const ITEM_POLL_MS_FAST = 100;
let ITEM_POLL_MS = ITEM_POLL_MS_MIN;
let ITEM_POLL_UNCHANGED_STREAK = 0;
let STATE_POLL_TIMER = null;
let STATE_POLL_INFLIGHT = false;
const STATE_POLL_MS_MIN = 400;
const STATE_POLL_MS_MAX = 3000;
let STATE_POLL_MS = STATE_POLL_MS_MIN;
let STATE_POLL_UNCHANGED_STREAK = 0;
let LAST_STATE_SIG = "";
let LAST_CATALOG_SIG = "";
let LAST_REMOTE_UPDATED_AT = "";
let LAST_REMOTE_SIG = "";
let HAS_REMOTE_NEW = false;
// Растёт при каждом сохранении и при открытии другого бланка. Ответ опроса,
// заказанный до этого момента, описывает уже неактуальное состояние, и
// применять его нельзя — иначе он вернёт в поле текст до правки.
let ITEM_SYNC_EPOCH = 0;
let ITEM_OPEN_CACHE = new Map(); // key -> /api/intercepts/item payload
const ITEM_OPEN_CACHE_MAX = 180;
let LAST_CATALOG_RENDER_SIG = "";
let OPEN_ITEM_INFLIGHT = false;
let OPEN_ITEM_GEN = 0;
let OPEN_ITEM_TARGET_KEY = "";
let TYPING_TIMER = null;
let LAST_TYPING_SENT = 0;
let IS_TYPING = false;
let LAST_TYPING_HEADER_SENT = "";
let CALLSIGN_LAST_SEEN = {}; // code -> iso datetime (within active freq/group)
let CALLSIGN_LAST_SEEN_KEY = "";
let IX_SIDEBAR_VIEW = "chats";
let IX_CALLSIGN_PROFILE_CODE = "";
let IX_CALLSIGN_PROFILE_EDIT = false;
let IX_CALLSIGN_PROFILE_REF = null;
// Переключатель красивого вида удалён: используем только обычный бланк.
let PREVIEW_HIGHLIGHT_CODE = "";
let AI_PROOFREAD_RESULT = null;
let AI_PROOFREAD_INFLIGHT = false;
let AI_PROOFREAD_DISABLED_UNTIL_RELOAD = false;
/** Авто- и ручная AI-проверка бланка (панель «AI-подсказки») */
const AI_PROOFREAD_ENABLED = false;

// --- Автосохранение (перехваты) ---
// - сразу при новой строке времени
// - через ~200 мс после последнего ввода в бланк (debounce)
// - запасной таймер простоя 15 с
const AUTO_SAVE_DEBOUNCE_MS = 200;
const AUTO_SAVE_IDLE_MS = 15_000;
let AUTO_SAVE_DEBOUNCE_TIMER = null;
let AUTO_SAVE_IDLE_TIMER = null;
/** Автосохранение бланка отключено — только ручное «Сохранить». */
const BLANK_AUTOSAVE_ENABLED = false;

let LAST_TIME_HEADER = "";






