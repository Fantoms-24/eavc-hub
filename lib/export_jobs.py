from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any
import logging

_log = logging.getLogger("web_portal.lib.export_jobs")


EXPORT_JOB_TTL_SEC = 24 * 60 * 60
EXPORT_JOB_MAX_ATTEMPTS = 3

# Макс. время формирования Word/Excel на большой БД (секунды).
_DEFAULT_EXPORT_JOB_MAX_RUNTIME_SEC = 6 * 60 * 60  # 6 ч
_DEFAULT_EXPORT_JOB_MAX_QUEUE_SEC = 3 * 60 * 60  # 3 ч в очереди
_DEFAULT_EXPORT_JOB_STALE_AFTER_SEC = 6 * 60 * 60  # не перехватывать running раньше


def export_job_max_runtime_sec() -> int:
    raw = os.environ.get("WEB_PORTAL_EXPORT_JOB_MAX_RUNTIME_SEC")
    try:
        v = int(raw) if raw is not None and str(raw).strip() != "" else _DEFAULT_EXPORT_JOB_MAX_RUNTIME_SEC
    except (TypeError, ValueError):
        v = _DEFAULT_EXPORT_JOB_MAX_RUNTIME_SEC
    return max(600, min(v, 24 * 60 * 60))


def export_job_max_queue_sec() -> int:
    raw = os.environ.get("WEB_PORTAL_EXPORT_JOB_MAX_QUEUE_SEC")
    try:
        v = int(raw) if raw is not None and str(raw).strip() != "" else _DEFAULT_EXPORT_JOB_MAX_QUEUE_SEC
    except (TypeError, ValueError):
        v = _DEFAULT_EXPORT_JOB_MAX_QUEUE_SEC
    return max(300, min(v, 24 * 60 * 60))


def export_job_stale_after_sec() -> int:
    raw = os.environ.get("WEB_PORTAL_EXPORT_JOB_STALE_AFTER_SEC")
    try:
        v = (
            int(raw)
            if raw is not None and str(raw).strip() != ""
            else _DEFAULT_EXPORT_JOB_STALE_AFTER_SEC
        )
    except (TypeError, ValueError):
        v = _DEFAULT_EXPORT_JOB_STALE_AFTER_SEC
    return max(export_job_max_runtime_sec(), min(v, 24 * 60 * 60))


def export_results_dir(base_dir: Path) -> Path:
    path = Path(base_dir) / "tmp" / "export_jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def init_export_jobs(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS export_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_uuid TEXT NOT NULL UNIQUE,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            position_name TEXT NOT NULL DEFAULT '',
            params_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            error_text TEXT NOT NULL DEFAULT '',
            created_by TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TEXT NOT NULL DEFAULT '',
            finished_at TEXT NOT NULL DEFAULT ''
        );
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_export_jobs_status_created ON export_jobs(status, created_at);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_export_jobs_uuid ON export_jobs(job_uuid);"
    )
    for ddl in (
        "ALTER TABLE export_jobs ADD COLUMN locked_at TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE export_jobs ADD COLUMN locked_by TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE export_jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE export_jobs ADD COLUMN next_run_at TEXT NOT NULL DEFAULT ''",
    ):
        try:
            conn.execute(ddl)
        except Exception:
            _log.debug("init_export_jobs: suppressed error", exc_info=True)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_export_jobs_claim ON export_jobs(status, next_run_at, locked_at, created_at);"
    )
    conn.commit()


def _dump(value: dict[str, Any]) -> str:
    return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))


