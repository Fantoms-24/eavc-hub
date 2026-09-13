"""Назначения ролей (duty/battalion/company) для пары частота/группа."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from web_portal.lib.db import (
    enqueue_sync_outbox,
    get_analysis_assignments,
    set_analysis_assignment,
)

from web_portal.application.analysis.errors import AnalysisUseCaseHTTP

_log = logging.getLogger("web_portal.analysis.assignments")


def load_analysis_assignments_for_pair(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    frequency: str,
    group_code: str,
) -> dict[str, object]:
    frequency = str(frequency or "").strip()
    group_code = str(group_code or "").strip()
    if not frequency or not group_code:
        raise AnalysisUseCaseHTTP(
            400, {"ok": False, "error": "frequency и group обязательны"}
        )
    return get_analysis_assignments(
        conn,
        position_name=position_name,
        frequency=frequency,
        group_code=group_code,
    )


def _enqueue_analysis_assignment_sync(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    frequency: str,
    group_code: str,
    role_type: str,
    code: str,
    now_ts: str,
) -> None:
    try:
        row = conn.execute(
            """
            SELECT position_name, frequency, group_code, role_type, callsign_code, updated_at
            FROM analysis_assignments
            WHERE position_name=? AND frequency=? AND group_code=? AND role_type=?
            """,
            (position_name, frequency, group_code, role_type),
        ).fetchone()
        payload = {
            "position_name": str(position_name),
            "frequency": str(frequency),
            "group_code": str(group_code),
            "role_type": str(role_type),
            "callsign_code": str(code or ""),
            "updated_at": (str(row["updated_at"] or "") if row else now_ts),
        }
        enqueue_sync_outbox(conn, kind="analysis:assignment", payload=payload)
    except Exception:
        _log.debug("_enqueue_analysis_assignment_sync: suppressed error", exc_info=True)


def execute_analysis_assign(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    frequency: str,
    group_code: str,
    role_type: str,
    code: str,
    mode: str,
    sync_hub: bool,
    now_ts: str,
) -> dict[str, Any]:
    frequency = str(frequency or "").strip()
    group_code = str(group_code or "").strip()
    role_type = str(role_type or "").strip()
    code = str(code or "").strip()
    mode = str(mode or "").strip()
    if not frequency or not group_code or not role_type:
        raise AnalysisUseCaseHTTP(
            400,
            {"ok": False, "error": "frequency/group/role_type обязательны"},
        )
    try:
        set_analysis_assignment(
            conn,
            position_name=position_name,
            frequency=frequency,
            group_code=group_code,
            role_type=role_type,
            callsign_code=code,
            mode=mode,
        )
    except Exception as e:
        raise AnalysisUseCaseHTTP(400, {"ok": False, "error": str(e)}) from e
    if sync_hub:
        _enqueue_analysis_assignment_sync(
            conn,
            position_name=position_name,
            frequency=frequency,
            group_code=group_code,
            role_type=role_type,
            code=code,
            now_ts=now_ts,
        )
    return {"ok": True}
