"""AI-отчёты анализа: список, feedback, stale job (без Flask)."""

from __future__ import annotations

import datetime as _dt
from typing import Any, Mapping

import sqlite3

from web_portal.application.analysis.errors import AnalysisUseCaseHTTP
from web_portal.lib.ai_client import current_ai_config
from web_portal.lib.db import (
    add_ai_feedback,
    get_ai_job,
    list_ai_reports,
    update_ai_job,
)


def parse_optional_session_id(raw: Any) -> int | None:
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except Exception as e:
        raise AnalysisUseCaseHTTP(
            400,
            {"ok": False, "error": "Некорректный session_id"},
        ) from e


def parse_period_report_range(raw: Mapping[str, Any]) -> tuple[str, str]:
    start = str(raw.get("start") or "").strip()
    end = str(raw.get("end") or "").strip()
    if not start or not end:
        raise AnalysisUseCaseHTTP(
            400,
            {"ok": False, "error": "Укажите начало и конец периода"},
        )
    return start, end


def assemble_ai_reports_list_payload(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    report_type: str = "",
    limit: int = 30,
) -> dict[str, Any]:
    reports = list_ai_reports(
        conn,
        position_name=str(position_name or ""),
        report_type=str(report_type or "").strip(),
        limit=limit,
    )
    cfg = current_ai_config()
    return {
        "ok": True,
        "reports": reports,
        "ai": {
            "provider": cfg.provider,
            "model": cfg.model,
        },
    }


def refresh_stale_ai_job(
    conn: sqlite3.Connection,
    job: dict[str, Any],
    *,
    job_id: int,
    timeout_sec: int = 7200,
) -> dict[str, Any]:
    """Если pending/running дольше timeout — помечает failed и перечитывает job."""
    status = str(job.get("status") or "").lower()
    started_raw = str(job.get("started_at") or job.get("created_at") or "").strip()
    if status not in {"pending", "running"} or not started_raw:
        return job
    try:
        started = _dt.datetime.fromisoformat(started_raw.replace(" ", "T"))
        if (_dt.datetime.now() - started).total_seconds() > timeout_sec:
            update_ai_job(
                conn,
                job_id,
                status="failed",
                error_text="AI-задача не завершилась за допустимое время. Запустите ее повторно.",
            )
            return get_ai_job(conn, job_id) or job
    except Exception:
        pass
    return job


def execute_ai_feedback(
    conn: sqlite3.Connection,
    *,
    report_id: Any,
    rating: str,
    corrected_text: str,
    comment: str,
    created_by: str,
    can_view_report: bool,
) -> dict[str, Any]:
    try:
        rid = int(report_id)
    except Exception as e:
        raise AnalysisUseCaseHTTP(
            400,
            {"ok": False, "error": "Некорректный report_id"},
        ) from e
    if not can_view_report:
        raise AnalysisUseCaseHTTP(
            403,
            {"ok": False, "error": "Нет доступа к AI-отчету"},
        )
    fid = add_ai_feedback(
        conn,
        report_id=rid,
        rating=str(rating or ""),
        corrected_text=str(corrected_text or ""),
        comment=str(comment or ""),
        created_by=created_by,
    )
    return {"ok": True, "feedback_id": fid}
