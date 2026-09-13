"""AI job/report records — физический доменный модуль."""
from __future__ import annotations

import json
from typing import Any
import sqlite3


def _json_dump_compact(value: Any) -> str:
    try:
        return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return "{}"


def _json_load_object(value: Any) -> dict[str, Any]:
    try:
        data = json.loads(str(value or "{}"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def init_ai_tables(conn: sqlite3.Connection) -> None:
    """Таблицы локального AI-модуля: задачи, отчеты, feedback и версии промптов."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_uuid TEXT NOT NULL UNIQUE,
            task_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            position_name TEXT NOT NULL DEFAULT '',
            params_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            error_text TEXT NOT NULL DEFAULT '',
            model_name TEXT NOT NULL DEFAULT '',
            prompt_version TEXT NOT NULL DEFAULT '',
            created_by TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TEXT NOT NULL DEFAULT '',
            finished_at TEXT NOT NULL DEFAULT ''
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_uuid TEXT NOT NULL UNIQUE,
            job_id INTEGER,
            report_type TEXT NOT NULL,
            position_name TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            input_summary TEXT NOT NULL DEFAULT '',
            report_text TEXT NOT NULL DEFAULT '',
            result_json TEXT NOT NULL DEFAULT '{}',
            model_name TEXT NOT NULL DEFAULT '',
            prompt_version TEXT NOT NULL DEFAULT '',
            created_by TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(job_id) REFERENCES ai_jobs(id) ON DELETE SET NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            rating TEXT NOT NULL DEFAULT '',
            corrected_text TEXT NOT NULL DEFAULT '',
            comment TEXT NOT NULL DEFAULT '',
            created_by TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(report_id) REFERENCES ai_reports(id) ON DELETE CASCADE
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_prompt_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt_key TEXT NOT NULL,
            version TEXT NOT NULL,
            template_text TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(prompt_key, version)
        );
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_jobs_status_created ON ai_jobs(status, created_at);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_jobs_type_pos ON ai_jobs(task_type, position_name, created_at);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_reports_type_pos ON ai_reports(report_type, position_name, created_at);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_reports_type_pos_version ON ai_reports(report_type, position_name, prompt_version, created_at);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_feedback_report ON ai_feedback(report_id, created_at);"
    )
    conn.commit()


def create_ai_job(
    conn: sqlite3.Connection,
    *,
    task_type: str,
    position_name: str = "",
    params: dict[str, Any] | None = None,
    model_name: str = "",
    prompt_version: str = "",
    created_by: str = "",
) -> int:
    from web_portal.lib.db.connection import init_db
    import uuid as _uuid

    init_db(conn)
    cur = conn.execute(
        """
        INSERT INTO ai_jobs (
            job_uuid, task_type, status, position_name, params_json,
            model_name, prompt_version, created_by
        )
        VALUES (?, ?, 'pending', ?, ?, ?, ?, ?)
        """,
        (
            str(_uuid.uuid4()),
            str(task_type or "").strip(),
            str(position_name or "").strip(),
            _json_dump_compact(params or {}),
            str(model_name or ""),
            str(prompt_version or ""),
            str(created_by or ""),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_ai_job(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error_text: str = "",
) -> None:
    from web_portal.lib.db.connection import init_db
    init_db(conn)
    status_v = str(status or "").strip() or "pending"
    if status_v == "running":
        conn.execute(
            """
            UPDATE ai_jobs
            SET status=?, started_at=COALESCE(NULLIF(started_at,''), CURRENT_TIMESTAMP)
            WHERE id=?
            """,
            (status_v, int(job_id)),
        )
    elif status_v in {"completed", "failed", "cancelled"}:
        conn.execute(
            """
            UPDATE ai_jobs
            SET status=?, result_json=?, error_text=?, finished_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                status_v,
                _json_dump_compact(result or {}),
                str(error_text or "")[:4000],
                int(job_id),
            ),
        )
    else:
        conn.execute("UPDATE ai_jobs SET status=? WHERE id=?", (status_v, int(job_id)))
    conn.commit()


