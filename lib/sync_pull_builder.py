from __future__ import annotations

from datetime import datetime
from typing import Any

from web_portal.config import DEFAULT_DB_NAME, db_path, portal_db_path, search_online_db_path
from web_portal.lib.auth_db import connect_portal, list_chat_messages_since, list_targeting_since, list_users_since
from web_portal.lib.aviation_db_sync import (
    list_aviation_callsigns_after,
    list_aviation_frequencies_after,
    list_aviation_intercepts_after,
)
from web_portal.lib.db import (
    connect,
    ensure_db,
    get_online_search_meta_payload,
    list_analysis_assignments_since,
    list_intercept_callsigns_since,
    list_intercept_catalog_deletes_since,
    list_intercept_catalog_since,
    list_intercept_items_since,
    list_intercept_sessions_since,
    list_online_search_rows_after,
    list_seanses_since,
    list_unit_rows_since,
)
import logging

_log = logging.getLogger("web_portal.lib.sync_pull_builder")


def build_sync_pull_payload(
    *,
    since: str,
    position_names: list[str],
    allow_seanses: bool,
    seanses_limit: int,
    unit_limit: int,
    online_limit: int,
) -> dict[str, Any]:
    """Собирает тело ответа /api/sync/pull (тяжёлые запросы к SQLite)."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    p = db_path(DEFAULT_DB_NAME)
    ensure_db(p)
    conn = connect(p)
    from web_portal.lib.seans_db import connect_seans_storage

    seans_conn = connect_seans_storage()
    try:
        result: dict[str, Any] = {
            "ok": True,
            "now": now,
            "since": since,
            "seanses": (
                list_seanses_since(
                    seans_conn,
                    since_ts=since,
                    limit=seanses_limit,
                    position_names=position_names,
                )
                if allow_seanses
                else []
            ),
            "unit_rows": list_unit_rows_since(conn, since_ts=since, limit=unit_limit),
            "sessions": list_intercept_sessions_since(
                conn, since_ts=since, position_names=position_names
            ),
            "catalog": list_intercept_catalog_since(
                conn, since_ts=since, position_names=position_names
            ),
            "catalog_deletes": list_intercept_catalog_deletes_since(
                conn, since_ts=since, position_names=position_names
            ),
            "callsigns": list_intercept_callsigns_since(
                conn, since_ts=since, position_names=position_names
            ),
            "items": list_intercept_items_since(
                conn, since_ts=since, position_names=position_names
            ),
            "analysis_assignments": list_analysis_assignments_since(
                conn, since_ts=since, position_names=position_names
            ),
            "aviation_frequencies": list_aviation_frequencies_after(
                conn, after_updated_at=since
            ),
            "aviation_intercepts": list_aviation_intercepts_after(
                conn, after_updated_at=since
            ),
            "aviation_callsigns": list_aviation_callsigns_after(
                conn, after_updated_at=since
            ),
        }
    finally:
        try:
            seans_conn.close()
        except Exception:
            _log.debug("build_sync_pull_payload: suppressed error", exc_info=True)
        conn.close()

    search_p = search_online_db_path()
    ensure_db(search_p)
    search_conn = connect(search_p)
    try:
        result["online_search"] = list_online_search_rows_after(
            search_conn, after_updated_at=since, after_id=0, limit=online_limit
        )
        meta = get_online_search_meta_payload(search_conn)
        if isinstance(meta, dict) and meta:
            result["online_search_meta"] = meta
    finally:
        search_conn.close()

    pconn = connect_portal(portal_db_path())
    try:
        result["targeting"] = list_targeting_since(pconn, since_ts=since)
        result["portal_users"] = list_users_since(pconn, since_ts=since)
        result["chat_messages"] = list_chat_messages_since(pconn, since_ts=since)
    finally:
        pconn.close()

    result["limits"] = {
        "seanses_limit": seanses_limit,
        "unit_limit": unit_limit,
        "online_limit": online_limit,
    }
    # Время имеет секунды, поэтому HUB держит короткое перекрытие курсора.
    # Если один из лимитов исчерпан, он продолжает старый постраничный режим,
    # пока не дочитает хвост; это не позволяет пропустить большой первый pull.
    result["pagination"] = {
        "seanses_truncated": len(result["seanses"]) >= seanses_limit,
        "unit_rows_truncated": len(result["unit_rows"]) >= unit_limit,
        "online_search_truncated": len(result.get("online_search") or []) >= online_limit,
    }
    return result
