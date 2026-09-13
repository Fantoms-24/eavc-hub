"""Статус и перенос seans.sqlite (API admin + CLI)."""

from __future__ import annotations

import shutil
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from web_portal.config import (
    DATA_DIR,
    DEFAULT_DB_NAME,
    db_path,
    detect_data_dir_mismatch_warning,
    hub_config_path,
)
from web_portal.lib.db import connect, ensure_db, get_sync_meta
from web_portal.lib.seans_db import (
    describe_seans_storage_resolution,
    find_seans_backup_files,
    init_seans_storage,
    invalidate_seans_storage_schema_cache,
    mark_seans_db_migrated,
    seans_db_path,
    seans_migrated_flag_path,
    use_separate_seans_db,
)
import logging

_log = logging.getLogger("web_portal.lib.seans_migrate")

TABLES: tuple[str, ...] = (
    "seanses",
    "seanses_archive",
    "seanses_daily_agg",
    "processed_files",
    "frequency_last_processed",
)

SYNC_META_KEYS: tuple[str, ...] = ("seanses_last_rowid",)

_MIGRATE_LOCK = threading.Lock()
_MIGRATE_PROGRESS: dict[str, Any] = {
    "running": False,
    "done": True,
    "phase": "idle",
    "message": "",
    "error": "",
    "table": "",
    "rows_copied": 0,
    "counts_main": {},
    "counts_seans": {},
}


def _file_size_mb(path: Path) -> float:
    try:
        if path.is_file():
            return round(path.stat().st_size / (1024 * 1024), 1)
    except Exception:
        _log.debug("_file_size_mb: suppressed error", exc_info=True)
    return 0.0


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone():
            return 0
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] or 0)
    except Exception:
        return 0


def _counts_for_path(db_file: Path) -> dict[str, int]:
    if not db_file.is_file():
        return {t: 0 for t in TABLES}
    conn = connect(db_file)
    try:
        return {t: _table_count(conn, t) for t in TABLES}
    finally:
        conn.close()


def get_seans_db_migration_progress() -> dict[str, Any]:
    with _MIGRATE_LOCK:
        return dict(_MIGRATE_PROGRESS)


def _set_progress(**kwargs: object) -> None:
    with _MIGRATE_LOCK:
        _MIGRATE_PROGRESS.update(kwargs)


def get_seans_db_migration_status() -> dict[str, Any]:
    """Сводка для admin UI и проверки при старте."""
    main_p = db_path(DEFAULT_DB_NAME)
    seans_p = seans_db_path()
    migrated = use_separate_seans_db()
    resolution = describe_seans_storage_resolution()
    counts_main = _counts_for_path(main_p)
    counts_seans = _counts_for_path(seans_p) if seans_p.is_file() else {
        t: 0 for t in TABLES
    }
    main_size = _file_size_mb(main_p)
    seans_size = _file_size_mb(seans_p)
    main_seanses = int(counts_main.get("seanses") or 0)
    seans_seanses = int(counts_seans.get("seanses") or 0)
    recommend = (not migrated) and (
        main_seanses >= 5000 or main_size >= 50.0 or counts_main.get("processed_files", 0) > 0
    )
    needs_purge_main = migrated and main_seanses > 1000 and seans_seanses > 0
    needs_repair = bool(resolution.get("needs_repair"))
    needs_recovery = bool(resolution.get("needs_recovery"))
    progress = get_seans_db_migration_progress()
    data_dir_warning = detect_data_dir_mismatch_warning()
    return {
        "ok": True,
        "migrated": migrated,
        "recommend_migrate": recommend,
        "needs_purge_main": needs_purge_main,
        "needs_repair": needs_repair,
        "needs_recovery": needs_recovery,
        "using_main_fallback": bool(resolution.get("using_main_fallback")),
        "active_storage_path": resolution.get("active_path"),
        "backup_files": resolution.get("backup_files") or find_seans_backup_files(),
        "data_dir": str(DATA_DIR),
        "hub_config_path": str(hub_config_path()),
        "data_dir_warning": data_dir_warning,
        "main_db_path": str(main_p),
        "seans_db_path": str(seans_p),
        "main_size_mb": main_size,
        "seans_db_size_mb": seans_size,
        "counts_main": counts_main,
        "counts_seans": counts_seans,
        "flag_path": str(seans_migrated_flag_path()),
        "migration": progress,
    }


def _copy_table_batch(
    main: sqlite3.Connection,
    seans: sqlite3.Connection,
    table: str,
    *,
    batch: int = 5000,
    on_progress: Callable[[str, int], None] | None = None,
) -> int:
    if not main.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone():
        return 0
    cols = [r[1] for r in main.execute(f"PRAGMA table_info({table})").fetchall()]
    if not cols:
        return 0
    col_list = ", ".join(cols)
    placeholders = ", ".join(["?"] * len(cols))
    total = 0
    offset = 0
    while True:
        rows = main.execute(
            f"SELECT {col_list} FROM {table} LIMIT ? OFFSET ?",
            (batch, offset),
        ).fetchall()
        if not rows:
            break
        seans.executemany(
            f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})",
            [tuple(r) for r in rows],
        )
        seans.commit()
        total += len(rows)
        offset += batch
        if on_progress is not None:
            on_progress(table, total)
    return total


