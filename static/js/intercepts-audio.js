function _audioItemFromSegOrItem(segOrItem) {
  if (!segOrItem) return null;
  return segOrItem.item || segOrItem;
}

/** Декод [+] прошёл, но речи нет — шум/помехи. */
function _audioSegmentIsNoise(segOrItem) {
  const item = _audioItemFromSegOrItem(segOrItem);
  if (!item) return false;
  return !!item.has_key && !item.has_message;
}

/** Колонка «Сообщ.»: речь — Message; декод [+] без речи — Message (шум). */
function _audioMessageLabel(item) {
  if (!item) return "";
  if (item.has_message) return "Message";
  if (item.has_key) return "Message (шум)";
  return "";
}

function _audioGroupMessageLabel(items) {
  if (!Array.isArray(items) || !items.length) return "";
  const rows = items.map((x) => _audioItemFromSegOrItem(x.seg));
  const keyed = rows.filter((it) => !!it && !!it.has_key);
  if (!keyed.length) return "";
  const speechN = keyed.filter((it) => !!it.has_message).length;
  const noiseN = keyed.length - speechN;
  if (speechN > 0 && noiseN > 0) return "Message (частично шум)";
  if (speechN > 0) return "Message";
  return "Message (шум)";
}
function _audioSegmentIndexAtTime(t) {
  const list = AUDIO_SEGMENTS;
  if (!list.length) return -1;
  const time = Math.max(0, Number(t) || 0);
  const total = Number(AUDIO_WAVE_DURATION) || 0;
  for (let i = 0; i < list.length; i++) {
    const seg = list[i];
    const start = Number(seg.startSec) || 0;
    const end = start + (Number(seg.duration) || 0);
    const isLast = i === list.length - 1;
    if (time >= start && (time < end || (isLast && time <= total + 0.05))) {
      return i;
    }
  }
  if (total > 0 && time >= total) return list.length - 1;
  return -1;
}

function _segmentTimeRange(idx) {
  const seg = AUDIO_SEGMENTS[idx];
  if (!seg) return null;
  const start = Math.max(0, Number(seg.startSec) || 0);
  const end = Math.min(
    AUDIO_WAVE_DURATION || Infinity,
    start + Math.max(0.05, Number(seg.duration) || 0)
  );
  return { start, end: Math.max(start + 0.05, end) };
}

function _applyAudioSelectionRange(start, end, enableLoop) {
  const s0 = Math.max(0, Math.min(start, end));
  const s1 = Math.max(s0 + 0.05, Math.max(start, end));
  AUDIO_SELECTION = { start: s0, end: s1 };
  if (enableLoop) {
    AUDIO_LOOP_SEGMENT = true;
    const { loopSegToggle } = _audioEls();
    if (loopSegToggle) loopSegToggle.checked = true;
  }
}

function _setAudioAutoSegmentLoop(idx, opts = {}) {
  const range = _segmentTimeRange(idx);
  if (!range) return false;
  AUDIO_AUTO_LOOP_SEGMENT = true;
  _applyAudioSelectionRange(range.start, range.end, true);
  AUDIO_LAST_SEG_IDX = -1;
  AUDIO_PLAYHEAD_TIME = range.start;
  setCurrentAudioIndex(idx, {
    autoplay: opts.autoplay !== false,
    seek: true,
    openCatalog: false,
  });
  _syncAudioSegmentRailActive(false);
  _scheduleWaveformOverlay();
  return true;
}

function _clearAudioAutoSegmentLoop() {
  if (!AUDIO_AUTO_LOOP_SEGMENT) return;
  AUDIO_AUTO_LOOP_SEGMENT = false;
  AUDIO_SELECTION = null;
  AUDIO_LOOP_SEGMENT = false;
  const { loopSegToggle } = _audioEls();
  if (loopSegToggle) loopSegToggle.checked = false;
  _syncAudioSegmentRailActive(false);
}

function _seekToAudioSegment(idx, opts = {}) {
  const { loopSegToggle } = _audioEls();
  if (!AUDIO_SEGMENTS.length) {
    setCurrentAudioIndex(idx, opts);
    return;
  }
  const nextIdx = Math.max(0, Math.min(idx, AUDIO_SEGMENTS.length - 1));
  const range = _segmentTimeRange(nextIdx);
  if (!range) return;
  if (AUDIO_LOOP_SEGMENT || (loopSegToggle && loopSegToggle.checked)) {
    _applyAudioSelectionRange(range.start, range.end, true);
  } else {
    AUDIO_SELECTION = null;
  }
  AUDIO_LAST_SEG_IDX = -1;
  AUDIO_PLAYHEAD_TIME = range.start;
  setCurrentAudioIndex(nextIdx, {
    autoplay: !!opts.autoplay,
    seek: opts.seek !== false,
    openCatalog: opts.openCatalog === true,
  });
}

function _syncAudioPlayheadSegment(t) {
  if (!AUDIO_SEGMENTS.length) return;
  const segIdx = _audioSegmentIndexAtTime(t);
  if (segIdx < 0) return;
  const seg = AUDIO_SEGMENTS[segIdx];
  const start = Number(seg.startSec) || 0;
  const end = start + (Number(seg.duration) || 0);
  if (AUDIO_LOOP_SEGMENT && AUDIO_SELECTION && AUDIO_WAVE_DURATION) {
    const s0 = Math.min(AUDIO_SELECTION.start, AUDIO_SELECTION.end);
    const s1 = Math.max(AUDIO_SELECTION.start, AUDIO_SELECTION.end);
    if (t < s0 || t >= s1) {
      const { audio } = _audioEls();
      if (audio) {
        try { audio.currentTime = Math.max(0, s0 + 0.01); } catch (_) { }
      }
      return;
    }
  } else if (AUDIO_LOOP_SEGMENT && !AUDIO_SELECTION && t >= end) {
    const { audio } = _audioEls();
    if (audio) {
      try { audio.currentTime = Math.max(0, start + 0.01); } catch (_) { }
    }
    return;
  }
  if (segIdx === AUDIO_LAST_SEG_IDX) {
    _syncAudioSegmentRailActive(false);
    return;
  }
  AUDIO_LAST_SEG_IDX = segIdx;
  AUDIO_CURRENT_INDEX = segIdx;
  const item = seg.item || seg;
  updateAudioMeta(item);
  _syncAudioSegmentRailActive(false);
  highlightCurrentSpeaker(_correspondentIdFromItem(item));
  setListeningFileKey(item);
}
// --- Аудиоперехваты ---
const INTERCEPTS_AUDIO_FOLDER_KEY = "wp_intercepts_audio_folder_path";
const AUDIO_TASKS_ONLY_KEY = "wp_intercepts_audio_tasks_only";
const AUDIO_SPEED_KEY = "wp_intercepts_audio_speed";
const AUDIO_LOOP_KEY = "wp_intercepts_audio_loop";
const AUDIO_LOOP_SEG_KEY = "wp_intercepts_audio_loop_seg";
const AUDIO_FILTER_ID_KEY = "wp_intercepts_audio_filter_id";
const AUDIO_LAST_TIME_KEY = "wp_intercepts_audio_last_time";
const AUDIO_SPEECH_RULES_VER = "7";
const AUDIO_SPEECH_RULES_KEY = "wp_audio_speech_rules_ver";
const AUDIO_LAYOUT_MODE_KEY = "wp_intercepts_audio_layout";
const AUDIO_REFRESH_MS = 3000; // сетевые Z:\: слишком частый опрос даёт таймауты
const AUDIO_REFRESH_HIDDEN_MS = 10000; // скрытая вкладка — реже, чтобы не грузить сервер
const AUDIO_REFRESH_BACKOFF_MS_MAX = 30000;
let AUDIO_LAYOUT_MODE = "dmr"; // dmr | bundle (Отложка / готовая папка)
const AUDIO_REFRESH_RECOVER_MS = 2500; // watchdog для восстановления цепочки после скрытой вкладки/свернутого окна
const AUDIO_PRESENCE_POLL_MS = 5000; // «кто слушает» — отдельно от тяжёлого сканирования папки
// Уникальный id этой вкладки/компьютера: позволяет видеть «слушает» даже при
// одинаковом логине на разных компьютерах (сервер исключает только этот client_id).
const AUDIO_CLIENT_ID = (() => {
  try {
    let v = sessionStorage.getItem("wp_audio_client_id");
    if (!v) {
      v = `c-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
      sessionStorage.setItem("wp_audio_client_id", v);
    }
    return v;
  } catch (_) {
    return `c-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  }
})();
let AUDIO_QUEUE = [];
let AUDIO_QUEUE_MAP = new Map();
let AUDIO_QUEUE_PENDING = [];
let AUDIO_QUEUE_PENDING_KEYS = new Set();
let AUDIO_QUEUE_REVEAL_TIMER = null;
let AUDIO_TASKS = [];
let AUDIO_CURRENT_INDEX = -1;
let AUDIO_REFRESH_TIMER = null;
let AUDIO_REFRESH_SCHEDULED = null; // setTimeout для следующего обновления (ровно 20 с после окончания текущего)
let AUDIO_REFRESH_INFLIGHT = false;
let AUDIO_REFRESH_STARTED_AT = 0;
let AUDIO_REFRESH_BACKOFF_MS = 0;
let AUDIO_SEGMENTS = [];
let AUDIO_QUEUE_SIG = "";
let AUDIO_LAST_SEG_IDX = -1;
let AUDIO_LISTENED_LOCAL = new Set();
let AUDIO_FILTER_ID = "";
let AUDIO_LOOP_SEGMENT = false;
let AUDIO_SELECTION = null; // {start: number, end: number}
let AUDIO_AUTO_LOOP_SEGMENT = false;
let AUDIO_WAVE_DURATION = 0;
let AUDIO_WAVE_BUFFER = null;
let AUDIO_GROUP_EXPANDED = new Set();
let AUDIO_SCAN_CATALOG = [];
let AUDIO_BUNDLE_GROUP_SEL = {};
let AUDIO_BUNDLE_NEW_KEYS = new Set();
let AUDIO_BUNDLE_FILTER_APPLIED = false;
let AUDIO_QUEUE_TIME_SORT = "desc";
const AUDIO_BUNDLE_GROUP_SEL_KEY = "wp_audio_bundle_group_sel_v2";
const AUDIO_TIME_SORT_KEY = "wp_audio_queue_time_sort";
let AUDIO_PAIR_FILTER = null; // {frequency, group}
let AUDIO_CURRENT_GROUP_KEY = ""; // ключ группы времени для открытой комбинированной дорожки
let AUDIO_LISTENING_KEY = "";
let AUDIO_LISTENING_TIMER = null;
let AUDIO_PRESENCE_POLL_TIMER = null;
let AUDIO_PRESENCE_POLL_INFLIGHT = false;
let AUDIO_PLAYHEAD_TIME = 0;
let AUDIO_WAVE_BASE_CANVAS = null;
let AUDIO_WAVE_BASE_CTX = null;
let AUDIO_WAVE_DRAW_PENDING = false;
let AUDIO_QUEUE_STICK_BOTTOM = true;
let AUDIO_LAST_TIME_TS = 0;
let AUDIO_TASKS_ONLY_PREF = null;
let AUDIO_STATE_SAVE_TIMER = null;
let AUDIO_STATE_CACHE = { folder_path: "", tasks_only: false, last_time_ts: 0 };
let AUDIO_TASKS_RUNNING = true;
let AUDIO_LAST_REFRESH_OK = 0;
let AUDIO_LAST_SCAN_WALL_TS = 0;
let AUDIO_IS_COMBINED_TRACK = false; // один общий блоб по группе — по окончании не переходить на «следующий» сегмент
let AUDIO_CATALOG_OPEN_REQ = 0;
let ASR_CURRENT_ITEM = null;
let ASR_LAST_TRANSCRIPT = null;
const ASR_UI_ENABLED = false;
let ASR_TRAINING_POLICY = {
  training_enabled: false,
  learn_on_blank_send: true,
  learn_on_feedback: true,
};
let ASR_BOOTSTRAP_TIMER = null;
let ASR_PENDING_JOB_ID = 0;
let ASR_BACKGROUND_POLL_TIMER = null;
let ASR_TRANSCRIBE_SEQ = 0;

function _audioEls() {
  return {
    audio: $("intercepts-audio"),
    list: $("audio-queue-list"),
    status: $("audio-queue-status"),
    meta: $("audio-current-meta"),
    folderInput: $("audio-folder-path"),
    folderStatus: $("audio-folder-status"),
    tasksOnly: $("audio-tasks-only"),
    tasksRunToggle: $("audio-tasks-run"),
    playBtn: $("audio-play-btn"),
    prevBtn: $("audio-prev-btn"),
    nextBtn: $("audio-next-btn"),
    refreshBtn: $("audio-refresh-btn"),
    refreshFullBtn: $("audio-refresh-full-btn"),
    downloadBtn: $("audio-download-btn"),
    speedSelect: $("audio-speed"),
    loopToggle: $("audio-loop"),
    loopSegToggle: $("audio-loop-seg"),
    filterId: $("audio-filter-id"),
    filterClear: $("audio-filter-clear"),
    queueBody: $("audio-queue-body"),
    taskFreq: $("audio-task-frequency"),
    taskName: $("audio-task-name"),
    taskAddBtn: $("audio-task-add-btn"),
    taskList: $("audio-task-list"),
    taskFromActiveBtn: $("audio-task-from-active-btn"),
    waveform: $("audio-waveform"),
    debugBtn: $("audio-debug-btn"),
    debugOut: $("audio-debug-out"),
    asrStatusRefreshBtn: $("asr-status-refresh-btn"),
    asrModelActive: $("asr-model-active"),
    asrModelMetrics: $("asr-model-metrics"),
    asrDiagnostics: $("asr-diagnostics"),
    asrModelRuns: $("asr-model-runs"),
    asrModelSelect: $("asr-model-select"),
    asrModelActivateBtn: $("asr-model-activate-btn"),
    asrWhisperModel: $("asr-whisper-model"),
    asrEpochs: $("asr-epochs"),
    asrBatchSize: $("asr-batch-size"),
    asrLearningRate: $("asr-learning-rate"),
    asrMinAlign: $("asr-min-align"),
    asrRetrainMin: $("asr-retrain-min"),
    asrAutoActivate: $("asr-auto-activate"),
    asrAutoRetrain: $("asr-auto-retrain"),
    asrSettingsSaveBtn: $("asr-settings-save-btn"),
    asrDatasetBuildBtn: $("asr-dataset-build-btn"),
    asrTrainBtn: $("asr-train-btn"),
    asrCurrentStatus: $("asr-current-status"),
    asrTranscriptRu: $("asr-transcript-ru"),
    asrTranscriptUa: $("asr-transcript-ua"),
    asrTranscriptMeta: $("asr-transcript-meta"),
    asrTranscribeBtn: $("asr-transcribe-btn"),
    asrFeedbackOkBtn: $("asr-feedback-ok-btn"),
    asrFeedbackFixBtn: $("asr-feedback-fix-btn"),
    asrBootstrapStatus: $("asr-bootstrap-status"),
    asrSendToInputBtn: $("asr-send-to-input-btn"),
    audioAsrHintWrap: $("audio-asr-hint-wrap"),
    audioAsrHintText: $("audio-asr-hint-text"),
    audioAsrHintStatus: $("audio-asr-hint-status"),
    audioAsrHintSendBtn: $("audio-asr-send-btn"),
  };
}

function _audioSortKey(item) {
  const recordedAt = String(item.recorded_at || "").trim();
  const orderIdx = Number(item.order_index || 0);
  const rel = String(item.file_rel || "");
  return `${recordedAt}|${String(orderIdx).padStart(6, "0")}|${rel}`;
}

function _setAudioStatus(msg) {
  const el = $("audio-queue-status");
  if (!el) return;
  const prefix = AUDIO_TASKS_RUNNING ? "Автопоиск: включен" : "Автопоиск: остановлен";
  el.textContent = msg ? `${prefix} — ${msg}` : prefix;
}

function _formatScanMetaStatus(scanMeta) {
  if (!scanMeta || !scanMeta.truncated) return "";
  const reasons = Array.isArray(scanMeta.reasons) ? scanMeta.reasons : [];
  let reasonText = "частично";
  if (reasons.includes("time_budget")) {
    reasonText = "частично: ограничение времени сканирования";
  } else if (reasons.includes("limit")) {
    reasonText = "частично: достигнут лимит списка";
  }
  const scanned = Number(scanMeta.bases_scanned || 0);
  const all = Number(scanMeta.base_count || 0);
  if (all > 0) {
    return `${reasonText} (${scanned}/${all} баз)`;
  }
  return reasonText;
}

function _mapAudioLoadError(message) {
  const msg = String(message || "");
  if (/таймаут|timeout/i.test(msg)) {
    return "Сеть или диск Z:\\ отвечает медленно. Подождите — загрузка повторится автоматически. Полный скан на сетевой папке обычно ещё дольше.";
  }
  if (/network|failed to fetch|fetch/i.test(msg)) return "Ошибка сети при загрузке списка.";
  if (/не выбрана позиция/i.test(msg)) return "Не выбрана позиция оператора.";
  if (/папка/i.test(msg) && /не/i.test(msg)) return "Папка не найдена или недоступна.";
  return msg || "Ошибка загрузки";
}

function _syncAudioSpeechRulesVersion() {
  try {
    const prev = localStorage.getItem(AUDIO_SPEECH_RULES_KEY);
    if (prev === AUDIO_SPEECH_RULES_VER) return false;
    localStorage.setItem(AUDIO_SPEECH_RULES_KEY, AUDIO_SPEECH_RULES_VER);
    _clearAudioQueueReveal();
    AUDIO_QUEUE = [];
    AUDIO_QUEUE_MAP = new Map();
    AUDIO_SEGMENTS = [];
    AUDIO_LAST_TIME_TS = 0;
    _resetLastAudioTime();
    return true;
  } catch (_) {
    return false;
  }
}

// «Идентичность» аудиозаписи: частота+сеанс+слот+группа+ID+порядок.
// Одна и та же дорожка может лежать в двух папках-дублях («…11-42-25» и «…11-42-25 (0)»),
// тогда file_key (путь файла) различается, а идентичность — нет.
function _audioIdentityKey(item) {
  const it = item || {};
  const at = String(it.recorded_at || "").trim();
  const cid = String(it.correspondent_id || "").trim();
  if (!at || !cid) return "";
  const freq = String(it.frequency || "").trim().replace(",", ".");
  const slot = String(it.slot || "").trim();
  const group = String(it.group_code || "").trim();
  const order = String(Number(it.order_index || 0));
  return `${freq}|${at}|${slot}|${group}|${cid}|${order}`;
}

function _mergeAudioQueue(existing, incoming) {
  // Дедуп по идентичности, а не по file_key: разные сканы могут возвращать копии
  // одной дорожки из разных папок-дублей, и по file_key они накапливались бы как дубли.
  const byIdentity = new Map();
  const add = (item) => {
    if (!item || !item.file_key) return;
    const idKey = _audioIdentityKey(item) || `fk:${String(item.file_key)}`;
    const prev = byIdentity.get(idKey);
    if (!prev) {
      byIdentity.set(idKey, item);
      return;
    }
    const listened = !!(prev.listened || item.listened);
    if (String(prev.file_key) === String(item.file_key)) {
      byIdentity.set(idKey, { ...prev, ...item, listened });
      return;
    }
    // Копии из разных папок: предпочитаем расшифрованную ([+]), иначе оставляем
    // прежнюю (стабильный file_key, чтобы строка/плеер не «прыгали»).
    const winner = item.has_key && !prev.has_key ? item : prev;
    byIdentity.set(idKey, { ...winner, listened });
  };
  (existing || []).forEach(add);
  (incoming || []).forEach(add);
  const map = new Map();
  byIdentity.forEach((item) => {
    map.set(String(item.file_key), item);
  });
  const out = Array.from(byIdentity.values());
  out.sort((a, b) => {
    const ka = _audioSortKey(a);
    const kb = _audioSortKey(b);
    if (ka < kb) return -1;
    if (ka > kb) return 1;
    return 0;
  });
  return { list: out, map };
}

function _audioIdentitySet(items) {
  const out = new Set();
  (items || []).forEach((item) => {
    const key = _audioIdentityKey(item) || (item && item.file_key ? `fk:${String(item.file_key)}` : "");
    if (key) out.add(key);
  });
  return out;
}

function _startAudioQueueReveal() {
  if (AUDIO_QUEUE_REVEAL_TIMER || !AUDIO_QUEUE_PENDING.length) return;
  AUDIO_QUEUE_REVEAL_TIMER = setInterval(() => {
    if (!AUDIO_QUEUE_PENDING.length) {
      clearInterval(AUDIO_QUEUE_REVEAL_TIMER);
      AUDIO_QUEUE_REVEAL_TIMER = null;
      return;
    }
    const next = AUDIO_QUEUE_PENDING.shift();
    const key = _audioIdentityKey(next) || (next && next.file_key ? `fk:${String(next.file_key)}` : "");
    if (key) AUDIO_QUEUE_PENDING_KEYS.delete(key);
    const merged = _mergeAudioQueue(AUDIO_QUEUE, next ? [next] : []);
    AUDIO_QUEUE = merged.list;
    AUDIO_QUEUE_MAP = merged.map;
    AUDIO_QUEUE_SIG = audioQueueSignature(_currentTrackItems().length ? _currentTrackItems() : AUDIO_QUEUE);
    renderAudioQueue();
    let maxTs = 0;
    for (const it of AUDIO_QUEUE) {
      const ts = Number(it.recorded_ts || 0);
      if (Number.isFinite(ts) && ts > maxTs) maxTs = ts;
    }
    if (maxTs > 0) {
      _saveLastAudioTime(maxTs);
      _scheduleAudioStateSave({ last_time_ts: maxTs });
    }
    if (AUDIO_QUEUE_PENDING.length) {
      _setAudioStatus(`добавлено 1 • в очереди ${AUDIO_QUEUE_PENDING.length}`);
    }
  }, 180);
}

function _enqueueAudioQueueReveal(items) {
  const added = [];
  (items || []).forEach((item) => {
    const key = _audioIdentityKey(item) || (item && item.file_key ? `fk:${String(item.file_key)}` : "");
    if (!key || AUDIO_QUEUE_PENDING_KEYS.has(key)) return;
    AUDIO_QUEUE_PENDING_KEYS.add(key);
    AUDIO_QUEUE_PENDING.push(item);
    added.push(item);
  });
  if (added.length) {
    _setAudioStatus(`новых: ${added.length} • добавляю по одному`);
    _startAudioQueueReveal();
  }
  return added.length;
}

function _clearAudioQueueReveal() {
  if (AUDIO_QUEUE_REVEAL_TIMER) clearInterval(AUDIO_QUEUE_REVEAL_TIMER);
  AUDIO_QUEUE_REVEAL_TIMER = null;
  AUDIO_QUEUE_PENDING = [];
  AUDIO_QUEUE_PENDING_KEYS = new Set();
}

function _normalizeAudioSinceTime(ts) {
  const v = Number(ts || 0);
  if (!Number.isFinite(v) || v <= 0) return 0;
  try {
    const now = new Date();
    const dayStartMs = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0).getTime();
    const dayStartSec = Math.floor(dayStartMs / 1000);
    return v < dayStartSec ? dayStartSec : v;
  } catch (_) {
    return v;
  }
}

