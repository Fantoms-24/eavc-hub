from __future__ import annotations

import os
import re
import time
from datetime import datetime
from pathlib import Path

from web_portal.lib.intercept_audio import (
    InterceptAudioEntry,
    _debug_add,
    _debug_inc,
    _debug_time,
    _enrich_message_flags,
    _freq_compare_key,
    _normalize_freq,
    _wav_duration_seconds,
)
from web_portal.lib.safe_paths import probe_path

# Папки частот: fr{149.9750}
FREQ_FOLDER_RE = re.compile(r"^fr\{(?P<freq>[\d.,]+)\}\s*$", re.IGNORECASE)

# Готовая выгрузка CT: 2026-06-05_07-42-09_id-101__0_CT_Group_TO_2047519_FR_4489_pe_0__47.wav
BUNDLE_CT_WAV_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})"
    r"_id-(?P<channel>\d+)__(?P<order>\d+)"
    r"_CT_Group_TO_(?P<group>\d+)"
    r"_FR_(?P<cid>\d+)"
    r"(?:_pe_\d+)?"
    r"(?:__\d+)?"
    r"\.wav$",
    re.IGNORECASE,
)

# Старый вариант: папка Group TO_* + FR_4489_2025-06-05_11-40-53_0[+].wav
BUNDLE_GROUP_DIR_RE = re.compile(
    r"^Group\s+TO_(?P<group>\d+)\s*$",
    re.IGNORECASE,
)
BUNDLE_LEGACY_WAV_RE = re.compile(
    r"^FR_(?P<cid>[\w\d]+)"
    r"(?:_(?P<date>\d{4}-\d{2}-\d{2}))?"
    r"(?:[-_](?P<time>\d{2}[-.:]\d{2}(?:[-.:]\d{2})?))?"
    r"(?:[-_](?P<order>\d+))?"
    r"(?P<decoded>\[\+\])?"
    r"\.wav$",
    re.IGNORECASE,
)

BUNDLE_FREQ_RE = re.compile(r"^\d{1,4}(?:[.,]\d+)?$")
BUNDLE_BATCH_ID_RE = re.compile(r"^\d{10,}$")

BUNDLE_SCAN_VERSION = 2
_BUNDLE_SCAN_CACHE: dict[tuple[object, ...], dict[str, object]] = {}
_BUNDLE_SCAN_CACHE_TTL_SECONDS = 30.0


def _looks_like_frequency(name: str) -> bool:
    s = str(name or "").strip()
    if not s:
        return False
    if BUNDLE_BATCH_ID_RE.match(s):
        return False
    norm = s.replace(",", ".")
    return bool(BUNDLE_FREQ_RE.match(norm))


def _frequency_from_folder_name(name: str) -> str:
    m = FREQ_FOLDER_RE.match(str(name or "").strip())
    if m:
        return str(m.group("freq") or "").replace(",", ".")
    if _looks_like_frequency(name):
        return str(name).replace(",", ".")
    return str(name or "").strip().replace(",", ".")


def _frequency_from_group_dir(group_dir: Path) -> str:
    parent = group_dir.parent
    freq = _frequency_from_folder_name(parent.name)
    if _looks_like_frequency(freq) or FREQ_FOLDER_RE.match(parent.name):
        return freq
    grand = parent.parent
    if grand:
        return _frequency_from_folder_name(grand.name)
    return freq


def _parse_bundle_recorded_at(
    *,
    date_raw: str,
    time_raw: str,
    file_path: Path,
) -> tuple[str, float]:
    date_s = str(date_raw or "").strip()
    time_s = str(time_raw or "").strip().replace(".", "-").replace(":", "-")
    if date_s and time_s:
        parts = time_s.split("-")
        while len(parts) < 3:
            parts.append("00")
        time_norm = "-".join(parts[:3])
        try:
            dt = datetime.strptime(f"{date_s} {time_norm}", "%Y-%m-%d %H-%M-%S")
            return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.timestamp()
        except ValueError:
            pass
    try:
        st = file_path.stat()
        dt = datetime.fromtimestamp(st.st_mtime)
        return dt.strftime("%Y-%m-%d %H:%M:%S"), float(st.st_mtime)
    except Exception:
        return "", 0.0


def _parse_bundle_wav_name(name: str) -> dict[str, str | int | bool] | None:
    n = str(name or "").strip()
    m = BUNDLE_CT_WAV_RE.match(n)
    if m:
        channel = int(m.group("channel") or 0)
        order = int(m.group("order") or 0)
        return {
            "correspondent_id": str(m.group("cid") or "").strip(),
            "group_code": str(m.group("group") or "").strip(),
            "order_index": order * 10000 + channel,
            "date": str(m.group("date") or ""),
            "time": str(m.group("time") or ""),
            "decoded": True,
            "slot": "0",
        }
    m = BUNDLE_LEGACY_WAV_RE.match(n)
    if not m:
        return None
    cid = str(m.group("cid") or "").strip()
    if not cid:
        return None
    order_raw = m.group("order")
    return {
        "correspondent_id": cid,
        "group_code": "",
        "order_index": int(order_raw) if order_raw is not None else 0,
        "decoded": bool(m.group("decoded")),
        "date": str(m.group("date") or ""),
        "time": str(m.group("time") or ""),
        "slot": "0",
    }


