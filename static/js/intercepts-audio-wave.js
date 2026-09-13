async function buildWaveformForSingle(item) {
  const { audio } = _audioEls();
  if (!audio || !item || !item.file_rel) return;
  const folderPath = getAudioFolderPath();
  if (!folderPath) return;
  const qs = new URLSearchParams();
  qs.set("folder_path", folderPath);
  qs.set("file_rel", item.file_rel);
  const res = await fetch(`/api/intercepts/audio/file?${qs.toString()}`);
  if (!res.ok) return;
  const arr = await res.arrayBuffer();
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const buf = await ctx.decodeAudioData(arr);
  AUDIO_SEGMENTS = [
    {
      item,
      startSec: 0,
      duration: buf.duration,
      segmentIndex: 0,
    },
  ];
  AUDIO_WAVE_DURATION = buf.duration || 0;
  if (item) item._duration = buf.duration;
  drawWaveform(buf);
  try { ctx.close(); } catch (_) { }
}

function _ensureWaveBaseCanvas(w, h) {
  if (!AUDIO_WAVE_BASE_CANVAS) {
    AUDIO_WAVE_BASE_CANVAS = document.createElement("canvas");
    AUDIO_WAVE_BASE_CTX = AUDIO_WAVE_BASE_CANVAS.getContext("2d");
  }
  if (AUDIO_WAVE_BASE_CANVAS.width !== w || AUDIO_WAVE_BASE_CANVAS.height !== h) {
    AUDIO_WAVE_BASE_CANVAS.width = w;
    AUDIO_WAVE_BASE_CANVAS.height = h;
  }
}

function _buildWaveformBase(buffer, w, h) {
  if (!AUDIO_WAVE_BASE_CTX) return;
  const ctx = AUDIO_WAVE_BASE_CTX;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#f1f4fb";
  ctx.fillRect(0, 0, w, h);

  // цветные зоны по корреспондентам
  if (AUDIO_SEGMENTS.length && buffer.duration) {
    AUDIO_SEGMENTS.forEach((seg) => {
      const cid = _correspondentIdFromSegment(seg);
      const col = _colorForCode(cid);
      const x1 = Math.floor((seg.startSec / buffer.duration) * w);
      const x2 = Math.floor(((seg.startSec + seg.duration) / buffer.duration) * w);
      ctx.fillStyle = (col.line || "rgba(37,99,235,0.15)");
      ctx.globalAlpha = 0.18;
      ctx.fillRect(x1, 0, Math.max(1, x2 - x1), h);
      ctx.globalAlpha = 1;
    });
  }

  const data = buffer.getChannelData(0);
  const step = Math.max(1, Math.floor(data.length / w));
  const mins = new Float32Array(w);
  const maxs = new Float32Array(w);
  for (let x = 0; x < w; x++) {
    const start = x * step;
    let min = 1.0;
    let max = -1.0;
    for (let i = 0; i < step; i++) {
      const v = data[start + i] || 0;
      if (v < min) min = v;
      if (v > max) max = v;
    }
    mins[x] = min;
    maxs[x] = max;
  }

  // базовая волна (нейтральная)
  ctx.strokeStyle = "rgba(29, 78, 216, 0.22)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let x = 0; x < w; x++) {
    const y1 = (1 + mins[x]) * 0.5 * h;
    const y2 = (1 + maxs[x]) * 0.5 * h;
    ctx.moveTo(x, y1);
    ctx.lineTo(x, y2);
  }
  ctx.stroke();

  // цветные волны по сегментам/ID
  if (AUDIO_SEGMENTS.length && buffer.duration) {
    AUDIO_SEGMENTS.forEach((seg) => {
      const cid = _correspondentIdFromSegment(seg);
      const col = _colorForCode(cid);
      const x1 = Math.floor((seg.startSec / buffer.duration) * w);
      const x2 = Math.floor(((seg.startSec + seg.duration) / buffer.duration) * w);
      ctx.strokeStyle = col.line || "#2563eb";
      ctx.lineWidth = 1.35;
      ctx.beginPath();
      for (let x = Math.max(0, x1); x < Math.min(w, x2); x++) {
        const y1 = (1 + mins[x]) * 0.5 * h;
        const y2 = (1 + maxs[x]) * 0.5 * h;
        ctx.moveTo(x, y1);
        ctx.lineTo(x, y2);
      }
      ctx.stroke();
    });
  }

  // границы сегментов; подписи только если сегмент достаточно широкий (на длинной дорожке иначе нечитаемо)
  if (AUDIO_SEGMENTS.length && buffer.duration) {
    let labelRow = 0;
    ctx.font = "bold 11px ui-monospace, Menlo, Consolas, monospace";
    AUDIO_SEGMENTS.forEach((seg) => {
      const x = Math.floor((seg.startSec / buffer.duration) * w);
      const cid = _correspondentIdFromSegment(seg);
      const col = _colorForCode(cid);
      ctx.strokeStyle = col.line || "rgba(0,0,0,0.25)";
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
      if (!cid) return;
      const x1 = Math.floor((seg.startSec / buffer.duration) * w);
      const x2 = Math.floor(((seg.startSec + seg.duration) / buffer.duration) * w);
      const segW = Math.max(0, x2 - x1);
      const isNoise = _audioSegmentIsNoise(seg);
      if (isNoise && segW >= 6) {
        const cx = x1 + segW / 2;
        ctx.save();
        ctx.fillStyle = "#dc2626";
        ctx.font = "bold 14px system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillText("!", Math.min(w - 3, Math.max(3, cx)), 1);
        ctx.restore();
      }
      const textW = ctx.measureText(cid).width + 10;
      if (segW < textW) return;
      const padX = 4;
      const tx = Math.max(x1 + padX, Math.min(x2 - padX - textW, x1 + (segW - textW) / 2));
      const ty = 12 + (labelRow % 2) * 14 + (isNoise ? 4 : 0);
      labelRow += 1;
      ctx.save();
      ctx.fillStyle = col.bg || "#fff";
      ctx.strokeStyle = isNoise ? "#dc2626" : (col.border || "#94a3b8");
      ctx.lineWidth = isNoise ? 1.5 : 1;
      ctx.fillRect(tx - 2, ty - 10, textW, 14);
      ctx.strokeRect(tx - 2, ty - 10, textW, 14);
      ctx.fillStyle = col.text || "#111827";
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(cid, tx, ty - 3);
      ctx.restore();
    });
  }
}

