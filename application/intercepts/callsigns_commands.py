"""Позывные перехватов: создание / правка / удаление / last-seen."""

from __future__ import annotations

from collections.abc import Callable
import re
import sqlite3
from typing import Any

from web_portal.lib.db import (
    delete_intercept_callsign,
    enqueue_sync_outbox,
    update_intercept_callsign_label,
    upsert_intercept_callsign,
)

from web_portal.application.intercepts.errors import InterceptsUseCaseHTTP


def execute_intercepts_callsign_upsert(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    label: str,
    code: str,
    unit_name: str,
    frequency: str,
    group_code: str,
    hub_sync_enabled: bool,
    invalidate_caches: Callable[[], None],
) -> dict[str, Any]:
    norm_code = "".join(re.findall(r"\d+", code or ""))
    if not norm_code:
        raise InterceptsUseCaseHTTP(400, {"ok": False, "error": "ID должен содержать цифры"})
    # Один и тот же ID (код) в паре частота/группа — обновляем название.
    # Разные ID с одинаковым названием (например «Сова» на 1343 и 2324) — разрешены.
    cid = upsert_intercept_callsign(
        conn,
        position_name=position_name,
        label=label,
        code=code,
        unit_name=unit_name,
        frequency=frequency,
        group_code=group_code,
    )
    invalidate_caches()

    if hub_sync_enabled:
        try:
            row = conn.execute(
                """
                SELECT uuid, position_name, label, code, unit_name, frequency, group_code, updated_at
                FROM intercept_callsigns
                WHERE id=?
                """,
                (int(cid),),
            ).fetchone()
            if row:
                enqueue_sync_outbox(
                    conn,
                    kind="intercepts:callsign",
                    payload={
                        "uuid": str(row["uuid"] or ""),
                        "position_name": str(row["position_name"] or ""),
                        "label": str(row["label"] or ""),
                        "code": str(row["code"] or ""),
                        "unit_name": str(row["unit_name"] or ""),
                        "frequency": str(row["frequency"] or ""),
                        "group_code": str(row["group_code"] or ""),
                        "updated_at": str(row["updated_at"] or ""),
                    },
                )
        except Exception:
            pass
    return {"ok": True, "id": cid}


def execute_intercepts_callsign_update_label(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    callsign_id: int,
    label: str,
    invalidate_caches: Callable[[], None],
) -> dict[str, Any]:
    if not callsign_id or not str(label or "").strip():
        raise InterceptsUseCaseHTTP(400, {"ok": False, "error": "id и label обязательны"})
    update_intercept_callsign_label(conn, position_name=position_name, callsign_id=callsign_id, label=label)
    invalidate_caches()
    return {"ok": True}


def execute_intercepts_callsign_delete(
    conn: sqlite3.Connection,
    *,
    callsign_id: int,
    invalidate_caches: Callable[[], None],
) -> dict[str, Any]:
    if not callsign_id:
        raise InterceptsUseCaseHTTP(400, {"ok": False, "error": "id обязателен"})
    delete_intercept_callsign(conn, callsign_id)
    invalidate_caches()
    return {"ok": True}


def execute_intercepts_callsigns_last_seen(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    frequency: str,
    group_code: str,
    raw_codes: list[Any],
) -> dict[str, Any]:
    fq = frequency.strip()
    gc = group_code.strip()
    if not fq or not gc:
        raise InterceptsUseCaseHTTP(
            400, {"ok": False, "error": "frequency/group_code обязательны"}
        )
    if not isinstance(raw_codes, list):
        raise InterceptsUseCaseHTTP(400, {"ok": False, "error": "codes должен быть списком"})

    norm_codes: list[str] = []
    seen_codes: set[str] = set()
    for x in raw_codes[:300]:
        c = "".join(re.findall(r"\d+", str(x or "")))
        if not c or c in seen_codes:
            continue
        seen_codes.add(c)
        norm_codes.append(c)

    result: dict[str, str] = {}
    sql = """
        SELECT MAX(updated_at) AS last_seen
        FROM (
            SELECT i.updated_at
            FROM intercept_items i
            JOIN intercept_sessions s ON s.id = i.session_id
            WHERE s.position_name = ?
              AND i.frequency = ?
              AND i.group_code = ?
              AND i.content LIKE ?
            UNION ALL
            SELECT ia.updated_at
            FROM intercept_items_archive ia
            JOIN intercept_sessions_archive sa ON sa.id = ia.session_id
            WHERE sa.position_name = ?
              AND ia.frequency = ?
              AND ia.group_code = ?
              AND ia.content LIKE ?
        ) q
    """
    for code in norm_codes:
        pat = f"%({code})%"
        row = conn.execute(
            sql,
            (
                position_name,
                fq,
                gc,
                pat,
                position_name,
                fq,
                gc,
                pat,
            ),
        ).fetchone()
        result[code] = str((row["last_seen"] if row else "") or "")

    return {
        "ok": True,
        "position": position_name,
        "frequency": fq,
        "group_code": gc,
        "last_seen": result,
    }
