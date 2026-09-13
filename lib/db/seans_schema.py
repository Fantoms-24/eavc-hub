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


_SEANSES_POSITION_KEY = ("date_time", "frequency", "group_", "id", "client_name")


def seanses_position_key_is_current(
    conn: sqlite3.Connection, table: str = "seanses"
) -> bool:
    """Проверяет, что источник является обязательной частью идентичности строки."""
    if table not in {"seanses", "seanses_archive"} or not _table_exists(conn, table):
        return False
    try:
        info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return False
    by_name = {str(row[1]): row for row in info}
    client = by_name.get("client_name")
    if client is None or int(client[3] or 0) != 1:
        return False
    primary_key = tuple(
        str(row[1])
        for row in sorted(
            (row for row in info if int(row[5] or 0) > 0),
            key=lambda row: int(row[5]),
        )
    )
    return primary_key == _SEANSES_POSITION_KEY


def ensure_seanses_position_primary_keys(
    conn: sqlite3.Connection, *, tables: tuple[str, ...] = ("seanses", "seanses_archive")
) -> bool:
    """Идемпотентно меняет legacy PK сеансов на ключ с именем позиции.

    SQLite не умеет добавлять колонку к PRIMARY KEY через ALTER TABLE. Поэтому
    таблица пересобирается внутри одного SAVEPOINT: число строк сверяется до и
    после копирования, а ``client_name`` канонизируется в непустое SQL-значение
    (пустая строка для исторического источника, который уже неизвестен).
    """
    wanted = tuple(table for table in tables if table in {"seanses", "seanses_archive"})
    outdated = [
        table
        for table in wanted
        if _table_exists(conn, table) and not seanses_position_key_is_current(conn, table)
    ]
    if not outdated:
        return False

    definitions = {
        "seanses": """
            CREATE TABLE __seanses_position_key_v2 (
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                date_time TEXT NOT NULL,
                frequency TEXT NOT NULL,
                group_ TEXT NOT NULL,
                id TEXT NOT NULL,
                aes_key TEXT,
                client_name TEXT NOT NULL DEFAULT '',
                color_voice TEXT,
                time_seconds REAL,
                PRIMARY KEY (date_time, frequency, group_, id, client_name)
            )
        """,
        "seanses_archive": """
            CREATE TABLE __seanses_archive_position_key_v2 (
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                date_time TEXT NOT NULL,
                frequency TEXT NOT NULL,
                group_ TEXT NOT NULL,
                id TEXT NOT NULL,
                aes_key TEXT,
                client_name TEXT NOT NULL DEFAULT '',
                color_voice TEXT,
                time_seconds REAL,
                archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (date_time, frequency, group_, id, client_name)
            )
        """,
    }
    temp_names = {
        "seanses": "__seanses_position_key_v2",
        "seanses_archive": "__seanses_archive_position_key_v2",
    }
    base_columns = [
        "created_at",
        "date_time",
        "frequency",
        "group_",
        "id",
        "aes_key",
        "client_name",
        "color_voice",
        "time_seconds",
    ]

    conn.execute("SAVEPOINT seanses_position_key_migration")
    try:
        for table in outdated:
            temp = temp_names[table]
            source_columns = {
                str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            columns = list(base_columns)
            if table == "seanses_archive":
                columns.append("archived_at")
            expressions: list[str] = []
            for column in columns:
                if column == "client_name":
                    expressions.append(
                        "TRIM(COALESCE(client_name, ''))"
                        if column in source_columns
                        else "''"
                    )
                elif column in {"created_at", "archived_at"}:
                    expressions.append(
                        f"COALESCE({column}, CURRENT_TIMESTAMP)"
                        if column in source_columns
                        else "CURRENT_TIMESTAMP"
                    )
                elif column in source_columns:
                    expressions.append(column)
                else:
                    expressions.append("NULL")

            before = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            conn.execute(f"DROP TABLE IF EXISTS {temp}")
            conn.execute(definitions[table])
            conn.execute(
                f"INSERT INTO {temp} ({', '.join(columns)}) "
                f"SELECT {', '.join(expressions)} FROM {table}"
            )
            after = int(conn.execute(f"SELECT COUNT(*) FROM {temp}").fetchone()[0])
            if after != before:
                raise RuntimeError(
                    f"Миграция {table}: ожидалось строк {before}, скопировано {after}"
                )
            conn.execute(f"DROP TABLE {table}")
            conn.execute(f"ALTER TABLE {temp} RENAME TO {table}")

        check_rows = conn.execute("PRAGMA integrity_check").fetchall()
        if any(str(row[0] or "").lower() != "ok" for row in check_rows):
            raise RuntimeError("Миграция seanses: SQLite integrity_check не прошёл")
        conn.execute("RELEASE SAVEPOINT seanses_position_key_migration")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT seanses_position_key_migration")
        conn.execute("RELEASE SAVEPOINT seanses_position_key_migration")
        raise
    return True


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
    "seanses_position_key_is_current",
    "ensure_seanses_position_primary_keys",
    "seanses_union_source_sql",
    "init_daily_aggregates",
    "refresh_seanses_daily_aggregates",
    "refresh_seanses_daily_aggregates_for_entries",
    "init_seans_tables",
]
