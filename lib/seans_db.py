"""Отдельное хранилище сеансов (seans.sqlite) — не блокирует main.sqlite / перехваты."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from web_portal.config import DATA_DIR, DEFAULT_DB_NAME, db_path
import logging

_log = logging.getLogger("web_portal.lib.seans_db")

SEANSES_DB_NAME = "seans.sqlite"
SEANSES_MIGRATED_FLAG = "seans_db_migrated.flag"


def seans_db_path() -> Path:
    return (DATA_DIR / SEANSES_DB_NAME).resolve()


def seans_migrated_flag_path() -> Path:
    return (DATA_DIR / SEANSES_MIGRATED_FLAG).resolve()


def use_separate_seans_db() -> bool:
    """True после migrate_seans_to_separate_db или при явном WEB_PORTAL_SEANS_DB=1."""
    raw = (os.environ.get("WEB_PORTAL_SEANS_DB") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return seans_migrated_flag_path().exists()


def _seans_row_count_at(db_file: Path) -> int:
    """Число строк seanses + seanses_archive в файле (0 если файла/таблиц нет)."""
    if not db_file.is_file():
        return 0
    from web_portal.lib.db import connect

    conn = connect(db_file)
    try:
        total = 0
        for table in ("seanses", "seanses_archive"):
            try:
                if conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone():
                    total += int(
                        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] or 0
                    )
            except Exception:
                _log.debug("_seans_row_count_at: suppressed error", exc_info=True)
        return total
    finally:
        try:
            conn.close()
        except Exception:
            _log.debug("_seans_row_count_at: suppressed error", exc_info=True)


def seans_storage_has_rows(db_file: Path | None = None) -> bool:
    target = (db_file or seans_db_path()).resolve()
    return _seans_row_count_at(target) > 0


def main_storage_has_seans_rows() -> bool:
    return _seans_row_count_at(db_path(DEFAULT_DB_NAME)) > 0


def describe_seans_storage_resolution() -> dict[str, object]:
    """
    Куда реально смотрит приложение и нужен ли repair/recovery.
    """
    main_p = db_path(DEFAULT_DB_NAME)
    seans_p = seans_db_path()
    migrated_mode = use_separate_seans_db()
    main_rows = _seans_row_count_at(main_p)
    seans_rows = _seans_row_count_at(seans_p)
    backups = find_seans_backup_files()

    if not migrated_mode:
        return {
            "migrated_mode": False,
            "active_path": str(main_p),
            "using_main_fallback": True,
            "needs_repair": False,
            "needs_recovery": False,
            "main_rows": main_rows,
            "seans_rows": seans_rows,
            "backup_files": backups,
        }

    using_fallback = seans_rows <= 0 and main_rows > 0
    active = main_p if using_fallback else seans_p
    needs_repair = migrated_mode and seans_rows <= 0 and main_rows > 0
    needs_recovery = migrated_mode and seans_rows <= 0 and main_rows <= 0 and bool(backups)

    return {
        "migrated_mode": True,
        "active_path": str(active),
        "using_main_fallback": using_fallback,
        "needs_repair": needs_repair,
        "needs_recovery": needs_recovery,
        "main_rows": main_rows,
        "seans_rows": seans_rows,
        "backup_files": backups,
    }


def find_seans_backup_files() -> list[str]:
    """Бэкапы seans.sqlite / main.sqlite в DATA_DIR (новые первыми)."""
    found: list[Path] = []
    for pattern in (
        "seans.sqlite.pre-migrate-*.bak",
        "seans.sqlite.bak",
        "main.sqlite.pre-migrate-*.bak",
        "main.sqlite.bak",
    ):
        found.extend(DATA_DIR.glob(pattern))
    uniq: dict[str, Path] = {}
    for p in found:
        if p.is_file():
            uniq[str(p.resolve())] = p.resolve()
    return [str(p) for p in sorted(uniq.values(), key=lambda x: x.stat().st_mtime, reverse=True)]


def resolve_seans_storage_path() -> Path:
    main_p = db_path(DEFAULT_DB_NAME)
    if not use_separate_seans_db():
        return main_p
    seans_p = seans_db_path()
    if seans_storage_has_rows(seans_p):
        return seans_p
    if main_storage_has_seans_rows():
        return main_p
    return seans_p


def connection_path_is_seans_storage(conn: sqlite3.Connection) -> bool:
    from web_portal.lib.db import _conn_schema_key

    key = _conn_schema_key(conn)
    if not key:
        return False
    try:
        return Path(key).resolve() == seans_db_path()
    except Exception:
        return SEANSES_DB_NAME.lower() in key.lower()


def _seans_core_tables_ok(conn: sqlite3.Connection) -> bool:
    try:
        return bool(
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='seanses'"
            ).fetchone()
        )
    except Exception:
        return False


def invalidate_seans_storage_schema_cache(db_file: Path | None = None) -> None:
    from web_portal.lib.db import _SCHEMA_READY_PATHS

    target = (db_file or seans_db_path()).resolve()
    _SCHEMA_READY_PATHS.discard(str(target))


def init_seans_storage(conn: sqlite3.Connection, *, force: bool = False) -> None:
    """Схема только для сеансов и автопоиска (без intercept/unit/sync_outbox)."""
    from web_portal.lib.db import (
        _CONN_INIT_IDS,
        _SCHEMA_READY_PATHS,
        _conn_schema_key,
        init_sync,
    )

    conn_id = id(conn)
    if not force:
        if conn_id in _CONN_INIT_IDS and _seans_core_tables_ok(conn):
            return
        if _conn_schema_key(conn) in _SCHEMA_READY_PATHS and _seans_core_tables_ok(conn):
            _CONN_INIT_IDS.add(conn_id)
            return

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
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS seanses_archive (
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            date_time TEXT NOT NULL,
            frequency TEXT NOT NULL,
            group_ TEXT NOT NULL,
            id TEXT NOT NULL,
            aes_key TEXT,
            client_name TEXT,
            archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT pk_seanses_archive PRIMARY KEY (date_time, frequency, group_, id)
        );
        """
    )
    for col, table in (
        ("client_name", "seanses"),
        ("color_voice", "seanses"),
        ("time_seconds", "seanses"),
        ("color_voice", "seanses_archive"),
        ("time_seconds", "seanses_archive"),
    ):
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT;")
        except sqlite3.OperationalError:
            pass
    try:
        cur.execute("ALTER TABLE seanses ADD COLUMN time_seconds REAL;")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE seanses_archive ADD COLUMN time_seconds REAL;")
    except sqlite3.OperationalError:
        pass

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
        """
        CREATE TABLE IF NOT EXISTS processed_files (
            path TEXT PRIMARY KEY,
            mtime REAL NOT NULL,
            size INTEGER NOT NULL,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS frequency_last_processed (
            frequency TEXT NOT NULL,
            folder_path TEXT NOT NULL,
            last_time TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (frequency, folder_path)
        );
        """
    )

    index_sql = [
        "CREATE INDEX IF NOT EXISTS idx_seanses_created_at ON seanses (created_at);",
        "CREATE INDEX IF NOT EXISTS idx_seanses_created_client ON seanses (created_at, client_name);",
        "CREATE INDEX IF NOT EXISTS idx_seanses_client_freq_group_dt ON seanses(client_name, frequency, group_, date_time);",
        "CREATE INDEX IF NOT EXISTS idx_seanses_archive_date_time on seanses_archive (date_time);",
        "CREATE INDEX IF NOT EXISTS idx_seanses_archive_client on seanses_archive (client_name);",
        "CREATE INDEX IF NOT EXISTS idx_seanses_archive_client_freq_group_dt ON seanses_archive(client_name, frequency, group_, date_time);",
        "CREATE INDEX IF NOT EXISTS idx_seanses_archive_date_time_client ON seanses_archive(date_time, client_name);",
        "CREATE INDEX IF NOT EXISTS idx_seanses_archive_covering ON seanses_archive(date_time, frequency, group_, id);",
        "CREATE INDEX IF NOT EXISTS idx_seanses_archive_covering_client ON seanses_archive(date_time, client_name, frequency, group_, id);",
        "CREATE INDEX IF NOT EXISTS idx_seanses_covering on seanses (date_time, frequency, group_, id);",
        "CREATE INDEX IF NOT EXISTS idx_seanses_covering_client on seanses (date_time, client_name, frequency, group_, id);",
        "CREATE INDEX IF NOT EXISTS idx_seanses_freq_group_dt_desc on seanses (frequency, group_, date_time DESC);",
        "CREATE INDEX IF NOT EXISTS idx_seanses_client_freq_group_dt_desc on seanses (client_name, frequency, group_, date_time DESC);",
        "CREATE INDEX IF NOT EXISTS idx_seanses_daily_client_day ON seanses_daily_agg(client_name, day);",
    ]
    for sql in index_sql:
        cur.execute(sql)

    init_sync(conn)
    conn.commit()
    ready_key = _conn_schema_key(conn)
    if ready_key:
        _SCHEMA_READY_PATHS.add(ready_key)
    _CONN_INIT_IDS.add(conn_id)