function _drawWaveformOverlay() {
  const { waveform } = _audioEls();
  if (!waveform || !AUDIO_WAVE_BASE_CANVAS || !AUDIO_WAVE_BUFFER) return;
  const w = waveform.clientWidth || 600;
  const h = waveform.clientHeight || 120;
  waveform.width = w;
  waveform.height = h;
  if (AUDIO_WAVE_BASE_CANVAS.width !== w || AUDIO_WAVE_BASE_CANVAS.height !== h) {
    _ensureWaveBaseCanvas(w, h);
    _buildWaveformBase(AUDIO_WAVE_BUFFER, w, h);
  }
  const ctx = waveform.getContext("2d");
  if (!ctx) return;
  ctx.clearRect(0, 0, w, h);
  ctx.drawImage(AUDIO_WAVE_BASE_CANVAS, 0, 0);

  // выделение
  if (AUDIO_SELECTION && AUDIO_WAVE_DURATION) {
    const x1 = Math.floor((AUDIO_SELECTION.start / AUDIO_WAVE_DURATION) * w);
    const x2 = Math.floor((AUDIO_SELECTION.end / AUDIO_WAVE_DURATION) * w);
    const left = Math.max(0, Math.min(x1, x2));
    const right = Math.min(w, Math.max(x1, x2));
    ctx.fillStyle = "rgba(29, 78, 216, 0.12)";
    ctx.fillRect(left, 0, Math.max(2, right - left), h);
    ctx.strokeStyle = "rgba(29, 78, 216, 0.4)";
    ctx.strokeRect(left, 0, Math.max(2, right - left), h);
  }

  // подсветка текущего сегмента (по позиции playhead, не только по индексу клика)
  const playSegIdx = _audioSegmentIndexAtTime(AUDIO_PLAYHEAD_TIME);
  if (AUDIO_SEGMENTS.length && AUDIO_WAVE_DURATION > 0 && playSegIdx >= 0) {
    const cur = AUDIO_SEGMENTS[playSegIdx];
    if (cur) {
      const cid = _correspondentIdFromSegment(cur);
      const col = _colorForCode(cid);
      const x1 = Math.floor((cur.startSec / AUDIO_WAVE_DURATION) * w);
      const x2 = Math.floor(((cur.startSec + (cur.duration || 0)) / AUDIO_WAVE_DURATION) * w);
      ctx.fillStyle = col.line || "rgba(29, 78, 216, 0.18)";
      ctx.globalAlpha = 0.22;
      ctx.fillRect(x1, 0, Math.max(2, x2 - x1), h);
      ctx.globalAlpha = 1;
    }
  }

  // playhead + время + ID корреспондента
  if (AUDIO_WAVE_DURATION > 0) {
    const x = Math.max(
      0,
      Math.min(
        Math.max(0, w - 1),
        Math.floor((AUDIO_PLAYHEAD_TIME / AUDIO_WAVE_DURATION) * w)
      )
    );
    ctx.strokeStyle = "rgba(29, 78, 216, 0.92)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
    const playCid = playSegIdx >= 0 ? _correspondentIdFromSegment(AUDIO_SEGMENTS[playSegIdx]) : "";
    const timeLabel = formatDuration(AUDIO_PLAYHEAD_TIME);
    const idLabel = playCid || "";
    ctx.font = "10px sans-serif";
    const timeW = ctx.measureText(timeLabel).width + 8;
    const idW = idLabel ? ctx.measureText(idLabel).width + 10 : 0;
    const boxW = Math.max(timeW, idW);
    const boxH = idLabel ? 28 : 14;
    const boxX = Math.min(x + 4, Math.max(0, w - boxW - 4));
    ctx.fillStyle = "rgba(26, 29, 38, 0.88)";
    ctx.fillRect(boxX, 4, boxW, boxH);
    if (idLabel) {
      const idCol = _colorForCode(idLabel);
      ctx.fillStyle = idCol.bg || "#f8fafc";
      ctx.fillRect(boxX + 2, 6, boxW - 4, 12);
      ctx.fillStyle = idCol.text || "#111827";
      ctx.fillText(idLabel, boxX + 6, 14);
      ctx.fillStyle = "#f8fafc";
      ctx.fillText(timeLabel, boxX + 4, 26);
    } else {
      ctx.fillStyle = "#f8fafc";
      ctx.fillText(timeLabel, boxX + 4, 14);
    }
  }
}

