"""Подключение SQLite, schema bootstrap, defer-commit."""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

_log = logging.getLogger("web_portal.db")

# Process-wide connection / schema caches
_sqlite_optimize_once_lock = threading.Lock()

_sqlite_optimize_once_done = False

_SCHEMA_READY_PATHS: set[str] = set()

_CONN_INIT_IDS: set[int] = set()

_CONN_SCHEMA_KEYS_BY_ID: dict[int, str] = {}

_CONN_DEFER_COMMIT_IDS: set[int] = set()

_CONN_DEFER_COMMIT_LOCK = threading.Lock()

def optimize_connection(conn: sqlite3.Connection) -> None:
    try:
        def _env_int(name: str, default: int, *, lo: int, hi: int) -> int:
            try:
                raw = (os.environ.get(name) or "").strip()
                v = int(raw) if raw else default
                return max(lo, min(hi, v))
            except Exception:
                return default

        cache_mb = _env_int("WEB_PORTAL_SQLITE_CACHE_MB", 24, lo=4, hi=512)
        mmap_mb = _env_int("WEB_PORTAL_SQLITE_MMAP_MB", 64, lo=0, hi=2048)

        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=60000;")  # 60 сек ожидания при lock вместо немедленной ошибки
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute(f"PRAGMA cache_size={-cache_mb * 1024};")
        conn.execute("PRAGMA temp_store=MEMORY;")
        if mmap_mb > 0:
            conn.execute(f"PRAGMA mmap_size={mmap_mb * 1024 * 1024};")
        else:
            conn.execute("PRAGMA mmap_size=0;")
        # Иначе GROUP_CONCAT в тяжёлых отчётах может обрезаться (зависит от сборки SQLite).
        conn.execute("PRAGMA group_concat_max_len=2147483647;")
        # PRAGMA optimize только один раз за жизнь процесса: при частом connect() (каждый HTTP-запрос)
        # повторный optimize заметно нагружает диск и воспринимается как «подвисание».
        global _sqlite_optimize_once_done
        with _sqlite_optimize_once_lock:
            if not _sqlite_optimize_once_done:
                conn.execute("PRAGMA analysis_limit=400;")
                conn.execute("PRAGMA optimize;")
                _sqlite_optimize_once_done = True
    except Exception:
        # оптимизации не критичны
        pass


def connect(db_file: Path) -> sqlite3.Connection:
    # timeout=60: ждать снятия блокировки до 60 сек (снижает "database is locked")
    conn = sqlite3.connect(str(db_file), timeout=60)
    conn.row_factory = sqlite3.Row
    _CONN_SCHEMA_KEYS_BY_ID[id(conn)] = str(db_file.resolve())
    optimize_connection(conn)
    return conn


def _conn_schema_key(conn: sqlite3.Connection) -> str:
    return str(_CONN_SCHEMA_KEYS_BY_ID.get(id(conn), "") or "")


def _schema_ready_for_conn(conn: sqlite3.Connection) -> bool:
    sk = _conn_schema_key(conn)
    return bool(sk and sk in _SCHEMA_READY_PATHS)


def set_connection_defer_commit(conn: sqlite3.Connection, enabled: bool) -> None:
    """Отложить commit до конца batch sync (api/sync/push, sync_pull_once)."""
    cid = id(conn)
    with _CONN_DEFER_COMMIT_LOCK:
        if enabled:
            _CONN_DEFER_COMMIT_IDS.add(cid)
        else:
            _CONN_DEFER_COMMIT_IDS.discard(cid)


def connection_defer_commit_active(conn: sqlite3.Connection) -> bool:
    with _CONN_DEFER_COMMIT_LOCK:
        return id(conn) in _CONN_DEFER_COMMIT_IDS


def finish_connection_defer_commit(conn: sqlite3.Connection, *, rollback: bool = False) -> None:
    """Снять defer-флаг; при rollback=True откатить незавершённую транзакцию."""
    active = connection_defer_commit_active(conn)
    set_connection_defer_commit(conn, False)
    if rollback and active:
        try:
            conn.rollback()
        except Exception:
            _log.debug("finish_connection_defer_commit: suppressed error", exc_info=True)


def unregister_connection(conn: sqlite3.Connection | None) -> None:
    """Очистить метаданные id(conn) после conn.close() (Python 3.12 не даёт conn.attr)."""
    if conn is None:
        return
    cid = id(conn)
    _CONN_SCHEMA_KEYS_BY_ID.pop(cid, None)
    with _CONN_DEFER_COMMIT_LOCK:
        _CONN_DEFER_COMMIT_IDS.discard(cid)


