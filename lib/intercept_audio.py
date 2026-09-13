from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import os
import struct
import time
from pathlib import Path
import logging
import re
import wave

from web_portal.lib.collect_seanses_from_dir import _session_group
from web_portal.lib.safe_paths import probe_path

_log = logging.getLogger("web_portal.lib.intercept_audio")

logger = logging.getLogger("web_portal.intercept_audio")

TIME_FOLDER_RE = re.compile(
  r"^(?P<freq>[\d.,]+)_(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})$"
)
# Новый формат выгрузки: папка сеанса без частоты (2026-06-10_13-21-30),
# частота — в имени .fd файла внутри (151.1750_2026-06-10_13-18-18.fd).
TIME_ONLY_FOLDER_RE = re.compile(
  r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})$"
)
FD_FILE_RE = re.compile(
  r"^(?P<freq>[\d.,]+)_(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})\.fd$",
  re.IGNORECASE,
)
# Суффиксы-дубли « (0)»/«(1)» в имени папки сеанса (пробел перед скобкой опционален):
# OPK может выгружать ту же сессию рядом как «160.8260_..._11-42-25 (0)».
_TIME_FOLDER_SUFFIX_RE = re.compile(r"\s*\(\d+\)\s*$")
_COMMON_FILE_EXACT = {
    "slot0_common_file.wav",
    "slot0_common_file_0.wav",
    "slot1_common_file.wav",
    "slot1_common_file_0.wav",
    "slot0_common_file",
    "slot0_common_file_0",
    "slot1_common_file",
    "slot1_common_file_0",
}
_COMMON_FILE_PREFIXES = ("slot0_common_file", "slot1_common_file")


def _normalize_time_folder_name(name: str) -> str:
    return _TIME_FOLDER_SUFFIX_RE.sub("", str(name or "").strip())


def _parse_datetime_pair(date: str, time_raw: str) -> tuple[str, float] | None:
    try:
        dt = datetime.strptime(f"{date} {time_raw}", "%Y-%m-%d %H-%M-%S")
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.timestamp()


def _parse_time_folder_name(name: str) -> tuple[str, str, float] | None:
    normalized = _normalize_time_folder_name(name)
    m = TIME_FOLDER_RE.match(normalized)
    if not m:
        return None
    freq = str(m.group("freq") or "").strip()
    parsed = _parse_datetime_pair(
        str(m.group("date") or "").strip(), str(m.group("time") or "").strip()
    )
    if not parsed:
        return None
    return freq, parsed[0], parsed[1]


def _is_session_folder_name(name: str) -> bool:
    normalized = _normalize_time_folder_name(name)
    return bool(TIME_FOLDER_RE.match(normalized) or TIME_ONLY_FOLDER_RE.match(normalized))


def _freq_time_from_fd_files(dir_path: Path) -> tuple[str, str, float] | None:
    """Частота и время записи из имени .fd файла (новый формат выгрузки)."""
    try:
        with os.scandir(dir_path) as it:
            for entry in it:
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                except Exception:
                    continue
                m = FD_FILE_RE.match(entry.name)
                if not m:
                    continue
                freq = str(m.group("freq") or "").strip()
                parsed = _parse_datetime_pair(
                    str(m.group("date") or ""), str(m.group("time") or "")
                )
                if freq and parsed:
                    return freq, parsed[0], parsed[1]
    except Exception:
        _log.debug("_freq_time_from_fd_files: suppressed error", exc_info=True)
    return None


def _parse_time_only_folder(dir_path: Path, name: str) -> tuple[str, str, float] | None:
    """Папка сеанса {date}_{time} без частоты: частота — из .fd внутри неё."""
    normalized = _normalize_time_folder_name(name)
    m = TIME_ONLY_FOLDER_RE.match(normalized)
    if not m:
        return None
    fd = _freq_time_from_fd_files(dir_path)
    if fd:
        return fd
    parsed = _parse_datetime_pair(str(m.group("date") or ""), str(m.group("time") or ""))
    if not parsed:
        return None
    return "", parsed[0], parsed[1]


def _dir_has_common_file(dir_path: Path) -> bool:
    """OPK может называть общий файл slot0_common_file ГУПИК.wav — учитываем префикс."""
    for name in _COMMON_FILE_EXACT:
        try:
            if (dir_path / name).is_file():
                return True
        except Exception:
            continue
    try:
        with os.scandir(dir_path) as it:
            for entry in it:
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                except Exception:
                    continue
                low = entry.name.lower()
                stem = low[:-4] if low.endswith(".wav") else low
                if any(stem.startswith(prefix) for prefix in _COMMON_FILE_PREFIXES):
                    return True
    except Exception:
        _log.debug("_dir_has_common_file: suppressed error", exc_info=True)
    return False
