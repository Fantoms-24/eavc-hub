"""Применение одного события sync/push (общий код для сервера и batch-фаз)."""

from __future__ import annotations

from collections.abc import Callable
import sqlite3
from typing import Any

from web_portal.config import portal_db_path, search_online_db_path
from web_portal.lib.auth_db import (
    connect_portal,
    ensure_position,
    set_user_positions_by_username_from_sync,
    upsert_chat_message_from_sync,
    upsert_targeting_from_sync,
    upsert_user_from_sync,
)
from web_portal.lib.aviation_db_sync import (
    apply_aviation_callsign_delete_from_sync,
    apply_aviation_frequency_delete_from_sync,
    upsert_aviation_callsign_from_sync,
    upsert_aviation_frequency_from_sync,
    upsert_aviation_intercept_from_sync,
    upsert_aviation_daily_intercept_from_sync,
)
from web_portal.lib.db import (
    apply_intercept_catalog_delete_from_sync,
    connect,
    delete_online_search_row,
    ensure_db,
    upsert_analysis_assignment_from_sync,
    upsert_intercept_callsign_from_sync,
    upsert_intercept_catalog_from_sync,
    upsert_intercept_item_from_sync,
    upsert_intercept_session_from_sync,
    upsert_online_search_meta_from_sync,
    upsert_online_search_rows_from_sync,
    upsert_seanses_rows_from_sync,
    upsert_unit_rows_from_sync,
)

from web_portal.lib.db import _SYNC_OUTBOX_PRIORITY_KINDS

# Бланки/смены — в отдельной короткой транзакции до seanses:batch и online_search.
SYNC_PUSH_PRIORITY_KINDS: frozenset[str] = frozenset(_SYNC_OUTBOX_PRIORITY_KINDS)

BULK_SYNC_PUSH_KINDS: frozenset[str] = frozenset(
    {
        "seanses:batch",
        "online_search:batch",
        "online_search:delete",
        "online_search:meta",
        "unit:batch",
        "aviation:frequency",
        "aviation:intercept",
        "aviation:daily_intercept",
        "aviation:callsign",
        "aviation:frequency_delete",
        "aviation:callsign_delete",
        "portal:user",
        "portal:positions",
        "portal:position",
        "targeting",
    }
)

# Не держат блокировку main.sqlite — отдельные файлы (seans, search, portal).
SYNC_PUSH_EXTERNAL_KINDS: frozenset[str] = frozenset(
    {
        "seanses:batch",
        "online_search:batch",
        "online_search:delete",
        "online_search:meta",
        "portal:user",
        "portal:positions",
        "portal:position",
        "targeting",
        "chat:message",
    }
)


def is_sync_push_priority_kind(kind: str) -> bool:
    return str(kind or "").strip() in SYNC_PUSH_PRIORITY_KINDS


def is_sync_push_external_kind(kind: str) -> bool:
    return str(kind or "").strip() in SYNC_PUSH_EXTERNAL_KINDS