def _iter_bundle_freq_dirs(base: Path, *, max_depth: int = 6) -> list[Path]:
    found: list[Path] = []
    stack: list[tuple[Path, int]] = [(base, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            with os.scandir(current) as it:
                dirs: list[tuple[Path, str]] = []
                for entry in it:
                    try:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                    except Exception:
                        continue
                    dirs.append((Path(entry.path), entry.name))
                for path, name in dirs:
                    if FREQ_FOLDER_RE.match(name) or _looks_like_frequency(name):
                        found.append(path)
                    elif depth < max_depth:
                        stack.append((path, depth + 1))
        except Exception:
            continue
    return found


def _iter_wav_entries_under(dir_path: Path, *, max_depth: int = 2) -> list[os.DirEntry]:
    found: list[os.DirEntry] = []
    stack: list[tuple[Path, int]] = [(dir_path, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            if str(entry.name or "").lower().endswith(".wav"):
                                found.append(entry)
                            continue
                        if entry.is_dir(follow_symlinks=False) and depth < max_depth:
                            stack.append((Path(entry.path), depth + 1))
                    except Exception:
                        continue
        except Exception:
            continue
    return found


def _iter_bundle_group_dirs(base: Path, *, max_depth: int = 6) -> list[Path]:
    found: list[Path] = []
    stack: list[tuple[Path, int]] = [(base, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            with os.scandir(current) as it:
                dirs: list[tuple[Path, str]] = []
                for entry in it:
                    try:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                    except Exception:
                        continue
                    dirs.append((Path(entry.path), entry.name))
                for path, name in dirs:
                    if BUNDLE_GROUP_DIR_RE.match(name):
                        found.append(path)
                    elif depth < max_depth:
                        stack.append((path, depth + 1))
        except Exception:
            continue
    return found


def probe_bundle_layout(base_folder: Path) -> bool:
    probe = probe_path(base_folder)
    if not probe.ok or not probe.exists or not probe.is_dir:
        return False
    base = Path(probe.resolved or str(base_folder))
    for freq_dir in _iter_bundle_freq_dirs(base, max_depth=5):
        try:
            with os.scandir(freq_dir) as it:
                for entry in it:
                    if str(entry.name or "").lower().endswith(".wav") and _parse_bundle_wav_name(
                        entry.name
                    ):
                        return True
        except Exception:
            continue
    return bool(_iter_bundle_group_dirs(base, max_depth=5))


def _ingest_bundle_wav(
    *,
    entry: os.DirEntry,
    base_folder: Path,
    frequency: str,
    group_code: str,
    debug: dict | None,
    tasks_only: bool,
    task_set: set[str],
    task_cmp_set: set[str],
    since_ts: float | None,
    dedupe: dict[tuple[str, str, str, int, str, str], InterceptAudioEntry],
    limit: int,
) -> bool:
    if not str(entry.name or "").lower().endswith(".wav"):
        _debug_add(debug, "not_wav", Path(entry.path))
        return False
    try:
        if not entry.is_file(follow_symlinks=False):
            return False
    except Exception:
        _debug_add(debug, "file_stat_error", Path(entry.path))
        return False
    meta_wav = _parse_bundle_wav_name(entry.name)
    if not meta_wav:
        _debug_add(debug, "name_mismatch", Path(entry.path))
        return False
    file_path = Path(entry.path)
    grp = str(meta_wav.get("group_code") or group_code or "").strip()
    recorded_at, recorded_ts = _parse_bundle_recorded_at(
        date_raw=str(meta_wav.get("date") or ""),
        time_raw=str(meta_wav.get("time") or ""),
        file_path=file_path,
    )
    if since_ts is not None and recorded_ts < float(since_ts):
        _debug_add(debug, "filtered_by_since", file_path)
        return False
    if tasks_only and task_set:
        pf = _normalize_freq(frequency)
        pcmp = _freq_compare_key(frequency)
        if (pf not in task_set) and (not pcmp or pcmp not in task_cmp_set):
            _debug_add(debug, "filtered_by_task", file_path)
            return False
    try:
        rel = file_path.relative_to(base_folder)
    except Exception:
        try:
            rel = Path(os.path.relpath(file_path, base_folder))
        except Exception:
            _debug_add(debug, "rel_error", file_path)
            return False
    file_rel = str(rel).replace("\\", "/")
    try:
        st = entry.stat()
    except Exception:
        _debug_add(debug, "stat_error", file_path)
        return False
    file_key = f"{file_rel}|{int(st.st_size)}|{int(st.st_mtime)}"
    correspondent_id = str(meta_wav.get("correspondent_id") or "")
    order_index = int(meta_wav.get("order_index") or 0)
    slot = str(meta_wav.get("slot") or "0")
    entry_obj = InterceptAudioEntry(
        file_path=file_path,
        file_rel=file_rel,
        file_key=file_key,
        frequency=frequency,
        group_code=grp,
        correspondent_id=correspondent_id,
        order_index=order_index,
        recorded_at=recorded_at,
        recorded_ts=recorded_ts,
        duration_sec=_wav_duration_seconds(file_path),
        has_key=True,
        has_message=False,
        aes_key="",
        slot=slot,
        peer_correspondent_id="",
        call_mode="group",
    )
    key = (
        entry_obj.frequency,
        entry_obj.group_code,
        entry_obj.correspondent_id,
        entry_obj.order_index,
        entry_obj.recorded_at,
        entry_obj.slot,
    )
    existing = dedupe.get(key)
    if existing is None or len(entry_obj.file_rel) < len(existing.file_rel):
        dedupe[key] = entry_obj
    return len(dedupe) >= limit * 3


def scan_bundle_intercept_audio_files(
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
) -> list[InterceptAudioEntry]:
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
        debug["layout"] = "bundle"
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
        meta["layout"] = "bundle"
        meta["cached"] = False
        meta["elapsed_ms"] = 0.0

    cache_key = (
        str(base_folder),
        bool(tasks_only),
        tuple(sorted(task_set)),
        int(limit),
        bool(newest_first),
        int(BUNDLE_SCAN_VERSION),
    )
    cache_now = time.time()
    if use_cache:
        cached = _BUNDLE_SCAN_CACHE.get(cache_key)
        if cached and (cache_now - float(cached.get("ts", 0))) <= _BUNDLE_SCAN_CACHE_TTL_SECONDS:
            if meta is not None:
                meta["cached"] = True
            if debug is not None:
                debug["cache"] = {"hit": True}
            return list(cached.get("result") or [])

    t_total = time.perf_counter()
    dedupe: dict[tuple[str, str, str, int, str, str], InterceptAudioEntry] = {}
    time_budget_hit = False

    freq_dirs = _iter_bundle_freq_dirs(base_folder, max_depth=6)
    _debug_inc(debug, "freq_dirs", len(freq_dirs))

    for freq_dir in freq_dirs:
        if time_budget_s is not None and (time.perf_counter() - t_total) >= float(time_budget_s):
            time_budget_hit = True
            break
        frequency = _frequency_from_folder_name(freq_dir.name)
        if debug is not None:
            debug["progress"]["last_dir"] = str(freq_dir)
        for entry in _iter_wav_entries_under(freq_dir, max_depth=2):
            if debug is not None:
                debug["scanned"] += 1
                debug["progress"]["last_file"] = entry.name
            if _ingest_bundle_wav(
                entry=entry,
                base_folder=base_folder,
                frequency=frequency,
                group_code="",
                debug=debug,
                tasks_only=tasks_only,
                task_set=task_set,
                task_cmp_set=task_cmp_set,
                since_ts=since_ts,
                dedupe=dedupe,
                limit=limit,
            ):
                break

    if not freq_dirs:
        group_dirs = _iter_bundle_group_dirs(base_folder, max_depth=6)
        _debug_inc(debug, "group_dirs", len(group_dirs))
        for group_dir in group_dirs:
            if time_budget_s is not None and (time.perf_counter() - t_total) >= float(time_budget_s):
                time_budget_hit = True
                break
            gm = BUNDLE_GROUP_DIR_RE.match(group_dir.name)
            if not gm:
                continue
            group_code = str(gm.group("group") or "").strip()
            frequency = _frequency_from_group_dir(group_dir)
            if debug is not None:
                debug["progress"]["last_dir"] = str(group_dir)
            try:
                with os.scandir(group_dir) as it:
                    for entry in it:
                        if debug is not None:
                            debug["scanned"] += 1
                            debug["progress"]["last_file"] = entry.name
                        if _ingest_bundle_wav(
                            entry=entry,
                            base_folder=base_folder,
                            frequency=frequency,
                            group_code=group_code,
                            debug=debug,
                            tasks_only=tasks_only,
                            task_set=task_set,
                            task_cmp_set=task_cmp_set,
                            since_ts=since_ts,
                            dedupe=dedupe,
                            limit=limit,
                        ):
                            break
            except Exception:
                _debug_add(debug, "scandir_error", group_dir)

    if time_budget_hit:
        if debug is not None:
            debug["truncated"] = True
        if meta is not None:
            meta["truncated"] = True
            meta["truncated_reason"] = "time_budget"

    out = list(dedupe.values())
    out.sort(
        key=lambda x: (x.recorded_ts, x.order_index, x.file_rel),
        reverse=bool(newest_first),
    )
    if len(out) > limit:
        out = out[:limit]
        if meta is not None:
            meta["truncated"] = True
            meta["truncated_reason"] = "limit"
    out = _enrich_message_flags(out)
    if meta is not None:
        meta["elapsed_ms"] = round((time.perf_counter() - t_total) * 1000.0, 2)
        meta["returned"] = len(out)
    if debug is not None:
        debug["kept"] = len(out)
        _debug_time(debug, "total", t_total)
    if use_cache:
        _BUNDLE_SCAN_CACHE[cache_key] = {"ts": cache_now, "result": list(out)}
    return out
