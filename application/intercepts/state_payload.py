"""
Сборка тела ответа GET /api/intercepts/state — вынесена из app.py как первый шаг к Clean-ish слою.

Фреймворк (Flask), кеш и проверки позиции остаются в маршруте; здесь только оркестрация данных SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Any

from web_portal.lib.db import (
    get_analysis_assignments,
    get_intercept_session,
    get_or_create_active_intercept_session,
    list_intercept_callsigns,
    list_intercept_catalog,
    list_intercept_sessions,
)


@dataclass(frozen=True)
class InterceptsGate:
    """Права на позицию (уже проверены: есть view); edit учитывает закрытие смены внутри use case."""

    permit_edit: bool
    permit_export: bool
    permit_start: bool


def assemble_intercepts_state_payload(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    username: str,
    role: str,
    requested_sid: int,
    explicit_pick: bool,
    req_freq: str,
    req_group: str,
    view_mode: str,
    unit_order: list[str],
    catalog_prefs: dict[str, Any] | None,
    gate: InterceptsGate,
) -> dict[str, Any]:
    catalog = list_intercept_catalog(conn, position_name)
    sessions = list_intercept_sessions(conn, position_name, limit=50)
    active = get_or_create_active_intercept_session(conn, position_name, username)
    callsigns = list_intercept_callsigns(conn, position_name)

    if requested_sid:
        selected = get_intercept_session(conn, requested_sid)
        if not selected or selected.get("position_name") != position_name:
            selected = active
        # Явный session_id (в т.ч. из опроса state) — не подменять закрытую смену на активную:
        # иначе в списке выбрана одна смена (10–14), а экспорт/данные — с другой.
    else:
        selected = active

    selected_closed = bool(selected.get("ended_at")) if selected else False

    items_max_updated_at = ""
    try:
        sid0 = int(selected.get("id") or 0) if selected else 0
        if sid0:
            row = conn.execute(
                "SELECT MAX(updated_at) AS mx FROM intercept_items WHERE session_id=?",
                (sid0,),
            ).fetchone()
            if row:
                items_max_updated_at = str(row["mx"] or "")
    except Exception:
        items_max_updated_at = ""

    assignments: dict[str, str] = {}
    try:
        fq = req_freq
        gr = req_group
        if fq and gr:
            assignments = get_analysis_assignments(
                conn, position_name=position_name, frequency=fq, group_code=gr
            )
    except Exception:
        assignments = {}

    try:
        sid0 = int(selected.get("id") or 0) if selected else 0
        if sid0:
            rows = conn.execute(
                """
                SELECT unit_name, frequency, group_code, MAX(updated_at) AS updated_at
                FROM (
                    SELECT unit_name, frequency, group_code, updated_at
                    FROM intercept_items
                    WHERE session_id=?
                    UNION ALL
                    SELECT unit_name, frequency, group_code, updated_at
                    FROM intercept_items_archive
                    WHERE session_id=?
                ) i
                GROUP BY unit_name, frequency, group_code
                """,
                (sid0, sid0),
            ).fetchall()
            cat_by_pair = {
                (str(c.get("frequency") or ""), str(c.get("group_code") or "")): c
                for c in (catalog or [])
            }
            extra = []
            for r in rows or []:
                freq = str(r["frequency"] or "")
                grp = str(r["group_code"] or "")
                key = (freq, grp)
                if key in cat_by_pair:
                    continue
                extra.append(
                    {
                        "id": 0,
                        "unit_name": str(r["unit_name"] or ""),
                        "frequency": freq,
                        "group_code": grp,
                        "location": "",
                        "updated_at": str(r["updated_at"] or ""),
                        "archived_only": True,
                    }
                )
            if extra:
                catalog = list(catalog or []) + extra

                def _freq_key(x: dict[str, Any]) -> float:
                    try:
                        return float(str(x.get("frequency") or "").replace(",", "."))
                    except Exception:
                        return 0.0

                catalog.sort(
                    key=lambda x: (
                        str(x.get("unit_name") or ""),
                        -_freq_key(x),
                        str(x.get("group_code") or ""),
                        int(x.get("id") or 0),
                    )
                )
    except Exception:
        pass

    can_edit = gate.permit_edit and not selected_closed
    can_export = gate.permit_export
    can_start = gate.permit_start

    return {
        "ok": True,
        "position": position_name,
        "role": role,
        "can_edit": can_edit,
        "can_export": can_export,
        "can_start": can_start,
        "catalog": catalog,
        "sessions": sessions,
        "current_session": active,
        "active_session": active,
        "selected_session": selected,
        "selected_closed": selected_closed,
        "items_max_updated_at": items_max_updated_at,
        "callsigns": callsigns,
        "assignments": assignments,
        "view_mode": view_mode,
        "unit_order": unit_order,
        "catalog_prefs": catalog_prefs
        if isinstance(catalog_prefs, dict)
        else {"favorites": [], "archived": []},
    }
