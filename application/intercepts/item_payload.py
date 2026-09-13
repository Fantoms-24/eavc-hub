"""
Сборка ответа GET /api/intercepts/item (логика ранее целиком в app.py).

Колбэк list_typing передаётся снаружи: в приложении там in-memory состояние TYPING.
"""

from __future__ import annotations

from collections.abc import Callable
import sqlite3
from typing import Any

from web_portal.lib.db import (
    get_analysis_assignments,
    get_intercept_session,
    get_or_create_intercept_item,
    get_intercept_item_sync_payload,
    enqueue_sync_outbox,
    is_intercept_session_closed,
)

from web_portal.application.intercepts.errors import InterceptsUseCaseHTTP


def assemble_intercepts_get_item_payload(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    session_id: int,
    catalog_id: int,
    frequency: str,
    group_code: str,
    permit_edit_when_open: bool,
    exclude_typing_user: str,
    hub_sync_enabled: bool,
    list_typing_labels: Callable[[str, int, int, str | None], list[str]],
) -> dict[str, Any]:
    if not session_id:
        raise InterceptsUseCaseHTTP(400, {"ok": False, "error": "session_id обязателен"})
    cid = catalog_id
    freq = frequency
    grp = group_code
    if not cid and (not freq or not grp):
        raise InterceptsUseCaseHTTP(
            400,
            {
                "ok": False,
                "error": "нужны session_id + (catalog_id или frequency+group_code)",
            },
        )

    closed = is_intercept_session_closed(conn, session_id)
    catalog_meta: dict[str, Any] | None = None
    cat_id_for_typing = cid

    if cid:
        cat = conn.execute(
            """
            SELECT id, position_name, unit_name, frequency, group_code, location, updated_at
            FROM intercept_catalog
            WHERE id=?
            """,
            (int(cid),),
        ).fetchone()
        if not cat:
            raise InterceptsUseCaseHTTP(400, {"ok": False, "error": "catalog not found"})
        if str(cat["position_name"] or "").strip() != str(position_name):
            raise InterceptsUseCaseHTTP(403, {"ok": False, "error": "Нет доступа к записи"})
        catalog_meta = {
            "id": int(cat["id"]),
            "unit_name": str(cat["unit_name"] or ""),
            "frequency": str(cat["frequency"] or ""),
            "group_code": str(cat["group_code"] or ""),
            "location": str(cat["location"] or ""),
            "updated_at": str(cat["updated_at"] or ""),
        }
        freq0 = str(cat["frequency"] or "")
        grp0 = str(cat["group_code"] or "")
        existing_item = conn.execute(
            "SELECT id FROM intercept_items WHERE session_id=? AND frequency=? AND group_code=?",
            (int(session_id), freq0, grp0),
        ).fetchone()
        item = get_or_create_intercept_item(
            conn,
            session_id=session_id,
            catalog_id=cid,
            create_if_missing=not closed,
        )
        if hub_sync_enabled and item.get("id") and not existing_item:
            try:
                payload = get_intercept_item_sync_payload(conn, int(item["id"]))
                enqueue_sync_outbox(conn, kind="intercepts:item", payload=payload)
            except Exception:
                pass
        cat_id_for_typing = int(cid)
    else:
        cat2 = conn.execute(
            """
            SELECT id, unit_name, frequency, group_code, location, updated_at
            FROM intercept_catalog
            WHERE position_name=? AND frequency=? AND group_code=?
            """,
            (str(position_name), freq, grp),
        ).fetchone()
        if cat2:
            cid = int(cat2["id"])
            cat_id_for_typing = cid
            catalog_meta = {
                "id": int(cat2["id"]),
                "unit_name": str(cat2["unit_name"] or ""),
                "frequency": str(cat2["frequency"] or ""),
                "group_code": str(cat2["group_code"] or ""),
                "location": str(cat2["location"] or ""),
                "updated_at": str(cat2["updated_at"] or ""),
            }
            existing_item = conn.execute(
                "SELECT id FROM intercept_items WHERE session_id=? AND frequency=? AND group_code=?",
                (int(session_id), freq, grp),
            ).fetchone()
            item = get_or_create_intercept_item(
                conn,
                session_id=session_id,
                catalog_id=cid,
                create_if_missing=not closed,
            )
            if hub_sync_enabled and item.get("id") and not existing_item:
                try:
                    payload = get_intercept_item_sync_payload(conn, int(item["id"]))
                    enqueue_sync_outbox(conn, kind="intercepts:item", payload=payload)
                except Exception:
                    pass
        else:
            r = conn.execute(
                """
                SELECT id, session_id, unit_name, frequency, group_code, content, updated_by, updated_at
                FROM intercept_items
                WHERE session_id=? AND frequency=? AND group_code=?
                """,
                (int(session_id), freq, grp),
            ).fetchone()
            if not r:
                r = conn.execute(
                    """
                    SELECT id, session_id, unit_name, frequency, group_code, content, updated_by, updated_at
                    FROM intercept_items_archive
                    WHERE session_id=? AND frequency=? AND group_code=?
                    """,
                    (int(session_id), freq, grp),
                ).fetchone()
            if not r:
                raise InterceptsUseCaseHTTP(404, {"ok": False, "error": "item not found"})
            item = {
                "id": int(r["id"]),
                "session_id": int(r["session_id"]),
                "unit_name": str(r["unit_name"] or ""),
                "frequency": str(r["frequency"] or ""),
                "group_code": str(r["group_code"] or ""),
                "content": str(r["content"] or ""),
                "updated_by": str(r["updated_by"] or ""),
                "updated_at": str(r["updated_at"] or ""),
            }
            catalog_meta = {
                "id": 0,
                "unit_name": str(item.get("unit_name") or ""),
                "frequency": str(item.get("frequency") or ""),
                "group_code": str(item.get("group_code") or ""),
                "location": "",
                "updated_at": "",
                "archived_only": True,
            }
            cat_id_for_typing = 0

    sess = get_intercept_session(conn, session_id)
    typing_list = list_typing_labels(
        position_name, session_id, int(cat_id_for_typing), exclude_typing_user or None
    )

    assignments: dict[str, str] = {}
    try:
        fq = str(item.get("frequency") or "").strip()
        gr = str(item.get("group_code") or "").strip()
        if fq and gr:
            assignments = get_analysis_assignments(
                conn, position_name=position_name, frequency=fq, group_code=gr
            )
    except Exception:
        assignments = {}

    can_edit = permit_edit_when_open and not closed

    return {
        "ok": True,
        "item": item,
        "catalog": catalog_meta,
        "session": sess,
        "closed": closed,
        "can_edit": can_edit,
        "typing": typing_list,
        "assignments": assignments,
    }