# OPK/STA: slot{N}_{from}_to_{Ggroup|peer}_{...AES256_k..}_{order}[+].wav
# [+] — декодирование прошло в OPK, но не гарантирует речь (может быть шум при неверном ключе).
FILE_RE = re.compile(
  r"^slot(?P<slot>\d+)_?(?P<id>\d{1,10})_to_"
  r"(?:G(?P<group>\d{1,10})|(?P<peer>\d{1,10}))"
  r".*?_(?P<order>\d+)(?P<decoded>\[\+\])?\.wav$",
  re.IGNORECASE,
)
AES_RE = re.compile(r"_k(?P<key>\d+)", re.IGNORECASE)
# Сколько файлов с [+] проверять на речь за один запрос списка (остальные — по [+] без чтения wav).
_SPEECH_CHECK_LIMIT = 50
# Увеличивать при смене эвристики — сбрасывает кэш скана и подсказку клиенту на полный пересчёт.
SPEECH_HEURISTIC_VERSION = 8


def _debug_add(debug: dict | None, reason: str, file_path: Path | None = None) -> None:
    if debug is None:
        return
    debug["reasons"][reason] = debug["reasons"].get(reason, 0) + 1
    if file_path and len(debug["samples"]) < 10:
        debug["samples"].append({"reason": reason, "file": str(file_path)})


def _debug_inc(debug: dict | None, key: str, inc: int = 1) -> None:
    if debug is None:
        return
    counters = debug.setdefault("counters", {})
    counters[key] = int(counters.get(key, 0)) + inc


def _debug_time(debug: dict | None, key: str, start: float) -> None:
    if debug is None:
        return
    timings = debug.setdefault("timings_ms", {})
    timings[key] = round((time.perf_counter() - start) * 1000.0, 2)


@dataclass(frozen=True)
class InterceptAudioEntry:
    file_path: Path
    file_rel: str
    file_key: str
    frequency: str
    group_code: str
    correspondent_id: str
    order_index: int
    recorded_at: str
    recorded_ts: float
    duration_sec: float
    has_key: bool
    has_message: bool
    aes_key: str
    slot: str
    peer_correspondent_id: str = ""
    call_mode: str = "group"


def _parse_slot_wav_name(name: str) -> dict[str, str | int | bool] | None:
    m = FILE_RE.match(name)
    if not m:
        return None
    correspondent_id = str(m.group("id") or "").strip()
    slot = str(m.group("slot") or "").strip()
    order_idx = int(m.group("order") or 0)
    decoded = bool(m.group("decoded"))
    aes_match = AES_RE.search(name)
    aes_key = aes_match.group("key") if aes_match else ""
    group_raw = str(m.group("group") or "").strip()
    peer_raw = str(m.group("peer") or "").strip()
    peer_correspondent_id = ""
    call_mode = "group"
    if peer_raw:
        peer_correspondent_id = peer_raw
        call_mode = "tt"
        session_group = _session_group(correspondent_id, peer_raw, private_call=True)
    else:
        session_group = _session_group(correspondent_id, f"G{group_raw}")
    if not correspondent_id or not session_group:
        return None
    group_code = session_group
    if group_code != "T-T" and group_code.upper().startswith("G"):
        group_code = group_code[1:]
    if session_group == "T-T":
        call_mode = "tt"
    return {
        "correspondent_id": correspondent_id,
        "slot": slot,
        "order_index": order_idx,
        "decoded": decoded,
        "aes_key": str(aes_key or ""),
        "group_code": group_code,
        "peer_correspondent_id": peer_correspondent_id,
        "call_mode": call_mode,
    }


def _wav_mono_samples(file_path: Path, *, max_seconds: float = 15.0) -> tuple[list[float], int] | None:
    try:
        with wave.open(str(file_path), "rb") as wf:
            nch = wf.getnchannels()
            sw = wf.getsampwidth()
            rate = wf.getframerate()
            nframes = wf.getnframes()
            if nframes <= 0 or rate <= 0 or sw not in (1, 2, 4):
                return None
            read_frames = min(nframes, int(rate * max_seconds))
            raw = wf.readframes(read_frames)
    except Exception:
        return None
    if not raw:
        return None
    try:
        if sw == 1:
            samples = struct.unpack(f"{len(raw)}b", raw)
            scale = 128.0
        elif sw == 2:
            samples = struct.unpack(f"{len(raw) // 2}h", raw)
            scale = 32768.0
        else:
            samples = struct.unpack(f"{len(raw) // 4}i", raw)
            scale = 2147483648.0
    except struct.error:
        return None
    if nch > 1:
        mono: list[float] = []
        for i in range(0, len(samples), nch):
            chunk = samples[i : i + nch]
            if not chunk:
                continue
            mono.append(sum(chunk) / float(len(chunk)))
        samples = mono
    norm = [float(s) / scale for s in samples]
    return norm, rate


def _wav_pitch_strength(samples: list[float], rate: int) -> float:
    """Нормированная автокорреляция в диапазоне ~50–200 Гц (голосовая основная)."""
    n = min(len(samples), int(rate * 3))
    if n < max(16, int(rate * 0.3)):
        return 0.0
    s = samples[:n]
    energy = sum(x * x for x in s) + 1e-12
    lo = max(2, int(rate / 200))
    hi = max(lo + 1, int(rate / 50))
    best = 0.0
    for lag in range(lo, min(hi, n - 1)):
        num = sum(s[i] * s[i + lag] for i in range(n - lag))
        best = max(best, num / energy)
    return float(best)