def partition_sync_push_events(
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    priority: list[dict[str, Any]] = []
    bulk: list[dict[str, Any]] = []
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        kind = str(ev.get("kind") or "").strip()
        if is_sync_push_priority_kind(kind):
            priority.append(ev)
        else:
            bulk.append(ev)
    return priority, bulk


def apply_sync_push_event(
    conn: sqlite3.Connection,
    *,
    kind: str,
    payload: dict[str, Any],
    forward_intercept: Callable[[sqlite3.Connection, dict[str, Any]], None] | None = None,
) -> int:
    """
    Применяет одно событие. Возвращает 1 если учтено, иначе 0.
    Исключения пробрасываются наверх (для логирования на сервере).
    """
    k = str(kind or "").strip()
    data = payload if isinstance(payload, dict) else {}

    if k == "intercepts:item":
        upsert_intercept_item_from_sync(conn, data=data)
        if forward_intercept is not None:
            forward_intercept(conn, data)
        return 1
    if k == "intercepts:session":
        upsert_intercept_session_from_sync(conn, data=data)
        return 1
    if k == "intercepts:catalog":
        upsert_intercept_catalog_from_sync(conn, data=data)
        return 1
    if k == "intercepts:catalog_delete":
        if apply_intercept_catalog_delete_from_sync(conn, payload=data):
            return 1
        return 0
    if k == "intercepts:callsign":
        upsert_intercept_callsign_from_sync(conn, data=data)
        return 1
    if k == "seanses:batch":
        rows = data.get("rows")
        if isinstance(rows, list) and rows:
            from web_portal.lib.seans_db import connect_seans_storage

            seans_conn = connect_seans_storage()
            try:
                upsert_seanses_rows_from_sync(seans_conn, rows=rows)
            finally:
                seans_conn.close()
            return 1
        return 0
    if k == "online_search:batch":
        rows = data.get("rows")
        if isinstance(rows, list) and rows:
            search_p = search_online_db_path()
            ensure_db(search_p)
            search_conn = connect(search_p)
            try:
                upsert_online_search_rows_from_sync(search_conn, rows=rows)
            finally:
                search_conn.close()
            return 1
        return 0
    if k == "online_search:delete":
        rid = int(data.get("id") or 0)
        if rid:
            search_p = search_online_db_path()
            ensure_db(search_p)
            search_conn = connect(search_p)
            try:
                delete_online_search_row(search_conn, rid)
            finally:
                search_conn.close()
            return 1
        return 0
    if k == "online_search:meta":
        if data:
            search_p = search_online_db_path()
            ensure_db(search_p)
            search_conn = connect(search_p)
            try:
                upsert_online_search_meta_from_sync(search_conn, payload=data)
            finally:
                search_conn.close()
            return 1
        return 0
    if k == "unit:batch":
        rows = data.get("rows")
        if isinstance(rows, list) and rows:
            upsert_unit_rows_from_sync(conn, rows=rows)
            return 1
        return 0
    if k == "aviation:frequency":
        upsert_aviation_frequency_from_sync(conn, data=data)
        return 1
    if k == "aviation:intercept":
        upsert_aviation_intercept_from_sync(conn, data=data)
        return 1
    if k == "aviation:daily_intercept":
        upsert_aviation_daily_intercept_from_sync(conn, data=data)
        return 1
    if k == "aviation:callsign":
        upsert_aviation_callsign_from_sync(conn, data=data)
        return 1
    if k == "aviation:frequency_delete":
        return 1 if apply_aviation_frequency_delete_from_sync(conn, payload=data) else 0
    if k == "aviation:callsign_delete":
        return 1 if apply_aviation_callsign_delete_from_sync(conn, payload=data) else 0
    if k == "portal:user":
        pconn = connect_portal(portal_db_path())
        try:
            upsert_user_from_sync(pconn, payload=data)
            return 1
        finally:
            pconn.close()
    if k == "portal:positions":
        pconn = connect_portal(portal_db_path())
        try:
            uname = str(data.get("username") or "").strip()
            positions = data.get("positions") or []
            if uname and isinstance(positions, list):
                set_user_positions_by_username_from_sync(
                    pconn,
                    username=uname,
                    positions=[str(x) for x in positions],
                )
                return 1
        finally:
            pconn.close()
        return 0
    if k == "portal:position":
        pconn = connect_portal(portal_db_path())
        try:
            nm = str(data.get("name") or "").strip()
            if nm:
                ensure_position(pconn, nm)
                return 1
        finally:
            pconn.close()
        return 0
    if k == "targeting":
        pconn = connect_portal(portal_db_path())
        try:
            upsert_targeting_from_sync(pconn, payload=data)
            return 1
        finally:
            pconn.close()
    if k == "analysis:assignment":
        upsert_analysis_assignment_from_sync(conn, payload=data)
        return 1
    if k == "chat:message":
        pconn2 = connect_portal(portal_db_path())
        try:
            upsert_chat_message_from_sync(pconn2, payload=data)
            return 1
        finally:
            pconn2.close()
    return 0


def apply_sync_push_events(
    conn: sqlite3.Connection,
    events: list[dict[str, Any]],
    *,
    forward_intercept: Callable[[sqlite3.Connection, dict[str, Any]], None] | None = None,
) -> int:
    applied = 0
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        kind = str(ev.get("kind") or "").strip()
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            applied += apply_sync_push_event(
                conn,
                kind=kind,
                payload=payload,
                forward_intercept=forward_intercept,
            )
        except Exception:
            continue
    return applied