def ensure_seans_storage(db_file: Path | None = None) -> None:
    from web_portal.lib.db import _SCHEMA_READY_PATHS, connect

    target = (db_file or resolve_seans_storage_path()).resolve()
    ready_key = str(target)
    if ready_key in _SCHEMA_READY_PATHS:
        probe = connect(target)
        try:
            if _seans_core_tables_ok(probe):
                return
        finally:
            try:
                probe.close()
            except Exception:
                _log.debug("ensure_seans_storage: suppressed error", exc_info=True)
        _SCHEMA_READY_PATHS.discard(ready_key)
    last_error: Exception | None = None
    for attempt in range(4):
        conn = connect(target)
        try:
            init_seans_storage(conn)
            return
        except sqlite3.OperationalError as e:
            last_error = e
            err_text = str(e).lower()
            if ("locked" in err_text or "busy" in err_text) and attempt < 3:
                time.sleep(0.4 * (attempt + 1))
                continue
            raise
        finally:
            try:
                conn.close()
            except Exception:
                _log.debug("ensure_seans_storage: suppressed error", exc_info=True)
    if last_error is not None:
        raise last_error


def connect_seans_storage() -> sqlite3.Connection:
    """Подключение к хранилищу сеансов (seans.sqlite или legacy main.sqlite)."""
    from web_portal.lib.db import connect

    target = resolve_seans_storage_path()
    ensure_seans_storage(target)
    return connect(target)


def mark_seans_db_migrated() -> None:
    seans_migrated_flag_path().write_text(
        f"migrated_at={time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        encoding="utf-8",
    )