def _wav_hf_ratio(samples: list[float]) -> float:
    """Доля ВЧ-энергии по разностям соседних отсчётов (шум/помехи дают высокое значение)."""
    if len(samples) < 4:
        return 0.0
    diff = [samples[i] - samples[i - 1] for i in range(1, len(samples))]
    hf = sum(x * x for x in diff) / len(diff)
    lf = sum(x * x for x in samples) / len(samples)
    return hf / (lf + 1e-12)


def _wav_zero_crossing_rate(samples: list[float]) -> float:
    if len(samples) < 2:
        return 0.0
    zc = sum(1 for i in range(1, len(samples)) if samples[i - 1] * samples[i] < 0)
    return zc / float(len(samples))


def _wav_has_speech_like_content(file_path: Path) -> bool:
    """
    Эвристика: отличить речь от тишины/шума/помех после «успешного» [+] декода OPK.
    """
    loaded = _wav_mono_samples(file_path)
    if not loaded:
        return False
    samples, rate = loaded
    if len(samples) < max(8, int(rate * 0.2)):
        return False
    duration = len(samples) / float(rate)
    if duration < 0.35:
        return False
    abs_samples = [abs(x) for x in samples]
    peak = max(abs_samples)
    if peak < 0.008:
        return False
    win = max(1, int(rate * 0.02))
    energies: list[float] = []
    for i in range(0, len(abs_samples), win):
        chunk = abs_samples[i : i + win]
        if not chunk:
            continue
        rms = (sum(x * x for x in chunk) / len(chunk)) ** 0.5
        energies.append(rms)
    if not energies:
        return False
    emean = sum(energies) / len(energies)
    if emean < 0.006:
        return False
    variance = sum((e - emean) ** 2 for e in energies) / len(energies)
    cv = (variance**0.5) / emean if emean > 0 else 0.0
    pitch = _wav_pitch_strength(samples, rate)
    hf_ratio = _wav_hf_ratio(samples)
    zcr = _wav_zero_crossing_rate(samples)

    # Шум: короткий «рваный» всплеск (slot0_1…_2[+].wav), не длинный перехват.
    if duration < 0.5 and zcr >= 0.28 and hf_ratio >= 0.30:
        return False
    if hf_ratio > 0.75 and duration < 0.8:
        return False
    if pitch < 0.22 and hf_ratio > 0.50:
        return False
    if zcr >= 0.30 and hf_ratio >= 0.38 and duration < 0.5:
        return False

    # Явная речь: устойчивая основная + достаточная длительность (дорожка 15500235/15500327).
    if pitch >= 0.28 and duration >= 0.9 and cv >= 0.35:
        return True
    if pitch >= 0.28 and duration >= 0.8 and hf_ratio < 0.50 and zcr < 0.26:
        return True
    if pitch >= 0.30 and hf_ratio < 0.28 and zcr < 0.25:
        return True
    if pitch >= 0.22 and hf_ratio < 0.35 and zcr < 0.22:
        return True

    # DMR-речь без яркой основной (slot0_1341839…): длинный фрагмент, сильная модуляция огибающей.
    if duration >= 1.0 and cv >= 0.35 and hf_ratio < 0.42 and zcr < 0.28:
        return True
    if duration >= 0.8 and cv >= 0.55 and hf_ratio < 0.40 and zcr < 0.23:
        return True
    # Запасной путь по огибающей — только при признаках голоса, не чистого шума.
    if cv >= 0.18 and pitch >= 0.20 and hf_ratio < 0.50 and zcr < 0.24:
        return True
    if cv >= 0.10 and 0.015 <= peak <= 0.85 and pitch >= 0.18 and hf_ratio < 0.45 and zcr < 0.22:
        return True
    # Равномерный громкий шум (часто неверный ключ, но [+] в имени есть).
    if emean > 0.08 and cv < 0.08:
        return False
    return cv >= 0.12 and peak >= 0.015 and pitch >= 0.20 and hf_ratio < 0.45


