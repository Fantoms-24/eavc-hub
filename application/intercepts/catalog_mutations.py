"""Удаление / переименование подразделения в каталоге перехватов; новая смена."""

from __future__ import annotations

from collections.abc import Callable
import sqlite3
from typing import Any

from web_portal.lib.db import (
    close_active_and_start_new_intercept_session,
    delete_intercept_catalog,
    enqueue_sync_outbox,
    get_intercept_item_sync_payload,
    record_intercept_catalog_delete,
)

from web_portal.application.intercepts.errors import InterceptsUseCaseHTTP


def execute_intercepts_catalog_delete(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    catalog_id: int,
    hub_sync_enabled: bool,
    schedule_hub_push_in_background: Callable[[], None] | None,
) -> dict[str, Any]:
    if not catalog_id:
        raise InterceptsUseCaseHTTP(400, {"ok": False, "error": "id обязателен"})
    row = None
    try:
        row = conn.execute(
            """
            SELECT uuid, position_name, unit_name, frequency, group_code
            FROM intercept_catalog
            WHERE id=?
            """,
            (int(catalog_id),),
        ).fetchone()
    except Exception:
        row = None
    if not row:
        raise InterceptsUseCaseHTTP(404, {"ok": False, "error": "not found"})
    if str(row["position_name"] or "").strip() != str(position_name):
        raise InterceptsUseCaseHTTP(403, {"ok": False, "error": "Нет доступа к записи"})
    try:
        record_intercept_catalog_delete(
            conn,
            position_name=str(row["position_name"] or ""),
            frequency=str(row["frequency"] or ""),
            group_code=str(row["group_code"] or ""),
            uuid=str(row["uuid"] or ""),
        )
    except Exception:
        pass
    deleted = delete_intercept_catalog(conn, catalog_id)
    if not deleted:
        raise InterceptsUseCaseHTTP(
            404, {"ok": False, "error": "Запись не найдена или уже удалена"}
        )
    if hub_sync_enabled:
        try:
            payload = {
                "uuid": str(row["uuid"] or "").strip(),
                "position_name": str(row["position_name"] or "").strip(),
                "unit_name": str(row["unit_name"] or ""),
                "frequency": str(row["frequency"] or ""),
                "group_code": str(row["group_code"] or ""),
            }
            enqueue_sync_outbox(conn, kind="intercepts:catalog_delete", payload=payload)
            if schedule_hub_push_in_background is not None:
                try:
                    schedule_hub_push_in_background()
                except Exception:
                    pass
        except Exception:
            pass
    return {"ok": True}


def execute_intercepts_catalog_rename_unit(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    old_name: str,
    new_name: str,
    hub_sync_enabled: bool,
) -> dict[str, Any]:
    if not old_name or not new_name:
        raise InterceptsUseCaseHTTP(
            400, {"ok": False, "error": "old_name и new_name обязательны"}
        )
    rows = conn.execute(
        """
        SELECT id FROM intercept_catalog
        WHERE position_name=? AND lower(unit_name)=lower(?)
        ORDER BY id ASC
        """,
        (str(position_name), old_name),
    ).fetchall()
    ids = [int(r["id"]) for r in rows]
    if not ids:
        return {"ok": True, "updated": 0}
    cs_rows = conn.execute(
        """
        SELECT id FROM intercept_callsigns
        WHERE position_name=? AND lower(unit_name)=lower(?)
        ORDER BY id ASC
        """,
        (str(position_name), old_name),
    ).fetchall()
    cs_ids = [int(r["id"]) for r in cs_rows]

    item_rows = conn.execute(
        """
        SELECT i.id
        FROM intercept_items i
        JOIN intercept_sessions s ON s.id=i.session_id
        WHERE s.position_name=? AND lower(i.unit_name)=lower(?)
        ORDER BY i.id ASC
        """,
        (str(position_name), old_name),
    ).fetchall()
    item_ids = [int(r["id"]) for r in item_rows]
    conn.execute(
        """
        UPDATE intercept_catalog
        SET unit_name=?, updated_at=CURRENT_TIMESTAMP
        WHERE position_name=? AND lower(unit_name)=lower(?)
        """,
        (new_name, str(position_name), old_name),
    )
    if cs_ids:
        conn.execute(
            """
            UPDATE intercept_callsigns
            SET unit_name=?, updated_at=CURRENT_TIMESTAMP
            WHERE position_name=? AND lower(unit_name)=lower(?)
            """,
            (new_name, str(position_name), old_name),
        )
    if item_ids:
        conn.execute(
            """
            UPDATE intercept_items
            SET unit_name=?, updated_at=CURRENT_TIMESTAMP
            WHERE lower(unit_name)=lower(?)
              AND session_id IN (
                SELECT id FROM intercept_sessions WHERE position_name=?
              )
            """,
            (new_name, old_name, str(position_name)),
        )
    conn.commit()

    if hub_sync_enabled:
        try:
            for cid in ids:
                crow = conn.execute(
                    """
                    SELECT uuid, position_name, unit_name, frequency, group_code, updated_at
                    FROM intercept_catalog
                    WHERE id=?
                    """,
                    (int(cid),),
                ).fetchone()
                if not crow:
                    continue
                enqueue_sync_outbox(
                    conn,
                    kind="intercepts:catalog",
                    payload={
                        "uuid": str(crow["uuid"] or ""),
                        "position_name": str(crow["position_name"] or ""),
                        "unit_name": str(crow["unit_name"] or ""),
                        "frequency": str(crow["frequency"] or ""),
                        "group_code": str(crow["group_code"] or ""),
                        "updated_at": str(crow["updated_at"] or ""),
                    },
                )
            for csid in cs_ids:
                row_cs = conn.execute(
                    """
                    SELECT uuid, position_name, label, code, unit_name, frequency, group_code, updated_at
                    FROM intercept_callsigns
                    WHERE id=?
                    """,
                    (int(csid),),
                ).fetchone()
                if not row_cs:
                    continue
                enqueue_sync_outbox(
                    conn,
                    kind="intercepts:callsign",
                    payload={
                        "uuid": str(row_cs["uuid"] or ""),
                        "position_name": str(row_cs["position_name"] or ""),
                        "label": str(row_cs["label"] or ""),
                        "code": str(row_cs["code"] or ""),
                        "unit_name": str(row_cs["unit_name"] or ""),
                        "frequency": str(row_cs["frequency"] or ""),
                        "group_code": str(row_cs["group_code"] or ""),
                        "updated_at": str(row_cs["updated_at"] or ""),
                    },
                )
            for iid in item_ids:
                payload = get_intercept_item_sync_payload(conn, int(iid))
                enqueue_sync_outbox(conn, kind="intercepts:item", payload=payload)
        except Exception:
            pass
    return {
        "ok": True,
        "updated": len(ids),
        "updated_catalog": len(ids),
        "updated_callsigns": len(cs_ids),
        "updated_items": len(item_ids),
    }


