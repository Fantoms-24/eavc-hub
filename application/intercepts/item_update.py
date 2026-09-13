"""Команда обновления бланка POST /api/intercepts/item/update."""

from __future__ import annotations

from collections.abc import Callable
import sqlite3
from typing import Any

from web_portal.lib.db import (
    enqueue_sync_outbox,
    get_intercept_item_sync_payload,
    replace_intercept_item_content,
    update_intercept_item_content,
)

from web_portal.application.intercepts.errors import InterceptsUseCaseHTTP


def execute_intercepts_item_update(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    content: str,
    merge: bool,
    updated_by: str,
    hub_sync_enabled: bool,
    forward_payload: Callable[[sqlite3.Connection, dict], None] | None,
) -> dict[str, Any]:
    if not item_id:
        raise InterceptsUseCaseHTTP(400, {"ok": False, "error": "item_id обязателен"})

    r = conn.execute(
        """
        SELECT s.ended_at
        FROM intercept_items i
        JOIN intercept_sessions s ON s.id=i.session_id
        WHERE i.id=?
        """,
        (item_id,),
    ).fetchone()
    if r and r["ended_at"]:
        raise InterceptsUseCaseHTTP(
            400, {"ok": False, "error": "Смена закрыта (только просмотр)"}
        )

    if merge:
        item = update_intercept_item_content(conn, item_id, content, updated_by)
    else:
        item = replace_intercept_item_content(conn, item_id, content, updated_by)

    sync_payload: dict[str, Any] | None = None
    if hub_sync_enabled or forward_payload is not None:
        try:
            sync_payload = get_intercept_item_sync_payload(conn, int(item_id))
        except Exception:
            sync_payload = None

    if hub_sync_enabled and sync_payload:
        try:
            enqueue_sync_outbox(conn, kind="intercepts:item", payload=sync_payload)
        except Exception:
            pass

    if forward_payload is not None and sync_payload:
        try:
            forward_payload(conn, sync_payload)
        except Exception:
            pass

    return {"ok": True, "item": item, "sync_payload": sync_payload}