function _loadLastAudioTime() {
  try {
    const raw = localStorage.getItem(AUDIO_LAST_TIME_KEY);
    if (!raw) return 0;
    const v = Number(raw);
    return Number.isFinite(v) ? _normalizeAudioSinceTime(v) : 0;
  } catch (_) { }
  return 0;
}

function _saveLastAudioTime(ts) {
  const v = Number(ts || 0);
  if (!Number.isFinite(v) || v <= 0) return;
  AUDIO_LAST_TIME_TS = v;
  try { localStorage.setItem(AUDIO_LAST_TIME_KEY, String(v)); } catch (_) { }
}

function _resetLastAudioTime() {
  AUDIO_LAST_TIME_TS = 0;
  try { localStorage.removeItem(AUDIO_LAST_TIME_KEY); } catch (_) { }
  _scheduleAudioStateSave({ last_time_ts: 0 });
}

function _scheduleAudioStateSave(patch = {}) {
  AUDIO_STATE_CACHE = { ...AUDIO_STATE_CACHE, ...patch };
  if (AUDIO_STATE_SAVE_TIMER) clearTimeout(AUDIO_STATE_SAVE_TIMER);
  AUDIO_STATE_SAVE_TIMER = setTimeout(async () => {
    try {
      await apiPost("/api/intercepts/audio/state", {
        folder_path: AUDIO_STATE_CACHE.folder_path || "",
        tasks_only: !!AUDIO_STATE_CACHE.tasks_only,
        last_time_ts: Number(AUDIO_STATE_CACHE.last_time_ts || 0),
        is_running: !!AUDIO_STATE_CACHE.is_running,
        layout_mode: AUDIO_STATE_CACHE.layout_mode || getAudioLayoutMode(),
      });
    } catch (_) { }
  }, 600);
}

async function loadAudioState() {
  try {
    const data = await apiGet("/api/intercepts/audio/state");
    const state = data && data.state ? data.state : {};
    AUDIO_STATE_CACHE = {
      folder_path: String(state.folder_path || ""),
      tasks_only: !!state.tasks_only,
      last_time_ts: _normalizeAudioSinceTime(state.last_time_ts || 0),
      is_running: state.is_running !== false,
      layout_mode: String(state.layout_mode || "dmr").toLowerCase() === "bundle" ? "bundle" : "dmr",
    };
    AUDIO_TASKS_ONLY_PREF = AUDIO_STATE_CACHE.tasks_only;
    AUDIO_TASKS_RUNNING = AUDIO_STATE_CACHE.is_running !== false;
    setAudioLayoutMode(AUDIO_STATE_CACHE.layout_mode, false);
    // Всегда подтягиваем путь к папке из БД хаба в UI,
    // чтобы операторам не нужно было вводить его вручную на каждом клиенте.
    if (AUDIO_STATE_CACHE.folder_path) {
      setAudioFolderPath(AUDIO_STATE_CACHE.folder_path, false);
    }
    if (!AUDIO_LAST_TIME_TS && AUDIO_STATE_CACHE.last_time_ts) {
      AUDIO_LAST_TIME_TS = AUDIO_STATE_CACHE.last_time_ts;
    }
  } catch (_) { }
}

function _currentTrackItems() {
  if (AUDIO_PAIR_FILTER) {
    return AUDIO_QUEUE.filter((x) => {
      if (String(x.frequency || "").trim() !== String(AUDIO_PAIR_FILTER.frequency || "").trim()) return false;
      if (AUDIO_PAIR_FILTER.group) {
        return String(x.group_code || "").trim() === String(AUDIO_PAIR_FILTER.group || "").trim();
      }
      return true;
    });
  }
  return AUDIO_QUEUE;
}

function _normalizeAudioFolderPath(raw) {
  let p = String(raw || "").trim();
  if (!p) return "";
  if ((p.startsWith('"') && p.endsWith('"')) || (p.startsWith("'") && p.endsWith("'"))) {
    p = p.slice(1, -1).trim();
  }
  if (p.startsWith("@")) {
    p = p.slice(1).trim();
  }
  return p;
}

function isBundleLayoutMode() {
  return String(AUDIO_LAYOUT_MODE || "dmr").toLowerCase() === "bundle";
}

function _parseAudioGroupKey(key) {
  const parts = String(key || "").split("|").map((p) => String(p).trim());
  if (parts.length >= 4) {
    return {
      frequency: parts[0],
      recorded_at: parts[1],
      slot: parts[2],
      group_code: parts.slice(3).join("|"),
    };
  }
  if (parts.length === 3) {
    return {
      frequency: parts[0],
      recorded_at: parts[1],
      slot: parts[2],
      group_code: "",
    };
  }
  return { frequency: "", recorded_at: "", slot: "", group_code: "" };
}

function _audioSessionGroupKey(item) {
  const it = item || {};
  const freq = String(it.frequency || "").trim();
  const recordedAt = String(it.recorded_at || "").trim();
  const slot = String(it.slot || "").trim();
  const group = String(it.group_code || "").trim();
  if (group) return `${freq}|${recordedAt}|${slot}|${group}`;
  return `${freq}|${recordedAt}|${slot}`;
}

function _itemMatchesGroupKey(item, key) {
  const parsed = _parseAudioGroupKey(key);
  const it = item || {};
  if (String(it.frequency || "").trim() !== parsed.frequency) return false;
  if (String(it.recorded_at || "").trim() !== parsed.recorded_at) return false;
  if (String(it.slot || "").trim() !== parsed.slot) return false;
  if (parsed.group_code && String(it.group_code || "").trim() !== parsed.group_code) return false;
  return true;
}

function _itemsForTimeGroupKey(groupKey) {
  if (!groupKey) return [];
  return AUDIO_QUEUE.filter((x) => _itemMatchesGroupKey(x, groupKey));
}

/** Только wav с декодом OPK [+] в имени — общая дорожка не включает сырой шифр без [+]. */
function _itemsForCombinedTrack(items) {
  return (items || []).filter((it) => it && !!it.has_key);
}

function _bundleGroupSelStorageKey() {
  const folder = _normalizeAudioFolderPath(getAudioFolderPath());
  return `${AUDIO_BUNDLE_GROUP_SEL_KEY}:${folder || "__none__"}`;
}

function _loadBundleGroupSelection() {
  try {
    const raw = localStorage.getItem(_bundleGroupSelStorageKey());
    if (!raw) return {};
    const data = JSON.parse(raw);
    return data && typeof data === "object" ? data : {};
  } catch (_) {
    return {};
  }
}

function _saveBundleGroupSelection(sel) {
  try {
    localStorage.setItem(_bundleGroupSelStorageKey(), JSON.stringify(sel || {}));
  } catch (_) { /* ignore */ }
}

/** Ключ для панели «Группы после сканирования» — одна строка на частоту+группу (без времени). */
function _audioBundlePickerGroupKey(item) {
  const freq = String((item && item.frequency) || "").trim();
  const group = String((item && item.group_code) || "").trim();
  if (!group) return "";
  return `${freq}|${group}`;
}

function _isBundleItemVisible(item, sel) {
  const key = _audioBundlePickerGroupKey(item);
  if (!key) return true;
  return sel[key] !== false;
}

function _collectBundlePickerGroups(items) {
  const map = new Map();
  for (const item of items || []) {
    const key = _audioBundlePickerGroupKey(item);
    if (!key) continue;
    if (!map.has(key)) {
      map.set(key, {
        key,
        frequency: String(item.frequency || ""),
        group_code: String(item.group_code || ""),
        sessionTimes: new Set(),
        count: 0,
      });
    }
    const row = map.get(key);
    row.count += 1;
    const at = String(item.recorded_at || "").trim();
    if (at) row.sessionTimes.add(at);
  }
  const list = Array.from(map.values()).map((r) => ({
    key: r.key,
    frequency: r.frequency,
    group_code: r.group_code,
    count: r.count,
    sessionCount: r.sessionTimes.size,
  }));
  list.sort((a, b) => {
    const byFreq = String(a.frequency || "").localeCompare(String(b.frequency || ""), undefined, { numeric: true });
    if (byFreq !== 0) return byFreq;
    return String(a.group_code || "").localeCompare(String(b.group_code || ""), undefined, { numeric: true });
  });
  return list;
}

function _mergeBundleGroupSelection(catalog, saved) {
  const sel = {};
  const newKeys = [];
  const hasSaved = saved && Object.keys(saved).length > 0;
  for (const row of catalog || []) {
    const key = String(row.key || "");
    if (!key) continue;
    if (!hasSaved) {
      sel[key] = true;
      continue;
    }
    if (Object.prototype.hasOwnProperty.call(saved, key)) {
      sel[key] = !!saved[key];
    } else {
      sel[key] = false;
      newKeys.push(key);
    }
  }
  return { sel, newKeys };
}

