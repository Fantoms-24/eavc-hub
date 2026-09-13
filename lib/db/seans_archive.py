"""Архивация / очистка сеансов (физически вынесено из ``_impl``)."""
from __future__ import annotations

import sqlite3
from typing import Any

from web_portal.lib.db.seans_schema import _table_exists, init_seans_tables


def clear_seanses_by_client_name(conn: sqlite3.Connection, client_name: str) -> int:
    from web_portal.lib.db.sql_util import _table_columns
    name = str(client_name or "").strip()
    if not name:
        return 0
    if not _table_exists(conn, "seanses"):
        return 0
    cols = _table_columns(conn, "seanses")
    if "client_name" not in cols:
        return 0
    cur = conn.execute("DELETE FROM seanses WHERE client_name=?", (name,))
    conn.commit()
    return int(cur.rowcount or 0)


def archive_seanses_outside_current_day(
    conn: sqlite3.Connection,
    *,
    keep_date: str | None = None,
    batch_size: int = 5000,
) -> dict[str, Any]:
    """
    Ручная архивация seanses:
    - оставляет только записи за keep_date (YYYY-MM-DD),
    - все остальные переносит в seanses_archive и удаляет из seanses.
    По умолчанию keep_date = текущая локальная дата компьютера.
    """
    init_seans_tables(conn)
    if not _table_exists(conn, "seanses"):
        return {
            "keep_date": "",
            "archived": 0,
            "remaining_active": 0,
            "archive_total": 0,
        }

    from datetime import datetime as _dt

    day = (str(keep_date or "").strip()[:10]) or _dt.now().strftime("%Y-%m-%d")
    batch_size = max(100, min(int(batch_size), 50000))
    archived = 0

    while True:
        rows = conn.execute(
            """
            SELECT rowid, created_at, date_time, frequency, group_, id, aes_key, color_voice, time_seconds, client_name
            FROM seanses
            WHERE substr(COALESCE(date_time,''), 1, 10) <> ?
            ORDER BY date_time ASC, rowid ASC
            LIMIT ?
            """,
            (day, batch_size),
        ).fetchall()
        if not rows:
            break

        to_archive = [
            (
                str(r["created_at"] or "") or None,
                str(r["date_time"] or ""),
                str(r["frequency"] or ""),
                str(r["group_"] or ""),
                str(r["id"] or ""),
                str(r["aes_key"] or "") or None,
                (str(r["color_voice"] or "").strip() or None) if "color_voice" in r else None,
                r["time_seconds"] if "time_seconds" in r and r["time_seconds"] is not None else None,
                str(r["client_name"] or "") or None,
            )
            for r in rows
        ]
        conn.executemany(
            """
            INSERT OR IGNORE INTO seanses_archive
            (created_at, date_time, frequency, group_, id, aes_key, color_voice, time_seconds, client_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            to_archive,
        )
        rowids = [int(r["rowid"]) for r in rows]
        placeholders = ",".join(["?"] * len(rowids))
        cur = conn.execute(
            f"DELETE FROM seanses WHERE rowid IN ({placeholders})",
            rowids,
        )
        conn.commit()
        archived += int(cur.rowcount or 0)

    remaining = int(conn.execute("SELECT COUNT(*) FROM seanses").fetchone()[0] or 0)
    archive_total = int(
        conn.execute("SELECT COUNT(*) FROM seanses_archive").fetchone()[0] or 0
    )
    return {
        "keep_date": day,
        "archived": archived,
        "remaining_active": remaining,
        "archive_total": archive_total,
    }


def archive_all_seanses_to_archive(
    conn: sqlite3.Connection,
    *,
    batch_size: int = 5000,
) -> dict[str, Any]:
    """
    Переносит все строки из seanses в seanses_archive и очищает seanses.

    Не затрагивает: unit (подразделения/частоты/группы), intercept_catalog,
    intercept_sessions, intercept_items, online_search, sessions_favorites,
    processed_files, frequency_last_processed и прочие справочники.
    """
    init_seans_tables(conn)
    if not _table_exists(conn, "seanses"):
        return {
            "mode": "all",
            "archived": 0,
            "remaining_active": 0,
            "archive_total": 0,
        }

    batch_size = max(100, min(int(batch_size), 50000))
    archived = 0

    while True:
        rows = conn.execute(
            """
            SELECT rowid, created_at, date_time, frequency, group_, id, aes_key, color_voice, time_seconds, client_name
            FROM seanses
            ORDER BY date_time ASC, rowid ASC
            LIMIT ?
            """,
            (batch_size,),
        ).fetchall()
        if not rows:
            break

        to_archive = [
            (
                str(r["created_at"] or "") or None,
                str(r["date_time"] or ""),
                str(r["frequency"] or ""),
                str(r["group_"] or ""),
                str(r["id"] or ""),
                str(r["aes_key"] or "") or None,
                (str(r["color_voice"] or "").strip() or None) if "color_voice" in r else None,
                r["time_seconds"] if "time_seconds" in r and r["time_seconds"] is not None else None,
                str(r["client_name"] or "") or None,
            )
            for r in rows
        ]
        conn.executemany(
            """
            INSERT OR IGNORE INTO seanses_archive
            (created_at, date_time, frequency, group_, id, aes_key, color_voice, time_seconds, client_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            to_archive,
        )
        rowids = [int(r["rowid"]) for r in rows]
        placeholders = ",".join(["?"] * len(rowids))
        cur = conn.execute(
            f"DELETE FROM seanses WHERE rowid IN ({placeholders})",
            rowids,
        )
        conn.commit()
        archived += int(cur.rowcount or 0)

    remaining = int(conn.execute("SELECT COUNT(*) FROM seanses").fetchone()[0] or 0)
    archive_total = int(
        conn.execute("SELECT COUNT(*) FROM seanses_archive").fetchone()[0] or 0
    )
    return {
        "mode": "all",
        "archived": archived,
        "remaining_active": remaining,
        "archive_total": archive_total,
    }


def init_seanses_archive_file_schema(conn: sqlite3.Connection) -> None:
    """
    Только таблица seanses (+ индексы) для внешнего файла архива.
    Не создаёт unit, intercept и т.д.
    """
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS seanses (
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            date_time TEXT NOT NULL,
            frequency TEXT NOT NULL,
            group_ TEXT NOT NULL,
            id TEXT NOT NULL,
            aes_key TEXT,
            CONSTRAINT pk PRIMARY KEY (date_time, frequency, group_, id)
        );
        """
    )
    try:
        cur.execute("ALTER TABLE seanses ADD COLUMN client_name TEXT;")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE seanses ADD COLUMN color_voice TEXT;")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE seanses ADD COLUMN time_seconds REAL;")
    except sqlite3.OperationalError:
        pass
    cur.execute("CREATE INDEX IF NOT EXISTS idx_date_time on seanses (date_time);")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_freq_group on seanses (frequency, group_);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_date_time_freq_group on seanses (date_time, frequency, group_);"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_client_name on seanses (client_name);")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_seanses_client_freq_group_dt ON seanses(client_name, frequency, group_, date_time);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_date_time_client on seanses (date_time, client_name);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_seanses_covering on seanses (date_time, frequency, group_, id);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_seanses_covering_client on seanses (date_time, client_name, frequency, group_, id);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_seanses_freq_group_dt_desc on seanses (frequency, group_, date_time DESC);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_seanses_client_freq_group_dt_desc on seanses (client_name, frequency, group_, date_time DESC);"
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS archive_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    conn.commit()


def archive_seanses_before_date_to_file(
    *,
    main_db_path: Path,
    archive_path: Path,
    before_date_exclusive: str,
    batch_size: int = 5000,
    vacuum_main: bool = False,
    include_seanses_archive_table: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Переносит старые сеансы из main.sqlite в отдельный файл SQLite и удаляет их из основной БД.

    Условие по календарному дню: substr(date_time,1,10) < before_date_exclusive
    (before_date — YYYY-MM-DD; при before_date=2026-04-22 остаются сеансы с датой 2026-04-22 и позже).

    - Таблица seanses: строки копируются в файл, затем удаляются из main.
    - Таблица seanses_archive (опционально): те же строки в файле попадают в seanses, затем удаляются из main.

    Не затрагивает unit, перехваты, processed_files и др.
    """
    from web_portal.lib.db.sql_util import _table_columns
    from web_portal.lib.db.connection import connect
    from datetime import datetime as _dt

    before_date_exclusive = str(before_date_exclusive or "").strip()[:10]
    if not before_date_exclusive or len(before_date_exclusive) < 10:
        raise ValueError("before_date должен быть в формате YYYY-MM-DD")

    archive_path = Path(archive_path).resolve()
    main_db_path = Path(main_db_path).resolve()

    if archive_path.exists():
        if not overwrite:
            raise ValueError(f"Файл уже существует: {archive_path}")
        try:
            archive_path.unlink()
        except OSError as e:
            raise ValueError(f"Не удалось удалить существующий файл: {e}") from e

    batch_size = max(100, min(int(batch_size), 50000))
    moved_seanses = 0
    moved_from_archive = 0

    arch_conn = connect(archive_path)
    try:
        init_seanses_archive_file_schema(arch_conn)
        main_conn = connect(main_db_path)
        try:
            from web_portal.lib.db import init_seans_tables

            init_seans_tables(main_conn)
            if not _table_exists(main_conn, "seanses"):
                raise ValueError("В основной БД нет таблицы seanses")

            cols = _table_columns(main_conn, "seanses")
            sel_cols = [
                "created_at",
                "date_time",
                "frequency",
                "group_",
                "id",
                "aes_key",
                "color_voice",
                "time_seconds",
                "client_name",
            ]
            present = [c for c in sel_cols if c in cols]
            if not present:
                raise ValueError("В таблице seanses нет ожидаемых колонок")
            col_sql = ", ".join(present)
            placeholders = ", ".join(["?"] * len(present))

            while True:
                rows = main_conn.execute(
                    f"""
                    SELECT rowid, {col_sql}
                    FROM seanses
                    WHERE substr(date_time, 1, 10) < ?
                    ORDER BY date_time ASC, rowid ASC
                    LIMIT ?
                    """,
                    (before_date_exclusive, batch_size),
                ).fetchall()
                if not rows:
                    break
                tuples = []
                rowids: list[int] = []
                for r in rows:
                    rowids.append(int(r["rowid"]))
                    tuples.append(tuple(r[c] for c in present))
                arch_conn.executemany(
                    f"""
                    INSERT OR IGNORE INTO seanses ({col_sql})
                    VALUES ({placeholders})
                    """,
                    tuples,
                )
                ph = ",".join(["?"] * len(rowids))
                main_conn.execute(
                    f"DELETE FROM seanses WHERE rowid IN ({ph})",
                    rowids,
                )
                main_conn.commit()
                arch_conn.commit()
                moved_seanses += len(rowids)

            if include_seanses_archive_table and _table_exists(main_conn, "seanses_archive"):
                arc_cols = _table_columns(main_conn, "seanses_archive")
                sel_a = [
                    c
                    for c in [
                        "created_at",
                        "date_time",
                        "frequency",
                        "group_",
                        "id",
                        "aes_key",
                        "color_voice",
                        "time_seconds",
                        "client_name",
                    ]
                    if c in arc_cols
                ]
                if sel_a:
                    col_sql_a = ", ".join(sel_a)
                    ph_a = ", ".join(["?"] * len(sel_a))
                    while True:
                        rows = main_conn.execute(
                            f"""
                            SELECT rowid, {col_sql_a}
                            FROM seanses_archive
                            WHERE substr(date_time, 1, 10) < ?
                            ORDER BY date_time ASC, rowid ASC
                            LIMIT ?
                            """,
                            (before_date_exclusive, batch_size),
                        ).fetchall()
                        if not rows:
                            break
                        tuples = []
                        rowids = []
                        for r in rows:
                            rowids.append(int(r["rowid"]))
                            tuples.append(tuple(r[c] for c in sel_a))
                        arch_conn.executemany(
                            f"""
                            INSERT OR IGNORE INTO seanses ({col_sql_a})
                            VALUES ({ph_a})
                            """,
                            tuples,
                        )
                        ph = ",".join(["?"] * len(rowids))
                        main_conn.execute(
                            f"DELETE FROM seanses_archive WHERE rowid IN ({ph})",
                            rowids,
                        )
                        main_conn.commit()
                        arch_conn.commit()
                        moved_from_archive += len(rowids)

            try:
                for k, v in (
                    ("before_date_exclusive", before_date_exclusive),
                    ("exported_at", _dt.now().strftime("%Y-%m-%d %H:%M:%S")),
                    ("moved_from_seanses", str(moved_seanses)),
                    ("moved_from_seanses_archive", str(moved_from_archive)),
                ):
                    arch_conn.execute(
                        "INSERT OR REPLACE INTO archive_meta (key, value) VALUES (?, ?)",
                        (k, v),
                    )
            except Exception:
                _log.debug("archive_seanses_before_date_to_file: suppressed error", exc_info=True)
            arch_conn.commit()

            if vacuum_main:
                try:
                    main_conn.execute("VACUUM")
                    main_conn.commit()
                except Exception:
                    _log.debug("archive_seanses_before_date_to_file: suppressed error", exc_info=True)
        finally:
            try:
                main_conn.close()
            except Exception:
                _log.debug("archive_seanses_before_date_to_file: suppressed error", exc_info=True)
    finally:
        try:
            arch_conn.close()
        except Exception:
            _log.debug("archive_seanses_before_date_to_file: suppressed error", exc_info=True)

    remaining_seanses = 0
    remaining_archive = 0
    try:
        c2 = connect(main_db_path)
        try:
            if _table_exists(c2, "seanses"):
                remaining_seanses = int(
                    c2.execute("SELECT COUNT(*) FROM seanses").fetchone()[0] or 0
                )
            if _table_exists(c2, "seanses_archive"):
                remaining_archive = int(
                    c2.execute("SELECT COUNT(*) FROM seanses_archive").fetchone()[0]
                    or 0
                )
        finally:
            c2.close()
    except Exception:
        _log.debug("archive_seanses_before_date_to_file: suppressed error", exc_info=True)

    arch_total = 0
    try:
        c3 = connect(archive_path)
        try:
            arch_total = int(
                c3.execute("SELECT COUNT(*) FROM seanses").fetchone()[0] or 0
            )
        finally:
            c3.close()
    except Exception:
        _log.debug("archive_seanses_before_date_to_file: suppressed error", exc_info=True)

    return {
        "archive_path": str(archive_path),
        "before_date_exclusive": before_date_exclusive,
        "moved_from_seanses": moved_seanses,
        "moved_from_seanses_archive": moved_from_archive,
        "rows_in_archive_file_seanses": arch_total,
        "remaining_seanses_in_main": remaining_seanses,
        "remaining_seanses_archive_in_main": remaining_archive,
        "vacuum_main": bool(vacuum_main),
    }


def cleanup_seanses(
    conn: sqlite3.Connection,
    *,
    keep_days: int = 30,
    max_rows: int = 50000,
    batch_size: int = 5000,
) -> dict[str, int]:
    """
    Очистка таблицы seanses для снижения нагрузки:
      1) удаляем записи старше keep_days (по date_time),
      2) ограничиваем общий объём таблицы до max_rows (удаляем самые старые).
    Удаление выполняется пакетами, чтобы не держать долгую блокировку.
    """
    init_seans_tables(conn)
    if not _table_exists(conn, "seanses"):
        return {"deleted_by_days": 0, "deleted_by_limit": 0, "total_deleted": 0}

    keep_days = max(1, int(keep_days))
    max_rows = max(1000, int(max_rows))
    batch_size = max(100, min(int(batch_size), 50000))

    from datetime import datetime as _dt, timedelta as _td

    cutoff = (_dt.utcnow() - _td(days=keep_days)).strftime("%Y-%m-%d %H:%M:%S")

    deleted_by_days = 0
    deleted_by_limit = 0

    # Этап 1: удаляем по сроку хранения.
    while True:
        cur = conn.execute(
            """
            DELETE FROM seanses
            WHERE rowid IN (
                SELECT rowid
                FROM seanses
                WHERE date_time < ?
                ORDER BY date_time ASC, rowid ASC
                LIMIT ?
            )
            """,
            (cutoff, batch_size),
        )
        deleted = int(cur.rowcount or 0)
        if deleted <= 0:
            break
        deleted_by_days += deleted
        conn.commit()
        if deleted < batch_size:
            break

    # Этап 2: удерживаем общий размер таблицы в пределах max_rows.
    while True:
        total = int(conn.execute("SELECT COUNT(*) FROM seanses").fetchone()[0] or 0)
        overflow = total - max_rows
        if overflow <= 0:
            break
        take = min(batch_size, overflow)
        cur = conn.execute(
            """
            DELETE FROM seanses
            WHERE rowid IN (
                SELECT rowid
                FROM seanses
                ORDER BY date_time ASC, rowid ASC
                LIMIT ?
            )
            """,
            (take,),
        )
        deleted = int(cur.rowcount or 0)
        if deleted <= 0:
            break
        deleted_by_limit += deleted
        conn.commit()
        if deleted < take:
            break

    total_deleted = deleted_by_days + deleted_by_limit
    return {
        "deleted_by_days": deleted_by_days,
        "deleted_by_limit": deleted_by_limit,
        "total_deleted": total_deleted,
    }


def resolve_seans_conn_for_queries(
    main_conn: sqlite3.Connection,
    seans_conn: sqlite3.Connection | None = None,
) -> sqlite3.Connection:
    """
    Подключение для seanses / seanses_archive / seanses_daily_agg.
    После миграции — seans.sqlite; unit и настройки остаются в main_conn.
    """
    if seans_conn is not None:
        init_seans_tables(seans_conn)
        return seans_conn
    from web_portal.lib.seans_db import (
        connect_seans_storage,
        connection_path_is_seans_storage,
    )

    if connection_path_is_seans_storage(main_conn):
        init_seans_tables(main_conn)
        return main_conn
    sc = connect_seans_storage()
    init_seans_tables(sc)
    return sc


__all__ = [
    "clear_seanses_by_client_name",
    "archive_seanses_outside_current_day",
    "archive_all_seanses_to_archive",
    "init_seanses_archive_file_schema",
    "archive_seanses_before_date_to_file",
    "cleanup_seanses",
    "resolve_seans_conn_for_queries",
]