function _scheduleWaveformOverlay() {
  if (AUDIO_WAVE_DRAW_PENDING) return;
  AUDIO_WAVE_DRAW_PENDING = true;
  requestAnimationFrame(() => {
    AUDIO_WAVE_DRAW_PENDING = false;
    _drawWaveformOverlay();
  });
  const listEl = _audioEls().list;
  if (listEl && AUDIO_QUEUE_STICK_BOTTOM) {
    listEl.scrollTop = listEl.scrollHeight;
  }
}

function drawWaveform(buffer) {
  const { waveform } = _audioEls();
  if (!waveform || !buffer) return;
  AUDIO_WAVE_BUFFER = buffer;
  const w = waveform.clientWidth || 600;
  const h = waveform.clientHeight || 120;
  AUDIO_WAVE_DURATION = buffer.duration || 0;
  _ensureWaveBaseCanvas(w, h);
  _buildWaveformBase(buffer, w, h);
  _renderAudioSegmentRail();
  _drawWaveformOverlay();
}

function encodeWav(buffer) {
  const numChannels = buffer.numberOfChannels;
  const sampleRate = buffer.sampleRate;
  const format = 1;
  const bitDepth = 16;
  const numSamples = buffer.length;
  const blockAlign = numChannels * bitDepth / 8;
  const byteRate = sampleRate * blockAlign;
  const dataSize = numSamples * blockAlign;
  const buf = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buf);

  function writeString(off, s) {
    for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i));
  }
  writeString(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, format, true);
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitDepth, true);
  writeString(36, "data");
  view.setUint32(40, dataSize, true);

  let offset = 44;
  const channels = [];
  for (let ch = 0; ch < numChannels; ch++) {
    channels.push(buffer.getChannelData(ch));
  }
  for (let i = 0; i < numSamples; i++) {
    for (let ch = 0; ch < numChannels; ch++) {
      let sample = channels[ch][i] || 0;
      sample = Math.max(-1, Math.min(1, sample));
      view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
      offset += 2;
    }
  }
  return new Blob([view], { type: "audio/wav" });
}