function renderBundleGroupPicker(catalog, sel, newKeys) {
  const wrap = $("audio-bundle-picker-wrap");
  const list = $("audio-bundle-picker-list");
  const statusEl = $("audio-bundle-picker-status");
  if (!wrap || !list) return;
  const rows = Array.isArray(catalog) ? catalog : [];
  const newSet = new Set(Array.isArray(newKeys) ? newKeys : []);
  if (!rows.length) {
    wrap.hidden = true;
    list.innerHTML = "";
    if (statusEl) statusEl.textContent = "";
    return;
  }
  wrap.hidden = false;
  list.innerHTML = rows.map((row) => {
    const key = String(row.key || "");
    const checked = sel[key] !== false;
    const isNew = newSet.has(key);
    const badge = isNew ? '<span class="badge text-bg-info ms-1">новое</span>' : "";
    const meta = `${escapeHtml(String(row.sessionCount || 0))} сеанс. • ${escapeHtml(String(row.count || 0))} зап.`;
    return `
      <label class="md3-audio-bundle-picker-row ${isNew ? "is-new" : ""}">
        <input type="checkbox" class="form-check-input audio-bundle-group-cb" value="${escapeHtml(key)}" ${checked ? "checked" : ""}>
        <span class="md3-audio-bundle-picker-row__group wp-mono fw-semibold">G ${escapeHtml(row.group_code || "—")}</span>
        <span class="md3-audio-bundle-picker-row__freq wp-mono">${escapeHtml(row.frequency || "")}</span>
        <span class="md3-audio-bundle-picker-row__meta wp-subtle">${meta}${badge}</span>
      </label>
    `;
  }).join("");
  const checkedCount = rows.filter((r) => sel[r.key] !== false).length;
  const newCount = newSet.size;
  if (statusEl) {
    statusEl.textContent = newCount
      ? `Групп: ${rows.length} • выбрано: ${checkedCount} • новых: ${newCount}`
      : `Групп: ${rows.length} • выбрано: ${checkedCount}`;
  }
}

function _readBundleGroupPickerSelection() {
  const sel = {};
  document.querySelectorAll(".audio-bundle-group-cb").forEach((cb) => {
    const key = String(cb.value || "").trim();
    if (key) sel[key] = !!cb.checked;
  });
  return sel;
}

function applyBundleGroupFilter() {
  const catalog = Array.isArray(AUDIO_SCAN_CATALOG) ? AUDIO_SCAN_CATALOG : [];
  if (!catalog.length) {
    _clearAudioQueueReveal();
    AUDIO_QUEUE = [];
    AUDIO_QUEUE_MAP = new Map();
    renderAudioQueue();
    return;
  }
  const sel = _readBundleGroupPickerSelection();
  AUDIO_BUNDLE_GROUP_SEL = sel;
  _saveBundleGroupSelection(sel);
  AUDIO_BUNDLE_FILTER_APPLIED = true;
  AUDIO_BUNDLE_NEW_KEYS = new Set();
  const merged = _mergeAudioQueue([], catalog.filter((item) => _isBundleItemVisible(item, sel)));
  AUDIO_QUEUE = merged.list;
  AUDIO_QUEUE_MAP = merged.map;
  AUDIO_CURRENT_INDEX = -1;
  AUDIO_SEGMENTS = [];
  AUDIO_IS_COMBINED_TRACK = false;
  AUDIO_CURRENT_GROUP_KEY = "";
  renderAudioQueue();
  _setAudioStatus(`Показано записей: ${AUDIO_QUEUE.length} из ${catalog.length}`);
}

function _syncAudioTimeSortHeader() {
  const th = $("audio-queue-sort-time");
  if (!th) return;
  const asc = AUDIO_QUEUE_TIME_SORT === "asc";
  th.classList.toggle("is-sort-asc", asc);
  th.classList.toggle("is-sort-desc", !asc);
  const icon = th.querySelector(".audio-sort-icon");
  if (icon) {
    icon.classList.remove("bi-arrow-down-short", "bi-arrow-up-short");
    icon.classList.add(asc ? "bi-arrow-up-short" : "bi-arrow-down-short");
  }
  th.title = asc ? "Сортировка: от старых к новым (нажмите для обратной)" : "Сортировка: от новых к старым (нажмите для обратной)";
}

function _toggleAudioTimeSort() {
  AUDIO_QUEUE_TIME_SORT = AUDIO_QUEUE_TIME_SORT === "asc" ? "desc" : "asc";
  try { localStorage.setItem(AUDIO_TIME_SORT_KEY, AUDIO_QUEUE_TIME_SORT); } catch (_) { }
  _syncAudioTimeSortHeader();
  renderAudioQueue();
  if (isBundleLayoutMode() && AUDIO_SCAN_CATALOG.length) {
    const catalog = _collectBundlePickerGroups(AUDIO_SCAN_CATALOG);
    renderBundleGroupPicker(catalog, AUDIO_BUNDLE_GROUP_SEL, Array.from(AUDIO_BUNDLE_NEW_KEYS || []));
  }
}

function getAudioLayoutMode() {
  return isBundleLayoutMode() ? "bundle" : "dmr";
}

function setAudioLayoutMode(mode, persist = true) {
  AUDIO_LAYOUT_MODE = String(mode || "dmr").toLowerCase() === "bundle" ? "bundle" : "dmr";
  const sel = $("audio-layout-mode");
  if (sel) sel.value = AUDIO_LAYOUT_MODE;
  const runToggle = $("audio-tasks-run");
  const runWrap = $("audio-tasks-run-wrap");
  if (runWrap) runWrap.hidden = isBundleLayoutMode();
  if (isBundleLayoutMode()) {
    AUDIO_TASKS_RUNNING = false;
    if (runToggle) runToggle.checked = false;
    if (AUDIO_REFRESH_TIMER) clearInterval(AUDIO_REFRESH_TIMER);
    AUDIO_REFRESH_TIMER = null;
    if (AUDIO_REFRESH_SCHEDULED) clearTimeout(AUDIO_REFRESH_SCHEDULED);
    AUDIO_REFRESH_SCHEDULED = null;
  }
  _syncAudioRefreshButtonLabels();
  if (!isBundleLayoutMode()) {
    const pickerWrap = $("audio-bundle-picker-wrap");
    if (pickerWrap) pickerWrap.hidden = true;
    AUDIO_BUNDLE_FILTER_APPLIED = false;
    AUDIO_SCAN_CATALOG = [];
  }
  if (persist) {
    try { localStorage.setItem(AUDIO_LAYOUT_MODE_KEY, AUDIO_LAYOUT_MODE); } catch (_) { }
    _scheduleAudioStateSave({
      layout_mode: AUDIO_LAYOUT_MODE,
      is_running: isBundleLayoutMode() ? false : !!AUDIO_TASKS_RUNNING,
    });
  }
  try {
    document.body.classList.toggle("audio-layout-bundle", isBundleLayoutMode());
  } catch (_) { }
}

function _syncAudioRefreshButtonLabels() {
  const refreshBtn = $("audio-refresh-btn");
  const refreshFullBtn = $("audio-refresh-full-btn");
  if (refreshBtn) {
    refreshBtn.innerHTML = isBundleLayoutMode()
      ? '<i class="bi bi-search me-1" aria-hidden="true"></i>Сканировать'
      : '<i class="bi bi-arrow-clockwise me-1" aria-hidden="true"></i>Обновить';
  }
  if (refreshFullBtn) refreshFullBtn.hidden = isBundleLayoutMode();
}

function getAudioFolderPath() {
  // Источник истины для папки аудио — состояние с сервера (AUDIO_STATE_CACHE).
  // Локальный input/LocalStorage используем только как временный буфер
  // до первой загрузки состояния.
  if (AUDIO_STATE_CACHE && AUDIO_STATE_CACHE.folder_path) {
    return _normalizeAudioFolderPath(AUDIO_STATE_CACHE.folder_path);
  }
  const { folderInput } = _audioEls();
  const direct = folderInput ? _normalizeAudioFolderPath(folderInput.value) : "";
  if (direct) return direct;
  return "";
}

function setAudioFolderPath(path, persist = true) {
  const normalized = _normalizeAudioFolderPath(path);
  const { folderInput } = _audioEls();
  if (folderInput) folderInput.value = normalized || "";
  // Также сразу обновляем локальный кеш состояния,
  // чтобы getAudioFolderPath() возвращал актуальный путь.
  AUDIO_STATE_CACHE = {
    ...AUDIO_STATE_CACHE,
    folder_path: normalized || "",
  };
}

let AUDIO_FOLDER_CHECK_TIMER = null;

async function checkAudioFolderPath(path) {
  const { folderStatus } = _audioEls();
  if (!folderStatus) return;
  const p = _normalizeAudioFolderPath(path);
  if (!p) {
    folderStatus.textContent = "Путь не задан";
    folderStatus.className = "small mt-1 text-muted";
    return;
  }
  folderStatus.textContent = "Проверка доступа...";
  folderStatus.className = "small mt-1 text-muted";
  try {
    const qs = new URLSearchParams();
    qs.set("folder_path", p);
    const data = await apiGetWithTimeout(`/api/intercepts/audio/check-path?${qs.toString()}`, 8000);
    if (data.exists && data.is_dir) {
      const hint = data.layout_hint === "bundle" ? " • структура «Отложка»" : "";
      folderStatus.textContent = `Папка доступна${hint}`;
      folderStatus.className = "small mt-1 text-success";
      if (data.layout_hint === "bundle" && !isBundleLayoutMode()) {
        setAudioLayoutMode("bundle");
      }
    } else if (data.exists) {
      folderStatus.textContent = "Путь найден, но это не папка";
      folderStatus.className = "small mt-1 text-warning";
    } else {
      folderStatus.textContent = "Папка не найдена";
      folderStatus.className = "small mt-1 text-danger";
    }
  } catch (e) {
    folderStatus.textContent = `Ошибка: ${e.message || e}`;
    folderStatus.className = "small mt-1 text-danger";
  }
}

function getTasksOnlyFlag() {
  const { tasksOnly } = _audioEls();
  if (tasksOnly) return !!tasksOnly.checked;
  // Если чекбокса ещё нет (ранний вызов) — читаем из кеша состояния,
  // который приходит с сервера и общий для всех клиентов хаба.
  if (AUDIO_STATE_CACHE && typeof AUDIO_STATE_CACHE.tasks_only === "boolean") {
    return !!AUDIO_STATE_CACHE.tasks_only;
  }
  return false;
}

function setTasksOnlyFlag(v) {
  const { tasksOnly } = _audioEls();
  if (tasksOnly) tasksOnly.checked = !!v;
  AUDIO_STATE_CACHE = {
    ...AUDIO_STATE_CACHE,
    tasks_only: !!v,
  };
}

function renderAudioTasks() {
  const { taskList } = _audioEls();
  if (!taskList) return;
  if (!AUDIO_TASKS || AUDIO_TASKS.length === 0) {
    taskList.innerHTML = "<div class='md3-post-task-list__empty'>Нет заданий по частотам</div>";
    return;
  }
  taskList.innerHTML = "";
  AUDIO_TASKS.forEach((t) => {
    const isActive = !!t.is_active;
    const row = document.createElement("div");
    row.className =
      "md3-post-task-item list-group-item d-flex align-items-center justify-content-between";
    row.innerHTML = `
      <div class="md3-post-task-item__main">
        <div class="md3-post-task-item__freq wp-mono">${escapeHtml(t.frequency || "")}</div>
        <div class="md3-post-task-item__unit">${escapeHtml(t.unit_name || "")}</div>
        <div class="md3-post-task-item__state ${isActive ? "md3-post-task-item__state--on" : ""}">
          ${isActive ? "Активно" : "Остановлено"}
        </div>
      </div>
      <div class="md3-post-task-item__actions d-flex gap-1">
        <button class="btn btn-sm md3-post-task-toggle ${isActive ? "md3-post-task-toggle--stop" : "md3-post-task-toggle--start"}" type="button"
          data-task-action="toggle" data-task-id="${escapeHtml(String(t.id || ""))}">
          <i class="bi ${isActive ? "bi-pause-fill" : "bi-play-fill"}"></i>
          ${isActive ? "Стоп" : "Старт"}
        </button>
        <button class="btn btn-sm md3-post-task-delete btn-outline-danger" type="button" data-task-action="delete"
          data-task-id="${escapeHtml(String(t.id || ""))}" title="Удалить">
          <i class="bi bi-x-lg"></i>
        </button>
      </div>
    `;
    taskList.appendChild(row);
  });
}

async function loadAudioTasks() {
  try {
    const data = await apiGet("/api/intercepts/audio/tasks");
    AUDIO_TASKS = Array.isArray(data.tasks) ? data.tasks : [];
    renderAudioTasks();
    const { tasksOnly } = _audioEls();
    const activeCount = AUDIO_TASKS.filter((t) => !!t.is_active).length;
    if (activeCount > 0) {
      setTasksOnlyFlag(true);
      if (tasksOnly) tasksOnly.disabled = true;
    } else {
      if (tasksOnly && AUDIO_TASKS_ONLY_PREF !== null) {
        setTasksOnlyFlag(!!AUDIO_TASKS_ONLY_PREF);
      } else {
        setTasksOnlyFlag(false);
      }
      if (tasksOnly) tasksOnly.disabled = false;
    }
  } catch (_) {
    AUDIO_TASKS = [];
    renderAudioTasks();
  }
}

async function addAudioTask() {
  const { taskFreq, taskName } = _audioEls();
  const freq = taskFreq ? String(taskFreq.value || "").trim() : "";
  const unitName = taskName ? String(taskName.value || "").trim() : "";
  if (!freq) {
    setText("intercepts-status", "Укажи частоту для задания.");
    return;
  }
  try {
    await apiPost("/api/intercepts/audio/tasks", {
      frequency: freq,
      unit_name: unitName,
    });
    AUDIO_TASKS_RUNNING = true;
    _scheduleAudioStateSave({ is_running: true });
    _resetLastAudioTime();
    if (taskFreq) taskFreq.value = "";
    if (taskName) taskName.value = "";
    await loadAudioTasks();
    await refreshAudioQueue();
  } catch (e) {
    setText("intercepts-status", `Ошибка задания: ${e.message || e}`);
  }
}

async function deleteAudioTask(taskId) {
  if (!taskId) return;
  try {
    await apiPost("/api/intercepts/audio/tasks/delete", { id: taskId });
    AUDIO_TASKS_RUNNING = true;
    _scheduleAudioStateSave({ is_running: true });
    _resetLastAudioTime();
    await loadAudioTasks();
    await refreshAudioQueue();
  } catch (e) {
    setText("intercepts-status", `Ошибка удаления задания: ${e.message || e}`);
  }
}

async function toggleAudioTask(taskId, isActive) {
  if (!taskId) return;
  try {
    await apiPost("/api/intercepts/audio/tasks/active", {
      id: taskId,
      is_active: isActive ? 0 : 1,
    });
    AUDIO_TASKS_RUNNING = true;
    _scheduleAudioStateSave({ is_running: true });
    _resetLastAudioTime();
    await loadAudioTasks();
    await refreshAudioQueue();
  } catch (e) {
    setText("intercepts-status", `Ошибка статуса задания: ${e.message || e}`);
  }
}

function _isMobileAudioApp() {
  return (
    typeof window.ixViewportIsNarrow === "function" &&
    window.ixViewportIsNarrow() &&
    document.body.classList.contains("eavc-page-audio")
  );
}

function _syncMobileAudioLayout() {
  const queueBlock = document.querySelector(".md3-intercepts-audio-queue-block");
  const audioBody = document.querySelector(".ix-mobile-panel--audio .audio-panel .card-body");
  const blankHost = document.querySelector(".audio-blank-col .col-12");
  if (!queueBlock || !audioBody || !blankHost) return;
  if (_isMobileAudioApp()) {
    if (queueBlock.parentElement !== audioBody) {
      audioBody.insertBefore(queueBlock, audioBody.firstChild);
      queueBlock.classList.add("ix-mobile-queue-in-listen");
    }
    const cards = document.getElementById("audio-mobile-queue-cards");
    const table = document.querySelector(".md3-audio-queue-table");
    if (cards) cards.hidden = false;
    if (table) table.hidden = true;
  } else {
    if (queueBlock.classList.contains("ix-mobile-queue-in-listen")) {
      blankHost.appendChild(queueBlock);
      queueBlock.classList.remove("ix-mobile-queue-in-listen");
    }
    const cards = document.getElementById("audio-mobile-queue-cards");
    const table = document.querySelector(".md3-audio-queue-table");
    if (cards) {
      cards.hidden = true;
      cards.innerHTML = "";
    }
    if (table) table.hidden = false;
  }
}

