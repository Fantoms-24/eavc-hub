
async function saveAsrSettings() {
  const settings = asrReadSettingsFromUi();
  const data = await apiPost("/api/intercepts/asr/settings", settings);
  asrApplySettingsToUi(data && data.settings ? data.settings : settings);
}

async function buildAsrDataset() {
  const settings = asrReadSettingsFromUi();
  const queued = await apiPost("/api/intercepts/asr/dataset-build", {
    min_alignment_score: settings.min_alignment_score,
  });
  if (!queued || !queued.job_id) return queued;
  _setAudioStatus("ASR dataset: задача в очереди...");
  const job = await waitAsrJob(queued.job_id, "ASR dataset");
  return job.result || {};
}

async function trainAsrModel() {
  const settings = asrReadSettingsFromUi();
  const queued = await apiPost("/api/intercepts/asr/train", {
    base_model: settings.whisper_model_name,
    activate: settings.auto_activate,
  });
  if (!queued || !queued.job_id) return queued;
  _setAudioStatus("ASR train: задача в очереди...");
  const job = await waitAsrJob(queued.job_id, "ASR train");
  return job.result || {};
}

function sleepAsrJob(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitAsrJob(jobId, label) {
  const id = Number(jobId || 0);
  if (!id) throw new Error("Сервер не вернул job_id");
  let delay = 1200;
  for (;;) {
    if (document.hidden) {
      await sleepAsrJob(Math.max(delay, 10000));
      continue;
    }
    const data = await apiGet(`/api/analysis/ai/jobs/${encodeURIComponent(id)}`);
    const job = data.job || {};
    const status = String(job.status || "").toLowerCase();
    if (status === "completed") return job;
    if (status === "failed" || status === "cancelled") {
      throw new Error(job.error_text || `${label || "ASR"} завершился с ошибкой`);
    }
    _setAudioStatus(`${label || "ASR"}: ${status === "pending" ? "в очереди" : "выполняется"}...`);
    await sleepAsrJob(delay);
    delay = Math.min(5000, Math.round(delay * 1.3));
  }
}

async function activateAsrModelSelected() {
  const { asrModelSelect } = _audioEls();
  const modelVersion = String(asrModelSelect ? asrModelSelect.value : "").trim();
  if (!modelVersion) throw new Error("Выбери модель для активации");
  await apiPost("/api/intercepts/asr/model-activate", { model_version: modelVersion });
}

function _hasActiveAudioTrack() {
  const { audio } = _audioEls();
  if (AUDIO_SEGMENTS.length || AUDIO_CURRENT_INDEX >= 0) return true;
  if (audio && String(audio.src || "").trim()) return true;
  return false;
}

function _syncAsrPlayerHintVisibility(show) {
  const { audioAsrHintWrap } = _audioEls();
  if (!audioAsrHintWrap) return;
  audioAsrHintWrap.hidden = !show;
}

function _setAsrPlayerHintStatus(message) {
  const { asrCurrentStatus, audioAsrHintStatus } = _audioEls();
  const msg = String(message || "").trim();
  if (audioAsrHintStatus) audioAsrHintStatus.textContent = msg;
  if (asrCurrentStatus && msg) asrCurrentStatus.textContent = msg;
  if (msg && _hasActiveAudioTrack()) _syncAsrPlayerHintVisibility(true);
}

function renderAsrTranscript(tr) {
  const {
    asrCurrentStatus,
    asrTranscriptRu,
    asrTranscriptUa,
    asrTranscriptMeta,
    asrSendToInputBtn,
    audioAsrHintText,
    audioAsrHintStatus,
    audioAsrHintSendBtn,
  } = _audioEls();
  ASR_LAST_TRANSCRIPT = tr || null;
  const trackActive = _hasActiveAudioTrack();
  if (!tr) {
    if (asrCurrentStatus) asrCurrentStatus.textContent = trackActive ? "Расшифровка не найдена" : "Выбери аудио из списка";
    if (asrTranscriptRu) asrTranscriptRu.textContent = "—";
    if (asrTranscriptUa) asrTranscriptUa.textContent = "—";
    if (asrTranscriptMeta) asrTranscriptMeta.textContent = "—";
    if (asrSendToInputBtn) asrSendToInputBtn.disabled = true;
    if (audioAsrHintText) audioAsrHintText.textContent = trackActive ? "—" : "—";
    if (audioAsrHintStatus) audioAsrHintStatus.textContent = trackActive ? "" : "";
    if (audioAsrHintSendBtn) audioAsrHintSendBtn.disabled = true;
    _syncAsrPlayerHintVisibility(trackActive);
    return;
  }
  const formatted = String(tr.formatted_text || tr.ru_text || "—");
  const statusText = tr.status === "done"
    ? `готово • conf ${Number(tr.confidence || 0).toFixed(2)}`
    : `Статус: ${tr.status || "—"}`;
  if (asrCurrentStatus) {
    asrCurrentStatus.textContent = tr.status === "done" ? "Как услышала нейросеть (формат бланка)" : `Статус: ${tr.status || "—"}`;
  }
  if (asrTranscriptRu) {
    asrTranscriptRu.textContent = formatted;
    asrTranscriptRu.style.whiteSpace = "pre-wrap";
  }
  if (audioAsrHintText) audioAsrHintText.textContent = formatted;
  if (audioAsrHintStatus) audioAsrHintStatus.textContent = statusText;
  if (asrTranscriptUa) asrTranscriptUa.textContent = String(tr.ua_text || "—");
  if (asrTranscriptMeta) {
    asrTranscriptMeta.textContent = `conf=${Number(tr.confidence || 0).toFixed(3)} • model=${tr.model_version || "—"} • updated=${tr.updated_at || "—"}`;
  }
  const canSend = !!(formatted && formatted !== "—" && tr.status === "done");
  if (asrSendToInputBtn) asrSendToInputBtn.disabled = !canSend;
  if (audioAsrHintSendBtn) audioAsrHintSendBtn.disabled = !canSend;
  _syncAsrPlayerHintVisibility(trackActive);
}

function _asrActiveFileKey() {
  if (AUDIO_SEGMENTS.length > 1 && AUDIO_IS_COMBINED_TRACK) {
    const firstItem = (AUDIO_SEGMENTS[0] && (AUDIO_SEGMENTS[0].item || AUDIO_SEGMENTS[0])) || null;
    const groupKey = AUDIO_CURRENT_GROUP_KEY || _asrGroupKeyFromItem(firstItem);
    return _asrTranscriptFileKeyForGroup(groupKey);
  }
  const it = ASR_CURRENT_ITEM;
  return it && it.file_key ? String(it.file_key) : "";
}

async function _requestAsrTranscription(payload, opts = {}) {
  const seq = ++ASR_TRANSCRIBE_SEQ;
  _setAsrPlayerHintStatus("Запуск расшифровки…");
  _syncAsrPlayerHintVisibility(true);
  const out = await apiPost("/api/intercepts/asr/transcribe", payload);
  if (seq !== ASR_TRANSCRIBE_SEQ) return out;
  if (out && out.transcript) {
    renderAsrTranscript(out.transcript);
    return out;
  }
  if (out && out.job_id) {
    if (opts.blocking) {
      const job = await waitAsrJob(out.job_id, "ASR transcribe");
      const result = job.result || {};
      renderAsrTranscript(result.transcript || null);
      return result;
    }
    startBackgroundAsrJobPoll(out.job_id, "ASR");
    return out;
  }
  renderAsrTranscript(null);
  return out;
}

async function loadAsrTranscriptForGroup(groupKey, segments, opts = {}) {
  const gk = String(groupKey || "").trim();
  const segs = Array.isArray(segments) ? segments : [];
  if (!gk || !segs.length) {
    renderAsrTranscript(null);
    return;
  }
  const fileKey = _asrTranscriptFileKeyForGroup(gk);
  const q = new URLSearchParams({ file_key: fileKey });
  const data = await apiGet(`/api/intercepts/asr/transcript?${q.toString()}`);
  const tr = data && data.transcript ? data.transcript : null;
  if (tr && tr.status === "done" && !opts.force) {
    renderAsrTranscript(tr);
    return;
  }
  if (!opts || !opts.autoTranscribe) {
    renderAsrTranscript(tr);
    return;
  }
  const folderPath = getAudioFolderPath();
  const first = (segs[0] && (segs[0].item || segs[0])) || {};
  try {
    await _requestAsrTranscription(
      {
        mode: "group",
        group_key: gk,
        file_key: fileKey,
        folder_path: folderPath,
        recorded_at: String(first.recorded_at || ""),
        frequency: String(first.frequency || ""),
        group_code: String(first.group_code || ""),
        force: !!opts.force,
        segments: segs.map((s) => {
          const it = s.item || s;
          return {
            file_key: String(it.file_key || ""),
            file_rel: String(it.file_rel || ""),
            correspondent_id: _correspondentIdFromItem(it),
            recorded_at: String(it.recorded_at || ""),
            has_key: !!it.has_key,
            has_message: !!it.has_message,
            duration_sec: Number(it.duration_sec || 0),
            frequency: String(it.frequency || ""),
            group_code: String(it.group_code || ""),
          };
        }),
      },
      { blocking: !!opts.blocking }
    );
  } catch (e) {
    const { asrCurrentStatus } = _audioEls();
    if (asrCurrentStatus) asrCurrentStatus.textContent = `ASR ошибка: ${e.message || e}`;
  }
}

async function loadAsrTranscriptForItem(item, opts = {}) {
  const it = item || ASR_CURRENT_ITEM;
  if (!it || !it.file_key) {
    renderAsrTranscript(null);
    return;
  }
  const q = new URLSearchParams({ file_key: String(it.file_key || "") });
  const data = await apiGet(`/api/intercepts/asr/transcript?${q.toString()}`);
  const tr = data && data.transcript ? data.transcript : null;
  if (tr && tr.status === "done" && !opts.force) {
    renderAsrTranscript(tr);
    return;
  }
  if (opts && opts.autoTranscribe) {
    try {
      await _requestAsrTranscription(
        {
          mode: "file",
          file_key: String(it.file_key || ""),
          folder_path: String(it.folder_path || getAudioFolderPath() || ""),
          file_rel: String(it.file_rel || ""),
          frequency: String(it.frequency || ""),
          group_code: String(it.group_code || ""),
          correspondent_id: String(it.correspondent_id || ""),
          recorded_at: String(it.recorded_at || ""),
          duration_sec: Number(it.duration_sec || 0),
          force: !!opts.force,
        },
        { blocking: !!opts.blocking }
      );
    } catch (e) {
      const { asrCurrentStatus } = _audioEls();
      if (asrCurrentStatus) asrCurrentStatus.textContent = `ASR ошибка: ${e.message || e}`;
    }
  } else {
    renderAsrTranscript(tr);
  }
}

async function transcribeCurrentAudioNow() {
  if (AUDIO_SEGMENTS.length > 1 && AUDIO_IS_COMBINED_TRACK) {
    const firstItem = (AUDIO_SEGMENTS[0] && (AUDIO_SEGMENTS[0].item || AUDIO_SEGMENTS[0])) || null;
    const groupKey = AUDIO_CURRENT_GROUP_KEY || _asrGroupKeyFromItem(firstItem);
    return loadAsrTranscriptForGroup(groupKey, AUDIO_SEGMENTS, {
      autoTranscribe: true,
      force: true,
      blocking: true,
    });
  }
  const it = ASR_CURRENT_ITEM;
  if (!it || !it.file_key) throw new Error("Сначала выбери аудио");
  return loadAsrTranscriptForItem(it, { autoTranscribe: true, force: true, blocking: true });
}

async function loadAsrTrainingPolicy() {
  if (!ASR_UI_ENABLED) return;
  try {
    const data = await apiGet("/api/intercepts/asr/training-policy");
    if (data && data.policy) ASR_TRAINING_POLICY = data.policy;
  } catch (_) { /* ignore */ }
}

function _asrSegmentsPayloadForLearning() {
  const segs = Array.isArray(AUDIO_SEGMENTS) ? AUDIO_SEGMENTS : [];
  return segs.map((s) => {
    const it = s.item || s;
    return {
      file_key: String(it.file_key || ""),
      file_rel: String(it.file_rel || ""),
      correspondent_id: _correspondentIdFromItem(it),
      has_key: !!it.has_key,
      has_message: !!it.has_message,
      duration_sec: Number(it.duration_sec || 0),
      frequency: String(it.frequency || ""),
      group_code: String(it.group_code || ""),
    };
  }).filter((x) => x.file_key && x.file_rel);
}

async function maybeLearnAsrFromBlankSend(operatorText) {
  if (!ASR_UI_ENABLED || !ASR_TRAINING_POLICY.training_enabled || !ASR_TRAINING_POLICY.learn_on_blank_send) {
    return null;
  }
  const text = String(operatorText || "").trim();
  if (!text) return null;
  const segments = _asrSegmentsPayloadForLearning();
  if (!segments.length) return null;
  const pred = ASR_LAST_TRANSCRIPT
    ? String(ASR_LAST_TRANSCRIPT.formatted_text || ASR_LAST_TRANSCRIPT.ru_text || "")
    : "";
  return apiPost("/api/intercepts/asr/learn-from-blank", {
    operator_text: text,
    prediction_text: pred,
    folder_path: getAudioFolderPath(),
    segments,
  });
}

async function sendAsrFeedback(isOk) {
  const fileKey = _asrActiveFileKey();
  if (!fileKey) throw new Error("Сначала выбери аудио");
  const pred = ASR_LAST_TRANSCRIPT ? String(ASR_LAST_TRANSCRIPT.formatted_text || ASR_LAST_TRANSCRIPT.ru_text || "") : "";
  let corrected = "";
  if (!isOk) {
    corrected = window.prompt("Введи корректный текст для обучения:", pred) || "";
    if (!corrected.trim()) return;
  }
  return apiPost("/api/intercepts/asr/feedback", {
    file_key: fileKey,
    prediction_text: pred,
    corrected_text: isOk ? "" : corrected.trim(),
    feedback_label: isOk ? "confirmed" : "corrected",
  });
}
function _asrGroupKeyFromItem(item) {
  return _audioSessionGroupKey(item);
}

function _asrTranscriptFileKeyForGroup(groupKey) {
  return `asr-group:${String(groupKey || "").trim()}`;
}

function stopBackgroundAsrJobPoll() {
  if (ASR_BACKGROUND_POLL_TIMER) {
    clearTimeout(ASR_BACKGROUND_POLL_TIMER);
    ASR_BACKGROUND_POLL_TIMER = null;
  }
  ASR_PENDING_JOB_ID = 0;
}

function startBackgroundAsrJobPoll(jobId, label) {
  const id = Number(jobId || 0);
  if (!id) return;
  stopBackgroundAsrJobPoll();
  ASR_PENDING_JOB_ID = id;
  const poll = async () => {
    if (!ASR_PENDING_JOB_ID || ASR_PENDING_JOB_ID !== id) return;
    try {
      const data = await apiGet(`/api/analysis/ai/jobs/${encodeURIComponent(id)}`);
      const job = data.job || {};
      const status = String(job.status || "").toLowerCase();
      if (status === "completed") {
        stopBackgroundAsrJobPoll();
        const result = job.result || {};
        renderAsrTranscript(result.transcript || null);
        _setAsrPlayerHintStatus("Расшифровка готова");
        return;
      }
      if (status === "failed" || status === "cancelled") {
        stopBackgroundAsrJobPoll();
        _setAsrPlayerHintStatus(`Ошибка: ${job.error_text || "расшифровка не удалась"}`);
        return;
      }
      _setAsrPlayerHintStatus(`${label || "ASR"}: ${status === "pending" ? "в очереди" : "расшифровывает…"}`);
    } catch (_) { }
    ASR_BACKGROUND_POLL_TIMER = setTimeout(poll, 2000);
  };
  poll();
}

function renderAsrBootstrapStatus(data) {
  const { asrBootstrapStatus } = _audioEls();
  if (!asrBootstrapStatus) return;
  const st = data && data.bootstrap ? data.bootstrap : {};
  const state = String(st.state || "idle");
  const msg = String(st.message || "");
  if (state === "ready" || st.ready) {
    asrBootstrapStatus.textContent = `Модель Whisper (${st.model || "tiny"}) готова`;
    asrBootstrapStatus.classList.remove("text-warning", "text-danger");
    asrBootstrapStatus.classList.add("text-success");
    return;
  }
  if (state === "downloading" || state === "checking") {
    asrBootstrapStatus.textContent = msg || "Загрузка модели…";
    asrBootstrapStatus.classList.remove("text-success", "text-danger");
    asrBootstrapStatus.classList.add("text-warning");
    return;
  }
  if (state === "offline") {
    asrBootstrapStatus.textContent = msg || "Нет интернета — модель загрузится позже";
    asrBootstrapStatus.classList.remove("text-success", "text-danger");
    asrBootstrapStatus.classList.add("text-warning");
    return;
  }
  if (state === "unavailable") {
    asrBootstrapStatus.textContent = msg || "ASR недоступен — модуль не установлен";
    asrBootstrapStatus.classList.remove("text-success", "text-danger");
    asrBootstrapStatus.classList.add("text-warning");
    return;
  }
  if (state === "error") {
    asrBootstrapStatus.textContent = msg || "Ошибка загрузки модели";
    asrBootstrapStatus.classList.remove("text-success", "text-warning");
    asrBootstrapStatus.classList.add("text-danger");
    return;
  }
  asrBootstrapStatus.textContent = msg || "Подготовка ASR…";
}

async function pollAsrBootstrapStatus() {
  try {
    const data = await apiGet("/api/intercepts/asr/bootstrap");
    renderAsrBootstrapStatus(data || {});
    const st = data && data.bootstrap ? data.bootstrap : {};
    // "unavailable" — терминальное состояние (модуль не установлен): не опрашиваем повторно.
    const terminal = st.ready || st.state === "ready" || st.state === "unavailable";
    if (!terminal) {
      if (!ASR_BOOTSTRAP_TIMER) {
        ASR_BOOTSTRAP_TIMER = setTimeout(() => {
          ASR_BOOTSTRAP_TIMER = null;
          pollAsrBootstrapStatus().catch(() => { });
        }, 4000);
      }
    }
  } catch (_) { }
}

function initAsrBootstrap() {
  pollAsrBootstrapStatus().catch(() => { });
}

async function queueAsrForCurrentTrack(opts = {}) {
  if (!ASR_UI_ENABLED) return;
  const folderPath = getAudioFolderPath();
  if (!folderPath) return;
  _syncAsrPlayerHintVisibility(true);
  if (opts && opts.autoTranscribe) {
    _setAsrPlayerHintStatus("Подготовка расшифровки…");
  }
  if (AUDIO_SEGMENTS.length > 1 && AUDIO_IS_COMBINED_TRACK) {
    const firstItem = (AUDIO_SEGMENTS[0] && (AUDIO_SEGMENTS[0].item || AUDIO_SEGMENTS[0])) || null;
    const groupKey = AUDIO_CURRENT_GROUP_KEY || _asrGroupKeyFromItem(firstItem);
    await loadAsrTranscriptForGroup(groupKey, AUDIO_SEGMENTS, opts);
    return;
  }
  const item = ASR_CURRENT_ITEM;
  if (item && item.file_key) {
    await loadAsrTranscriptForItem(item, opts);
  }
}

function sendAsrTextToInput() {
  const tr = ASR_LAST_TRANSCRIPT;
  const text = tr ? String(tr.formatted_text || tr.ru_text || "").trim() : "";
  if (!text) return;
  const input = $("intercept-input");
  if (!input) return;
  const prev = String(input.value || "").trim();
  input.value = prev ? `${prev}\n${text}` : text;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.focus();
}

function asrReadSettingsFromUi() {
  const {
    asrWhisperModel,
    asrEpochs,
    asrBatchSize,
    asrLearningRate,
    asrMinAlign,
    asrRetrainMin,
    asrAutoActivate,
    asrAutoRetrain,
  } = _audioEls();
  return {
    whisper_model_name: String(asrWhisperModel ? asrWhisperModel.value : "small").trim() || "small",
    epochs: Math.max(1, Number(asrEpochs ? asrEpochs.value : 6) || 6),
    batch_size: Math.max(1, Number(asrBatchSize ? asrBatchSize.value : 8) || 8),
    learning_rate: Math.max(0.000001, Number(asrLearningRate ? asrLearningRate.value : 0.0001) || 0.0001),
    min_alignment_score: Math.max(0, Math.min(1, Number(asrMinAlign ? asrMinAlign.value : 0.35) || 0.35)),
    auto_retrain_min_samples: Math.max(1, Number(asrRetrainMin ? asrRetrainMin.value : 40) || 40),
    auto_activate: !!(asrAutoActivate && asrAutoActivate.checked),
    auto_retrain: !!(asrAutoRetrain && asrAutoRetrain.checked),
  };
}

function asrApplySettingsToUi(settings) {
  const s = settings || {};
  const {
    asrWhisperModel,
    asrEpochs,
    asrBatchSize,
    asrLearningRate,
    asrMinAlign,
    asrRetrainMin,
    asrAutoActivate,
    asrAutoRetrain,
  } = _audioEls();
  if (asrWhisperModel) {
    const m = String(s.whisper_model_name || "small").trim();
    asrWhisperModel.value = (m === "tiny" || m === "openai/whisper-tiny") ? "small" : m;
  }
  if (asrEpochs) asrEpochs.value = String(Number(s.epochs || 6));
  if (asrBatchSize) asrBatchSize.value = String(Number(s.batch_size || 8));
  if (asrLearningRate) asrLearningRate.value = String(Number(s.learning_rate || 0.0001));
  if (asrMinAlign) asrMinAlign.value = String(Number(s.min_alignment_score || 0.35));
  if (asrRetrainMin) asrRetrainMin.value = String(Number(s.auto_retrain_min_samples || 40));
  if (asrAutoActivate) asrAutoActivate.checked = !!s.auto_activate;
  if (asrAutoRetrain) asrAutoRetrain.checked = !!s.auto_retrain;
}

function asrRenderStatus(data) {
  const {
    asrModelActive,
    asrModelMetrics,
    asrDiagnostics,
    asrModelRuns,
    asrModelSelect,
  } = _audioEls();
  const active = data && data.active_model ? data.active_model : null;
  const models = Array.isArray(data && data.models ? data.models : []) ? data.models : [];
  const diagnostics = data && data.diagnostics ? data.diagnostics : {};
  if (asrModelActive) asrModelActive.textContent = active ? `Активная модель: ${active.model_version || "—"}` : "Активная модель: отсутствует";
  if (asrModelMetrics) {
    const m = active && active.metrics ? active.metrics : {};
    asrModelMetrics.textContent = active
      ? `Метрики: wer=${Number(m.val_wer || 0).toFixed(3)}, cer=${Number(m.val_cer || 0).toFixed(3)}`
      : "Метрики: —";
  }
  if (asrDiagnostics) {
    asrDiagnostics.textContent = `Диагностика: samples=${Number(diagnostics.validated_samples || 0)}, feedback=${Number(diagnostics.validated_feedback || 0)}, retrain=${diagnostics.retrain_recommended ? "да" : "нет"}`;
  }
  if (asrModelRuns) {
    asrModelRuns.textContent = models.length
      ? `Последние модели: ${models.slice(0, 4).map((x) => String(x.model_version || "—")).join(", ")}`
      : "Последние модели: —";
  }
  if (asrModelSelect) {
    const current = String(asrModelSelect.value || "");
    asrModelSelect.innerHTML = "";
    if (!models.length) {
      const o = document.createElement("option");
      o.value = "";
      o.textContent = "Нет моделей";
      asrModelSelect.appendChild(o);
    } else {
      models.forEach((m) => {
        const o = document.createElement("option");
        o.value = String(m.model_version || "");
        o.textContent = `${m.model_version || "—"}${m.is_active ? " (active)" : ""}`;
        asrModelSelect.appendChild(o);
      });
    }
    if (current && models.some((m) => String(m.model_version || "") === current)) {
      asrModelSelect.value = current;
    } else if (active && active.model_version) {
      asrModelSelect.value = String(active.model_version);
    }
  }
  asrApplySettingsToUi(data && data.settings ? data.settings : {});
}

async function loadAsrModelStatus() {
  const data = await apiGet("/api/intercepts/asr/model-status");
  asrRenderStatus(data || {});
}


window.queueAsrForCurrentTrack = queueAsrForCurrentTrack;
window.initAsrBootstrap = initAsrBootstrap;
window.loadAsrTrainingPolicy = loadAsrTrainingPolicy;
window.maybeLearnAsrFromBlankSend = maybeLearnAsrFromBlankSend;
window.sendAsrTextToInput = sendAsrTextToInput;
window.transcribeCurrentAudioNow = transcribeCurrentAudioNow;
window.saveAsrSettings = saveAsrSettings;
window.buildAsrDataset = buildAsrDataset;
window.trainAsrModel = trainAsrModel;
window.activateAsrModelSelected = activateAsrModelSelected;
window.sendAsrFeedback = sendAsrFeedback;
window.asrApplySettingsToUi = asrApplySettingsToUi;
window.loadAsrModelStatus = loadAsrModelStatus;
