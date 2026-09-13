"""Диагностика синхронизации админки (без Flask)."""

from __future__ import annotations

import logging
from typing import Any

import sqlite3

from web_portal.lib.db import get_sync_meta, list_sync_outbox_pending

_log = logging.getLogger("web_portal.application.admin.sync_status")


def _collect_sync_db_stats(conn: sqlite3.Connection) -> dict[str, int]:
    stats: dict[str, int] = {}
    try:
        stats["seanses_total"] = int(
            conn.execute("SELECT COUNT(*) FROM seanses").fetchone()[0] or 0
        )
        stats["unit_total"] = int(
            conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0] or 0
        )
        stats["intercept_sessions_total"] = int(
            conn.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM intercept_sessions)
                  +
                  (SELECT COUNT(*) FROM intercept_sessions_archive)
                """
            ).fetchone()[0]
            or 0
        )
        stats["intercept_catalog_total"] = int(
            conn.execute("SELECT COUNT(*) FROM intercept_catalog").fetchone()[0]
            or 0
        )
    except Exception:
        _log.debug("_collect_sync_db_stats: suppressed error", exc_info=True)
    return stats


def assemble_admin_sync_status_payload(
    conn: sqlite3.Connection,
    *,
    now_ts: str,
    sync_upstream: str | None,
    sync_key: str | None,
) -> dict[str, Any]:
    meta_keys = [
        "last_pull_ts",
        "seanses_last_rowid",
        "unit_last_rowid",
        "online_search_last_ts",
        "online_search_last_id",
    ]
    source_name = conn.execute("PRAGMA database_list").fetchone()[2]
    if sync_upstream and sync_key and source_name:
        from pathlib import Path
        from web_portal.lib.sync_delivery import load_cursor, pending_delivery, session_source

        source = Path(source_name)
        pending = pending_delivery(source, limit=200)
        meta = {
            key: load_cursor(session_source() if key == "seanses_last_rowid" else source, key)
            for key in meta_keys
        }
    else:
        pending = list_sync_outbox_pending(conn, limit=200)
        meta = {k: (get_sync_meta(conn, k) or "") for k in meta_keys}
    stats = _collect_sync_db_stats(conn)

    return {
        "ok": True,
        "now": now_ts,
        "is_hub": bool(sync_upstream and sync_key),
        "upstream": sync_upstream or "",
        "sync_key_set": bool(sync_key),
        "outbox_pending": len(pending),
        "outbox_head": [
            {
                "id": int(x["id"]),
                "kind": str(x["kind"] or ""),
                "created_at": str(x["created_at"] or ""),
                "attempts": int(x["attempts"] or 0),
                "last_error": str(x.get("last_error") or ""),
            }
            for x in (pending[:20] if isinstance(pending, list) else [])
        ],
        "meta": meta,
        "stats": stats,
    }