function _renderAudioQueueMobileCards(visible, order, groups, currentItem, durationByKey) {
  const cardsEl = document.getElementById("audio-mobile-queue-cards");
  if (!cardsEl || !_isMobileAudioApp()) return;
  cardsEl.innerHTML = "";
  if (!visible.length) {
    const emptyMsg = isBundleLayoutMode() && AUDIO_SCAN_CATALOG.length && !AUDIO_BUNDLE_FILTER_APPLIED
      ? "Сканирование завершено. Отметьте группы и нажмите «Показать»."
      : "Нет новых аудиоперехватов";
    cardsEl.innerHTML = `<div class="ix-audio-card ix-audio-card--empty" role="status">${escapeHtml(emptyMsg)}</div>`;
    return;
  }
  order.forEach((key) => {
    const items = groups.get(key) || [];
    if (!items.length) return;
    const firstItem = items[0].seg.item || items[0].seg;
    const freq = String(firstItem.frequency || "");
    const groupCode = String(firstItem.group_code || "");
    const { timePart } = splitRecordedAt(firstItem.recorded_at || "");
    const expanded = AUDIO_GROUP_EXPANDED.has(key);
    const anyListening = items.some((x) => {
      const it = x.seg.item || x.seg;
      return Array.isArray(it.listening_by) && it.listening_by.length > 0;
    });
    const groupCard = document.createElement("button");
    groupCard.type = "button";
    groupCard.className = `ix-audio-card ix-audio-card--group${anyListening ? " ix-audio-card--listening" : ""}`;
    groupCard.setAttribute("data-group-key", key);
    groupCard.setAttribute("data-action", "toggle-group");
    groupCard.innerHTML = `
      <span class="ix-audio-card__icon"><i class="bi bi-${expanded ? "chevron-down" : "chevron-right"}"></i></span>
      <span class="ix-audio-card__main">
        <span class="ix-audio-card__title">${escapeHtml(timePart || "—")} · ${escapeHtml(freq)} ${escapeHtml(groupCode)}</span>
        <span class="ix-audio-card__sub">${escapeHtml(String(items.length))} корр.</span>
      </span>
      <span class="ix-audio-card__play"><i class="bi bi-play-fill"></i></span>`;
    cardsEl.appendChild(groupCard);
    if (expanded) {
      items.forEach(({ seg, idx }) => {
        const item = seg.item || seg;
        const segIndex = seg.segmentIndex !== undefined ? seg.segmentIndex : idx;
        const isActive = !!(currentItem && item && currentItem.file_key && currentItem.file_key === item.file_key);
        const cid = _correspondentIdFromItem(item);
        const col = _colorForCode(cid);
        const card = document.createElement("button");
        card.type = "button";
        card.className = `ix-audio-card ix-audio-card--item${isActive ? " active" : ""}${item.listened ? " ix-audio-card--done" : ""}`;
        card.dataset.idx = String(segIndex);
        card.setAttribute("data-file-key", String(item.file_key || ""));
        card.innerHTML = `
          <span class="ix-audio-card__avatar" style="background:${col.bg};border-color:${col.border};color:${col.text}">${escapeHtml(cid || "—")}</span>
          <span class="ix-audio-card__main">
            <span class="ix-audio-card__title">${escapeHtml(item.frequency || "")} ${escapeHtml(item.group_code || "")}</span>
            <span class="ix-audio-card__sub">${escapeHtml(_audioMessageLabel(item) || "—")}</span>
          </span>
          <span class="ix-audio-card__dur">${escapeHtml(formatDuration((item.duration_sec || durationByKey.get(item.file_key) || 0)))}</span>`;
        cardsEl.appendChild(card);
      });
    }
  });
}

function renderAudioQueue() {
  const { queueBody, status, nextBtn } = _audioEls();
  if (!queueBody || !status) return;
  const listEl = _audioEls().list;
  const base = AUDIO_QUEUE.map((item, idx) => ({ item, segmentIndex: idx }));
  const durationByKey = new Map(
    (AUDIO_SEGMENTS || [])
      .filter((s) => (s.item || s).file_key)
      .map((s) => [(s.item || s).file_key, Number(s.duration || 0)])
  );
  const currentItem =
    AUDIO_SEGMENTS.length && AUDIO_SEGMENTS[AUDIO_CURRENT_INDEX]
      ? (AUDIO_SEGMENTS[AUDIO_CURRENT_INDEX].item || AUDIO_SEGMENTS[AUDIO_CURRENT_INDEX])
      : null;
  const visible = base.filter((seg) => {
    if (AUDIO_FILTER_ID) {
      const cid = String((seg.item && seg.item.correspondent_id) || seg.correspondent_id || "");
      return cid.includes(AUDIO_FILTER_ID);
    }
    return true;
  });
  const newCount = visible.filter((seg) => {
    const item = seg.item || seg;
    return !item.listened;
  }).length;
  _setAudioStatus(`Аудиосообщений: ${visible.length}`);
  queueBody.innerHTML = "";
  if (!visible.length) {
    const emptyMsg = isBundleLayoutMode() && AUDIO_SCAN_CATALOG.length && !AUDIO_BUNDLE_FILTER_APPLIED
      ? "Сканирование завершено. Отметьте группы выше и нажмите «Показать»."
      : "Нет новых аудиоперехватов";
    queueBody.innerHTML = `
      <tr>
        <td colspan="7" class="md3-audio-queue-empty">${escapeHtml(emptyMsg)}</td>
      </tr>
    `;
    if (nextBtn) nextBtn.disabled = true;
    return;
  }
  // группировка по времени перехвата (папка времени); порядок: новые сверху (снизу вверх = новые внизу списка при скролле, т.е. order по убыванию времени)
  const groups = new Map();
  const order = [];
  visible.forEach((seg, idx) => {
    const item = seg.item || seg;
    const key = _audioSessionGroupKey(item);
    if (!groups.has(key)) {
      groups.set(key, []);
      order.push(key);
    }
    groups.get(key).push({ seg, idx });
  });
  order.sort((a, b) => {
    const ta = (_parseAudioGroupKey(a).recorded_at || "").trim();
    const tb = (_parseAudioGroupKey(b).recorded_at || "").trim();
    if (ta < tb) return AUDIO_QUEUE_TIME_SORT === "asc" ? -1 : 1;
    if (ta > tb) return AUDIO_QUEUE_TIME_SORT === "asc" ? 1 : -1;
    const ga = (_parseAudioGroupKey(a).group_code || "").trim();
    const gb = (_parseAudioGroupKey(b).group_code || "").trim();
    return ga.localeCompare(gb);
  });

  order.forEach((key) => {
    const items = groups.get(key) || [];
    if (!items.length) return;
    const firstItem = items[0].seg.item || items[0].seg;
    const parsedKey = _parseAudioGroupKey(key);
    const freq = String(firstItem.frequency || parsedKey.frequency || "");
    const slot = String(firstItem.slot || parsedKey.slot || "");
    const groupCode = String(firstItem.group_code || parsedKey.group_code || "");
    const { datePart, timePart } = splitRecordedAt(firstItem.recorded_at || "");
    const expanded = AUDIO_GROUP_EXPANDED.has(key);
    const anyListening = items.some((x) => {
      const it = x.seg.item || x.seg;
      return Array.isArray(it.listening_by) && it.listening_by.length > 0;
    });
    const listeningUsers = [
      ...new Set(
        items.flatMap((x) => {
          const it = x.seg.item || x.seg;
          const by = Array.isArray(it.listening_by) ? it.listening_by : [];
          return by.filter(Boolean).map((u) => String(u).trim()).filter(Boolean);
        })
      ),
    ];
    const listeningSummary = listeningUsers.length
      ? `<span class="badge text-bg-warning md3-audio-queue-chip"><i class="bi bi-headphones me-1"></i>${escapeHtml(
        listeningUsers.length === 1
          ? `Слушает: ${listeningUsers[0]}`
          : `Слушают: ${listeningUsers.length}`
      )}</span>`
      : "";
    const allListened = items.every((x) => !!(x.seg.item || x.seg).listened);
    const groupMark = anyListening
      ? `<span class="text-warning fw-bold" title="Сейчас слушает другой оператор">!</span>`
      : (allListened ? "✓" : "");
    const groupRow = document.createElement("tr");
    groupRow.className = `audio-group-row audio-queue-item ${anyListening ? "audio-listening-now" : ""}`;
    groupRow.dataset.idx = String(items[0].seg.segmentIndex ?? items[0].idx ?? 0);
    groupRow.setAttribute("data-group-row", "1");
    groupRow.setAttribute("data-group-key", key);
    const totalDur = items.reduce((acc, x) => {
      const it = x.seg.item || x.seg;
      const d = (it && it.duration_sec) || (it && it._duration) || (it && it.file_key ? durationByKey.get(it.file_key) : 0);
      return acc + Number(d || 0);
    }, 0);
    const groupCodes = [...new Set(items.map((x) => String((x.seg.item || x.seg).group_code || "").trim()).filter(Boolean))];
    const groupCellText = groupCode || (groupCodes.length ? groupCodes.join(", ") : (slot ? `slot${slot}` : "—"));
    const groupMessageLabel = _audioGroupMessageLabel(items);
    const messageCell = `${groupMessageLabel}${groupMessageLabel && anyListening ? " " : ""}${anyListening ? listeningSummary : ""}`;
    groupRow.innerHTML = `
      <td class="text-center">${groupMark}</td>
      <td>
        <button type="button" class="audio-group-toggle md3-audio-group-toggle" data-action="toggle-group" data-group-key="${escapeHtml(key)}">
          <i class="bi bi-${expanded ? "chevron-down" : "chevron-right"}"></i>
        </button>
        ${escapeHtml(timePart || "—")}
      </td>
      <td class="wp-mono">${escapeHtml(freq || "")}</td>
      <td class="wp-mono">${escapeHtml(groupCellText)}</td>
      <td>${escapeHtml(items.length ? `${items.length} корр.` : "—")}</td>
      <td>${escapeHtml(formatDuration(totalDur || 0))}</td>
      <td class="text-center">${messageCell}</td>
    `;
    queueBody.appendChild(groupRow);

    if (expanded) {
      items.forEach(({ seg, idx }) => {
        const item = seg.item || seg;
        const row = document.createElement("tr");
        const segIndex = seg.segmentIndex !== undefined ? seg.segmentIndex : idx;
        const isActive = !!(currentItem && item && currentItem.file_key && currentItem.file_key === item.file_key);
        const listened = !!item.listened;
        const listeners = Array.isArray(item.listening_by)
          ? item.listening_by.filter(Boolean).map((u) => String(u).trim()).filter(Boolean)
          : [];
        row.className = `audio-queue-item ${isActive ? "active" : ""} ${listened ? "text-muted" : ""} ${listeners.length ? "audio-listening-now" : ""}`;
        row.dataset.idx = String(segIndex);
        row.setAttribute("data-file-key", String(item.file_key || ""));
        row.setAttribute("data-frequency", String(item.frequency || ""));
        row.setAttribute("data-group", String(item.group_code || ""));
        row.setAttribute("data-group-key", key);
        const cid = _correspondentIdFromItem(item);
        const col = _colorForCode(cid);
        const { datePart, timePart } = splitRecordedAt(item.recorded_at || "");
        const keyText = item.has_message
          ? "КЛЮЧ ЕСТЬ"
          : (item.has_key
            ? "ДЕКОД: шум / нет речи"
            : `КЛЮЧА НЕТ! AES КЛЮЧ: ${escapeHtml(item.aes_key || "—")}`);
        const peerId = String(item.peer_correspondent_id || "").trim();
        const callMode = String(item.call_mode || "").trim();
        const groupLabel = callMode === "direct" && peerId
          ? `${escapeHtml(item.group_code || "")} → ${escapeHtml(peerId)}`
          : escapeHtml(item.group_code || "");
        const listeningDetail = listeners.length
          ? `<div class="small text-warning"><i class="bi bi-headphones me-1"></i>Слушает: ${escapeHtml(
            listeners.join(", ")
          )}</div>`
          : "";
        const segDur = (item && item.duration_sec) || (item && item._duration) || (item && item.file_key ? durationByKey.get(item.file_key) : 0);
        const detailMessageCell = _audioMessageLabel(item);
        const rowMark = listeners.length
          ? `<span class="text-warning fw-bold" title="Сейчас слушает другой оператор">!</span>`
          : (item.listened ? "✓" : "");
        row.innerHTML = `
      <td class="text-center">${rowMark}</td>
      <td>${escapeHtml(timePart || "—")}</td>
      <td class="wp-mono">${escapeHtml(item.frequency || "")}</td>
      <td class="wp-mono">${groupLabel}</td>
      <td>
        <span class="audio-avatar" style="background:${col.bg}; border:1px solid ${col.border}; color:${col.text};">
          ${escapeHtml(cid || "—")}
        </span>
        <div class="small wp-subtle">${keyText}</div>
        ${listeningDetail}
      </td>
      <td>${escapeHtml(formatDuration(segDur || 0))}</td>
      <td class="text-center">${escapeHtml(detailMessageCell)}</td>
    `;
        queueBody.appendChild(row);
      });
    }
  });
  if (nextBtn) nextBtn.disabled = visible.length <= 1;
  _renderAudioQueueMobileCards(visible, order, groups, currentItem, durationByKey);
}

function updateAudioMeta(item) {
  const { meta, downloadBtn } = _audioEls();
  if (!item) {
    if (meta) meta.textContent = "—";
    if (downloadBtn) downloadBtn.disabled = true;
    _updateAudioCurrentIdBadge(null);
    return;
  }
  const cid = _correspondentIdFromItem(item);
  const peer = String(item.peer_correspondent_id || "").trim();
  const mode = String(item.call_mode || "").trim();
  const route =
    mode === "direct" && peer ? `${item.group_code || ""} → ${peer}` : (item.group_code || "");
  if (meta) {
    meta.textContent = `${item.frequency || ""} ${route} • ID ${cid || ""} • ${item.recorded_at || ""}`;
  }
  if (downloadBtn) downloadBtn.disabled = false;
  _updateAudioCurrentIdBadge(item);
}

function _updateAudioCurrentIdBadge(item) {
  const idEl = $("audio-current-id");
  if (!idEl) return;
  const cid = _correspondentIdFromItem(item);
  if (!cid) {
    idEl.textContent = "—";
    idEl.hidden = true;
    idEl.removeAttribute("style");
    return;
  }
  const col = _colorForCode(cid);
  idEl.hidden = false;
  idEl.textContent = cid;
  idEl.title = `ID корреспондента: ${cid}`;
  idEl.style.background = col.bg;
  idEl.style.borderColor = col.border;
  idEl.style.color = col.text;
}

function _renderAudioSegmentRail() {
  const rail = $("audio-segment-rail");
  const wrap = $("audio-segment-rail-wrap");
  if (!rail || !wrap) return;
  if (!AUDIO_SEGMENTS.length || !(AUDIO_WAVE_DURATION > 0)) {
    wrap.hidden = true;
    rail.replaceChildren();
    return;
  }
  wrap.hidden = AUDIO_SEGMENTS.length < 2;
  const total = AUDIO_WAVE_DURATION;
  rail.replaceChildren();
  AUDIO_SEGMENTS.forEach((seg, idx) => {
    const item = seg.item || seg;
    const cid = _correspondentIdFromItem(item) || "—";
    const col = _colorForCode(cid === "—" ? "" : cid);
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "md3-audio-seg-chip";
    chip.dataset.idx = String(idx);
    chip.setAttribute("role", "listitem");
    const share = Math.max(0.001, (seg.duration || 0) / total);
    chip.style.flexGrow = String(share);
    chip.style.flexBasis = `${Math.max(2.85, share * 100)}%`;
    chip.style.background = col.bg;
    chip.style.borderColor = col.border;
    chip.style.color = col.text;
    const isNoise = _audioSegmentIsNoise(item);
    chip.title = isNoise
      ? `${cid} • шум • ${formatDuration(seg.duration || 0)}`
      : `${cid} • ${formatDuration(seg.duration || 0)}`;
    chip.textContent = isNoise ? `! ${cid}` : cid;
    chip.classList.toggle("is-noise", isNoise);
    if (idx === AUDIO_CURRENT_INDEX) chip.classList.add("is-active");
    chip.addEventListener("click", () => {
      _seekToAudioSegment(idx, { autoplay: true, openCatalog: false });
    });
    chip.addEventListener("dblclick", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      _setAudioAutoSegmentLoop(idx, { autoplay: true });
    });
    rail.appendChild(chip);
  });
  _syncAudioSegmentRailActive(false);
}

