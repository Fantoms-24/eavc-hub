"""Команды каталога перехватов: upsert / update-location + общий outbox для Hub."""

from __future__ import annotations

import sqlite3
from typing import Any

from web_portal.lib.db import enqueue_sync_outbox, upsert_intercept_catalog

from web_portal.application.intercepts.errors import InterceptsUseCaseHTTP


def maybe_enqueue_intercept_catalog_sync(conn: sqlite3.Connection, catalog_id: int) -> None:
    """Ставит в outbox полную строку каталога (как в прежних маршрутах app.py)."""
    try:
        row = conn.execute(
            """
            SELECT uuid, position_name, unit_name, frequency, group_code, location, updated_at
            FROM intercept_catalog
            WHERE id=?
            """,
            (int(catalog_id),),
        ).fetchone()
        if not row:
            return
        location_value = ""
        try:
            location_value = str(row["location"] or "")
        except (KeyError, IndexError):
            pass
        enqueue_sync_outbox(
            conn,
            kind="intercepts:catalog",
            payload={
                "uuid": str(row["uuid"] or ""),
                "position_name": str(row["position_name"] or ""),
                "unit_name": str(row["unit_name"] or ""),
                "frequency": str(row["frequency"] or ""),
                "group_code": str(row["group_code"] or ""),
                "location": location_value,
                "updated_at": str(row["updated_at"] or ""),
            },
        )
    except Exception:
        pass


def execute_intercepts_catalog_upsert(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    unit_name: str,
    frequency: str,
    group_code: str,
    location: str,
    hub_sync_enabled: bool,
) -> dict[str, Any]:
    cid = upsert_intercept_catalog(
        conn,
        position_name=position_name,
        unit_name=unit_name,
        frequency=frequency,
        group_code=group_code,
        location=location,
    )
    if hub_sync_enabled:
        maybe_enqueue_intercept_catalog_sync(conn, int(cid))
    return {"ok": True, "id": cid}


def execute_intercepts_catalog_update_location(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    catalog_id: int,
    location: str,
    hub_sync_enabled: bool,
) -> dict[str, Any]:
    if not catalog_id:
        raise InterceptsUseCaseHTTP(400, {"ok": False, "error": "id обязателен"})

    row = conn.execute(
        "SELECT position_name FROM intercept_catalog WHERE id=?",
        (catalog_id,),
    ).fetchone()
    if not row:
        raise InterceptsUseCaseHTTP(404, {"ok": False, "error": "Запись не найдена"})
    if str(row["position_name"] or "").strip() != position_name:
        raise InterceptsUseCaseHTTP(403, {"ok": False, "error": "Нет доступа к записи"})

    conn.execute(
        "UPDATE intercept_catalog SET location=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (location, catalog_id),
    )
    conn.commit()

    if hub_sync_enabled:
        maybe_enqueue_intercept_catalog_sync(conn, int(catalog_id))

    return {"ok": True}
