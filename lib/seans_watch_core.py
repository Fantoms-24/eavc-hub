"""
Ядро автопоиска сеансов (result0.txt): один цикл сканирования.
Может работать в потоке процесса Flask или в отдельном процессе — см. app.py.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from web_portal.config import DATA_DIR, db_path
from web_portal.lib.seans_db import connect_seans_storage, ensure_seans_storage, resolve_seans_storage_path
from web_portal.lib.collect_seanses_from_dir import parse_result0_file
from web_portal.lib.db import (
    mark_processed,
    max_seans_date_times_by_frequency,
    refresh_seanses_daily_aggregates_for_entries,
    save_seans_entries,
    seans_entries_fully_in_database,
    was_processed,
)

_log = logging.getLogger("web_portal.lib.seans_watch_core")

LOG = logging.getLogger("web_portal.sessions")
DEFAULT_FREQ_PARALLEL = 5
_SEANS_CACHE_EPOCH_FILE = "seans_watch_cache_epoch.txt"


def seans_watch_cache_epoch() -> str:
    """Версия данных для инвалидации кэша таблицы сеансов (обновляет автопоиск)."""
    p = (DATA_DIR / _SEANS_CACHE_EPOCH_FILE).resolve()
    try:
        if p.is_file():
            raw = p.read_text(encoding="utf-8").strip()
            if raw:
                return raw
            return str(int(p.stat().st_mtime))
    except Exception:
        _log.debug("seans_watch_cache_epoch: suppressed error", exc_info=True)
    return "0"


def bump_seans_watch_cache_epoch() -> None:
    p = (DATA_DIR / _SEANS_CACHE_EPOCH_FILE).resolve()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"{time.time():.3f}", encoding="utf-8")
    except Exception:
        _log.debug("bump_seans_watch_cache_epoch: suppressed error", exc_info=True)


def seans_watch_freq_parallel() -> int:
    raw = (os.environ.get("WEB_PORTAL_SEANS_WATCH_FREQ_PARALLEL") or "").strip()
    try:
        n = int(raw) if raw else DEFAULT_FREQ_PARALLEL
    except Exception:
        n = DEFAULT_FREQ_PARALLEL
    return max(1, min(n, 16))


def atomic_write_status_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def run_seans_watch_loop(
    *,
    position_name: str,
    folder_path: str,
    interval_sec: float,
    should_stop: Callable[[], bool],
    wait_secs: Callable[[float], None],
    status: dict[str, object],
    status_lock: threading.Lock,
    persist_status_path: Path | None = None,
) -> None:
    """
    should_stop / wait_secs:
      в потоке: stop_event.is_set и stop_event.wait(timeout=...)
      в отдельном процессе: проверка файла-флага и sleep чанками
    """
    folder = Path(folder_path)

    TIME_FOLDER_RE = re.compile(
        r"(\d{4})[-_](\d{2})[-_](\d{2})[_-](\d{2})-(\d{2})(?:-(\d{2}))?"
    )
    DAY_IN_PATH_RE = re.compile(r"(\d{4}-\d{2}-\d{2})$")
    GRACE = timedelta(hours=24)
    FIRST_SCAN_LOOKBACK = timedelta(days=14)

    def _use_folder_time_cutoff() -> bool:
        raw = (os.environ.get("WEB_PORTAL_SEANS_WATCH_USE_CUTOFF") or "").strip().lower()
        return raw in ("1", "true", "yes", "on")

    def _resolve_result0_file(time_folder: Path) -> Path | None:
        for cand in (
            time_folder / "result0.txt",
            time_folder / "result0",
            time_folder / "DMR" / "result0.txt",
            time_folder / "DMR" / "result0",
        ):
            if cand.exists() and cand.is_file():
                return cand
        return None

    def _normalize_file_path(raw: str) -> tuple[str, str]:
        fpath_raw = str(raw or "")
        try:
            fpath = os.path.normcase(os.path.normpath(os.path.abspath(fpath_raw)))
        except Exception:
            fpath = fpath_raw
        return fpath_raw, fpath

    def _build_time_folder_worklist(
        conn_obj,
        time_dirs_all: list[tuple[datetime, Path]],
    ) -> list[tuple[datetime, Path, Path]]:
        """Все папки времени с result0: сначала неимпортированные (старые → новые), затем уже обработанные."""
        pending: list[tuple[datetime, Path, Path]] = []
        done: list[tuple[datetime, Path, Path]] = []
        for folder_time, time_folder in time_dirs_all:
            result0_file = _resolve_result0_file(time_folder)
            if result0_file is None:
                continue
            try:
                st = result0_file.stat()
                fpath_raw, fpath = _normalize_file_path(str(result0_file))
                mtime = float(st.st_mtime)
                size = int(st.st_size)
            except Exception:
                continue
            item = (folder_time, time_folder, result0_file)
            if was_processed(conn_obj, fpath, mtime, size, position_name=position_name):
                done.append(item)
                continue
            if fpath_raw != fpath and was_processed(
                conn_obj, fpath_raw, mtime, size, position_name=position_name
            ):
                done.append(item)
                continue
            pending.append(item)

        pending.sort(key=lambda x: x[0])
        done.sort(key=lambda x: x[0], reverse=True)
        return pending + done

    def _set_status(**kwargs: object) -> None:
        try:
            with status_lock:
                status.update(kwargs)
                snap = dict(status)
        except Exception:
            return
        if persist_status_path is not None:
            try:
                atomic_write_status_json(persist_status_path, snap)
            except Exception:
                _log.debug("_set_status: suppressed error", exc_info=True)

    def _bump(key: str, inc: int = 1) -> None:
        try:
            with status_lock:
                status[key] = int(status.get(key) or 0) + int(inc)
        except Exception:
            _log.debug("_bump: suppressed error", exc_info=True)

    def _make_scan_progress_reporter() -> Callable[..., None]:
        last_log_at = 0.0
        last_status_at = 0.0

        def _report(
            *,
            freq_done: int,
            freq_total: int,
            time_done: int = 0,
            time_total: int = 0,
            current_freq: str = "",
            force: bool = False,
        ) -> None:
            nonlocal last_log_at, last_status_at
            if freq_total > 0:
                pct = int(min(100, round(freq_done * 100 / freq_total)))
            else:
                pct = 0
            msg = f"Обработано {freq_done} частот из {freq_total} ({pct}%)"
            if time_total > 0:
                msg += f", папок result0 {time_done}/{time_total}"
            if current_freq:
                msg += f" · {current_freq}"
            now = time.perf_counter()
            if force or now - last_status_at >= 1.0:
                last_status_at = now
                _set_status(
                    scan_in_progress=True,
                    scan_progress_pct=pct,
                    scan_freq_done=freq_done,
                    scan_freq_total=freq_total,
                    scan_time_done=time_done,
                    scan_time_total=time_total,
                    scan_current_freq=current_freq,
                    last_message=msg,
                )
            if force or now - last_log_at >= 2.0:
                last_log_at = now
                LOG.info("[watch] %s", msg)

        return _report

    while not should_stop():
        t0 = time.perf_counter()
        cycle_freq_dirs = 0
        cycle_time_dirs = 0
        cycle_result0_found = 0
        cycle_skipped_unchanged = 0
        cycle_seeded = 0
        cycle_processed_now = 0
        cycle_skipped_already_in_db = 0
        unmatched_examples: list[str] = []
        try:
            current_date = datetime.now().strftime("%Y-%m-%d")
            path_str = str(folder)
            date_match = DAY_IN_PATH_RE.search(path_str)
            if date_match:
                path_date = date_match.group(1)
                if path_date != current_date:
                    new_path = DAY_IN_PATH_RE.sub(current_date, path_str)
                    watch_folder = Path(new_path)
                else:
                    watch_folder = folder
            else:
                watch_folder = folder

            if not watch_folder.exists():
                _set_status(
                    last_check_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    watch_folder=str(watch_folder),
                    last_message="Папка не существует, ожидание...",
                )
                wait_secs(60)
                continue

            p = resolve_seans_storage_path()
            ensure_seans_storage(p)
            conn = connect_seans_storage()
            try:
                _set_status(
                    last_check_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    watch_folder=str(watch_folder),
                    last_message="Сканирование (только новые файлы)...",
                    scan_freq_parallel=seans_watch_freq_parallel(),
                )
                cur = conn.cursor()

                def _parse_last_time(v: object) -> datetime | None:
                    try:
                        return datetime.strptime(str(v or ""), "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        return None

                root_path_raw = str(watch_folder)
                try:
                    root_path_norm = os.path.normcase(
                        os.path.normpath(os.path.abspath(root_path_raw))
                    )
                except Exception:
                    root_path_norm = root_path_raw
                root_key = f"{root_path_norm}::pos={position_name}"
                legacy_root_key = f"{root_path_raw}::pos={position_name}"
                last_time_rows = cur.execute(
                    """
                    SELECT frequency, folder_path, last_time
                    FROM frequency_last_processed
                    WHERE folder_path IN (?, ?)
                    """,
                    (root_key, legacy_root_key),
                ).fetchall()
                last_time_map: dict[tuple[str, str], datetime] = {}
                for rr in last_time_rows or []:
                    dtv = _parse_last_time(rr[2])
                    if dtv is None:
                        continue
                    last_time_map[(str(rr[0] or ""), str(rr[1] or ""))] = dtv

                report_scan = _make_scan_progress_reporter()
                seans_max_by_freq = max_seans_date_times_by_frequency(
                    conn, client_name=position_name
                )

                try:
                    freq_entries_list = [
                        e
                        for e in os.scandir(str(watch_folder))
                        if e.is_dir(follow_symlinks=False)
                    ]
                except Exception as e:
                    _set_status(last_error=str(e), last_message="Ошибка доступа к папке")
                    wait_secs(10)
                    continue

                freq_total = len(freq_entries_list)
                freq_parallel = seans_watch_freq_parallel()
                freq_done = 0
                progress_lock = threading.Lock()

                def _report_freq_progress(
                    *, current_freq: str = "", force: bool = False
                ) -> None:
                    report_scan(
                        freq_done=freq_done,
                        freq_total=freq_total,
                        time_done=cycle_time_dirs,
                        time_total=max(cycle_time_dirs, 0),
                        current_freq=current_freq,
                        force=force,
                    )

                _set_status(
                    scan_in_progress=True,
                    scan_progress_pct=0,
                    scan_freq_done=0,
                    scan_freq_total=freq_total,
                    scan_time_done=0,
                    scan_time_total=0,
                    scan_current_freq="",
                    scan_freq_parallel=freq_parallel,
                    last_message=f"Обработано 0 частот из {freq_total} (0%)",
                )
                _report_freq_progress(force=True)

                def _run_one_frequency(freq_entry: os.DirEntry) -> dict[str, Any]:
                    """Одна частота: scandir + result0 + запись в seans.sqlite (свой conn)."""
                    local = {
                        "freq": "",
                        "seeded": 0,
                        "time_dirs": 0,
                        "result0_found": 0,
                        "processed_now": 0,
                        "skipped_unchanged": 0,
                        "skipped_already_in_db": 0,
                        "files_seen": 0,
                        "files_processed": 0,
                        "rows_parsed": 0,
                        "has_writes": False,
                        "pending_last_time": None,
                        "unmatched_examples": [],
                        "error": "",
                    }
                    freq_folder = Path(freq_entry.path)
                    freq = freq_folder.name
                    local["freq"] = freq
                    worker_conn = connect_seans_storage()
                    try:
                        last_time = last_time_map.get((freq, root_key))
                        if last_time is None and legacy_root_key != root_key:
                            legacy_last = last_time_map.get((freq, legacy_root_key))
                            if legacy_last is not None:
                                last_time = legacy_last

                        had_last_marker = last_time is not None
                        db_wm = None
                        if last_time is None:
                            db_wm = seans_max_by_freq.get(freq)
                            if db_wm is not None:
                                last_time = db_wm
                        if last_time is None:
                            last_time = datetime.now().replace(
                                hour=0, minute=0, second=0, microsecond=0
                            ) - FIRST_SCAN_LOOKBACK
                            local["seeded"] = 1

                        cutoff = last_time - GRACE
                        if not had_last_marker and db_wm is None:
                            cutoff = last_time
                        use_cutoff = _use_folder_time_cutoff()
                        new_last = last_time
                        time_dirs_all: list[tuple[datetime, Path]] = []
                        try:
                            for time_entry in os.scandir(str(freq_folder)):
                                if not time_entry.is_dir(follow_symlinks=False):
                                    continue
                                name = time_entry.name
                                m = TIME_FOLDER_RE.search(name)
                                if not m:
                                    if len(local["unmatched_examples"]) < 3:
                                        local["unmatched_examples"].append(
                                            f"{freq}/{name}"
                                        )
                                    continue
                                y, mo, d, hh, mm, ss = m.groups()
                                folder_time = datetime(
                                    int(y),
                                    int(mo),
                                    int(d),
                                    int(hh),
                                    int(mm),
                                    int(ss) if ss is not None else 0,
                                )
                                if use_cutoff and folder_time <= cutoff:
                                    continue
                                time_dirs_all.append(
                                    (folder_time, Path(time_entry.path))
                                )
                        except Exception as exc:
                            local["error"] = str(exc)
                            return local

                        if not time_dirs_all:
                            return local

                        time_dirs_all.sort(key=lambda x: x[0])
                        time_dirs = _build_time_folder_worklist(
                            worker_conn, time_dirs_all
                        )
                        if not time_dirs:
                            return local

                        local["time_dirs"] = len(time_dirs)

                        def _flush_writes_to_db(
                            entries_for_agg: list | None = None,
                        ) -> None:
                            """Сразу fsync в seans.sqlite + daily_agg + сброс кэша UI."""
                            try:
                                if new_last > last_time:
                                    worker_conn.execute(
                                        """INSERT OR REPLACE INTO frequency_last_processed
                                        (frequency, folder_path, last_time, updated_at)
                                        VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
                                        (
                                            freq,
                                            root_key,
                                            new_last.strftime("%Y-%m-%d %H:%M:%S"),
                                        ),
                                    )
                                    local["pending_last_time"] = (
                                        freq,
                                        root_key,
                                        new_last,
                                    )
                                worker_conn.commit()
                                if entries_for_agg:
                                    refresh_seanses_daily_aggregates_for_entries(
                                        worker_conn,
                                        entries_for_agg,
                                        client_name=position_name,
                                    )
                                bump_seans_watch_cache_epoch()
                            except Exception as exc:
                                local["error"] = str(exc)
                                LOG.error(
                                    "Commit failed for freq %s: %s", freq, exc
                                )
                                try:
                                    worker_conn.rollback()
                                except Exception:
                                    _log.debug("_flush_writes_to_db: suppressed error", exc_info=True)

                        for folder_time, _time_folder, result0_file in time_dirs:
                            local["result0_found"] += 1
                            local["files_seen"] += 1
                            try:
                                st = result0_file.stat()
                                fpath_raw, fpath = _normalize_file_path(
                                    str(result0_file)
                                )
                                mtime = float(st.st_mtime)
                                size = int(st.st_size)

                                if was_processed(
                                    worker_conn,
                                    fpath,
                                    mtime,
                                    size,
                                    position_name=position_name,
                                ):
                                    if folder_time > new_last:
                                        new_last = folder_time
                                    local["skipped_unchanged"] += 1
                                    continue
                                if fpath_raw != fpath and was_processed(
                                    worker_conn,
                                    fpath_raw,
                                    mtime,
                                    size,
                                    position_name=position_name,
                                ):
                                    mark_processed(
                                        worker_conn,
                                        fpath,
                                        mtime,
                                        size,
                                        position_name=position_name,
                                        commit=False,
                                    )
                                    local["has_writes"] = True
                                    if folder_time > new_last:
                                        new_last = folder_time
                                    local["skipped_unchanged"] += 1
                                    _flush_writes_to_db()
                                    continue

                                seans_list = parse_result0_file(result0_file)
                                if seans_list is None:
                                    seans_list = []

                                if not seans_list:
                                    mark_processed(
                                        worker_conn,
                                        fpath,
                                        mtime,
                                        size,
                                        position_name=position_name,
                                        commit=False,
                                    )
                                    local["has_writes"] = True
                                    local["files_processed"] += 1
                                    local["processed_now"] += 1
                                    if folder_time > new_last:
                                        new_last = folder_time
                                    _flush_writes_to_db()
                                    continue

                                if seans_entries_fully_in_database(
                                    worker_conn, seans_list, client_name=position_name
                                ):
                                    mark_processed(
                                        worker_conn,
                                        fpath,
                                        mtime,
                                        size,
                                        position_name=position_name,
                                        commit=False,
                                    )
                                    local["has_writes"] = True
                                    local["skipped_unchanged"] += 1
                                    local["skipped_already_in_db"] += 1
                                    if folder_time > new_last:
                                        new_last = folder_time
                                    _flush_writes_to_db()
                                    continue

                                save_seans_entries(
                                    worker_conn,
                                    seans_list,
                                    client_name=position_name,
                                    commit=False,
                                )
                                local["rows_parsed"] += len(seans_list)
                                local["has_writes"] = True
                                mark_processed(
                                    worker_conn,
                                    fpath,
                                    mtime,
                                    size,
                                    position_name=position_name,
                                    commit=False,
                                )
                                local["files_processed"] += 1
                                local["processed_now"] += 1
                                if folder_time > new_last:
                                    new_last = folder_time
                                _flush_writes_to_db(seans_list)
                            except Exception as exc:
                                local["error"] = str(exc)
                                LOG.error(
                                    "Error processing %s: %s", result0_file, exc
                                )
                                try:
                                    worker_conn.rollback()
                                except Exception:
                                    _log.debug("_flush_writes_to_db: suppressed error", exc_info=True)
                    finally:
                        try:
                            worker_conn.close()
                        except Exception:
                            _log.debug("_run_one_frequency: suppressed error", exc_info=True)
                    return local

                pending_last_time: dict[tuple[str, str], datetime] = {}

                with ThreadPoolExecutor(max_workers=freq_parallel) as pool:
                    futures = [
                        pool.submit(_run_one_frequency, entry)
                        for entry in freq_entries_list
                    ]
                    for fut in as_completed(futures):
                        if should_stop():
                            break
                        try:
                            res = fut.result()
                        except Exception as exc:
                            LOG.error("Freq worker failed: %s", exc)
                            res = {"error": str(exc), "freq": ""}
                        cycle_freq_dirs += 1
                        cycle_time_dirs += int(res.get("time_dirs") or 0)
                        cycle_result0_found += int(res.get("result0_found") or 0)
                        cycle_processed_now += int(res.get("processed_now") or 0)
                        cycle_skipped_unchanged += int(
                            res.get("skipped_unchanged") or 0
                        )
                        cycle_skipped_already_in_db += int(
                            res.get("skipped_already_in_db") or 0
                        )
                        cycle_seeded += int(res.get("seeded") or 0)
                        _bump("files_seen", int(res.get("files_seen") or 0))
                        _bump("files_processed", int(res.get("files_processed") or 0))
                        _bump("rows_parsed", int(res.get("rows_parsed") or 0))
                        plt = res.get("pending_last_time")
                        if plt and isinstance(plt, tuple) and len(plt) == 3:
                            f_key, rp_key, dt_val = plt
                            pending_last_time[(str(f_key), str(rp_key))] = dt_val
                            last_time_map[(str(f_key), str(rp_key))] = dt_val
                        for ex in res.get("unmatched_examples") or []:
                            if len(unmatched_examples) < 3:
                                unmatched_examples.append(str(ex))
                        err = str(res.get("error") or "").strip()
                        if err:
                            _set_status(
                                last_error=err,
                                last_message="Ошибка обработки частоты "
                                f"{res.get('freq') or ''}",
                            )
                        with progress_lock:
                            freq_done += 1
                            _report_freq_progress(
                                current_freq=str(res.get("freq") or ""),
                            )
            finally:
                try:
                    conn.close()
                except Exception:
                    _log.debug("_report: suppressed error", exc_info=True)

            ms = int((time.perf_counter() - t0) * 1000)
            _set_status(
                scan_in_progress=False,
                scan_progress_pct=100,
                scan_freq_done=cycle_freq_dirs,
                scan_freq_total=cycle_freq_dirs,
                scan_time_done=cycle_time_dirs,
                scan_time_total=max(cycle_time_dirs, 1),
                scan_current_freq="",
                freq_dirs_scanned=cycle_freq_dirs,
                time_dirs_scanned=cycle_time_dirs,
                result0_found=cycle_result0_found,
                skipped_unchanged=cycle_skipped_unchanged,
                skipped_already_in_db=cycle_skipped_already_in_db,
                seeded_freqs=cycle_seeded,
                last_cycle_ms=ms,
                last_message=(
                    f"Обработано {cycle_freq_dirs} частот из {cycle_freq_dirs} (100%), "
                    f"папок result0 {cycle_time_dirs}, импорт новых={cycle_processed_now}, "
                    f"{ms}мс. Жду новые файлы..."
                ),
            )
            if unmatched_examples:
                _set_status(last_error="", unmatched_examples=unmatched_examples)
            try:
                LOG.info(
                    "[watch] folder=%s cycle_done freq=%s time_dirs=%s result0=%s "
                    "imported_new=%s skipped=%s skipped_in_db=%s seeded=%s cycle_ms=%s",
                    str(watch_folder),
                    cycle_freq_dirs,
                    cycle_time_dirs,
                    cycle_result0_found,
                    cycle_processed_now,
                    cycle_skipped_unchanged - cycle_skipped_already_in_db,
                    cycle_skipped_already_in_db,
                    cycle_seeded,
                    ms,
                )
            except Exception:
                _log.debug("_report: suppressed error", exc_info=True)
            if cycle_processed_now > 0:
                next_wait = max(0.5, float(interval_sec))
            elif cycle_result0_found > 0:
                next_wait = max(0.5, float(interval_sec))
            else:
                next_wait = min(15.0, max(2.0, float(interval_sec) * 1.8))
            wait_secs(next_wait)
        except Exception as e:
            LOG.error("Error in watch loop: %s", e)
            _set_status(last_error=str(e), last_message="Ошибка в автопоиске")
            wait_secs(60)

    _set_status(running=False, last_message="Автопоиск остановлен")


def wait_interruptible_seconds(
    seconds: float, should_stop: Callable[[], bool], chunk: float = 0.5
) -> None:
    """Ожидание с проверкой остановки (отдельный процесс без threading.Event)."""
    end = time.time() + float(seconds)
    while time.time() < end:
        if should_stop():
            return
        time.sleep(min(chunk, max(0.0, end - time.time())))
