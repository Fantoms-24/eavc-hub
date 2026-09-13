"""Seans schema / daily aggregates (physically extracted)."""
from __future__ import annotations

from typing import Any
import sqlite3


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    try:
        r = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (str(table),),
        ).fetchone()
        return bool(r)
    except Exception:
        return False


def seanses_union_source_sql(conn: sqlite3.Connection) -> str:
    """Подзапрос seanses + seanses_archive (для сверки ключей, крипто и т.п.)."""
    if _table_exists(conn, "seanses_archive"):
        return """
            SELECT date_time, frequency, group_, id, aes_key, client_name
            FROM seanses
            UNION ALL
            SELECT date_time, frequency, group_, id, aes_key, client_name
            FROM seanses_archive
        """
    return """
        SELECT date_time, frequency, group_, id, aes_key, client_name
        FROM seanses
    """


def init_daily_aggregates(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS seanses_daily_agg (
            day TEXT NOT NULL,
            client_name TEXT NOT NULL DEFAULT '',
            frequency TEXT NOT NULL DEFAULT '',
            group_ TEXT NOT NULL DEFAULT '',
            sessions_count INTEGER NOT NULL DEFAULT 0,
            correspondents_count INTEGER NOT NULL DEFAULT 0,
            ids_csv TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(day, client_name, frequency, group_)
        );
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_seanses_daily_client_day ON seanses_daily_agg(client_name, day);"
    )
    conn.commit()


def refresh_seanses_daily_aggregates(
    conn: sqlite3.Connection,
    *,
    start_day: str | None = None,
    end_day: str | None = None,
) -> int:
    init_daily_aggregates(conn)
    start = str(start_day or "").strip()
    end = str(end_day or "").strip()
    delete_where = ""
    params: list[Any] = []
    if start and end:
        delete_where = "WHERE day BETWEEN ? AND ?"
        params.extend([start, end])
    conn.execute(f"DELETE FROM seanses_daily_agg {delete_where}", tuple(params))
    src_filter = ""
    src_params: list[Any] = []
    if start and end:
        src_filter = "WHERE substr(date_time, 1, 10) BETWEEN ? AND ?"
        src_params.extend([start, end])
    cur = conn.execute(
        f"""
        INSERT OR REPLACE INTO seanses_daily_agg
            (day, client_name, frequency, group_, sessions_count, correspondents_count, ids_csv, updated_at)
        SELECT
            day,
            COALESCE(client_name, '') AS client_name,
            TRIM(COALESCE(frequency, '')) AS frequency,
            TRIM(COALESCE(group_, '')) AS group_,
            COUNT(DISTINCT date_time) AS sessions_count,
            COUNT(DISTINCT id) AS correspondents_count,
            GROUP_CONCAT(DISTINCT id) AS ids_csv,
            CURRENT_TIMESTAMP
        FROM (
            SELECT substr(date_time, 1, 10) AS day, client_name, frequency, group_, id, date_time
            FROM seanses
            {src_filter}
            UNION ALL
            SELECT substr(date_time, 1, 10) AS day, client_name, frequency, group_, id, date_time
            FROM seanses_archive
            {src_filter}
        ) s
        WHERE TRIM(COALESCE(frequency, '')) != ''
          AND TRIM(COALESCE(group_, '')) != ''
        GROUP BY day, COALESCE(client_name, ''), TRIM(COALESCE(frequency, '')), TRIM(COALESCE(group_, ''))
        """,
        tuple(src_params + src_params),
    )
    conn.commit()
    return int(cur.rowcount or 0)


def refresh_seanses_daily_aggregates_for_entries(
    conn: sqlite3.Connection, entries: list[Any], *, client_name: str | None = None
) -> int:
    days = sorted(
        {
            str(getattr(e, "date_time", "") or "")[:10]
            for e in (entries or [])
            if str(getattr(e, "date_time", "") or "")[:10]
        }
    )
    total = 0
    for day in days:
        total += refresh_seanses_daily_aggregates(conn, start_day=day, end_day=day)
    return total


def init_seans_tables(conn: sqlite3.Connection) -> None:
    """
    Схема для операций с seanses/processed_files:
    seans.sqlite после миграции или legacy main.sqlite до неё.
    """
    from web_portal.lib.db.connection import init_db
    from web_portal.lib.seans_db import connection_path_is_seans_storage, init_seans_storage

    if connection_path_is_seans_storage(conn):
        init_seans_storage(conn)
    else:
        init_db(conn)


__all__ = [
    "_table_exists",
    "seanses_union_source_sql",
    "init_daily_aggregates",
    "refresh_seanses_daily_aggregates",
    "refresh_seanses_daily_aggregates_for_entries",
    "init_seans_tables",
]