def execute_intercepts_catalog_delete_unit(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    unit_name: str,
    hub_sync_enabled: bool,
    schedule_hub_push_in_background: Callable[[], None] | None,
) -> dict[str, Any]:
    if not unit_name:
        raise InterceptsUseCaseHTTP(400, {"ok": False, "error": "unit_name обязателен"})
    rows = conn.execute(
        """
        SELECT id, uuid, position_name, unit_name, frequency, group_code
        FROM intercept_catalog
        WHERE position_name=? AND lower(unit_name)=lower(?)
        ORDER BY id ASC
        """,
        (str(position_name), unit_name),
    ).fetchall()
    ids = [int(r["id"]) for r in rows]
    if not ids:
        return {"ok": True, "deleted": 0}

    deleted_catalog = 0
    for r in rows:
        try:
            record_intercept_catalog_delete(
                conn,
                position_name=str(r["position_name"] or ""),
                frequency=str(r["frequency"] or ""),
                group_code=str(r["group_code"] or ""),
                uuid=str(r["uuid"] or ""),
            )
        except Exception:
            pass
        try:
            if delete_intercept_catalog(conn, int(r["id"])):
                deleted_catalog += 1
        except Exception:
            pass

    cs_res = conn.execute(
        """
        DELETE FROM intercept_callsigns
        WHERE position_name=? AND lower(unit_name)=lower(?)
        """,
        (str(position_name), unit_name),
    )
    deleted_callsigns = int(cs_res.rowcount or 0)

    # Блоки бланка удаляем до самих записей: иначе останутся сироты без родителя.
    conn.execute(
        """
        DELETE FROM intercept_blocks
        WHERE item_id IN (
            SELECT id FROM intercept_items
            WHERE lower(unit_name)=lower(?)
              AND session_id IN (
                SELECT id FROM intercept_sessions WHERE position_name=?
              )
        )
        """,
        (unit_name, str(position_name)),
    )

    items_res = conn.execute(
        """
        DELETE FROM intercept_items
        WHERE lower(unit_name)=lower(?)
          AND session_id IN (
            SELECT id FROM intercept_sessions WHERE position_name=?
          )
        """,
        (unit_name, str(position_name)),
    )
    deleted_items = int(items_res.rowcount or 0)
    conn.commit()

    if hub_sync_enabled:
        try:
            for r in rows:
                payload = {
                    "uuid": str(r["uuid"] or "").strip(),
                    "position_name": str(r["position_name"] or "").strip(),
                    "unit_name": str(r["unit_name"] or ""),
                    "frequency": str(r["frequency"] or ""),
                    "group_code": str(r["group_code"] or ""),
                }
                enqueue_sync_outbox(conn, kind="intercepts:catalog_delete", payload=payload)
            if schedule_hub_push_in_background is not None:
                try:
                    schedule_hub_push_in_background()
                except Exception:
                    pass
        except Exception:
            pass

    return {
        "ok": True,
        "deleted": deleted_catalog,
        "deleted_callsigns": deleted_callsigns,
        "deleted_items": deleted_items,
    }


def execute_intercepts_session_start_new(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    username: str,
    hub_sync_enabled: bool,
) -> dict[str, Any]:
    s = close_active_and_start_new_intercept_session(conn, position_name, username)
    if hub_sync_enabled and s.get("id"):
        try:
            row = conn.execute(
                """
                SELECT uuid, position_name, started_at, ended_at, created_by
                FROM intercept_sessions
                WHERE id=?
                """,
                (int(s["id"]),),
            ).fetchone()
            if row:
                enqueue_sync_outbox(
                    conn,
                    kind="intercepts:session",
                    payload={
                        "uuid": str(row["uuid"] or ""),
                        "position_name": str(row["position_name"] or ""),
                        "started_at": str(row["started_at"] or ""),
                        "ended_at": str(row["ended_at"] or ""),
                        "created_by": str(row["created_by"] or ""),
                    },
                )
        except Exception:
            pass
    return {"ok": True, "current_session": s}