function _syncAudioSegmentRailActive(scrollIntoView) {
  const rail = $("audio-segment-rail");
  if (!rail) return;
  rail.querySelectorAll(".md3-audio-seg-chip").forEach((el) => {
    const idx = Number(el.dataset.idx);
    el.classList.toggle("is-active", idx === AUDIO_CURRENT_INDEX);
    const range = _segmentTimeRange(idx);
    const looped =
      AUDIO_AUTO_LOOP_SEGMENT &&
      AUDIO_SELECTION &&
      range &&
      Math.abs(Number(AUDIO_SELECTION.start) - range.start) < 0.03 &&
      Math.abs(Number(AUDIO_SELECTION.end) - range.end) < 0.03;
    el.classList.toggle("is-looping", !!looped);
  });
  if (!scrollIntoView) return;
  const active = rail.querySelector(".md3-audio-seg-chip.is-active");
  if (active) {
    active.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
  }
}

function _currentAudioItem() {
  const list = AUDIO_SEGMENTS.length ? AUDIO_SEGMENTS : AUDIO_QUEUE;
  const seg = list[AUDIO_CURRENT_INDEX] || null;
  return seg ? (seg.item || seg) : null;
}

function _downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || "audio.wav";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function playSingleAudio(item, opts = {}) {
  const { audio } = _audioEls();
  if (!audio || !item || !item.file_rel) return false;
  const folderPath = getAudioFolderPath();
  if (!folderPath) return false;
  const qs = new URLSearchParams();
  qs.set("folder_path", folderPath);
  qs.set("file_rel", item.file_rel);
  AUDIO_SEGMENTS = [];
  AUDIO_QUEUE_SIG = "";
  AUDIO_IS_COMBINED_TRACK = false;
  AUDIO_CURRENT_GROUP_KEY = "";
  _renderAudioSegmentRail();
  audio.src = `/api/intercepts/audio/file?${qs.toString()}`;
  audio.load();
  if (opts.autoplay) {
    audio.play().catch(() => { });
  }
  // загрузка волны/корреспондента для одиночного файла
  buildWaveformForSingle(item).catch(() => { });
  return true;
}

}

async function downloadCurrentAudio() {
  const { audio } = _audioEls();
  const item = _currentAudioItem();
  if (item && item.file_rel) {
    const folderPath = getAudioFolderPath();
    if (!folderPath) return;
    try {
      const qs = new URLSearchParams();
      qs.set("folder_path", folderPath);
      qs.set("file_rel", item.file_rel);
      const res = await fetch(`/api/intercepts/audio/file?${qs.toString()}`);
      if (!res.ok) return;
      const blob = await res.blob();
      const name = String(item.file_rel || "audio.wav").split(/[\\/]/).pop() || "audio.wav";
      _downloadBlob(blob, name);
    } catch (_) { }
    return;
  }
  if (audio && audio.src) {
    try {
      const res = await fetch(audio.src);
      if (!res.ok) return;
      const blob = await res.blob();
      _downloadBlob(blob, "combined.wav");
    } catch (_) { }
  }
}

function audioTimeLabelFromItem(item) {
  const raw = String((item && item.recorded_at) || "").trim();
  if (raw) {
    const parts = raw.split(" ");
    if (parts.length >= 2) {
      const t = parts[1].slice(0, 5).replace(":", ".");
      return _normalizeTimeLike(t) || t;
    }
  }
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  return `${hh}.${mm}`;
}

function _audioDashLineFromItem(_item) {
  // Только тире: ID корреспондента оператор вписывает вручную при необходимости.
  return "-";
}

function ensureAudioTimeInInput(item, opts = {}) {
  const ta = $("intercept-input");
  if (!ta) return;
  const t = audioTimeLabelFromItem(item);
  const dashLine = _audioDashLineFromItem(item);
  const current = String(ta.value || "");
  const force = !!opts.force;
  // Если оператор уже что‑то ввёл в блоке, не вмешиваемся и не подставляем
  // новое время автоматически, чтобы не появлялись "непонятные" заголовки.
  if (!force && current.trim().length > 0) {
    return;
  }
  const lastHeader = extractLastTimeHeader(current);
  if (lastHeader === t) {
    ta.focus();
    const len = ta.value.length;
    ta.setSelectionRange(len, len);
    return;
  }
  // Если предыдущий заголовок времени стоит в конце и под ним только пустой "-",
  // заменяем этот блок на новое время, чтобы не накапливались пустые интервалы:
  // 10.51\n-\n11.00\n-  ->  11.00\n-
  if (lastHeader) {
    const tailRe = /(^|\n)(\d{1,2}[.:]\d{2})\s*\n-\s*(?:\([^)]*\)\s*)?$/;
    const m = tailRe.exec(current);
    if (m && normalizeTimeHeader(m[2]) === normalizeTimeHeader(lastHeader)) {
      const before = current.slice(0, m.index);
      const prefixBefore = before && !before.endsWith("\n") ? "\n" : "";
      ta.value = before + prefixBefore + t + "\n" + dashLine;
      ta.focus();
      const len2 = ta.value.length;
      ta.setSelectionRange(len2, len2);
      return;
    }
  }
  const prefix = current && !current.endsWith("\n") ? "\n" : "";
  ta.value = current + prefix + t + "\n" + dashLine;
  ta.focus();
  const len = ta.value.length;
  ta.setSelectionRange(len, len);
}

function highlightCurrentSpeaker(code) {
  PREVIEW_HIGHLIGHT_CODE = String(code || "");
  try {
    _renderPreview();
  } catch (_) { }
}

/** «173,4750» и «173.4750» — одна и та же частота. */
function _freqMatchKey(freq) {
  return String(freq || "").trim().replace(",", ".");
}

function getTaskUnitNameByFrequency(freq) {
  const f = _freqMatchKey(freq);
  if (!f || !Array.isArray(AUDIO_TASKS)) return "";
  const found = AUDIO_TASKS.find((t) => _freqMatchKey(t.frequency) === f);
  return found ? String(found.unit_name || "").trim() : "";
}

/**
 * Подразделение для новой карточки каталога.
 * Наследуем только при однозначном совпадении: одну частоту могут использовать
 * разные подразделения, и догадка отправила бы записи в чужое.
 */
function getUnitNameForNewCatalog(freq) {
  const f = _freqMatchKey(freq);
  if (!f) return "";
  const taskName = getTaskUnitNameByFrequency(f);
  if (taskName) return taskName;
  const cat = (STATE && STATE.catalog) ? STATE.catalog : [];
  const names = new Set();
  for (const c of cat) {
    if (_freqMatchKey(c.frequency) !== f) continue;
    const name = String(c.unit_name || "").trim();
    if (name) names.add(name);
  }
  return names.size === 1 ? String(names.values().next().value) : "";
}

async function openAudioCatalog(item) {
  if (!item) return;
  const reqId = ++AUDIO_CATALOG_OPEN_REQ;
  const freq = String(item.frequency || "").trim();
  const grp = String(item.group_code || "").trim();
  if (!freq || !grp) return;
  if (!ACTIVE_SESSION_ID && typeof loadState === "function") {
    await loadState(null);
    if (reqId !== AUDIO_CATALOG_OPEN_REQ) return;
    if (!ACTIVE_SESSION_ID && STATE && (STATE.selected_session || STATE.current_session)) {
      const s = STATE.selected_session || STATE.current_session;
      ACTIVE_SESSION_ID = Number(s.id || 0);
      if (STATE.sessions && renderShifts) renderShifts(STATE.sessions, s);
    }
  }
  if (!ACTIVE_SESSION_ID) return;
  if (!STATE || !STATE.catalog) {
    if (typeof loadState === "function") await loadState(ACTIVE_SESSION_ID || null);
    if (reqId !== AUDIO_CATALOG_OPEN_REQ) return;
    if (!STATE || !STATE.catalog) return;
  }
  const cat = STATE.catalog.find(
    (c) =>
      _freqMatchKey(c.frequency) === _freqMatchKey(freq) &&
      String(c.group_code || "").trim() === grp
  );
  const catalogGroup = grp;
  if (!cat) {
    if (CAN_START) {
      const unitName = getUnitNameForNewCatalog(freq);
      try {
        await apiPost("/api/intercepts/catalog", {
          unit_name: unitName || "—",
          frequency: freq,
          group_code: catalogGroup,
          location: "",
        });
        if (reqId !== AUDIO_CATALOG_OPEN_REQ) return;
        await loadState(ACTIVE_SESSION_ID || null);
        if (reqId !== AUDIO_CATALOG_OPEN_REQ) return;
        const newCat = (STATE && STATE.catalog) ? STATE.catalog.find(
          (c) =>
            _freqMatchKey(c.frequency) === _freqMatchKey(freq) &&
            String(c.group_code || "").trim() === catalogGroup
        ) : null;
        if (newCat) {
          if (reqId !== AUDIO_CATALOG_OPEN_REQ) return;
          await openItem(Number(newCat.id || 0), {
            id: newCat.id,
            unit_name: newCat.unit_name || "",
            frequency: newCat.frequency || "",
            group_code: newCat.group_code || "",
            location: String(newCat.location || "").trim(),
            archived_only: !!newCat.archived_only,
          });
          return;
        }
      } catch (_) { }
    }
    const archivedCat = {
      id: 0,
      unit_name: getUnitNameForNewCatalog(freq) || "",
      frequency: freq,
      group_code: catalogGroup,
      location: "",
      archived_only: true,
    };
    if (reqId !== AUDIO_CATALOG_OPEN_REQ) return;
    await openItem(0, archivedCat);
    return;
  }
  try {
    if (reqId !== AUDIO_CATALOG_OPEN_REQ) return;
    await openItem(Number(cat.id || 0), {
      id: cat.id,
      unit_name: cat.unit_name || "",
      frequency: cat.frequency || "",
      group_code: cat.group_code || "",
      location: String(cat.location || "").trim(),
      archived_only: !!cat.archived_only,
    });
  } catch (_) { }
}

function setCurrentAudioIndex(idx, opts = {}) {
  const { audio } = _audioEls();
  if (!audio) return;
  const list = AUDIO_SEGMENTS.length ? AUDIO_SEGMENTS : AUDIO_QUEUE;
  if (!list.length) {
    AUDIO_CURRENT_INDEX = -1;
    AUDIO_IS_COMBINED_TRACK = false;
    audio.removeAttribute("src");
    audio.load();
    updateAudioMeta(null);
    _renderAudioSegmentRail();
    _syncAsrPlayerHintVisibility(false);
    return;
  }
  const nextIdx = Math.max(0, Math.min(idx, list.length - 1));
  const seg = list[nextIdx];
  const item = seg.item || seg;
  AUDIO_CURRENT_INDEX = nextIdx;
  if (opts.seek !== false) {
    AUDIO_LAST_SEG_IDX = nextIdx;
  }
  updateAudioMeta(item);
  _syncAudioSegmentRailActive(true);
  renderAudioQueue();
  highlightCurrentSpeaker(_correspondentIdFromItem(item));
  if (opts.openCatalog !== false) {
    openAudioCatalog(item);
  }
  setListeningFileKey(item);
  if (AUDIO_SEGMENTS.length && seg.startSec !== undefined && opts.seek !== false) {
    const seekTo = Math.max(0, Number(seg.startSec) + 0.01);
    try {
      audio.currentTime = seekTo;
      AUDIO_PLAYHEAD_TIME = seekTo;
      _scheduleWaveformOverlay();
    } catch (_) { }
  }
  if (opts.autoplay) {
    audio.play().catch(() => { });
  }
  ASR_CURRENT_ITEM = item || null;
  if (ASR_UI_ENABLED) {
    queueAsrForCurrentTrack({ autoTranscribe: true }).catch(() => { });
  }
}


async function markListened(item) {
  if (!item) return;
  try {
    await apiPost("/api/intercepts/audio/mark-listened", { file_key: item.file_key });
    if (item.file_key) {
      AUDIO_LISTENED_LOCAL.add(String(item.file_key));
      item.listened = true;
      renderAudioQueue();
    }
  } catch (_) { }
}

async function playNextAudio(opts = {}) {
  const openCatalog = opts.openCatalog !== false;
  const wantPlay = opts.autoplay !== false;

  // Комбинированная дорожка из нескольких сегментов — seek внутри текущего src.
  if (AUDIO_IS_COMBINED_TRACK && AUDIO_SEGMENTS.length > 1) {
    const list = AUDIO_SEGMENTS;
    const currentSeg = list[AUDIO_CURRENT_INDEX] || null;
    const currentItem = currentSeg ? currentSeg.item || currentSeg : null;
    if (currentItem) await markListened(currentItem);
    if (AUDIO_CURRENT_INDEX >= list.length - 1) return;
    const nextIdx = AUDIO_CURRENT_INDEX + 1;
    setCurrentAudioIndex(nextIdx, {
      autoplay: wantPlay,
      openCatalog,
    });
    const nextSeg = list[nextIdx] || null;
    const nextItem = nextSeg ? nextSeg.item || nextSeg : null;
    if (nextItem) ensureAudioTimeInInput(nextItem, { force: true });
    return;
  }

  // Обычная очередь одиночных файлов.
  if (!AUDIO_QUEUE.length) return;
  let idx = AUDIO_CURRENT_INDEX;
  const curItem = _currentAudioItem();
  if (curItem && curItem.file_key) {
    const byKey = AUDIO_QUEUE.findIndex(
      (x) => String(x.file_key || "") === String(curItem.file_key)
    );
    if (byKey >= 0) idx = byKey;
  }
  if (idx < 0) idx = 0;
  const currentItem = AUDIO_QUEUE[idx] || null;
  if (currentItem) await markListened(currentItem);
  if (idx >= AUDIO_QUEUE.length - 1) return;
  const nextIdx = idx + 1;
  const nextItem = AUDIO_QUEUE[nextIdx];
  if (!nextItem) return;
  setCurrentAudioIndex(nextIdx, {
    autoplay: false,
    seek: false,
    openCatalog,
  });
  ensureAudioTimeInInput(nextItem, { force: true });
  if (wantPlay) playSingleAudio(nextItem, { autoplay: true });
}

function formatTime(sec) {
  const s = Math.max(0, Number(sec || 0));
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}

function formatDuration(sec) {
  const s = Math.max(0, Math.floor(Number(sec || 0)));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h > 0) {
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
  }
  return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}

function _syncMd3AudioPlayButton() {
  const { audio, playBtn } = _audioEls();
  if (!playBtn || !audio) return;
  const playing = !audio.paused && !audio.ended;
  const icon = playBtn.querySelector(".md3-audio-fab__icon");
  if (icon) {
    icon.classList.remove("bi-play-fill", "bi-pause-fill");
    icon.classList.add(playing ? "bi-pause-fill" : "bi-play-fill");
  }
  playBtn.setAttribute("aria-pressed", playing ? "true" : "false");
  playBtn.title = playing ? "Пауза" : "Слушать";
}

function _updateMd3AudioTimeRange() {
  const el = $("audio-time-range");
  const { audio } = _audioEls();
  if (!el || !audio) return;
  const cur = formatDuration(audio.currentTime || 0);
  const d = audio.duration;
  const dur = d && Number.isFinite(d) && d > 0 ? formatDuration(d) : "—";
  el.textContent = `${cur} / ${dur}`;
}

function splitRecordedAt(v) {
  const s = String(v || "").trim();
  if (!s) return { datePart: "", timePart: "" };
  const parts = s.split(" ");
  if (parts.length >= 2) {
    return { datePart: parts[0], timePart: parts[1] };
  }
  return { datePart: s, timePart: "" };
}

function setListeningFileKey(item) {
  const key = String((item && item.file_key) || "");
  if (!key) return;
  if (AUDIO_LISTENING_KEY && AUDIO_LISTENING_KEY !== key) {
    apiPost("/api/intercepts/audio/listening/stop", { file_key: AUDIO_LISTENING_KEY, client_id: AUDIO_CLIENT_ID }).catch(() => { });
  }
  AUDIO_LISTENING_KEY = key;
  apiPost("/api/intercepts/audio/listening/start", { file_key: key, client_id: AUDIO_CLIENT_ID })
    .then(() => pollAudioListeningPresence())
    .catch(() => { });
  if (AUDIO_LISTENING_TIMER) clearInterval(AUDIO_LISTENING_TIMER);
  AUDIO_LISTENING_TIMER = setInterval(() => {
    if (document.hidden) return;
    if (AUDIO_LISTENING_KEY) {
      apiPost("/api/intercepts/audio/listening/start", { file_key: AUDIO_LISTENING_KEY, client_id: AUDIO_CLIENT_ID }).catch(() => { });
    }
  }, 8000);
}

