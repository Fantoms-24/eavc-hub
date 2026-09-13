"""Фоновая обработка export_jobs внутри процесса портала (без отдельного jobs_worker.py)."""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from pathlib import Path

from web_portal.config import DEFAULT_DB_NAME, db_path
from web_portal.lib.background_jobs import BackgroundJobRunner
from web_portal.lib.db import connect, ensure_db
from web_portal.lib.export_job_builders import build_export_job_result
from web_portal.lib.export_jobs import (
    claim_next_export_job,
    complete_claimed_export_job,
    fail_claimed_export_job,
    init_export_jobs,
    try_start_export_job,
    update_export_job,
)

_LOG = logging.getLogger("web_portal.export_jobs")

_export_runner = BackgroundJobRunner(workers=4, maxsize=128)
_embedded_started = False
_embedded_lock = threading.Lock()


def submit_export_task(name: str, run) -> bool:
    _export_runner.start()
    return _export_runner.submit(str(name or "export"), run)


def _worker_id() -> str:
    return f"embedded:{socket.gethostname()}:{os.getpid()}"


def run_export_job_by_id(base_dir: Path, job_id: int, build_fn) -> None:
    """Выполняет экспорт по id задачи (без claim — для прямого submit)."""
    p = db_path(DEFAULT_DB_NAME)
    ensure_db(p)
    conn = connect(p)
    try:
        if not try_start_export_job(conn, int(job_id)):
            return
    finally:
        conn.close()
    try:
        result = build_fn()
        conn = connect(p)
        try:
            update_export_job(conn, int(job_id), status="completed", result=result)
        finally:
            conn.close()
    except Exception as exc:
        _LOG.exception("export job %s failed", job_id)
        conn = connect(p)
        try:
            update_export_job(conn, int(job_id), status="failed", error_text=str(exc))
        finally:
            conn.close()


def _poll_claimed_once(base_dir: Path) -> bool:
    p = db_path(DEFAULT_DB_NAME)
    ensure_db(p)
    conn = connect(p)
    try:
        init_export_jobs(conn)
        job = claim_next_export_job(conn, worker_id=_worker_id())
        if not job:
            return False
    finally:
        conn.close()

    job_id = int(job.get("id") or 0)
    try:
        result = build_export_job_result(base_dir, job)
        conn = connect(p)
        try:
            complete_claimed_export_job(conn, job_id, result=result)
        finally:
            conn.close()
        _LOG.info("export job %s completed (%s)", job_id, job.get("job_type"))
        return True
    except Exception as exc:
        conn = connect(p)
        try:
            fail_claimed_export_job(conn, job_id, error_text=str(exc), retry=True)
        finally:
            conn.close()
        _LOG.exception("export job %s failed (%s)", job_id, job.get("job_type"))
        return True


def start_embedded_export_jobs_worker(base_dir: Path) -> None:
    """Подхватывает pending export_jobs, если очередь submit не успела."""
    global _embedded_started
    with _embedded_lock:
        if _embedded_started:
            return
        _embedded_started = True

    idle_sec = float(os.environ.get("WEB_PORTAL_EXPORT_JOBS_IDLE_SLEEP") or "0.75")

    def _loop() -> None:
        while True:
            try:
                if not _poll_claimed_once(base_dir):
                    time.sleep(max(0.25, idle_sec))
            except Exception:
                _LOG.exception("embedded export jobs loop error")
                time.sleep(max(1.0, idle_sec))

    threading.Thread(
        target=_loop,
        daemon=True,
        name="wp-export-jobs-embedded",
    ).start()