def _purge_seans_tables_from_main(main: sqlite3.Connection) -> dict[str, int]:
    """Удаляет таблицы сеансов из main.sqlite после успешного переноса в seans.sqlite."""
    removed: dict[str, int] = {}
    for table in TABLES:
        if not main.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone():
            continue
        n = int(main.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] or 0)
        if n > 0:
            main.execute(f"DELETE FROM {table}")
            removed[table] = n
    for key in SYNC_META_KEYS:
        main.execute("DELETE FROM sync_meta WHERE key=?", (key,))
    main.commit()
    return removed


def purge_seans_from_main_database() -> dict[str, Any]:
    """Очистить дубликаты сеансов из main.sqlite (после миграции в seans.sqlite)."""
    if not use_separate_seans_db():
        return {
            "ok": False,
            "error": "Сначала выполните миграцию в seans.sqlite",
        }
    main_p = db_path(DEFAULT_DB_NAME)
    if not main_p.is_file():
        return {"ok": False, "error": f"Нет файла {main_p.name}"}
    seans_p = seans_db_path()
    counts_seans = _counts_for_path(seans_p) if seans_p.is_file() else {}
    if int(counts_seans.get("seanses") or 0) <= 0:
        return {
            "ok": False,
            "error": "seans.sqlite пуст — сначала перенесите сеансы",
        }
    size_before = _file_size_mb(main_p)
    main = connect(main_p)
    try:
        removed = _purge_seans_tables_from_main(main)
    finally:
        main.close()
    size_after = _file_size_mb(main_p)
    return {
        "ok": True,
        "removed": removed,
        "size_mb_before": size_before,
        "size_mb_after": size_after,
        "message": (
            f"Из main.sqlite удалено seanses={removed.get('seanses', 0)}. "
            f"Размер: {size_before} MB → {size_after} MB. "
            "Нажмите VACUUM main для уменьшения файла на диске."
        ),
    }


def run_seans_db_migration(*, dry_run: bool = False) -> dict[str, Any]:
    """
    Перенос таблиц сеансов main.sqlite → seans.sqlite.
    Возвращает {ok, error?, counts_main, counts_seans, ...}.
    """
    main_p = db_path(DEFAULT_DB_NAME)
    if not main_p.is_file():
        return {"ok": False, "error": f"Нет файла {main_p.name}"}

    migrated = use_separate_seans_db()
    counts_main_before = _counts_for_path(main_p)
    if migrated and not dry_run and int(counts_main_before.get("seanses") or 0) <= 0:
        return {
            "ok": True,
            "already_migrated": True,
            "message": "Уже используется seans.sqlite, main.sqlite очищена",
        }

    if migrated and not dry_run:
        _set_progress(
            running=True,
            done=False,
            phase="purge_main",
            message="Миграция уже выполнена — очистка дубликатов в main.sqlite…",
        )
        main = connect(main_p)
        try:
            removed = _purge_seans_tables_from_main(main)
        finally:
            main.close()
        _set_progress(
            running=False,
            done=True,
            phase="done",
            message=f"Очищено из main: {removed}",
        )
        return {
            "ok": True,
            "purged_main": True,
            "removed": removed,
            "message": "Дубликаты сеансов удалены из main.sqlite. Выполните VACUUM main.",
        }

    seans_p = seans_db_path()
    _set_progress(
        running=True,
        done=False,
        phase="prepare",
        message="Подготовка…",
        error="",
        table="",
        rows_copied=0,
    )

    main = connect(main_p)
    try:
        counts_main = {t: _table_count(main, t) for t in TABLES}
        _set_progress(counts_main=counts_main, message="Подсчёт строк в main.sqlite…")
        if dry_run:
            _set_progress(
                running=False,
                done=True,
                phase="dry_run",
                message="Пробный прогон завершён (без записи)",
            )
            return {
                "ok": True,
                "dry_run": True,
                "counts_main": counts_main,
                "main_size_mb": _file_size_mb(main_p),
            }

        if seans_p.exists():
            bak = seans_p.with_suffix(f".sqlite.pre-migrate-{int(time.time())}.bak")
            try:
                shutil.copy2(seans_p, bak)
                _set_progress(message=f"Бэкап seans.sqlite: {bak.name}")
            except Exception:
                _log.debug("run_seans_db_migration: suppressed error", exc_info=True)

        ensure_db(main_p)
        invalidate_seans_storage_schema_cache(seans_p)

        seans = connect(seans_p)
        try:
            init_seans_storage(seans, force=True)
            copied: dict[str, int] = {}

            def _prog(table: str, n: int) -> None:
                _set_progress(
                    phase="copy",
                    table=table,
                    rows_copied=n,
                    message=f"Копирование {table}: {n} строк…",
                )

            for table in TABLES:
                _set_progress(phase="copy", table=table, message=f"Копирование {table}…")
                copied[table] = _copy_table_batch(
                    main, seans, table, on_progress=_prog
                )

            for key in SYNC_META_KEYS:
                val = get_sync_meta(main, key)
                if val:
                    seans.execute(
                        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)",
                        (key, val),
                    )
            seans.commit()

            counts_seans = {t: _table_count(seans, t) for t in TABLES}
            for t in TABLES:
                if counts_main.get(t, 0) != counts_seans.get(t, 0):
                    err = (
                        f"Расхождение {t}: main={counts_main.get(t)} "
                        f"seans={counts_seans.get(t)}"
                    )
                    _set_progress(
                        running=False,
                        done=True,
                        phase="error",
                        error=err,
                        message=err,
                    )
                    return {"ok": False, "error": err, "counts_main": counts_main}

            chk = seans.execute("PRAGMA integrity_check").fetchone()[0]
            if str(chk).lower() != "ok":
                err = f"integrity_check: {chk}"
                _set_progress(
                    running=False, done=True, phase="error", error=err, message=err
                )
                return {"ok": False, "error": err}
        finally:
            seans.close()

        _set_progress(phase="purge_main", message="Очистка сеансов из main.sqlite…")
        removed_main = _purge_seans_tables_from_main(main)
        counts_main_after = {t: _table_count(main, t) for t in TABLES}

        mark_seans_db_migrated()
        _set_progress(
            running=False,
            done=True,
            phase="done",
            error="",
            message=(
                "Миграция завершена. Сеансы в seans.sqlite, main.sqlite очищена. "
                "Выполните VACUUM main для уменьшения файла."
            ),
            counts_seans=counts_seans,
        )
        return {
            "ok": True,
            "counts_main": counts_main_after,
            "counts_main_before": counts_main,
            "counts_seans": counts_seans,
            "removed_from_main": removed_main,
            "flag_path": str(seans_migrated_flag_path()),
            "message": "Сеансы перенесены в seans.sqlite, main очищена",
        }
    except Exception as exc:
        err = str(exc)
        _set_progress(
            running=False,
            done=True,
            phase="error",
            error=err,
            message=f"Ошибка: {err}",
        )
        return {"ok": False, "error": err}
    finally:
        main.close()