function clearListeningFileKey() {
  if (AUDIO_LISTENING_TIMER) {
    clearInterval(AUDIO_LISTENING_TIMER);
    AUDIO_LISTENING_TIMER = null;
  }
  if (AUDIO_LISTENING_KEY) {
    apiPost("/api/intercepts/audio/listening/stop", { file_key: AUDIO_LISTENING_KEY, client_id: AUDIO_CLIENT_ID }).catch(() => { });
  }
  AUDIO_LISTENING_KEY = "";
}

function _sameListeningUsers(a, b) {
  const left = (Array.isArray(a) ? a : []).map((u) => String(u || "").trim()).filter(Boolean).sort();
  const right = (Array.isArray(b) ? b : []).map((u) => String(u || "").trim()).filter(Boolean).sort();
  if (left.length !== right.length) return false;
  for (let i = 0; i < left.length; i += 1) {
    if (left[i] !== right[i]) return false;
  }
  return true;
}

function applyAudioListeningSnapshot(snapshot) {
  const snap = snapshot && typeof snapshot === "object" ? snapshot : {};
  if (!Array.isArray(AUDIO_QUEUE) || !AUDIO_QUEUE.length) return false;
  let changed = false;
  for (const item of AUDIO_QUEUE) {
    const key = String((item && item.file_key) || "").trim();
    if (!key) continue;
    const next = Array.isArray(snap[key]) ? snap[key] : [];
    const prev = Array.isArray(item.listening_by) ? item.listening_by : [];
    if (!_sameListeningUsers(prev, next)) {
      item.listening_by = next.slice();
      changed = true;
    }
  }
  return changed;
}

async function pollAudioListeningPresence() {
  if (AUDIO_PRESENCE_POLL_INFLIGHT) return;
  if (document.hidden) return;
  if (!getAudioFolderPath() || !Array.isArray(AUDIO_QUEUE) || !AUDIO_QUEUE.length) return;
  AUDIO_PRESENCE_POLL_INFLIGHT = true;
  try {
    const data = await apiGet(`/api/intercepts/audio/listening?client_id=${encodeURIComponent(AUDIO_CLIENT_ID)}`);
    if (applyAudioListeningSnapshot((data && data.listening) || {})) {
      renderAudioQueue();
    }
  } catch (_) {
    // тихо — индикатор «кто слушает» не должен мешать основному UI
  } finally {
    AUDIO_PRESENCE_POLL_INFLIGHT = false;
  }
}

function startAudioListeningPresencePoll() {
  if (AUDIO_PRESENCE_POLL_TIMER) clearInterval(AUDIO_PRESENCE_POLL_TIMER);
  AUDIO_PRESENCE_POLL_TIMER = setInterval(() => {
    pollAudioListeningPresence().catch(() => { });
  }, AUDIO_PRESENCE_POLL_MS);
  pollAudioListeningPresence().catch(() => { });
}

function stopAudioListeningPresencePoll() {
  if (AUDIO_PRESENCE_POLL_TIMER) {
    clearInterval(AUDIO_PRESENCE_POLL_TIMER);
    AUDIO_PRESENCE_POLL_TIMER = null;
  }
}

async function buildTrackForPair(freq, group) {
  const f = String(freq || "").trim();
  const g = String(group || "").trim();
  if (!f) return;
  const items = AUDIO_QUEUE.filter((x) => {
    if (String(x.frequency || "").trim() !== f) return false;
    if (g && String(x.group_code || "").trim() !== g) return false;
    return true;
  });
  if (!items.length) return;
  await buildCombinedTrack(items);
  setCurrentAudioIndex(0, { autoplay: true });
}

function audioQueueSignature(items) {
  return (items || []).map((i) => i.file_key).join("|");
}


function scheduleNextAudioRefresh() {
  if (isBundleLayoutMode()) return;
  if (AUDIO_REFRESH_SCHEDULED) clearTimeout(AUDIO_REFRESH_SCHEDULED);
  AUDIO_REFRESH_SCHEDULED = null;
  if (!getAudioFolderPath()) return;
  const baseDelay = document.hidden ? AUDIO_REFRESH_HIDDEN_MS : AUDIO_REFRESH_MS;
  const delay = baseDelay + (Number(AUDIO_REFRESH_BACKOFF_MS) || 0);
  AUDIO_REFRESH_SCHEDULED = setTimeout(() => {
    AUDIO_REFRESH_SCHEDULED = null;
    refreshAudioQueue();
  }, delay);
}

async function refreshAudioQueue(opts = {}) {
  if (AUDIO_REFRESH_INFLIGHT) return;
  const fullScan = !!opts.fullScan;
  const retryNoSince = !!opts.retryNoSince;
  const folderPath = getAudioFolderPath();
  if (!folderPath) {
    stopAudioListeningPresencePoll();
    _clearAudioQueueReveal();
    AUDIO_QUEUE = [];
    AUDIO_SEGMENTS = [];
    renderAudioQueue();
    _setAudioStatus("Папка не задана");
    return;
  }
  AUDIO_REFRESH_INFLIGHT = true;
  AUDIO_REFRESH_STARTED_AT = Date.now();
  _setAudioStatus("загрузка списка...");
  try {
    if (fullScan || retryNoSince) _clearAudioQueueReveal();
    const qs = new URLSearchParams();
    qs.set("folder_path", folderPath);
    qs.set("client_id", AUDIO_CLIENT_ID);
    qs.set("layout", getAudioLayoutMode());
    qs.set("tasks_only", isBundleLayoutMode() ? "0" : (getTasksOnlyFlag() ? "1" : "0"));
    qs.set("is_running", isBundleLayoutMode() ? "1" : (AUDIO_TASKS_RUNNING ? "1" : "0"));
    const activeTasksCount = Array.isArray(AUDIO_TASKS)
      ? AUDIO_TASKS.filter((t) => !!t.is_active).length
      : 0;
    const bundleScan = isBundleLayoutMode();
    const isBootstrap = !AUDIO_QUEUE.length && !fullScan && !bundleScan;
    const isIncremental = !isBootstrap && !fullScan && !bundleScan && AUDIO_QUEUE.length > 0;
    // На сетевых папках большой limit = долгий обход = таймаут клиента и пустой список.
    let dynamicLimit = 250;
    if (fullScan || bundleScan) {
      dynamicLimit = Math.min(50000, Math.max(8000, activeTasksCount * 300));
    } else if (isIncremental) {
      dynamicLimit = Math.min(500, Math.max(200, activeTasksCount * 40));
    } else if (!isBootstrap) {
      dynamicLimit = Math.min(400, Math.max(200, activeTasksCount * 50));
    }
    qs.set("limit", String(dynamicLimit));
    if (isBootstrap || (retryNoSince && !fullScan && !bundleScan)) {
      qs.set("quick", "1");
    }
    const sinceTs = AUDIO_LAST_TIME_TS || _loadLastAudioTime();
    const skipSinceForFullList = !AUDIO_QUEUE.length;
    if (!bundleScan && !fullScan && !retryNoSince && sinceTs > 0 && !skipSinceForFullList) {
      // recorded_ts файла = время папки сессии, а не появления файла на диске.
      // Файлы (например, расшифрованные [+]) дозаписываются в старые сессии позже,
      // поэтому откатываем фильтр на 30 минут назад — дубликаты отсеет merge по file_key.
      const AUDIO_SINCE_MARGIN_SEC = 1800;
      qs.set("since_time", String(Math.max(0, sinceTs - AUDIO_SINCE_MARGIN_SEC)));
    }
    // recent_mtime_since только для инкрементального опроса: на сетевых Z:\ глубокий
    // stat по всем сессиям блокирует API на минуты и оставляет список пустым.
    if (!bundleScan && !fullScan && AUDIO_QUEUE.length > 0 && AUDIO_LAST_SCAN_WALL_TS) {
      qs.set("recent_mtime_since", String(Math.max(0, AUDIO_LAST_SCAN_WALL_TS - 30)));
      qs.set("cache", "0");
    }
    if (fullScan || bundleScan) {
      qs.set("full_scan", "1");
      qs.set("cache", "0");
    }
    let data = null;
    const listTimeoutMs = (fullScan || bundleScan) ? 45000 : (isBootstrap ? 20000 : 14000);
    const fallbackTimeoutMs = (fullScan || bundleScan) ? 30000 : 18000;
    try {
      data = await apiGetWithTimeout(`/api/intercepts/audio/list?${qs.toString()}`, listTimeoutMs);
    } catch (primaryErr) {
      const primaryMsg = (primaryErr && primaryErr.message) ? String(primaryErr.message) : "";
      const isTimeout = /таймаут|timeout/i.test(primaryMsg);
      if (!isTimeout) throw primaryErr;

      // Фолбэк: минимальный быстрый проход по свежим сессиям.
      const fallbackQs = new URLSearchParams(qs.toString());
      fallbackQs.set("limit", "120");
      fallbackQs.set("quick", "1");
      fallbackQs.delete("since_time");
      fallbackQs.delete("recent_mtime_since");
      _setAudioStatus("медленный ответ сети, повторяю быстрый проход...");
      data = await apiGetWithTimeout(`/api/intercepts/audio/list?${fallbackQs.toString()}`, fallbackTimeoutMs);
    }
    AUDIO_TASKS = Array.isArray(data.tasks) ? data.tasks : AUDIO_TASKS;
    const items = Array.isArray(data.items) ? data.items : [];
    const scanMeta = data.scan_meta || {};
    const serverSpeechVer = String(scanMeta.speech_heuristic_version || "");
    if (
      !fullScan &&
      !retryNoSince &&
      serverSpeechVer &&
      serverSpeechVer !== AUDIO_SPEECH_RULES_VER
    ) {
      _syncAudioSpeechRulesVersion();
      await refreshAudioQueue({ fullScan: true });
      return;
    }
    if (scanMeta && scanMeta.stopped) {
      _setAudioStatus("Остановлено планировщиком");
      renderAudioTasks();
      if (Array.isArray(AUDIO_QUEUE) && AUDIO_QUEUE.length) {
        renderAudioQueue();
      } else {
        const { queueBody, nextBtn } = _audioEls();
        if (queueBody) {
          queueBody.innerHTML = `
            <tr>
              <td colspan="7" class="text-muted">Сканирование остановлено. Нажмите "Автопоиск", чтобы снова получать аудиоперехваты.</td>
            </tr>
          `;
        }
        if (nextBtn) nextBtn.disabled = true;
      }
      AUDIO_LAST_REFRESH_OK = Date.now();
      return;
    }
    const prevSig = AUDIO_QUEUE_SIG;
    if (!fullScan && !retryNoSince && sinceTs > 0 && !items.length && !AUDIO_QUEUE.length) {
      await refreshAudioQueue({ retryNoSince: true });
      return;
    }
    let revealQueuedCount = 0;
    if (bundleScan) {
      AUDIO_SCAN_CATALOG = items.slice();
      const catalog = _collectBundlePickerGroups(AUDIO_SCAN_CATALOG);
      let saved = _loadBundleGroupSelection();
      const pickerWrap = $("audio-bundle-picker-wrap");
      if (pickerWrap && !pickerWrap.hidden && document.querySelector(".audio-bundle-group-cb")) {
        saved = { ...saved, ..._readBundleGroupPickerSelection() };
      }
      const mergedSel = _mergeBundleGroupSelection(catalog, saved);
      AUDIO_BUNDLE_GROUP_SEL = mergedSel.sel;
      AUDIO_BUNDLE_NEW_KEYS = new Set(mergedSel.newKeys || []);
      renderBundleGroupPicker(catalog, AUDIO_BUNDLE_GROUP_SEL, Array.from(AUDIO_BUNDLE_NEW_KEYS));
      if (AUDIO_BUNDLE_FILTER_APPLIED) {
        const merged = _mergeAudioQueue([], items.filter((item) => _isBundleItemVisible(item, AUDIO_BUNDLE_GROUP_SEL)));
        AUDIO_QUEUE = merged.list;
        AUDIO_QUEUE_MAP = merged.map;
      } else {
        _clearAudioQueueReveal();
        AUDIO_QUEUE = [];
        AUDIO_QUEUE_MAP = new Map();
      }
    } else {
      const shouldRevealOneByOne =
        !fullScan &&
        !retryNoSince &&
        Array.isArray(AUDIO_QUEUE) &&
        AUDIO_QUEUE.length > 0;
      if (shouldRevealOneByOne) {
        const existingKeys = _audioIdentitySet(AUDIO_QUEUE);
        const immediate = [];
        const fresh = [];
        for (const item of items) {
          const key = _audioIdentityKey(item) || (item && item.file_key ? `fk:${String(item.file_key)}` : "");
          if (key && existingKeys.has(key)) {
            immediate.push(item);
          } else {
            fresh.push(item);
          }
        }
        const merged = _mergeAudioQueue(AUDIO_QUEUE, immediate);
        AUDIO_QUEUE = merged.list;
        AUDIO_QUEUE_MAP = merged.map;
        revealQueuedCount = _enqueueAudioQueueReveal(fresh);
      } else {
        const merged = _mergeAudioQueue(AUDIO_QUEUE, items);
        AUDIO_QUEUE = merged.list;
        AUDIO_QUEUE_MAP = merged.map;
      }
    }
    AUDIO_LISTENED_LOCAL = new Set();
    renderAudioTasks();
    if (AUDIO_FILTER_ID && AUDIO_QUEUE.length) {
      const hasAny = AUDIO_QUEUE.some((item) => {
        const cid = String(item.correspondent_id || "");
        return cid.includes(AUDIO_FILTER_ID);
      });
      if (!hasAny) {
        AUDIO_FILTER_ID = "";
        const { filterId } = _audioEls();
        if (filterId) filterId.value = "";
        try { localStorage.setItem(AUDIO_FILTER_ID_KEY, ""); } catch (_) { }
      }
    }

    if (AUDIO_QUEUE.length) {
      const trackItems = _currentTrackItems();
      const actualTrack = trackItems.length ? trackItems : AUDIO_QUEUE;
      const nextSig = audioQueueSignature(actualTrack);
      const shouldRebuild = !prevSig || prevSig !== nextSig;
      if (shouldRebuild) {
        // Не сбрасываем уже открытую комбинированную дорожку на каждом автообновлении:
        // иначе пропадают цветные сегменты/ID и визуально всё "сереет".
        if (!AUDIO_IS_COMBINED_TRACK) {
          AUDIO_SEGMENTS = [];
          AUDIO_LAST_SEG_IDX = -1;
          AUDIO_IS_COMBINED_TRACK = false;
          AUDIO_CURRENT_GROUP_KEY = "";
        }
      }
      AUDIO_QUEUE_SIG = nextSig;
      renderAudioQueue();
    } else {
      AUDIO_CURRENT_INDEX = -1;
      AUDIO_SEGMENTS = [];
      AUDIO_IS_COMBINED_TRACK = false;
      AUDIO_CURRENT_GROUP_KEY = "";
      updateAudioMeta(null);
      renderAudioQueue();
    }
    if (AUDIO_QUEUE.length) {
      let maxTs = 0;
      for (const it of AUDIO_QUEUE) {
        const ts = Number(it.recorded_ts || 0);
        if (Number.isFinite(ts) && ts > maxTs) maxTs = ts;
      }
      if (maxTs > 0) {
        _saveLastAudioTime(maxTs);
        _scheduleAudioStateSave({ last_time_ts: maxTs });
      }
    }
    const partialMsg = _formatScanMetaStatus(scanMeta);
    if (partialMsg) {
      _setAudioStatus(partialMsg);
    } else {
      if (isBundleLayoutMode()) {
        const cat = _collectBundlePickerGroups(AUDIO_SCAN_CATALOG);
        const newN = AUDIO_BUNDLE_NEW_KEYS ? AUDIO_BUNDLE_NEW_KEYS.size : 0;
        _setAudioStatus(
          AUDIO_BUNDLE_FILTER_APPLIED
            ? `Сканировано: ${items.length} • групп: ${cat.length}${newN ? ` • новых: ${newN}` : ""}`
            : `Сканировано: ${items.length} • групп: ${cat.length}. Выберите и нажмите «Показать».`
        );
      } else if (revealQueuedCount > 0) {
        _setAudioStatus(`новых: ${revealQueuedCount} • добавляю по одному`);
      } else {
        _setAudioStatus(`обновлено: ${items.length}`);
      }
    }
    AUDIO_LAST_REFRESH_OK = Date.now();
    AUDIO_REFRESH_BACKOFF_MS = 0;
    AUDIO_LAST_SCAN_WALL_TS = AUDIO_REFRESH_STARTED_AT
      ? AUDIO_REFRESH_STARTED_AT / 1000
      : Date.now() / 1000;
    pollAudioListeningPresence().catch(() => { });
  } catch (e) {
    const msg = _mapAudioLoadError((e && e.message) ? String(e.message) : "Ошибка загрузки");
    _setAudioStatus(`ошибка: ${msg}`);
    AUDIO_REFRESH_BACKOFF_MS = Math.min(
      AUDIO_REFRESH_BACKOFF_MS_MAX,
      Math.max(5000, (Number(AUDIO_REFRESH_BACKOFF_MS) || 0) + 4000)
    );
    // Не стираем уже загруженный список при временном таймауте/abort.
    // Иначе UI "сереет", хотя данные ещё актуальны.
    const hasExistingRows = Array.isArray(AUDIO_QUEUE) && AUDIO_QUEUE.length > 0;
    if (!hasExistingRows) {
      const { queueBody } = _audioEls();
      if (queueBody) {
        queueBody.innerHTML = `<tr><td colspan="7" class="text-muted">${escapeHtml(msg)}</td></tr>`;
      }
    }
  } finally {
    AUDIO_REFRESH_INFLIGHT = false;
    scheduleNextAudioRefresh();
  }
}