def _load(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def try_start_export_job(conn, job_id: int) -> bool:
    """Атомарно pending → running. False, если задачу уже взял другой воркер."""
    init_export_jobs(conn)
    cur = conn.execute(
        """
        UPDATE export_jobs
        SET status='running',
            started_at=COALESCE(NULLIF(started_at, ''), CURRENT_TIMESTAMP)
        WHERE id=? AND status='pending'
        """,
        (int(job_id),),
    )
    conn.commit()
    return int(cur.rowcount or 0) == 1


def create_export_job(
    conn,
    *,
    job_type: str,
    position_name: str,
    params: dict[str, Any],
    created_by: str,
) -> int:
    init_export_jobs(conn)
    cur = conn.execute(
        """
        INSERT INTO export_jobs (job_uuid, job_type, status, position_name, params_json, created_by)
        VALUES (?, ?, 'pending', ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            str(job_type or "").strip(),
            str(position_name or "").strip(),
            _dump(params),
            str(created_by or ""),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_export_job(
    conn,
    job_id: int,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error_text: str = "",
) -> None:
    init_export_jobs(conn)
    status_v = str(status or "").strip() or "pending"
    if status_v == "running":
        conn.execute(
            """
            UPDATE export_jobs
            SET status=?, started_at=COALESCE(NULLIF(started_at,''), CURRENT_TIMESTAMP)
            WHERE id=?
            """,
            (status_v, int(job_id)),
        )
    elif status_v in {"completed", "failed", "cancelled"}:
        conn.execute(
            """
            UPDATE export_jobs
            SET status=?, result_json=?, error_text=?, finished_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (status_v, _dump(result or {}), str(error_text or "")[:4000], int(job_id)),
        )
    else:
        conn.execute("UPDATE export_jobs SET status=? WHERE id=?", (status_v, int(job_id)))
    conn.commit()


def claim_next_export_job(
    conn, *, worker_id: str, stale_after_sec: int | None = None
) -> dict[str, Any] | None:
    if stale_after_sec is None:
        stale_after_sec = export_job_stale_after_sec()
    init_export_jobs(conn)
    row = conn.execute(
        """
        SELECT id
        FROM export_jobs
        WHERE status IN ('pending', 'running')
          AND attempts < ?
          AND (next_run_at='' OR next_run_at <= CURRENT_TIMESTAMP)
          AND (
            status='pending'
            OR locked_at=''
            OR datetime(locked_at) <= datetime('now', ?)
          )
        ORDER BY created_at ASC, id ASC
        LIMIT 1
        """,
        (EXPORT_JOB_MAX_ATTEMPTS, f"-{int(stale_after_sec)} seconds"),
    ).fetchone()
    if not row:
        return None
    job_id = int(row["id"])
    cur = conn.execute(
        """
        UPDATE export_jobs
        SET status='running',
            locked_at=CURRENT_TIMESTAMP,
            locked_by=?,
            attempts=attempts + 1,
            started_at=COALESCE(NULLIF(started_at,''), CURRENT_TIMESTAMP)
        WHERE id=?
          AND status IN ('pending', 'running')
          AND attempts < ?
          AND (locked_at='' OR locked_by='' OR datetime(locked_at) <= datetime('now', ?))
        """,
        (str(worker_id or ""), job_id, EXPORT_JOB_MAX_ATTEMPTS, f"-{int(stale_after_sec)} seconds"),
    )
    conn.commit()
    if int(cur.rowcount or 0) != 1:
        return None
    return get_export_job(conn, job_id)


def complete_claimed_export_job(conn, job_id: int, *, result: dict[str, Any]) -> None:
    init_export_jobs(conn)
    conn.execute(
        """
        UPDATE export_jobs
        SET status='completed',
            result_json=?,
            error_text='',
            finished_at=CURRENT_TIMESTAMP,
            locked_at='',
            locked_by=''
        WHERE id=?
        """,
        (_dump(result or {}), int(job_id)),
    )
    conn.commit()


def fail_claimed_export_job(conn, job_id: int, *, error_text: str, retry: bool = True) -> None:
    init_export_jobs(conn)
    row = conn.execute("SELECT attempts FROM export_jobs WHERE id=?", (int(job_id),)).fetchone()
    attempts = int(row["attempts"] or 0) if row else EXPORT_JOB_MAX_ATTEMPTS
    should_retry = bool(retry and attempts < EXPORT_JOB_MAX_ATTEMPTS)
    if should_retry:
        backoff_sec = min(900, 30 * (2 ** max(0, attempts - 1)))
        conn.execute(
            """
            UPDATE export_jobs
            SET status='pending',
                error_text=?,
                locked_at='',
                locked_by='',
                next_run_at=datetime('now', ?)
            WHERE id=?
            """,
            (str(error_text or "")[:4000], f"+{backoff_sec} seconds", int(job_id)),
        )
    else:
        conn.execute(
            """
            UPDATE export_jobs
            SET status='failed',
                error_text=?,
                finished_at=CURRENT_TIMESTAMP,
                locked_at='',
                locked_by=''
            WHERE id=?
            """,
            (str(error_text or "")[:4000], int(job_id)),
        )
    conn.commit()


def get_export_job(conn, job_id: int) -> dict[str, Any] | None:
    init_export_jobs(conn)
    row = conn.execute(
        """
        SELECT id, job_uuid, job_type, status, position_name, params_json, result_json,
               error_text, created_by, created_at, started_at, finished_at,
               locked_at, locked_by, attempts, next_run_at
        FROM export_jobs
        WHERE id=?
        """,
        (int(job_id),),
    ).fetchone()
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "uuid": str(row["job_uuid"] or ""),
        "job_type": str(row["job_type"] or ""),
        "status": str(row["status"] or ""),
        "position_name": str(row["position_name"] or ""),
        "params": _load(str(row["params_json"] or "{}")),
        "result": _load(str(row["result_json"] or "{}")),
        "error_text": str(row["error_text"] or ""),
        "created_by": str(row["created_by"] or ""),
        "created_at": str(row["created_at"] or ""),
        "started_at": str(row["started_at"] or ""),
        "finished_at": str(row["finished_at"] or ""),
        "locked_at": str(row["locked_at"] or "") if "locked_at" in row.keys() else "",
        "locked_by": str(row["locked_by"] or "") if "locked_by" in row.keys() else "",
        "attempts": int(row["attempts"] or 0) if "attempts" in row.keys() else 0,
        "next_run_at": str(row["next_run_at"] or "") if "next_run_at" in row.keys() else "",
    }


def cleanup_export_results(base_dir: Path) -> None:
    root = export_results_dir(base_dir)
    cutoff = time.time() - EXPORT_JOB_TTL_SEC
    for path in root.glob("*"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except Exception:
            _log.debug("cleanup_export_results: suppressed error", exc_info=True)


def remove_export_result(path: str) -> None:
    try:
        os.unlink(path)
    except Exception:
        _log.debug("remove_export_result: suppressed error", exc_info=True)