def _enrich_message_flags(
    entries: list[InterceptAudioEntry], *, max_checks: int = _SPEECH_CHECK_LIMIT
) -> list[InterceptAudioEntry]:
    """Проверка речи только для части записей — иначе скан папки зависает на минуты."""
    if not entries:
        return list(entries)
    if max_checks <= 0:
        return [replace(e, has_message=bool(e.has_key)) for e in entries]
    keyed_idx = [i for i, e in enumerate(entries) if e.has_key]
    check_idx: set[int] = set()
    # В сеансе с несколькими корреспондентами проверяем все [+] — иначе часть ID
    # остаётся «шумом», хотя речь есть (как slot0_1_to_G…_2[+].wav).
    session_groups: dict[tuple[str, str, str], list[int]] = {}
    for i in keyed_idx:
        e = entries[i]
        sk = (str(e.frequency), str(e.recorded_at), str(e.slot))
        session_groups.setdefault(sk, []).append(i)
    for indices in session_groups.values():
        if len(indices) < 2:
            continue
        for i in indices:
            if len(check_idx) >= max_checks:
                break
            check_idx.add(i)
    for i in reversed(keyed_idx):
        if len(check_idx) >= max_checks:
            break
        check_idx.add(i)
    out: list[InterceptAudioEntry] = []
    for i, e in enumerate(entries):
        if not e.has_key:
            out.append(replace(e, has_message=False))
            continue
        if i in check_idx:
            has_msg = _wav_has_speech_like_content(e.file_path)
        else:
            # Если wav не успел пройти анализ, не называем его шумом без доказательств.
            # [+] в OPK означает декод; "Message (шум)" ставим только после проверки.
            has_msg = True
        out.append(replace(e, has_message=has_msg))
    return out