async function buildTrackForTimeGroup(groupKey) {
  if (!groupKey) return;
  AUDIO_CURRENT_GROUP_KEY = String(groupKey);
  const items = _itemsForTimeGroupKey(groupKey);
  if (!items.length) return;
  await buildCombinedTrack(_sortAudioTrackItems(items));
  setCurrentAudioIndex(0, { autoplay: true });
}

async function runAudioDebug() {
  const { debugOut } = _audioEls();
  if (debugOut) debugOut.textContent = "Загрузка...";
  const folderPath = getAudioFolderPath();
  if (!folderPath) {
    if (debugOut) debugOut.textContent = "Папка не задана";
    return;
  }
  const t0 = performance.now();
  let slowTimer = null;
  try {
    const qs = new URLSearchParams();
    qs.set("folder_path", folderPath);
    qs.set("tasks_only", getTasksOnlyFlag() ? "1" : "0");
    qs.set("limit", "50");
    qs.set("debug", "1");
    qs.set("cache", "0");
    const controller = new AbortController();
    const timeoutMs = 180_000;
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    slowTimer = setTimeout(() => {
      if (debugOut) debugOut.textContent = "Долгая операция... продолжаю ждать ответ.";
    }, 10_000);
    console.info("[audio.debug] request start");
    const res = await fetch(`/api/intercepts/audio/list?${qs.toString()}`, {
      cache: "no-store",
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    const dbg = data.debug || {};
    const elapsed = Math.round(performance.now() - t0);
    console.info("[audio.debug] request done in", elapsed, "ms", dbg);
    if (debugOut) debugOut.textContent = JSON.stringify({ elapsed_ms: elapsed, ...dbg }, null, 2);
  } catch (e) {
    let msg = e && e.message ? String(e.message) : "Ошибка debug";
    if (e && (e.name === "AbortError" || /abort/i.test(msg))) {
      msg = `Запрос прерван по таймауту (${Math.round(timeoutMs / 1000)} сек).`;
    }
    if (debugOut) debugOut.textContent = msg;
    console.warn("[audio.debug] request error", e);
  } finally {
    if (slowTimer) clearTimeout(slowTimer);
  }
}

function startAudioPolling() {
  startAudioListeningPresencePoll();
  if (isBundleLayoutMode()) return;
  if (AUDIO_REFRESH_TIMER) {
    clearInterval(AUDIO_REFRESH_TIMER);
    AUDIO_REFRESH_TIMER = null;
  }
  if (AUDIO_REFRESH_SCHEDULED) {
    clearTimeout(AUDIO_REFRESH_SCHEDULED);
    AUDIO_REFRESH_SCHEDULED = null;
  }
  AUDIO_REFRESH_TIMER = setInterval(() => {
    if (document.hidden) return;
    if (!AUDIO_TASKS_RUNNING) return;
    if (!getAudioFolderPath()) return;
    // В фоне браузер может "усыпить" setTimeout; watchdog подхватывает цепочку после возврата.
    const staleMs = AUDIO_REFRESH_MS + 8000;
    const lastOk = Number(AUDIO_LAST_REFRESH_OK || 0);
    if (!lastOk || (Date.now() - lastOk) >= staleMs) {
      refreshAudioQueue({ retryNoSince: true }).catch(() => { });
    }
  }, AUDIO_REFRESH_RECOVER_MS);
  if (getAudioFolderPath()) refreshAudioQueue();
}

function initAudioUi() {
  if (ASR_UI_ENABLED) loadAsrTrainingPolicy().catch(() => { });
  _syncAudioSpeechRulesVersion();
  const {
    audio,
    list,
    folderInput,
    tasksOnly,
    tasksRunToggle,
    playBtn,
    prevBtn,
    nextBtn,
    refreshBtn,
    refreshFullBtn,
    downloadBtn,
    speedSelect,
    loopToggle,
    loopSegToggle,
    filterId,
    filterClear,
    queueBody,
    taskAddBtn,
    taskList,
    taskFromActiveBtn,
    debugBtn,
    asrStatusRefreshBtn,
    asrModelActivateBtn,
    asrSettingsSaveBtn,
    asrDatasetBuildBtn,
    asrTrainBtn,
    asrTranscribeBtn,
    asrFeedbackOkBtn,
    asrFeedbackFixBtn,
  } = _audioEls();

  const panel = $("audio-intercepts-panel");
  if (!panel || !audio) return;

  // Стартовое состояние берём из кеша, который приходит с сервера (loadAudioState).
  const savedPath = getAudioFolderPath();
  if (savedPath) {
    setAudioFolderPath(savedPath, false);
    checkAudioFolderPath(savedPath);
  }
  try {
    const savedLayout = localStorage.getItem(AUDIO_LAYOUT_MODE_KEY);
    if (savedLayout && !AUDIO_STATE_CACHE.layout_mode) {
      setAudioLayoutMode(savedLayout, false);
    }
    const savedSort = localStorage.getItem(AUDIO_TIME_SORT_KEY);
    if (savedSort === "asc" || savedSort === "desc") AUDIO_QUEUE_TIME_SORT = savedSort;
  } catch (_) { }
  _syncAudioRefreshButtonLabels();
  _syncAudioTimeSortHeader();
  setTasksOnlyFlag(getTasksOnlyFlag());
  AUDIO_LAST_TIME_TS = _loadLastAudioTime();
  try {
    if (speedSelect) {
      const savedSpeed = localStorage.getItem(AUDIO_SPEED_KEY);
      if (savedSpeed) speedSelect.value = String(savedSpeed);
    }
    if (loopToggle) {
      loopToggle.checked = localStorage.getItem(AUDIO_LOOP_KEY) === "1";
    }
    if (loopSegToggle) {
      loopSegToggle.checked = localStorage.getItem(AUDIO_LOOP_SEG_KEY) === "1";
      AUDIO_LOOP_SEGMENT = !!loopSegToggle.checked;
    }
    if (filterId) {
      const savedFilter = localStorage.getItem(AUDIO_FILTER_ID_KEY);
      if (savedFilter) filterId.value = String(savedFilter);
      AUDIO_FILTER_ID = String(filterId.value || "").trim();
    }
  } catch (_) { }

  if (folderInput) {
    folderInput.addEventListener("input", () => {
      const nextPath = String(folderInput.value || "").trim();
      setAudioFolderPath(nextPath);
      _scheduleAudioStateSave({
        folder_path: _normalizeAudioFolderPath(nextPath),
        tasks_only: getTasksOnlyFlag(),
      });
      if (isBundleLayoutMode()) {
        AUDIO_BUNDLE_FILTER_APPLIED = false;
        AUDIO_SCAN_CATALOG = [];
        const pickerWrap = $("audio-bundle-picker-wrap");
        if (pickerWrap) pickerWrap.hidden = true;
        _setAudioStatus("Папка задана. Нажмите «Сканировать».");
      } else {
        refreshAudioQueue();
      }
      if (AUDIO_FOLDER_CHECK_TIMER) clearTimeout(AUDIO_FOLDER_CHECK_TIMER);
      AUDIO_FOLDER_CHECK_TIMER = setTimeout(() => {
        checkAudioFolderPath(String(folderInput.value || "").trim());
      }, 400);
    });
  }
  if (tasksOnly) {
    tasksOnly.addEventListener("change", () => {
      setTasksOnlyFlag(!!tasksOnly.checked);
      _scheduleAudioStateSave({ tasks_only: !!tasksOnly.checked });
      refreshAudioQueue();
    });
  }
  if (tasksRunToggle) {
    tasksRunToggle.checked = !!AUDIO_TASKS_RUNNING;
    tasksRunToggle.addEventListener("change", () => {
      AUDIO_TASKS_RUNNING = !!tasksRunToggle.checked;
      _scheduleAudioStateSave({ is_running: AUDIO_TASKS_RUNNING });
      if (AUDIO_TASKS_RUNNING) {
        refreshAudioQueue();
        startAudioPolling();
      } else {
        if (AUDIO_REFRESH_TIMER) clearInterval(AUDIO_REFRESH_TIMER);
        AUDIO_REFRESH_TIMER = null;
        if (AUDIO_REFRESH_SCHEDULED) clearTimeout(AUDIO_REFRESH_SCHEDULED);
        AUDIO_REFRESH_SCHEDULED = null;
        startAudioListeningPresencePoll();
        _setAudioStatus("Остановлено оператором");
      }
    });
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      loadAudioState()
        .then(() => {
          if (tasksRunToggle) tasksRunToggle.checked = !!AUDIO_TASKS_RUNNING;
          _setAudioStatus("");
          if (AUDIO_TASKS_RUNNING) {
            startAudioPolling();
            refreshAudioQueue({ retryNoSince: true });
          } else {
            startAudioListeningPresencePoll();
          }
          pollAudioListeningPresence().catch(() => { });
        })
        .catch(() => { });
    }
  });
  window.addEventListener("focus", () => {
    loadAudioState()
      .then(() => {
        if (tasksRunToggle) tasksRunToggle.checked = !!AUDIO_TASKS_RUNNING;
        _setAudioStatus("");
        if (AUDIO_TASKS_RUNNING) {
          startAudioPolling();
          refreshAudioQueue({ retryNoSince: true });
        } else {
          startAudioListeningPresencePoll();
        }
        pollAudioListeningPresence().catch(() => { });
      })
      .catch(() => { });
  });
  window.addEventListener("pageshow", () => {
    if (AUDIO_TASKS_RUNNING) {
      startAudioPolling();
      refreshAudioQueue({ retryNoSince: true });
    } else {
      startAudioListeningPresencePoll();
    }
    pollAudioListeningPresence().catch(() => { });
  });
  const layoutSelect = $("audio-layout-mode");
  if (layoutSelect) {
    layoutSelect.value = getAudioLayoutMode();
    layoutSelect.addEventListener("change", () => {
      setAudioLayoutMode(layoutSelect.value);
      if (isBundleLayoutMode()) {
        AUDIO_BUNDLE_FILTER_APPLIED = false;
        AUDIO_SCAN_CATALOG = [];
        const pickerWrap = $("audio-bundle-picker-wrap");
        if (pickerWrap) pickerWrap.hidden = true;
        _setAudioStatus("Режим «Отложка»: нажмите «Сканировать» после выбора папки.");
      } else if (getAudioFolderPath()) {
        refreshAudioQueue({ fullScan: true });
        startAudioPolling();
      }
    });
  }
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => refreshAudioQueue({ fullScan: isBundleLayoutMode() }));
  }
  const bundleApplyBtn = $("audio-bundle-apply-btn");
  if (bundleApplyBtn) bundleApplyBtn.addEventListener("click", () => applyBundleGroupFilter());
  const bundleSelAll = $("audio-bundle-sel-all");
  if (bundleSelAll) {
    bundleSelAll.addEventListener("click", () => {
      document.querySelectorAll(".audio-bundle-group-cb").forEach((cb) => { cb.checked = true; });
    });
  }
  const bundleSelNone = $("audio-bundle-sel-none");
  if (bundleSelNone) {
    bundleSelNone.addEventListener("click", () => {
      document.querySelectorAll(".audio-bundle-group-cb").forEach((cb) => { cb.checked = false; });
    });
  }
  const sortTimeTh = $("audio-queue-sort-time");
  if (sortTimeTh) {
    sortTimeTh.addEventListener("click", () => _toggleAudioTimeSort());
  }
  if (downloadBtn) downloadBtn.addEventListener("click", downloadCurrentAudio);
  if (asrStatusRefreshBtn) {
    asrStatusRefreshBtn.addEventListener("click", () => {
      loadAsrModelStatus().catch((e) => _setAudioStatus(`ASR status: ${e.message || e}`));
    });
  }
  if (asrSettingsSaveBtn) {
    asrSettingsSaveBtn.addEventListener("click", () => {
      saveAsrSettings()
        .then(() => _setAudioStatus("ASR настройки сохранены"))
        .catch((e) => _setAudioStatus(`ASR settings: ${e.message || e}`));
    });
  }
  if (asrDatasetBuildBtn) {
    asrDatasetBuildBtn.addEventListener("click", () => {
      buildAsrDataset()
        .then((res) => {
          _setAudioStatus(`ASR dataset: +${Number(res.inserted || 0)} (scan ${Number(res.scanned || 0)})`);
          return loadAsrModelStatus();
        })
        .catch((e) => _setAudioStatus(`ASR dataset: ${e.message || e}`));
    });
  }
  if (asrTrainBtn) {
    asrTrainBtn.addEventListener("click", () => {
      trainAsrModel()
        .then((res) => {
          _setAudioStatus(`ASR train: ${res.model_version || "done"}`);
          return loadAsrModelStatus();
        })
        .catch((e) => _setAudioStatus(`ASR train: ${e.message || e}`));
    });
  }
  if (asrModelActivateBtn) {
    asrModelActivateBtn.addEventListener("click", () => {
      activateAsrModelSelected()
        .then(() => {
          _setAudioStatus("ASR модель активирована");
          return loadAsrModelStatus();
        })
        .catch((e) => _setAudioStatus(`ASR activate: ${e.message || e}`));
    });
  }
  if (asrTranscribeBtn) {
    asrTranscribeBtn.addEventListener("click", () => {
      transcribeCurrentAudioNow()
        .then(() => _setAudioStatus("ASR расшифровка обновлена"))
        .catch((e) => _setAudioStatus(`ASR transcribe: ${e.message || e}`));
    });
  }
  if (asrFeedbackOkBtn) {
    asrFeedbackOkBtn.addEventListener("click", () => {
      sendAsrFeedback(true)
        .then((res) => _setAudioStatus(`ASR feedback: confirmed${res && res.retrain_recommended ? " • retrain рекомендован" : ""}`))
        .catch((e) => _setAudioStatus(`ASR feedback: ${e.message || e}`));
    });
  }
  if (asrFeedbackFixBtn) {
    asrFeedbackFixBtn.addEventListener("click", () => {
      sendAsrFeedback(false)
        .then((res) => _setAudioStatus(`ASR feedback: corrected${res && res.retrain_recommended ? " • retrain рекомендован" : ""}`))
        .catch((e) => _setAudioStatus(`ASR feedback: ${e.message || e}`));
    });
  }
  const { asrSendToInputBtn, audioAsrHintSendBtn } = _audioEls();
  if (asrSendToInputBtn) {
    asrSendToInputBtn.addEventListener("click", () => sendAsrTextToInput());
  }
  if (audioAsrHintSendBtn) {
    audioAsrHintSendBtn.addEventListener("click", () => sendAsrTextToInput());
  }
  if (prevBtn) {
    prevBtn.addEventListener("click", () => {
      const list = AUDIO_SEGMENTS.length ? AUDIO_SEGMENTS : AUDIO_QUEUE;
      if (!list.length) return;
      const nextIdx = Math.max(0, AUDIO_CURRENT_INDEX - 1);
      setCurrentAudioIndex(nextIdx, { autoplay: true });
    });
  }
  if (playBtn) {
    playBtn.addEventListener("click", async () => {
      if (!AUDIO_QUEUE.length) return;
      if (audio && !audio.paused && !audio.ended) {
        audio.pause();
        return;
      }
      // Возобновление после паузы: не перезагружать src и не сбрасывать комбинированную дорожку.
      if (audio && audio.src) {
        const current = _currentAudioItem();
        if (current) {
          ensureAudioTimeInInput(current, { force: false });
          setListeningFileKey(current);
          if (audio.ended) {
            try { audio.currentTime = 0; } catch (_) { }
          }
          audio.play().catch(() => { });
          return;
        }
      }
      if (AUDIO_SEGMENTS.length > 1 && audio && audio.src) {
        if (AUDIO_CURRENT_INDEX < 0) {
          setCurrentAudioIndex(0, { autoplay: true, seek: false, openCatalog: false });
        } else {
          const current = _currentAudioItem();
          if (current) ensureAudioTimeInInput(current, { force: false });
          setListeningFileKey(current);
          audio.play().catch(() => { });
        }
        return;
      }
      if (AUDIO_CURRENT_INDEX < 0 && AUDIO_QUEUE.length) {
        setCurrentAudioIndex(0, { autoplay: false, seek: false });
      }
      const item = _currentAudioItem() || AUDIO_QUEUE[0] || null;
      if (item) ensureAudioTimeInInput(item, { force: true });
      playSingleAudio(item, { autoplay: true });
    });
  }
  if (nextBtn) {
    nextBtn.addEventListener("click", () => {
      playNextAudio({ autoplay: true, openCatalog: true });
    });
  }
  if (list) {
    list.addEventListener("scroll", () => {
      const atBottom = list.scrollTop + list.clientHeight >= list.scrollHeight - 12;
      AUDIO_QUEUE_STICK_BOTTOM = atBottom;
    });
  }
  if (queueBody) {
    queueBody.addEventListener("click", async (ev) => {
      const toggle = ev.target && ev.target.closest ? ev.target.closest("[data-action='toggle-group']") : null;
      if (toggle) {
        const key = String(toggle.getAttribute("data-group-key") || "");
        if (key) {
          if (AUDIO_GROUP_EXPANDED.has(key)) {
            AUDIO_GROUP_EXPANDED.delete(key);
          } else {
            AUDIO_GROUP_EXPANDED.add(key);
          }
          renderAudioQueue();
        }
        return;
      }
      const row = ev.target && ev.target.closest ? ev.target.closest("tr[data-idx]") : null;
      if (!row) return;
      if (row.getAttribute("data-group-row") === "1") {
        const key = String(row.getAttribute("data-group-key") || "");
        const groupItems = _itemsForTimeGroupKey(key);
        for (const it of groupItems) {
          await markListened(it);
        }
        if (groupItems.length) {
          const firstItem = groupItems[0];
          ensureAudioTimeInInput(firstItem, { force: true });
        }
        await buildTrackForTimeGroup(key);
        return;
      }
      const fileKey = String(row.getAttribute("data-file-key") || "");
      let idx = -1;
      if (fileKey) {
        idx = AUDIO_QUEUE.findIndex((x) => String(x.file_key || "") === fileKey);
      }
      if (idx < 0) {
        idx = Number(row.dataset.idx || 0);
      }
      const item = AUDIO_QUEUE[idx] || null;
      if (item) {
        await markListened(item);
        // Один путь play: индекс без autoplay, затем playSingleAudio.
        setCurrentAudioIndex(idx, { autoplay: false, seek: false });
        ensureAudioTimeInInput(item, { force: true });
        playSingleAudio(item, { autoplay: true });
        if (_isMobileAudioApp() && typeof window.setInterceptsMobilePanel === "function") {
          window.setInterceptsMobilePanel("audio");
        }
      }
    });
  }
  const mobileCardsEl = document.getElementById("audio-mobile-queue-cards");
  if (mobileCardsEl && !mobileCardsEl.dataset.bound) {
    mobileCardsEl.dataset.bound = "1";
    mobileCardsEl.addEventListener("click", async (ev) => {
      const toggle = ev.target && ev.target.closest ? ev.target.closest("[data-action='toggle-group']") : null;
      if (toggle) {
        const key = String(toggle.getAttribute("data-group-key") || "");
        if (key) {
          if (AUDIO_GROUP_EXPANDED.has(key)) AUDIO_GROUP_EXPANDED.delete(key);
          else AUDIO_GROUP_EXPANDED.add(key);
          renderAudioQueue();
        }
        return;
      }
      const card = ev.target && ev.target.closest ? ev.target.closest(".ix-audio-card--item") : null;
      if (!card) return;
      const fileKey = String(card.getAttribute("data-file-key") || "");
      let idx = fileKey ? AUDIO_QUEUE.findIndex((x) => String(x.file_key || "") === fileKey) : Number(card.dataset.idx || 0);
      const item = AUDIO_QUEUE[idx] || null;
      if (!item) return;
      await markListened(item);
      setCurrentAudioIndex(idx, { autoplay: false, seek: false });
      ensureAudioTimeInInput(item, { force: true });
      playSingleAudio(item, { autoplay: true });
      if (typeof window.setInterceptsMobilePanel === "function") {
        window.setInterceptsMobilePanel("audio");
      }
    });
  }
  const { waveform } = _audioEls();
  if (waveform) {
    let isSelecting = false;
    let selStart = 0;
    let selStartX = 0;
    const toTime = (clientX) => {
      const rect = waveform.getBoundingClientRect();
      const x = Math.max(0, Math.min(rect.width, clientX - rect.left));
      if (!AUDIO_WAVE_DURATION || rect.width <= 0) return 0;
      return (x / rect.width) * AUDIO_WAVE_DURATION;
    };
    const onWaveStart = (clientX) => {
      isSelecting = true;
      if (AUDIO_AUTO_LOOP_SEGMENT) _clearAudioAutoSegmentLoop();
      selStart = toTime(clientX);
      selStartX = clientX;
      AUDIO_SELECTION = { start: selStart, end: selStart };
      _scheduleWaveformOverlay();
    };
    const onWaveEnd = (clientX) => {
      if (!isSelecting) return;
      isSelecting = false;
      const end = toTime(clientX);
      const dragPx = Math.abs(clientX - selStartX);
      const dragSec = Math.abs(end - selStart);
      const isClick = dragPx < 8 && dragSec < 0.2;
      if (isClick && AUDIO_SEGMENTS.length) {
        const segIdx = _audioSegmentIndexAtTime(selStart);
        if (segIdx >= 0) {
          _seekToAudioSegment(segIdx, { autoplay: true, openCatalog: false });
          return;
        }
        if (audio) {
          try { audio.currentTime = Math.max(0, selStart + 0.01); } catch (_) { }
          AUDIO_PLAYHEAD_TIME = audio.currentTime || selStart;
          AUDIO_LAST_SEG_IDX = -1;
          _scheduleWaveformOverlay();
          audio.play().catch(() => { });
        }
        return;
      }
      if (AUDIO_SELECTION) AUDIO_SELECTION.end = end;
      if (AUDIO_SELECTION && AUDIO_WAVE_DURATION) {
        const minLen = 0.05;
        let s0 = Math.min(AUDIO_SELECTION.start, AUDIO_SELECTION.end);
        let s1 = Math.max(AUDIO_SELECTION.start, AUDIO_SELECTION.end);
        if (s1 - s0 < minLen) {
          s1 = Math.min(AUDIO_WAVE_DURATION, s0 + minLen);
          if (s1 - s0 < minLen) s0 = Math.max(0, s1 - minLen);
        }
        AUDIO_SELECTION.start = s0;
        AUDIO_SELECTION.end = s1;
        if (loopSegToggle) loopSegToggle.checked = true;
        AUDIO_LOOP_SEGMENT = true;
        if (audio) {
          try { audio.currentTime = Math.max(0, s0 + 0.01); } catch (_) { }
          audio.play().catch(() => { });
        }
        AUDIO_AUTO_LOOP_SEGMENT = false;
      }
      _scheduleWaveformOverlay();
    };
    waveform.addEventListener("mousedown", (ev) => onWaveStart(ev.clientX));
    window.addEventListener("mouseup", (ev) => onWaveEnd(ev.clientX));
    waveform.addEventListener("mousemove", (ev) => {
      if (!isSelecting || !AUDIO_SELECTION) return;
      AUDIO_SELECTION.end = toTime(ev.clientX);
      _scheduleWaveformOverlay();
    });
    waveform.addEventListener("pointerdown", (ev) => {
      if (ev.pointerType === "mouse") return;
      try { waveform.setPointerCapture(ev.pointerId); } catch (_) { }
      onWaveStart(ev.clientX);
    });
    waveform.addEventListener("pointerup", (ev) => {
      if (ev.pointerType === "mouse") return;
      onWaveEnd(ev.clientX);
    });
    waveform.addEventListener("pointermove", (ev) => {
      if (ev.pointerType === "mouse" || !isSelecting || !AUDIO_SELECTION) return;
      AUDIO_SELECTION.end = toTime(ev.clientX);
      _scheduleWaveformOverlay();
    });
    waveform.addEventListener("dblclick", (ev) => {
      const segIdx = _audioSegmentIndexAtTime(toTime(ev.clientX));
      if (segIdx >= 0) {
        _setAudioAutoSegmentLoop(segIdx, { autoplay: true });
        return;
      }
      AUDIO_SELECTION = null;
      AUDIO_LOOP_SEGMENT = false;
      AUDIO_AUTO_LOOP_SEGMENT = false;
      if (loopSegToggle) loopSegToggle.checked = false;
      _scheduleWaveformOverlay();
    });
  }
  if (audio) {
    audio.addEventListener("play", () => {
      _syncMd3AudioPlayButton();
    });
    audio.addEventListener("loadedmetadata", () => {
      _updateMd3AudioTimeRange();
    });
    audio.addEventListener("durationchange", () => {
      _updateMd3AudioTimeRange();
    });
    audio.addEventListener("ended", () => {
      if (AUDIO_LOOP_SEGMENT && AUDIO_SELECTION && AUDIO_WAVE_DURATION) {
        const s0 = Math.min(AUDIO_SELECTION.start, AUDIO_SELECTION.end);
        try { audio.currentTime = Math.max(0, s0 + 0.01); } catch (_) { }
        audio.play().catch(() => { });
        return;
      }
      const wantLoop = !!(loopToggle && loopToggle.checked) || !!audio.loop;
      if (wantLoop) {
        try { audio.currentTime = 0; } catch (_) { }
        audio.play().catch(() => { });
        return;
      }
      // Комбинированная дорожка — стоп в конце, без автоперехода.
      if (AUDIO_IS_COMBINED_TRACK) {
        _syncMd3AudioPlayButton();
        return;
      }
      playNextAudio({ autoplay: true, openCatalog: true }).catch(() => {
        _syncMd3AudioPlayButton();
      });
    });
    audio.addEventListener("pause", () => {
      clearListeningFileKey();
      _syncMd3AudioPlayButton();
      _updateMd3AudioTimeRange();
    });
    audio.addEventListener("timeupdate", () => {
      _updateMd3AudioTimeRange();
      AUDIO_PLAYHEAD_TIME = audio.currentTime || 0;
      _scheduleWaveformOverlay();
      const t = audio.currentTime || 0;
      if (AUDIO_LOOP_SEGMENT && AUDIO_SELECTION && AUDIO_WAVE_DURATION) {
        const s0 = Math.min(AUDIO_SELECTION.start, AUDIO_SELECTION.end);
        const s1 = Math.max(AUDIO_SELECTION.start, AUDIO_SELECTION.end);
        if (t < s0 || t >= s1) {
          try { audio.currentTime = Math.max(0, s0 + 0.01); } catch (_) { }
          return;
        }
      }
      _syncAudioPlayheadSegment(t);
    });
  }
  if (speedSelect) {
    speedSelect.addEventListener("change", () => {
      const v = Number(speedSelect.value || 1);
      audio.playbackRate = Number.isFinite(v) ? v : 1;
      try { localStorage.setItem(AUDIO_SPEED_KEY, String(speedSelect.value || "1")); } catch (_) { }
    });
    const v0 = Number(speedSelect.value || 1);
    audio.playbackRate = Number.isFinite(v0) ? v0 : 1;
  }
  if (loopToggle) {
    loopToggle.addEventListener("change", () => {
      audio.loop = !!loopToggle.checked;
      try { localStorage.setItem(AUDIO_LOOP_KEY, loopToggle.checked ? "1" : "0"); } catch (_) { }
    });
    audio.loop = !!loopToggle.checked;
  }
  if (loopSegToggle) {
    loopSegToggle.addEventListener("change", () => {
      AUDIO_LOOP_SEGMENT = !!loopSegToggle.checked;
      try { localStorage.setItem(AUDIO_LOOP_SEG_KEY, loopSegToggle.checked ? "1" : "0"); } catch (_) { }
    });
    AUDIO_LOOP_SEGMENT = !!loopSegToggle.checked;
  }
  if (filterId) {
    filterId.addEventListener("input", () => {
      AUDIO_FILTER_ID = String(filterId.value || "").trim();
      try { localStorage.setItem(AUDIO_FILTER_ID_KEY, AUDIO_FILTER_ID); } catch (_) { }
      renderAudioQueue();
    });
  }
  if (filterClear) {
    filterClear.addEventListener("click", () => {
      if (filterId) filterId.value = "";
      AUDIO_FILTER_ID = "";
      try { localStorage.setItem(AUDIO_FILTER_ID_KEY, ""); } catch (_) { }
      renderAudioQueue();
    });
  }
  if (taskAddBtn) taskAddBtn.addEventListener("click", addAudioTask);
  if (taskList) {
    taskList.addEventListener("click", (ev) => {
      const btn = ev.target && ev.target.closest ? ev.target.closest("[data-task-id]") : null;
      if (!btn) return;
      const tid = Number(btn.getAttribute("data-task-id") || 0);
      const action = String(btn.getAttribute("data-task-action") || "");
      if (action === "delete") {
        deleteAudioTask(tid);
        return;
      }
      if (action === "toggle") {
        const t = (AUDIO_TASKS || []).find((x) => Number(x.id || 0) === tid);
        toggleAudioTask(tid, t && t.is_active);
      }
    });
  }
  if (taskFromActiveBtn) {
    taskFromActiveBtn.addEventListener("click", () => {
      if (!ACTIVE_CAT || !ACTIVE_CAT.frequency || !ACTIVE_CAT.group_code) {
        setText("intercepts-status", "Сначала выбери группу слева.");
        return;
      }
      const { taskFreq, taskName } = _audioEls();
      if (taskFreq) taskFreq.value = ACTIVE_CAT.frequency || "";
      if (taskName) taskName.value = ACTIVE_CAT.unit_name || "";
    });
  }
  if (debugBtn) debugBtn.addEventListener("click", runAudioDebug);
  if (refreshFullBtn) {
    refreshFullBtn.addEventListener("click", () => refreshAudioQueue({ fullScan: true }));
  }
  if (ASR_UI_ENABLED) {
    initAsrBootstrap();
    loadAsrModelStatus().catch(() => { });
    apiGet("/api/intercepts/asr/settings")
      .then((res) => asrApplySettingsToUi(res && res.settings ? res.settings : {}))
      .catch(() => { });
  }

  loadAudioState().then(() => {
    loadAudioTasks().then(() => {
      if (!isBundleLayoutMode() && !AUDIO_TASKS_RUNNING) {
        AUDIO_TASKS_RUNNING = true;
        _scheduleAudioStateSave({ is_running: true });
      }
      if (tasksRunToggle) tasksRunToggle.checked = !!AUDIO_TASKS_RUNNING;
      const folderPath = getAudioFolderPath();
      if (folderPath && !isBundleLayoutMode()) refreshAudioQueue();
      else if (folderPath && isBundleLayoutMode()) _setAudioStatus("Нажмите «Сканировать» для загрузки папки.");
      startAudioPolling();
      _setAudioStatus("");
    });
  });
}

  window.initAudioUi = initAudioUi;
  window.refreshAudioQueue = refreshAudioQueue;
  window.getAudioFolderPath = getAudioFolderPath;
  window.openAudioCatalog = openAudioCatalog;
  window._currentAudioItem = _currentAudioItem;