def start_seans_db_migration_background(*, dry_run: bool = False) -> dict[str, Any]:
    with _MIGRATE_LOCK:
        if _MIGRATE_PROGRESS.get("running"):
            return {"ok": False, "error": "Миграция уже выполняется"}
        if use_separate_seans_db() and not dry_run:
            left = int(
                (_counts_for_path(db_path(DEFAULT_DB_NAME)) or {}).get("seanses") or 0
            )
            if left <= 0:
                return {"ok": True, "already_migrated": True}

    def _worker() -> None:
        run_seans_db_migration(dry_run=dry_run)

    threading.Thread(target=_worker, daemon=True, name="seans-db-migrate").start()
    return {"ok": True, "started": True, "dry_run": dry_run}


def log_startup_seans_db_hint(logger) -> None:
    """WARNING в лог при старте, если сеансы ещё в main.sqlite."""
    try:
        st = get_seans_db_migration_status()
        logger.info("Seans DB: DATA_DIR=%s", st.get("data_dir"))
        warn = st.get("data_dir_warning")
        if warn:
            logger.warning("Seans DB: %s", warn)
        if st.get("migrated"):
            main_left = int((st.get("counts_main") or {}).get("seanses") or 0)
            if main_left > 1000:
                logger.warning(
                    "Seans DB: seans.sqlite активна, но в main.sqlite осталось seanses=%s "
                    "(%s MB). Админ → Очистить seans из main → VACUUM.",
                    main_left,
                    st.get("main_size_mb"),
                )
            else:
                logger.info(
                    "Seans DB: отдельный файл seans.sqlite (%s MB, seanses=%s)",
                    st.get("seans_db_size_mb"),
                    (st.get("counts_seans") or {}).get("seanses"),
                )
            return
        if st.get("recommend_migrate"):
            logger.warning(
                "Seans DB: main.sqlite тяжёлая (%s MB, seanses=%s). "
                "Рекомендуется миграция: Админ → Настройки → «Отдельная БД сеансов».",
                st.get("main_size_mb"),
                (st.get("counts_main") or {}).get("seanses"),
            )
    except Exception as exc:
        logger.debug("Seans DB startup hint skipped: %s", exc)


def vacuum_main_database() -> dict[str, Any]:
    """VACUUM main.sqlite (после переноса seans — уменьшает файл)."""
    if not use_separate_seans_db():
        return {
            "ok": False,
            "error": "Сначала выполните миграцию в seans.sqlite",
        }
    main_p = db_path(DEFAULT_DB_NAME)
    if not main_p.is_file():
        return {"ok": False, "error": f"Нет файла {main_p.name}"}
    size_before = _file_size_mb(main_p)
    conn = connect(main_p)
    try:
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()
    size_after = _file_size_mb(main_p)
    return {
        "ok": True,
        "path": str(main_p),
        "size_mb_before": size_before,
        "size_mb_after": size_after,
        "message": f"VACUUM: {size_before} MB → {size_after} MB",
    }
