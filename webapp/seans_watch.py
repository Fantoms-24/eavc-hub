"""Глобальный watcher папок с сеансами (hub_global) и его автостарт-конфиг.

Вынесено из app.py без изменения поведения.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask

from web_portal.config import seans_watch_status_path, seans_watch_stop_path

_log = logging.getLogger("web_portal.webapp.seans_watch")


def _normalize_watch_folder_path(path: str) -> str:
    try:
        return os.path.normcase(
            os.path.normpath(os.path.abspath(str(path or "").strip()))
        )
    except Exception:
        return str(path or "").strip()


def _read_seans_watch_autostart() -> dict | None:
    from web_portal.config import seans_watch_autostart_path

    p = seans_watch_autostart_path()
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_seans_watch_autostart(
    *,
    enabled: bool,
    position_name: str = "",
    folder_path: str = "",
    interval_sec: float = 5.0,
) -> None:
    from web_portal.config import seans_watch_autostart_path

    p = seans_watch_autostart_path()
    body = {
        "enabled": bool(enabled),
        "position_name": str(position_name or "").strip(),
        "folder_path": str(folder_path or "").strip(),
        "interval_sec": float(interval_sec),
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _clear_seans_watch_autostart() -> None:
    _write_seans_watch_autostart(
        enabled=False, position_name="", folder_path="", interval_sec=5.0
    )


def _launch_global_seans_watch_worker(
    app: Flask,
    position_name: str,
    folder_path: str,
    interval_sec: float,
) -> dict:
    """
    Поднимает глобальный watcher (hub_global). Если уже работает тот же путь/позиция/интервал —
    возвращает ok без остановки процесса (обновление страницы не перезапускает воркер).
    """
    if not hasattr(app, "session_watchers"):
        app.session_watchers = {}
    watcher_key = "hub_global"
    norm_new = _normalize_watch_folder_path(folder_path)

    prev = app.session_watchers.get(watcher_key)
    if prev:
        try:
            same = (
                str(prev.get("position_name") or "") == str(position_name)
                and _normalize_watch_folder_path(str(prev.get("folder_path") or ""))
                == norm_new
                and float(prev.get("interval_sec") or interval_sec) == float(interval_sec)
            )
            alive = False
            if prev.get("mode") == "subprocess":
                pr = prev.get("proc")
                alive = pr is not None and pr.poll() is None
            else:
                tr = prev.get("thread")
                alive = tr is not None and tr.is_alive()
            if same and alive:
                return {
                    "ok": True,
                    "message": "Автопоиск уже запущен с теми же параметрами",
                    "noop": True,
                }
        except Exception:
            _log.debug("_launch_global_seans_watch_worker: suppressed error", exc_info=True)

    if watcher_key in app.session_watchers:
        try:
            prev = app.session_watchers[watcher_key]
            if prev.get("mode") == "subprocess":
                sp_prev = prev.get("stop_path")
                proc_prev = prev.get("proc")
                if sp_prev:
                    try:
                        sp_prev.touch()
                    except Exception:
                        _log.debug("_launch_global_seans_watch_worker: suppressed error", exc_info=True)
                if proc_prev:
                    try:
                        proc_prev.terminate()
                        proc_prev.wait(timeout=6)
                    except Exception:
                        try:
                            proc_prev.kill()
                        except Exception:
                            _log.debug("_launch_global_seans_watch_worker: suppressed error", exc_info=True)
                try:
                    seans_watch_status_path().unlink(missing_ok=True)
                except Exception:
                    _log.debug("_launch_global_seans_watch_worker: suppressed error", exc_info=True)
            else:
                try:
                    prev_stop = prev.get("stop")
                    if prev_stop:
                        prev_stop.set()
                except Exception:
                    _log.debug("_launch_global_seans_watch_worker: suppressed error", exc_info=True)
                try:
                    prev_thr = prev.get("thread")
                    if prev_thr:
                        prev_thr.join(timeout=5)
                except Exception:
                    _log.debug("_launch_global_seans_watch_worker: suppressed error", exc_info=True)
        except Exception:
            _log.debug("_launch_global_seans_watch_worker: suppressed error", exc_info=True)

    use_subprocess = (
        os.environ.get("WEB_PORTAL_SEANS_WATCH_SUBPROCESS", "1")
        .strip()
        .lower()
        not in ("0", "false", "no", "off")
    )
    if use_subprocess:
        from web_portal.lib.seans_watch_core import atomic_write_status_json

        spath = seans_watch_stop_path()
        try:
            spath.unlink(missing_ok=True)
        except Exception:
            _log.debug("_launch_global_seans_watch_worker: suppressed error", exc_info=True)
        if getattr(sys, "frozen", False):
            cmd = [
                sys.executable,
                "--seans-watch-worker",
                "--position",
                position_name,
                "--folder",
                folder_path,
                "--interval",
                str(interval_sec),
            ]
        else:
            child = Path(__file__).resolve().parent.parent / "seans_watch_child.py"
            cmd = [
                sys.executable,
                str(child),
                "--position",
                position_name,
                "--folder",
                folder_path,
                "--interval",
                str(interval_sec),
            ]
        popen_kw: dict[str, object] = {}
        if sys.platform == "win32":
            popen_kw["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        proc = subprocess.Popen(cmd, **popen_kw)
        st_path = seans_watch_status_path()
        init_status = {
            "running": True,
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "position_name": position_name,
            "folder_path": folder_path,
            "watch_folder": folder_path,
            "interval_sec": interval_sec,
            "mode": "subprocess",
            "pid": proc.pid,
            "last_message": "Запуск отдельного процесса автопоиска...",
            "last_error": "",
            "files_seen": 0,
            "files_processed": 0,
            "rows_parsed": 0,
            "freq_dirs_scanned": 0,
            "time_dirs_scanned": 0,
            "result0_found": 0,
            "skipped_unchanged": 0,
            "skipped_already_in_db": 0,
            "seeded_freqs": 0,
            "last_cycle_ms": 0,
            "scan_in_progress": False,
            "scan_progress_pct": 0,
            "scan_freq_done": 0,
            "scan_freq_total": 0,
            "scan_time_done": 0,
            "scan_time_total": 0,
            "scan_current_freq": "",
        }
        try:
            atomic_write_status_json(st_path, init_status)
        except Exception:
            _log.debug("_launch_global_seans_watch_worker: suppressed error", exc_info=True)
        app.session_watchers[watcher_key] = {
            "mode": "subprocess",
            "proc": proc,
            "folder_path": folder_path,
            "position_name": position_name,
            "interval_sec": interval_sec,
            "status_path": st_path,
            "stop_path": spath,
        }
        _write_seans_watch_autostart(
            enabled=True,
            position_name=position_name,
            folder_path=folder_path,
            interval_sec=interval_sec,
        )
        return {
            "ok": True,
            "message": "Автопоиск запущен в отдельном процессе (вторая консоль на Windows)",
        }

    stop_event = threading.Event()
    status_lock = threading.Lock()
    status: dict[str, object] = {
        "running": True,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "position_name": position_name,
        "folder_path": folder_path,
        "watch_folder": folder_path,
        "interval_sec": interval_sec,
        "last_check_at": None,
        "last_message": "Запуск автопоиска...",
        "last_error": "",
        "files_seen": 0,
        "files_processed": 0,
        "rows_parsed": 0,
        "freq_dirs_scanned": 0,
        "time_dirs_scanned": 0,
        "result0_found": 0,
        "skipped_unchanged": 0,
        "skipped_already_in_db": 0,
        "seeded_freqs": 0,
        "last_cycle_ms": 0,
        "scan_in_progress": False,
        "scan_progress_pct": 0,
        "scan_freq_done": 0,
        "scan_freq_total": 0,
        "scan_time_done": 0,
        "scan_time_total": 0,
        "scan_current_freq": "",
    }

    def watch_loop():
        from web_portal.lib.seans_watch_core import run_seans_watch_loop

        run_seans_watch_loop(
            position_name=position_name,
            folder_path=folder_path,
            interval_sec=interval_sec,
            should_stop=stop_event.is_set,
            wait_secs=stop_event.wait,
            status=status,
            status_lock=status_lock,
            persist_status_path=None,
        )

    thread = threading.Thread(target=watch_loop, daemon=True)
    thread.start()

    app.session_watchers[watcher_key] = {
        "mode": "thread",
        "thread": thread,
        "stop": stop_event,
        "folder_path": folder_path,
        "position_name": position_name,
        "interval_sec": interval_sec,
        "status": status,
        "status_lock": status_lock,
    }
    _write_seans_watch_autostart(
        enabled=True,
        position_name=position_name,
        folder_path=folder_path,
        interval_sec=interval_sec,
    )
    return {"ok": True, "message": "Автопоиск запущен (в потоке процесса сервера)"}