def get_ai_job(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    from web_portal.lib.db.connection import init_db
    init_db(conn)
    r = conn.execute(
        """
        SELECT id, job_uuid, task_type, status, position_name, params_json, result_json,
               error_text, model_name, prompt_version, created_by, created_at, started_at, finished_at
        FROM ai_jobs
        WHERE id=?
        """,
        (int(job_id),),
    ).fetchone()
    if not r:
        return None
    return {
        "id": int(r["id"]),
        "uuid": str(r["job_uuid"] or ""),
        "task_type": str(r["task_type"] or ""),
        "status": str(r["status"] or ""),
        "position_name": str(r["position_name"] or ""),
        "params": _json_load_object(r["params_json"]),
        "result": _json_load_object(r["result_json"]),
        "error_text": str(r["error_text"] or ""),
        "model_name": str(r["model_name"] or ""),
        "prompt_version": str(r["prompt_version"] or ""),
        "created_by": str(r["created_by"] or ""),
        "created_at": str(r["created_at"] or ""),
        "started_at": str(r["started_at"] or ""),
        "finished_at": str(r["finished_at"] or ""),
    }


def create_ai_report(
    conn: sqlite3.Connection,
    *,
    job_id: int | None,
    report_type: str,
    position_name: str = "",
    title: str = "",
    input_summary: str = "",
    report_text: str = "",
    result: dict[str, Any] | None = None,
    model_name: str = "",
    prompt_version: str = "",
    created_by: str = "",
) -> int:
    from web_portal.lib.db.connection import init_db
    import uuid as _uuid

    init_db(conn)
    cur = conn.execute(
        """
        INSERT INTO ai_reports (
            report_uuid, job_id, report_type, position_name, title, input_summary,
            report_text, result_json, model_name, prompt_version, created_by
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(_uuid.uuid4()),
            int(job_id) if job_id else None,
            str(report_type or "").strip(),
            str(position_name or "").strip(),
            str(title or "")[:500],
            str(input_summary or "")[:2000],
            str(report_text or ""),
            _json_dump_compact(result or {}),
            str(model_name or ""),
            str(prompt_version or ""),
            str(created_by or ""),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_ai_reports(
    conn: sqlite3.Connection,
    *,
    position_name: str = "",
    report_type: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    from web_portal.lib.db.connection import init_db
    init_db(conn)
    limit = max(1, min(int(limit or 50), 200))
    where = []
    params: list[Any] = []
    pos = str(position_name or "").strip()
    typ = str(report_type or "").strip()
    if pos and pos != "__all__":
        where.append("(position_name = ? OR TRIM(COALESCE(position_name,'')) = '')")
        params.append(pos)
    if typ:
        where.append("report_type = ?")
        params.append(typ)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        f"""
        SELECT id, report_uuid, job_id, report_type, position_name, title,
               input_summary, report_text, result_json, model_name, prompt_version,
               created_by, created_at
        FROM ai_reports
        {where_sql}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "uuid": str(r["report_uuid"] or ""),
            "job_id": int(r["job_id"]) if r["job_id"] is not None else None,
            "report_type": str(r["report_type"] or ""),
            "position_name": str(r["position_name"] or ""),
            "title": str(r["title"] or ""),
            "input_summary": str(r["input_summary"] or ""),
            "report_text": str(r["report_text"] or ""),
            "result": _json_load_object(r["result_json"]),
            "model_name": str(r["model_name"] or ""),
            "prompt_version": str(r["prompt_version"] or ""),
            "created_by": str(r["created_by"] or ""),
            "created_at": str(r["created_at"] or ""),
        }
        for r in rows
    ]


def add_ai_feedback(
    conn: sqlite3.Connection,
    *,
    report_id: int,
    rating: str = "",
    corrected_text: str = "",
    comment: str = "",
    created_by: str = "",
) -> int:
    init_db(conn)
    cur = conn.execute(
        """
        INSERT INTO ai_feedback (report_id, rating, corrected_text, comment, created_by)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            int(report_id),
            str(rating or "").strip()[:50],
            str(corrected_text or ""),
            str(comment or "")[:2000],
            str(created_by or ""),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)

__all__ = [
    "add_ai_feedback",
    "init_ai_tables",
    "create_ai_job",
    "update_ai_job",
    "get_ai_job",
    "create_ai_report",
    "list_ai_reports",
]