function _sortAudioTrackItems(items) {
  return (items || []).slice().sort((a, b) => {
    const oa = Number(a.order_index || 0);
    const ob = Number(b.order_index || 0);
    if (oa !== ob) return oa - ob;
    return String(a.file_rel || "").localeCompare(String(b.file_rel || ""));
  });
}

async function buildCombinedTrack(items) {
  const { audio } = _audioEls();
  if (!audio) return;
  if (!items || !items.length) return;

  const folderPath = getAudioFolderPath();
  if (!folderPath) return;

  const orderedItems = _sortAudioTrackItems(_itemsForCombinedTrack(items));
  if (!orderedItems.length) {
    _setAudioStatus("Нет расшифрованных сообщений [+] для сборки дорожки");
    return;
  }
  const sig = audioQueueSignature(orderedItems);
  if (sig && sig === AUDIO_QUEUE_SIG && audio.src) {
    return;
  }

  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const buffers = [];
  const segments = [];
  const skipped = [];
  let totalLength = 0;
  let channels = 1;
  let segIndex = 0;
  for (const item of orderedItems) {
    try {
      const qs = new URLSearchParams();
      qs.set("folder_path", folderPath);
      qs.set("file_rel", item.file_rel);
      const res = await fetch(`/api/intercepts/audio/file?${qs.toString()}`);
      if (!res.ok) {
        skipped.push(item);
        continue;
      }
      const arr = await res.arrayBuffer();
      let buf;
      try {
        buf = await ctx.decodeAudioData(arr.slice(0));
      } catch (_) {
        skipped.push(item);
        continue;
      }
      channels = Math.max(channels, buf.numberOfChannels);
      const startSec = totalLength / ctx.sampleRate;
      segments.push({
        item,
        startSec: startSec,
        duration: buf.duration,
        segmentIndex: segIndex,
      });
      totalLength += buf.length;
      buffers.push(buf);
      segIndex += 1;
    } catch (_) {
      skipped.push(item);
    }
  }

  if (!buffers.length) {
    _setAudioStatus("Не удалось собрать комбинированную дорожку");
    try { ctx.close(); } catch (_) { }
    return;
  }
  if (skipped.length) {
    const ids = skipped
      .map((it) => String(it.correspondent_id || it.file_rel || "").trim())
      .filter(Boolean)
      .join(", ");
    _setAudioStatus(
      ids
        ? `Дорожка: пропущено ${skipped.length} (${ids})`
        : `Дорожка: пропущено ${skipped.length}`
    );
  }

  const out = ctx.createBuffer(channels, totalLength, ctx.sampleRate);
  let offset = 0;
  for (const buf of buffers) {
    for (let ch = 0; ch < channels; ch++) {
      const dest = out.getChannelData(ch);
      const src = buf.getChannelData(Math.min(ch, buf.numberOfChannels - 1));
      dest.set(src, offset);
    }
    offset += buf.length;
  }

  const blob = encodeWav(out);
  const url = URL.createObjectURL(blob);
  audio.src = url;
  audio.load();
  AUDIO_SEGMENTS = segments;
  AUDIO_WAVE_DURATION = out.duration || 0;
  if (segments.length) {
    for (const seg of segments) {
      if (seg && seg.item) seg.item._duration = seg.duration;
    }
  }
  AUDIO_QUEUE_SIG = sig;
  AUDIO_LAST_SEG_IDX = -1;
  AUDIO_SELECTION = null;
  AUDIO_IS_COMBINED_TRACK = orderedItems.length > 1;
  if (orderedItems.length) {
    const first = orderedItems[0] || {};
    AUDIO_CURRENT_GROUP_KEY = _asrGroupKeyFromItem(first);
  }
  renderAudioQueue();
  drawWaveform(out);
  try { ctx.close(); } catch (_) { }
  if (ASR_UI_ENABLED && segments.length) {
    queueAsrForCurrentTrack({ autoTranscribe: true }).catch(() => { });
  }
}


window.buildWaveformForSingle = buildWaveformForSingle;
window.drawWaveform = drawWaveform;
window.buildCombinedTrack = buildCombinedTrack;
window._scheduleWaveformOverlay = _scheduleWaveformOverlay;
window.encodeWav = encodeWav;