def _wav_duration_seconds(file_path: Path) -> float:
    try:
        with wave.open(str(file_path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if not rate:
                return 0.0
            return float(frames) / float(rate)
    except Exception:
        return 0.0


def _find_time_folder(p: Path) -> tuple[str, str, float] | None:
    for parent in [p] + list(p.parents):
        parsed = _parse_time_folder_name(parent.name)
        if parsed:
            return parsed
        parsed = _parse_time_only_folder(parent, parent.name)
        if parsed:
            return parsed
    return None


def _normalize_freq(freq: str) -> str:
    return str(freq or "").strip().replace(",", ".")


def _freq_compare_key(freq: str) -> str:
    s = _normalize_freq(freq)
    if not s:
        return ""
    try:
        return f"{float(s):.6f}".rstrip("0").rstrip(".")
    except Exception:
        return s


def parse_intercept_audio_file(
    file_path: Path, base_folder: Path, *, debug: dict | None = None
) -> InterceptAudioEntry | None:
    if not file_path.is_file():
        _debug_add(debug, "not_file", file_path)
        return None
    if file_path.suffix.lower() != ".wav":
        _debug_add(debug, "not_wav", file_path)
        return None

    m = FILE_RE.match(file_path.name)
    if not m:
        _debug_add(debug, "name_mismatch", file_path)
        return None

    meta = _parse_slot_wav_name(file_path.name)
    if not meta:
        _debug_add(debug, "name_mismatch", file_path)
        return None

    # Показываем только если есть общий файл записи (slot0_common_file*.wav)
    parent = file_path.parent
    parent_common = _dir_has_common_file(parent)
    up_common = _dir_has_common_file(parent.parent)
    if not parent_common and not up_common:
        _debug_add(debug, "missing_common", file_path)
        return None

    time_info = _find_time_folder(file_path.parent)
    if not time_info:
        _debug_add(debug, "missing_time_folder", file_path)
        return None
    frequency, recorded_at, recorded_ts = time_info

    try:
        rel = file_path.resolve().relative_to(base_folder.resolve())
    except Exception:
        _debug_add(debug, "rel_error", file_path)
        return None
    file_rel = str(rel).replace("\\", "/")

    try:
        st = file_path.stat()
    except Exception:
        _debug_add(debug, "stat_error", file_path)
        return None
    file_key = f"{file_rel}|{int(st.st_size)}|{int(st.st_mtime)}"

    decoded = bool(meta["decoded"])
    duration_sec = _wav_duration_seconds(file_path)
    base = InterceptAudioEntry(
        file_path=file_path,
        file_rel=file_rel,
        file_key=file_key,
        frequency=frequency,
        group_code=str(meta["group_code"]),
        correspondent_id=str(meta["correspondent_id"]),
        order_index=int(meta["order_index"]),
        recorded_at=recorded_at,
        recorded_ts=recorded_ts,
        duration_sec=duration_sec,
        has_key=decoded,
        has_message=False,
        aes_key=str(meta["aes_key"]),
        slot=str(meta["slot"]),
        peer_correspondent_id=str(meta.get("peer_correspondent_id") or ""),
        call_mode=str(meta.get("call_mode") or "group"),
    )
    enriched = _enrich_message_flags([base], max_checks=1)
    return enriched[0] if enriched else base


def _parse_intercept_audio_entry(
    entry: os.DirEntry,
    base_folder: Path,
    *,
    time_info: tuple[str, str, float] | None,
    has_common: bool,
    debug: dict | None = None,
) -> InterceptAudioEntry | None:
    name = entry.name
    if not name.lower().endswith(".wav"):
        _debug_add(debug, "not_wav", Path(entry.path))
        return None

    m = FILE_RE.match(name)
    if not m:
        _debug_add(debug, "name_mismatch", Path(entry.path))
        return None

    meta = _parse_slot_wav_name(name)
    if not meta:
        _debug_add(debug, "name_mismatch", Path(entry.path))
        return None

    if not has_common:
        _debug_add(debug, "missing_common", Path(entry.path))
        return None

    if not time_info:
        _debug_add(debug, "missing_time_folder", Path(entry.path))
        return None

    frequency, recorded_at, recorded_ts = time_info

    try:
        rel = Path(entry.path).relative_to(base_folder)
    except Exception:
        try:
            rel = Path(os.path.relpath(entry.path, base_folder))
        except Exception:
            _debug_add(debug, "rel_error", Path(entry.path))
            return None
    file_rel = str(rel).replace("\\", "/")

    try:
        st = entry.stat()
    except Exception:
        _debug_add(debug, "stat_error", Path(entry.path))
        return None
    file_key = f"{file_rel}|{int(st.st_size)}|{int(st.st_mtime)}"

    decoded = bool(meta["decoded"])
    duration_sec = _wav_duration_seconds(Path(entry.path))
    return InterceptAudioEntry(
        file_path=Path(entry.path),
        file_rel=file_rel,
        file_key=file_key,
        frequency=frequency,
        group_code=str(meta["group_code"]),
        correspondent_id=str(meta["correspondent_id"]),
        order_index=int(meta["order_index"]),
        recorded_at=recorded_at,
        recorded_ts=recorded_ts,
        duration_sec=duration_sec,
        has_key=decoded,
        has_message=False,
        aes_key=str(meta["aes_key"]),
        slot=str(meta["slot"]),
        peer_correspondent_id=str(meta.get("peer_correspondent_id") or ""),
        call_mode=str(meta.get("call_mode") or "group"),
    )


def _iter_dmr_dirs(
    root: Path, *, debug: dict | None = None, newest_first: bool = False
) -> list[Path]:
    dmr_dirs: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                    except Exception:
                        _debug_add(debug, "dir_stat_error", Path(entry.path))
                        continue
                    if entry.name == "DMR":
                        dmr_dirs.append(Path(entry.path))
                        continue
                    stack.append(Path(entry.path))
        except Exception:
            _debug_add(debug, "scandir_error", current)
    if newest_first and dmr_dirs:
        def _ts(d: Path) -> float:
            info = _find_time_folder(d)
            return float(info[2]) if info else 0.0
        dmr_dirs.sort(key=_ts, reverse=True)
    return dmr_dirs


# На UNC/сетевых путях глубокий stat по всем сессиям блокирует HTTP на минуты.
RECENT_SESSION_NAME_WINDOW_SEC = 5400.0  # 90 мин — окно по имени папки сеанса
MAX_RECENT_SESSION_EXTRAS = 16
MAX_RECENT_MTIME_STAT_CHECKS = 32


def _session_folder_ts_from_path(path: Path) -> float | None:
    parsed = _parse_time_folder_name(path.name)
    if parsed:
        return float(parsed[2])
    parsed = _parse_time_only_folder(path, path.name)
    if parsed:
        return float(parsed[2])
    return None


def _resolve_task_freq_roots(base_folder: Path, task_set: set[str]) -> list[Path]:
    """Подпапки частот для tasks_only — через probe_path с таймаутом (UNC не блокирует поток)."""
    roots: list[Path] = []
    seen: set[str] = set()
    for f in sorted(task_set):
        for cand_name in (f, f.replace(".", ",")):
            if cand_name in seen:
                continue
            seen.add(cand_name)
            cand = base_folder / cand_name
            probe = probe_path(cand, timeout_sec=2.0)
            if probe.timed_out:
                continue
            if probe.ok and probe.exists and probe.is_dir:
                roots.append(Path(probe.resolved or str(cand)))
                break
    return roots


def _iter_dmr_dirs_by_time_folder(
    root: Path,
    *,
    debug: dict | None = None,
    newest_first: bool = True,
    max_dirs: int | None = None,
    recent_mtime_since: float | None = None,
) -> tuple[list[Path], set[str]]:
    time_dirs: list[Path] = []
    entry_mtimes: dict[str, float] = {}
    collect_mtimes = bool(recent_mtime_since and float(recent_mtime_since) > 0)
    try:
        with os.scandir(root) as it:
            for entry in it:
                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                except Exception:
                    _debug_add(debug, "dir_stat_error", Path(entry.path))
                    continue
                if not _is_session_folder_name(entry.name):
                    continue
                p = Path(entry.path)
                time_dirs.append(p)
                if collect_mtimes:
                    try:
                        entry_mtimes[str(p)] = float(entry.stat(follow_symlinks=False).st_mtime)
                    except Exception:
                        _log.debug("_iter_dmr_dirs_by_time_folder: suppressed error", exc_info=True)
    except Exception:
        _debug_add(debug, "scandir_error", root)
    if time_dirs:
        time_dirs.sort(key=lambda p: p.name, reverse=newest_first)

    recent_dir_keys: set[str] = set()
    if max_dirs is not None and max_dirs > 0:
        selected = list(time_dirs[:max_dirs])
        selected_set = {str(p) for p in selected}
        since = float(recent_mtime_since or 0.0)
        if since > 0:
            newest_ts = 0.0
            for p in selected:
                ts = _session_folder_ts_from_path(p)
                if ts is not None and ts > newest_ts:
                    newest_ts = ts
            window_start = (
                newest_ts - RECENT_SESSION_NAME_WINDOW_SEC if newest_ts > 0 else 0.0
            )
            extras_added = 0
            stat_checks = 0
            for p in time_dirs[max_dirs:]:
                if extras_added >= MAX_RECENT_SESSION_EXTRAS:
                    break
                key = str(p)
                if key in selected_set:
                    continue
                ts = _session_folder_ts_from_path(p)
                if ts is not None and window_start > 0 and ts >= window_start:
                    selected.append(p)
                    selected_set.add(key)
                    recent_dir_keys.add(key)
                    extras_added += 1
                    continue
                if stat_checks >= MAX_RECENT_MTIME_STAT_CHECKS:
                    continue
                stat_checks += 1
                mtime = entry_mtimes.get(key)
                if mtime is None:
                    try:
                        mtime = float(p.stat().st_mtime)
                    except Exception:
                        continue
                if mtime >= since:
                    selected.append(p)
                    selected_set.add(key)
                    recent_dir_keys.add(key)
                    extras_added += 1
            if debug is not None:
                debug["recent_session_extras"] = extras_added
        time_dirs = selected
    return time_dirs, recent_dir_keys


def _session_folder_recently_modified(session_dir: Path, since_ts: float) -> bool:
    """True если OPK дозаписал common/wav в старую по времени папку после прошлого скана."""
    if since_ts <= 0:
        return False
    try:
        if session_dir.stat().st_mtime >= since_ts:
            return True
    except Exception:
        _log.debug("_session_folder_recently_modified: suppressed error", exc_info=True)
    for p in (session_dir / "DMR", session_dir / "DMR" / "DMR"):
        try:
            if not p.is_dir():
                continue
            with os.scandir(p) as it:
                for entry in it:
                    try:
                        name = entry.name.lower()
                        if not (
                            name.endswith(".wav")
                            or name.startswith("slot0_common_file")
                            or name.startswith("slot1_common_file")
                        ):
                            continue
                        if entry.stat(follow_symlinks=False).st_mtime >= since_ts:
                            return True
                    except Exception:
                        continue
        except Exception:
            continue
    return False


def _has_common_files(dmr_dir: Path) -> bool:
    if _dir_has_common_file(dmr_dir):
        return True
    return _dir_has_common_file(dmr_dir.parent)


_SCAN_CACHE: dict[tuple[object, ...], dict[str, object]] = {}
_SCAN_CACHE_TTL_SECONDS = 4.0
_SCAN_CACHE_MAX_ITEMS = 120


def _scan_cache_prune() -> None:
    if len(_SCAN_CACHE) <= _SCAN_CACHE_MAX_ITEMS:
        return
    victims = sorted(_SCAN_CACHE.items(), key=lambda x: float((x[1] or {}).get("ts", 0.0)))[: max(1, len(_SCAN_CACHE) - _SCAN_CACHE_MAX_ITEMS)]
    for k, _v in victims:
        _SCAN_CACHE.pop(k, None)


def scan_intercept_audio_files(
    base_folder: Path,
    *,
    tasks: list[str] | None = None,
    tasks_only: bool = False,
    limit: int = 300,
    debug: dict | None = None,
    use_cache: bool | None = None,
    meta: dict | None = None,
    time_budget_s: float | None = None,
    since_ts: float | None = None,
    newest_first: bool = True,
    max_time_folders: int | None = None,
    recent_mtime_since: float | None = None,
) -> list[InterceptAudioEntry]:
    # Верхний предел повышен: при большом числе частот/файлов
    # не обрезать очередь слишком агрессивно.
    limit = max(1, min(int(limit or 300), 50000))
    if use_cache is None:
        use_cache = debug is None

    base_probe = probe_path(base_folder)
    if not base_probe.ok or not base_probe.exists or not base_probe.is_dir:
        if debug is not None:
            debug["base_folder"] = str(base_folder)
            reason = "base_probe_timeout" if base_probe.timed_out else "base_unavailable"
            debug["reasons"][reason] = debug["reasons"].get(reason, 0) + 1
        return []
    base_folder = Path(base_probe.resolved or str(base_folder))

    task_set: set[str] = set()
    task_cmp_set: set[str] = set()
    if tasks:
        task_set = {_normalize_freq(f) for f in tasks}
        task_cmp_set = {_freq_compare_key(f) for f in tasks if _freq_compare_key(f)}

    if debug is not None:
        debug["base_folder"] = str(base_folder)
        debug["tasks_only"] = bool(tasks_only)
        debug["task_set"] = sorted(task_set)
        debug["scanned"] = 0
        debug["kept"] = 0
        debug["reasons"] = {}
        debug["samples"] = []
        debug["counters"] = {}
        debug["timings_ms"] = {}
        debug["cache"] = {"hit": False}
        debug["progress"] = {"last_dir": "", "last_file": ""}
        debug["truncated"] = False
    if meta is not None:
        meta["truncated"] = False
        meta["truncated_reason"] = ""
        meta["time_budget_hit"] = False
        meta["limit_capped"] = False
        meta["cached"] = False
        meta["elapsed_ms"] = 0.0

    out: list[InterceptAudioEntry] = []
    dedupe: dict[tuple[str, str, str, int, str, str], InterceptAudioEntry] = {}

    search_roots: list[Path] = [base_folder]
    if tasks_only and task_set:
        search_roots = _resolve_task_freq_roots(base_folder, task_set)
        if debug is not None and not search_roots:
            debug["reasons"]["task_folder_missing"] = (
                debug["reasons"].get("task_folder_missing", 0) + 1
            )

    cache_key = (
        str(base_folder),
        bool(tasks_only),
        tuple(sorted(task_set)),
        tuple(sorted(task_cmp_set)),
        int(limit),
        int((time_budget_s or 0.0) * 1000.0),
        int(since_ts or 0.0),
        bool(newest_first),
        int(max_time_folders or 0),
        int(recent_mtime_since or 0.0),
        int(SPEECH_HEURISTIC_VERSION),
    )
    cache_now = time.time()
    if use_cache:
        cached = _SCAN_CACHE.get(cache_key)
        if cached:
            ts = float(cached.get("ts", 0))
            if (cache_now - ts) <= _SCAN_CACHE_TTL_SECONDS:
                cached_out = cached.get("result") or []
                cached_meta = cached.get("meta") or {}
                if meta is not None:
                    meta.update(
                        {
                            "cached": True,
                            "truncated": bool(cached_meta.get("truncated")),
                            "truncated_reason": str(cached_meta.get("truncated_reason") or ""),
                            "time_budget_hit": bool(cached_meta.get("time_budget_hit")),
                            "limit_capped": bool(cached_meta.get("limit_capped")),
                            "elapsed_ms": float(cached_meta.get("elapsed_ms") or 0.0),
                        }
                    )
                if debug is not None:
                    debug["cache"] = {"hit": True, "age_s": round(cache_now - ts, 2)}
                    debug["kept"] = len(list(cached_out))
                    _debug_time(debug, "total", time.perf_counter())
                return list(cached_out)

    t_total = time.perf_counter()
    time_budget_hit = False
    # Делим бюджет времени между всеми частотами (search_roots), чтобы обрабатывались все задания
    budget_per_root: float | None = None
    if time_budget_s is not None and search_roots:
        budget_per_root = float(time_budget_s) / len(search_roots)
    _debug_inc(debug, "search_roots", len(search_roots))
    last_log_ts = time.perf_counter()
    for root in search_roots:
        t_roots = time.perf_counter()
        root_deadline = (t_roots + budget_per_root) if budget_per_root else None
        dmr_dirs, recent_session_dirs = _iter_dmr_dirs_by_time_folder(
            root,
            debug=debug,
            newest_first=newest_first,
            max_dirs=max_time_folders,
            recent_mtime_since=recent_mtime_since,
        )
        if not dmr_dirs:
            dmr_dirs = _iter_dmr_dirs(root, debug=debug, newest_first=newest_first)
            recent_session_dirs = set()
        _debug_inc(debug, "dmr_dirs", len(dmr_dirs))
        _debug_time(debug, f"dmr_scan:{root}", t_roots)
        for dmr_dir in dmr_dirs:
            session_recent = str(dmr_dir) in recent_session_dirs
            if time_budget_s is not None:
                if (time.perf_counter() - t_total) >= float(time_budget_s):
                    time_budget_hit = True
                    if debug is not None:
                        debug["truncated"] = True
                    if meta is not None:
                        meta["truncated"] = True
                        meta["time_budget_hit"] = True
                        meta["truncated_reason"] = "time_budget"
                    break
                # Лимит на одну частоту — переходим к следующей, не исчерпывая общий бюджет
                if root_deadline is not None and time.perf_counter() >= root_deadline:
                    break
            if debug is not None:
                debug["progress"]["last_dir"] = str(dmr_dir)
            scan_dirs = []
            if dmr_dir.name.lower() == "dmr":
                # Новый формат: декодированные [+] лежат во вложенном DMR/DMR
                scan_dirs = [dmr_dir, dmr_dir.parent, dmr_dir / "DMR"]
            else:
                scan_dirs = [dmr_dir / "DMR", dmr_dir, dmr_dir / "DMR" / "DMR"]
            for scan_dir in scan_dirs:
                if not scan_dir.exists() or not scan_dir.is_dir():
                    continue
                time_info = _find_time_folder(scan_dir)
                common_base = scan_dir if scan_dir.name.lower() == "dmr" else (scan_dir / "DMR")
                has_common = _has_common_files(common_base)
                try:
                    with os.scandir(scan_dir) as it:
                        for entry in it:
                            _debug_inc(debug, "files_seen")
                            if not entry.name.lower().endswith(".wav"):
                                _debug_add(debug, "not_wav", Path(entry.path))
                                continue
                            try:
                                if not entry.is_file(follow_symlinks=False):
                                    continue
                            except Exception:
                                _debug_add(debug, "file_stat_error", Path(entry.path))
                                continue
                            _debug_inc(debug, "files_wav")
                            if debug is not None:
                                debug["scanned"] += 1
                                debug["progress"]["last_file"] = entry.name
                                now_ts = time.perf_counter()
                                if (now_ts - last_log_ts) >= 5.0:
                                    last_log_ts = now_ts
                                    logger.warning(
                                        "[audio.debug] progress scanned=%s kept=%s last_dir=%s last_file=%s",
                                        debug.get("scanned"),
                                        len(dedupe),
                                        debug["progress"].get("last_dir"),
                                        debug["progress"].get("last_file"),
                                    )
                            if debug is None:
                                if not entry.name.startswith("slot"):
                                    continue
                                if not FILE_RE.match(entry.name):
                                    continue
                            parsed = _parse_intercept_audio_entry(
                                entry,
                                base_folder,
                                time_info=time_info,
                                has_common=has_common,
                                debug=debug,
                            )
                            if not parsed:
                                continue
                            if (
                                since_ts is not None
                                and parsed.recorded_ts < float(since_ts)
                                and not session_recent
                            ):
                                _debug_add(debug, "filtered_by_since", Path(entry.path))
                                continue
                            if tasks_only and task_set:
                                pf = _normalize_freq(parsed.frequency)
                                pcmp = _freq_compare_key(parsed.frequency)
                                if (pf not in task_set) and (not pcmp or pcmp not in task_cmp_set):
                                    _debug_add(debug, "filtered_by_task", Path(entry.path))
                                    continue
                            key = (
                                _freq_compare_key(parsed.frequency)
                                or _normalize_freq(parsed.frequency),
                                parsed.group_code,
                                parsed.correspondent_id,
                                parsed.order_index,
                                parsed.recorded_at,
                                parsed.slot,
                            )
                            existing = dedupe.get(key)
                            if existing is None:
                                dedupe[key] = parsed
                            else:
                                # Дубликаты в разных подпапках: расшифрованный [+]
                                # приоритетнее сырого; при равенстве — короче путь.
                                replace_existing = (
                                    parsed.has_key and not existing.has_key
                                ) or (
                                    parsed.has_key == existing.has_key
                                    and len(parsed.file_rel) < len(existing.file_rel)
                                )
                                if replace_existing:
                                    dedupe[key] = parsed
                                    _debug_inc(debug, "dedupe_replaced")
                            if len(dedupe) >= limit * 3:
                                # защищаемся от слишком больших обходов
                                break
                except Exception:
                    _debug_add(debug, "scandir_error", scan_dir)
            if time_budget_hit:
                break
        if time_budget_hit:
            break

    out = list(dedupe.values())
    out.sort(
        key=lambda x: (
            x.recorded_ts,
            x.order_index,
            x.file_rel,
        )
    )
    if debug is not None:
        debug["kept"] = len(out[:limit])
        _debug_time(debug, "total", t_total)
        debug["cache"] = debug.get("cache") or {"hit": False}
        logger.warning(
            "[audio.debug] scan stats base=%s scanned=%s kept=%s timings=%s counters=%s cache=%s",
            str(base_folder),
            debug.get("scanned"),
            debug.get("kept"),
            debug.get("timings_ms"),
            debug.get("counters"),
            debug.get("cache"),
        )
    if len(out) > limit and meta is not None:
        meta["truncated"] = True
        if not meta.get("truncated_reason"):
            meta["truncated_reason"] = "limit"
        meta["limit_capped"] = True
    if meta is not None:
        meta["elapsed_ms"] = round((time.perf_counter() - t_total) * 1000.0, 2)
        meta["scanned_estimate"] = int((debug or {}).get("scanned") or 0)
        meta["kept_before_limit"] = int(len(out))
        meta["returned"] = int(len(out[:limit]))
    trimmed = list(out[:limit])
    speech_checks = _SPEECH_CHECK_LIMIT
    if time_budget_s is not None and float(time_budget_s) <= 6.0:
        speech_checks = min(12, _SPEECH_CHECK_LIMIT)
    trimmed = _enrich_message_flags(trimmed, max_checks=speech_checks)
    if use_cache:
        _SCAN_CACHE[cache_key] = {
            "ts": cache_now,
            "result": list(trimmed),
            "meta": {
                "truncated": bool((meta or {}).get("truncated")),
                "truncated_reason": str((meta or {}).get("truncated_reason") or ""),
                "time_budget_hit": bool((meta or {}).get("time_budget_hit")),
                "limit_capped": bool((meta or {}).get("limit_capped")),
                "elapsed_ms": float((meta or {}).get("elapsed_ms") or 0.0),
            },
        }
        _scan_cache_prune()
    return trimmed