def _commit_if_needed(conn: sqlite3.Connection) -> None:
    """Один commit на batch sync вместо fsync на каждое событие."""
    with _CONN_DEFER_COMMIT_LOCK:
        if id(conn) in _CONN_DEFER_COMMIT_IDS:
            return
    conn.commit()


def _conn_has_table(conn: sqlite3.Connection, table: str) -> bool:
    """Дешёвая проверка, что таблица реально есть в ЭТОМ соединении.

    id(conn) переиспользуется CPython после сборки мусора, поэтому записи в
    _CONN_INIT_IDS/_CONN_SCHEMA_KEYS_BY_ID могут быть от уже закрытого чужого
    соединения. Без этой проверки init-функции молча пропускали бы создание
    таблиц для нового соединения (например, свежего :memory:).
    """
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master"
            " WHERE type = 'table' AND name = ? LIMIT 1",
            (table,),
        ).fetchone()
        return row is not None
    except Exception:
        return False


def _conn_has_core_schema(conn: sqlite3.Connection) -> bool:
    from web_portal.lib.db.seans_schema import seanses_position_key_is_current

    return _conn_has_table(conn, "intercept_sessions") and seanses_position_key_is_current(conn)


def init_db(conn: sqlite3.Connection) -> None:
    from web_portal.lib.db.online_search import init_online_search
    from web_portal.lib.db.intercepts import init_intercepts, _migrate_intercepts_sync_fields
    from web_portal.lib.db.seans_schema import ensure_seanses_position_primary_keys
    from web_portal.lib.db.sync import init_sync
    conn_id = id(conn)
    if (
        conn_id in _CONN_INIT_IDS
        and _schema_ready_for_conn(conn)
        and _conn_has_core_schema(conn)
    ):
        return
    # ensure_db() уже прогнал миграции для этого файла; не повторяем CREATE INDEX /
    # init_online_search UPDATE на каждом новом sqlite3.Connection (sync/push/pull).
    if _schema_ready_for_conn(conn) and _conn_has_core_schema(conn):
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
            client_name TEXT NOT NULL DEFAULT '',
            CONSTRAINT pk PRIMARY KEY (date_time, frequency, group_, id, client_name)
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
            client_name TEXT NOT NULL DEFAULT '',
            archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT pk_seanses_archive PRIMARY KEY (date_time, frequency, group_, id, client_name)
        );
        """
    )
    # Миграция: добавляем client_name (позиция/источник) для фильтрации по позициям
    try:
        cur.execute("ALTER TABLE seanses ADD COLUMN client_name TEXT;")
    except sqlite3.OperationalError:
        pass
    # Миграция: Color Voice и время выхода (секунды) для каждого ID корреспондента
    try:
        cur.execute("ALTER TABLE seanses ADD COLUMN color_voice TEXT;")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE seanses ADD COLUMN time_seconds REAL;")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE seanses_archive ADD COLUMN color_voice TEXT;")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE seanses_archive ADD COLUMN time_seconds REAL;")
    except sqlite3.OperationalError:
        pass
    ensure_seanses_position_primary_keys(conn)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS unit (
            frequency TEXT NOT NULL,
            group_ TEXT NOT NULL,
            name TEXT NOT NULL,
            manual INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT pk_unit PRIMARY KEY (frequency, group_, name)
        );
        """
    )
    # миграция старых БД: добавляем updated_at в unit
    try:
        cur.execute("ALTER TABLE unit ADD COLUMN updated_at TIMESTAMP;")
    except sqlite3.OperationalError:
        pass
    # миграция: флаг ручного переименования (чтобы online_search не перезатирал)
    try:
        cur.execute("ALTER TABLE unit ADD COLUMN manual INTEGER NOT NULL DEFAULT 0;")
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
        "CREATE INDEX IF NOT EXISTS idx_seanses_created_at ON seanses (created_at);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_seanses_created_client ON seanses (created_at, client_name);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_seanses_client_freq_group_dt ON seanses(client_name, frequency, group_, date_time);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_seanses_archive_date_time on seanses_archive (date_time);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_seanses_archive_client on seanses_archive (client_name);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_seanses_archive_client_freq_group_dt ON seanses_archive(client_name, frequency, group_, date_time);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_seanses_archive_date_time_client ON seanses_archive(date_time, client_name);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_seanses_archive_covering ON seanses_archive(date_time, frequency, group_, id);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_seanses_archive_covering_client ON seanses_archive(date_time, client_name, frequency, group_, id);"
    )
    # Составной индекс для оптимизации запросов с фильтром по дате и клиенту
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_date_time_client on seanses (date_time, client_name);"
    )
    # Покрывающие индексы для оптимизации DISTINCT запросов - включают все нужные колонки
    # Это позволяет SQLite использовать только индекс без обращения к таблице (covering index)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_seanses_covering on seanses (date_time, frequency, group_, id);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_seanses_covering_client on seanses (date_time, client_name, frequency, group_, id);"
    )
    # Индекс под горячий шаблон анализа: фильтр по (частота, группа) и диапазон date_time.
    # Ведущие колонки — equality-фильтры, затем range по date_time (DESC для свежих записей наверху).
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_seanses_freq_group_dt_desc on seanses (frequency, group_, date_time DESC);"
    )
    # То же с client_name — когда включен фильтр по позиции.
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_seanses_client_freq_group_dt_desc on seanses (client_name, frequency, group_, date_time DESC);"
    )
    # Состояние инкрементального импорта result0.txt (для автопоиска/мониторинга).
    # Храним mtime/size, чтобы не перечитывать неизменившиеся файлы.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS seans_import_files (
            position_name TEXT NOT NULL DEFAULT '',
            file_path TEXT NOT NULL,
            mtime_ns INTEGER NOT NULL DEFAULT 0,
            size INTEGER NOT NULL DEFAULT 0,
            sig INTEGER NOT NULL DEFAULT 0,
            last_import_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (position_name, file_path)
        );
        """
    )
    # миграция старых БД: добавляем sig
    try:
        cur.execute(
            "ALTER TABLE seans_import_files ADD COLUMN sig INTEGER NOT NULL DEFAULT 0;"
        )
    except sqlite3.OperationalError:
        pass
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_seans_import_files_pos ON seans_import_files(position_name);"
    )
    # Таблица для отслеживания обработанных файлов (аналогично основному проекту)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_files (
            path TEXT PRIMARY KEY,
            mtime REAL,
            size INTEGER,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    # Таблица для хранения последнего времени обработки для каждой частоты (для автопоиска)
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
    # Таблица для избранного пользователя (сеансы)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions_favorites (
            user_id INTEGER NOT NULL,
            frequency TEXT NOT NULL,
            group_ TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, frequency, group_)
        );
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_favorites_user ON sessions_favorites (user_id);"
    )

    # Таблица проверки AES-ключей (импорт из Excel)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis_keys (
            frequency TEXT NOT NULL,
            frequency_norm TEXT NOT NULL,
            group_ TEXT NOT NULL,
            aes_id TEXT NOT NULL,
            aes_key TEXT NOT NULL,
            unit_name TEXT,
            added_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (frequency, group_, aes_id, aes_key)
        );
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_analysis_keys_pair ON analysis_keys (frequency_norm, group_, aes_id);"
    )

    # Общие метки/папки карты: синхронизация между компьютерами (общая БД)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS map_shared_objects (
            position_name TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL,
            obj_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (position_name, kind, obj_id)
        );
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_map_shared_pos ON map_shared_objects (position_name);"
    )
    conn.commit()
    init_online_search(conn)
    init_intercepts(conn)
    # Вызываем миграции для intercepts после создания таблиц
    _migrate_intercepts_sync_fields(conn)
    init_sync(conn)
    from web_portal.lib.aviation_db import init_aviation

    init_aviation(conn)
    try:
        from web_portal.lib.ai_vector_recall import init_ai_vector_schema

        init_ai_vector_schema(conn)
    except Exception:
        _log.debug("init_db: suppressed error", exc_info=True)
    conn.commit()
    _CONN_INIT_IDS.add(conn_id)


def ensure_db(db_file: Path) -> None:
    """Создаёт файл БД при необходимости и применяет схему. При блокировке повторяет до 4 раз."""
    db_file.parent.mkdir(parents=True, exist_ok=True)
    ready_key = str(db_file.resolve())
    if ready_key in _SCHEMA_READY_PATHS:
        return
    last_error = None
    for attempt in range(4):
        conn = connect(db_file)
        try:
            init_db(conn)
            _SCHEMA_READY_PATHS.add(ready_key)
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
                _log.debug("ensure_db: suppressed error", exc_info=True)
    if last_error is not None:
        raise last_error


def list_db_files(data_dir: Path) -> list[str]:
    if not data_dir.exists():
        return []
    dbs: list[str] = []
    for p in sorted(data_dir.glob("*.sqlite")) + sorted(data_dir.glob("*.db")):
        if p.is_file():
            dbs.append(p.name)
    return dbs


__all__ = [
    "optimize_connection",
    "connect",
    "set_connection_defer_commit",
    "connection_defer_commit_active",
    "finish_connection_defer_commit",
    "unregister_connection",
    "_commit_if_needed",
    "init_db",
    "ensure_db",
    "list_db_files",
    "_SCHEMA_READY_PATHS",
]
