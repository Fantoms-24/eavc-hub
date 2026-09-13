from __future__ import annotations

import logging

from dataclasses import dataclass
from pathlib import Path
import os
import sqlite3
from typing import Any
import json

from werkzeug.security import check_password_hash, generate_password_hash

from web_portal.lib.db import optimize_connection

_log = logging.getLogger("web_portal.auth_db")


ROLE_ADMIN = "admin"
ROLE_MODERATOR = "moderator"
ROLE_SEARCH_EDITOR = "search_editor"
ROLE_VIEWER = "viewer"
ROLE_AUDIO_VIEWER = "audio_viewer"

# Роли внутри вкладки "Перехваты" (на уровне позиции)
POS_ROLE_OPERATOR = "operator"
POS_ROLE_CHIEF = "chief"  # начальник аппаратной


ROLE_PERMS: dict[str, set[str]] = {
    ROLE_ADMIN: {"view_sessions", "import_folder", "edit_search", "manage_users"},
    ROLE_MODERATOR: {"view_sessions", "import_folder"},
    ROLE_SEARCH_EDITOR: {"view_sessions", "edit_search"},
    ROLE_VIEWER: {"view_sessions"},
    ROLE_AUDIO_VIEWER: {"view_sessions"},
}

# Подписи ролей и прав для админ-панели (расширение ролей)
ROLE_LABELS: dict[str, str] = {
    ROLE_ADMIN: "Администратор",
    ROLE_MODERATOR: "Модератор",
    ROLE_SEARCH_EDITOR: "Редактор поиска",
    ROLE_VIEWER: "Наблюдатель",
    ROLE_AUDIO_VIEWER: "Аудиоперехваты (только просмотр)",
}

PERM_LABELS: dict[str, str] = {
    "view_sessions": "Просмотр сеансов",
    "import_folder": "Импорт папок",
    "edit_search": "Редактирование поиска",
    "manage_users": "Управление пользователями",
}

# Категории вкладок: доступ к разделам (галочками в кастомных ролях)
TAB_INTERCEPTS = "tab_intercepts"
TAB_AUDIO_INTERCEPTS = "tab_audio_intercepts"
TAB_AVIATION = "tab_aviation"
TAB_SESSIONS = "tab_sessions"
TAB_ANALYSIS = "tab_analysis"
TAB_SEARCH_ONLINE = "tab_search_online"
TAB_INSTRUCTIONS = "tab_instructions"
TAB_ADMIN = "tab_admin"

TAB_CATEGORIES: list[tuple[str, str]] = [
    (TAB_INTERCEPTS, "Перехваты"),
    (TAB_AUDIO_INTERCEPTS, "Аудиоперехваты"),
    (TAB_AVIATION, "Авиация"),
    (TAB_SESSIONS, "Сеансы"),
    (TAB_ANALYSIS, "Анализ"),
    (TAB_SEARCH_ONLINE, "Поиск онлайн"),
    (TAB_INSTRUCTIONS, "Инструкции"),
    (TAB_ADMIN, "Админ-панель"),
]

# Добавляем подписи вкладок в PERM_LABELS
for _id, _label in TAB_CATEGORIES:
    PERM_LABELS[_id] = _label

# Встроенные роли: добавляем доступ к вкладкам
_ALL_TABS = {t[0] for t in TAB_CATEGORIES}
_VIEWER_TABS = _ALL_TABS - {TAB_ADMIN}
_EDITOR_TABS = _ALL_TABS - {TAB_ADMIN}

ROLE_PERMS[ROLE_ADMIN] = ROLE_PERMS[ROLE_ADMIN] | _ALL_TABS
ROLE_PERMS[ROLE_MODERATOR] = ROLE_PERMS[ROLE_MODERATOR] | _ALL_TABS
ROLE_PERMS[ROLE_SEARCH_EDITOR] = ROLE_PERMS[ROLE_SEARCH_EDITOR] | _EDITOR_TABS
ROLE_PERMS[ROLE_VIEWER] = ROLE_PERMS[ROLE_VIEWER] | _VIEWER_TABS
ROLE_PERMS[ROLE_AUDIO_VIEWER] = ROLE_PERMS[ROLE_AUDIO_VIEWER] | {TAB_AUDIO_INTERCEPTS}


@dataclass(frozen=True)
class UserRecord:
    id: int
    username: str
    callsign: str
    role: str
    permissions: frozenset[str] | None = (
        None  # разрешено при логине (встроенная или кастомная роль)
    )

    def has_perm(self, perm: str) -> bool:
        if self.permissions is not None:
            return perm in self.permissions
        return perm in ROLE_PERMS.get(self.role, set())


def connect_portal(db_file: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_file), timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON;")
    except Exception:
        _log.debug("connect_portal: suppressed error", exc_info=True)
    optimize_connection(conn)
    return conn


def _portal_table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {str(r["name"] or "") for r in (rows or [])}
    except Exception:
        return set()


def _heal_portal_positions_and_user_links(conn: sqlite3.Connection) -> None:
    """
    Восстанавливает строки в `positions` по именам из:
    - position_settings (ключи позиций уже использовались в портале);
    - main.sqlite: DISTINCT client_name из seanses (позиции из сеансов).

    Если таблица user_positions полностью пуста, а пользователи и позиции есть —
    связывает каждого не-админа со всеми позициями (operator), чтобы снова появились
    доступы после сбоя/миграции. Не трогает частично заполненную user_positions.
    """
    if (os.environ.get("WEB_PORTAL_SKIP_PORTAL_HEAL") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return
    cur = conn.cursor()
    names: set[str] = set()
    try:
        rows = cur.execute(
            """
            SELECT DISTINCT TRIM(position_name) AS n
            FROM position_settings
            WHERE TRIM(COALESCE(position_name, '')) != ''
            """
        ).fetchall()
        for r in rows or []:
            n = str(r["n"] or "").strip()
            if n:
                names.add(n)
    except sqlite3.OperationalError:
        pass
    try:
        from web_portal.config import DEFAULT_DB_NAME, db_path
        from web_portal.lib.db import connect as _main_connect
        from web_portal.lib.db import ensure_db as _main_ensure

        mp = db_path(DEFAULT_DB_NAME)
        _main_ensure(mp)
        mconn = _main_connect(mp)
        try:
            if mconn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='seanses'"
            ).fetchone():
                mr = mconn.execute(
                    """
                    SELECT DISTINCT TRIM(client_name) AS n
                    FROM seanses
                    WHERE TRIM(COALESCE(client_name, '')) != ''
                    """
                ).fetchall()
                for row in mr or []:
                    n = str(row["n"] or "").strip()
                    if n:
                        names.add(n)
        finally:
            mconn.close()
    except Exception:
        _log.debug("_heal_portal_positions_and_user_links: suppressed error", exc_info=True)

    for n in sorted(names):
        try:
            cur.execute("INSERT OR IGNORE INTO positions (name) VALUES (?)", (n,))
        except sqlite3.OperationalError:
            pass
    try:
        conn.commit()
    except Exception:
        _log.debug("_heal_portal_positions_and_user_links: suppressed error", exc_info=True)

    n_links = int(
        cur.execute("SELECT COUNT(*) FROM user_positions").fetchone()[0] or 0
    )
    n_pos = int(cur.execute("SELECT COUNT(*) FROM positions").fetchone()[0] or 0)
    n_users = int(cur.execute("SELECT COUNT(*) FROM users").fetchone()[0] or 0)
    if n_links > 0 or n_pos == 0 or n_users == 0:
        return

    cols = _portal_table_columns(conn, "user_positions")
    has_role = "role" in cols
    has_updated_at = "updated_at" in cols
    urows = cur.execute(
        "SELECT id, role FROM users WHERE LOWER(COALESCE(role,'')) != ?",
        (ROLE_ADMIN,),
    ).fetchall()
    prows = cur.execute("SELECT id, name FROM positions").fetchall()
    for ur in urows or []:
        uid = int(ur["id"])
        for pr in prows or []:
            pid = int(pr["id"])
            try:
                if has_role and has_updated_at:
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO user_positions (user_id, position_id, role, updated_at)
                        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                        """,
                        (uid, pid, POS_ROLE_OPERATOR),
                    )
                elif has_role:
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO user_positions (user_id, position_id, role)
                        VALUES (?, ?, ?)
                        """,
                        (uid, pid, POS_ROLE_OPERATOR),
                    )
                elif has_updated_at:
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO user_positions (user_id, position_id, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                        """,
                        (uid, pid),
                    )
                else:
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO user_positions (user_id, position_id)
                        VALUES (?, ?)
                        """,
                        (uid, pid),
                    )
            except sqlite3.OperationalError:
                pass
    try:
        conn.commit()
    except Exception:
        _log.debug("_heal_portal_positions_and_user_links: suppressed error", exc_info=True)


def _backfill_portal_updated_at(conn: sqlite3.Connection) -> None:
    """
    После ADD COLUMN updated_at старые строки могли остаться с NULL/пустым updated_at.
    Тогда list_users_since(..., since_ts='1970-...') их не отдаёт (строковое сравнение с '').
    """
    try:
        conn.execute(
            """
            UPDATE users
            SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)
            WHERE updated_at IS NULL OR TRIM(COALESCE(updated_at, '')) = ''
            """
        )
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(
            """
            UPDATE positions
            SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)
            WHERE updated_at IS NULL OR TRIM(COALESCE(updated_at, '')) = ''
            """
        )
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(
            """
            UPDATE user_positions
            SET updated_at = CURRENT_TIMESTAMP
            WHERE updated_at IS NULL OR TRIM(COALESCE(updated_at, '')) = ''
            """
        )
    except sqlite3.OperationalError:
        pass


def _ensure_portal_columns(conn: sqlite3.Connection) -> None:
    """
    Добавляет колонки, если их нет (PRAGMA), на случай старых БД или сбоя ALTER при блокировке.
    """
    cur = conn.cursor()

    def _add(table: str, col: str, ddl: str) -> None:
        try:
            cols = _portal_table_columns(conn, table)
        except Exception:
            cols = set()
        if col in cols:
            return
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError:
            pass

    # SQLite ALTER не принимает DEFAULT CURRENT_TIMESTAMP (non-constant default).
    _add("users", "updated_at", "TEXT")
    _add("users", "intercept_view_mode", "TEXT NOT NULL DEFAULT 'pretty'")
    _add("users", "intercept_unit_order", "TEXT NOT NULL DEFAULT '[]'")
    _add("users", "intercept_catalog_prefs", "TEXT NOT NULL DEFAULT '{}'")
    _add("positions", "updated_at", "TEXT")
    _add("user_positions", "role", "TEXT NOT NULL DEFAULT 'operator'")
    _add("user_positions", "updated_at", "TEXT")
    try:
        _backfill_portal_updated_at(conn)
        conn.commit()
    except Exception:
        _log.debug("_ensure_portal_columns: suppressed error", exc_info=True)


def init_portal_db(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            callsign TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'viewer',
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            intercept_view_mode TEXT NOT NULL DEFAULT 'pretty'
        );
        """
    )
    # миграция: users.updated_at
    try:
        cur.execute(
            "ALTER TABLE users ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"
        )
    except sqlite3.OperationalError:
        pass
    # миграция: users.intercept_view_mode
    try:
        cur.execute(
            "ALTER TABLE users ADD COLUMN intercept_view_mode TEXT NOT NULL DEFAULT 'pretty';"
        )
    except sqlite3.OperationalError:
        pass
    # миграция: users.intercept_unit_order
    try:
        cur.execute(
            "ALTER TABLE users ADD COLUMN intercept_unit_order TEXT NOT NULL DEFAULT '[]';"
        )
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute(
            "ALTER TABLE users ADD COLUMN intercept_catalog_prefs TEXT NOT NULL DEFAULT '{}';"
        )
    except sqlite3.OperationalError:
        pass
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS custom_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            permissions TEXT NOT NULL DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    # миграция: positions.updated_at
    try:
        cur.execute(
            "ALTER TABLE positions ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"
        )
    except sqlite3.OperationalError:
        pass
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_positions (
            user_id INTEGER NOT NULL,
            position_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'operator',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, position_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (position_id) REFERENCES positions(id) ON DELETE CASCADE
        );
        """
    )
    # миграция старых БД: добавляем role, если таблица была создана ранее
    try:
        cur.execute(
            "ALTER TABLE user_positions ADD COLUMN role TEXT NOT NULL DEFAULT 'operator';"
        )
    except sqlite3.OperationalError:
        pass
    # миграция: user_positions.updated_at
    try:
        cur.execute(
            "ALTER TABLE user_positions ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"
        )
    except sqlite3.OperationalError:
        pass

    # избранное пользователя (например, "Сеансы": выбранные подразделения/период)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_favorites (
            user_id INTEGER NOT NULL,
            scope TEXT NOT NULL,
            position_name TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'main',
            payload TEXT NOT NULL DEFAULT '{}',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, scope, position_name, source),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    # Настройки на уровне ПОЗИЦИИ (общие для всех пользователей этой позиции)
    # Например: IP/URL сервера для отправки TXT из вкладки "Перехваты".
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS position_settings (
            position_name TEXT NOT NULL DEFAULT '',
            key TEXT NOT NULL,
            value TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (position_name, key)
        );
        """
    )
    # Нацеливания (targeting/notifications) - сообщения от центрального сервера к Hub'ам
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS targeting (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL DEFAULT '',
            target_type TEXT NOT NULL CHECK (target_type IN ('all', 'position', 'users')),
            target_position TEXT NOT NULL DEFAULT '',
            target_user_ids TEXT NOT NULL DEFAULT '[]',
            created_by TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            is_active INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_targeting_active ON targeting(is_active, created_at DESC);
        """
    )
    # Отслеживание прочитанных нацеливаний пользователями
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS targeting_reads (
            targeting_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            read_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (targeting_id, user_id),
            FOREIGN KEY (targeting_id) REFERENCES targeting(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    # Отслеживание активности Hub'ов (для админ-панели)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS hub_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hub_id TEXT NOT NULL UNIQUE,
            hub_name TEXT NOT NULL DEFAULT '',
            position_name TEXT NOT NULL DEFAULT '',
            ip_address TEXT NOT NULL DEFAULT '',
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_push TIMESTAMP,
            last_pull TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hub_activity_last_seen ON hub_activity(last_seen DESC);
        """
    )
    # Чат: группы/каналы
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            is_global INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        );
        """
    )
    # Чат: файлы (раньше chat_messages: FK на chat_files)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid TEXT NOT NULL UNIQUE,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            file_size INTEGER NOT NULL DEFAULT 0,
            mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
            uploaded_by INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    # Чат: сообщения
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid TEXT NOT NULL UNIQUE,
            group_id INTEGER,
            user_id INTEGER NOT NULL,
            message_text TEXT NOT NULL DEFAULT '',
            file_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (group_id) REFERENCES chat_groups(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (file_id) REFERENCES chat_files(id) ON DELETE SET NULL
        );
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_messages_group_created ON chat_messages(group_id, created_at DESC);
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_messages_user ON chat_messages(user_id, created_at DESC);
        """
    )
    # Прочитанные сообщения (для синхронизации)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_reads (
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            read_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (message_id, user_id),
            FOREIGN KEY (message_id) REFERENCES chat_messages(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    # Доступ к чатам по ролям (какой канал кому виден)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_channel_roles (
            channel_name TEXT NOT NULL,
            role TEXT NOT NULL,
            PRIMARY KEY (channel_name, role)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_agent_memory (
            user_id INTEGER NOT NULL,
            scope TEXT NOT NULL DEFAULT 'ai_assistant',
            memory_json TEXT NOT NULL DEFAULT '{}',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, scope),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_agent_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message_id INTEGER,
            goal TEXT NOT NULL DEFAULT '',
            tool TEXT NOT NULL DEFAULT '',
            risk TEXT NOT NULL DEFAULT '',
            args_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            confirmed INTEGER NOT NULL DEFAULT 0,
            changed INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (message_id) REFERENCES chat_messages(id) ON DELETE SET NULL
        );
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ai_agent_actions_user_created
        ON ai_agent_actions(user_id, created_at DESC);
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_chat_message_feedback (
            user_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            rating INTEGER NOT NULL DEFAULT 0,
            comment TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, message_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (message_id) REFERENCES chat_messages(id) ON DELETE CASCADE
        );
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ai_chat_feedback_message
        ON ai_chat_message_feedback(message_id);
        """
    )
    _ensure_portal_columns(conn)
    # Сначала восстанавливаем имена позиций и связи, затем заполняем пустые updated_at
    _heal_portal_positions_and_user_links(conn)
    _backfill_portal_updated_at(conn)
    conn.commit()


def get_user_favorite(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    scope: str,
    position_name: str,
    source: str,
) -> dict[str, Any] | None:
    init_portal_db(conn)
    uid = int(user_id)
    scope = str(scope or "").strip()
    pos = str(position_name or "").strip()
    source = "legacy" if str(source or "").strip().lower() == "legacy" else "main"
    r = conn.execute(
        """
        SELECT payload, updated_at
        FROM user_favorites
        WHERE user_id=? AND scope=? AND position_name=? AND source=?
        """,
        (uid, scope, pos, source),
    ).fetchone()
    if not r:
        return None
    try:
        payload = json.loads(str(r["payload"] or "{}"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload["_updated_at"] = str(r["updated_at"] or "")
    return payload


def set_user_favorite(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    scope: str,
    position_name: str,
    source: str,
    payload: dict[str, Any],
) -> None:
    init_portal_db(conn)
    uid = int(user_id)
    scope = str(scope or "").strip()
    pos = str(position_name or "").strip()
    source = "legacy" if str(source or "").strip().lower() == "legacy" else "main"
    try:
        payload_s = json.dumps(payload or {}, ensure_ascii=False)
    except Exception:
        payload_s = "{}"
    conn.execute(
        """
        INSERT INTO user_favorites (user_id, scope, position_name, source, payload)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, scope, position_name, source) DO UPDATE SET
          payload=excluded.payload,
          updated_at=CURRENT_TIMESTAMP
        """,
        (uid, scope, pos, source, payload_s),
    )
    conn.commit()


def get_position_setting(
    conn: sqlite3.Connection, *, position_name: str, key: str
) -> str | None:
    init_portal_db(conn)
    pos = str(position_name or "").strip()
    k = str(key or "").strip()
    if not k:
        return None
    r = conn.execute(
        """
        SELECT value
        FROM position_settings
        WHERE position_name=? AND key=?
        """,
        (pos, k),
    ).fetchone()
    if not r:
        return None
    return str(r["value"] or "")


def set_position_setting(
    conn: sqlite3.Connection, *, position_name: str, key: str, value: str
) -> None:
    init_portal_db(conn)
    pos = str(position_name or "").strip()
    k = str(key or "").strip()
    if not k:
        return
    v = str(value or "")
    conn.execute(
        """
        INSERT INTO position_settings (position_name, key, value)
        VALUES (?, ?, ?)
        ON CONFLICT(position_name, key) DO UPDATE SET
          value=excluded.value,
          updated_at=CURRENT_TIMESTAMP
        """,
        (pos, k, v),
    )
    conn.commit()


PORTAL_GLOBAL_POSITION = "__portal__"
ASR_TRAINING_ENABLED_KEY = "asr_training_enabled"
ASR_LEARN_ON_BLANK_KEY = "asr_learn_on_blank_send"
ASR_LEARN_ON_FEEDBACK_KEY = "asr_learn_on_feedback"


def get_portal_global_setting(
    conn: sqlite3.Connection, *, key: str, default: str = ""
) -> str:
    v = get_position_setting(conn, position_name=PORTAL_GLOBAL_POSITION, key=key)
    if v is None or v == "":
        return str(default or "")
    return str(v)


def set_portal_global_setting(
    conn: sqlite3.Connection, *, key: str, value: str
) -> None:
    set_position_setting(
        conn,
        position_name=PORTAL_GLOBAL_POSITION,
        key=key,
        value=str(value or ""),
    )


def get_asr_training_policy(conn: sqlite3.Connection) -> dict[str, bool]:
    def _flag(key: str, default: bool = False) -> bool:
        raw = get_portal_global_setting(conn, key=key, default="1" if default else "0")
        return str(raw).strip().lower() in ("1", "true", "yes", "on")

    return {
        "training_enabled": _flag(ASR_TRAINING_ENABLED_KEY, default=False),
        "learn_on_blank_send": _flag(ASR_LEARN_ON_BLANK_KEY, default=True),
        "learn_on_feedback": _flag(ASR_LEARN_ON_FEEDBACK_KEY, default=True),
    }


def set_asr_training_policy(
    conn: sqlite3.Connection,
    *,
    training_enabled: bool,
    learn_on_blank_send: bool,
    learn_on_feedback: bool,
) -> None:
    set_portal_global_setting(
        conn,
        key=ASR_TRAINING_ENABLED_KEY,
        value="1" if training_enabled else "0",
    )
    set_portal_global_setting(
        conn,
        key=ASR_LEARN_ON_BLANK_KEY,
        value="1" if learn_on_blank_send else "0",
    )
    set_portal_global_setting(
        conn,
        key=ASR_LEARN_ON_FEEDBACK_KEY,
        value="1" if learn_on_feedback else "0",
    )


def get_user_intercept_view_mode(conn: sqlite3.Connection, *, user_id: int) -> str:
    init_portal_db(conn)
    cols = _portal_table_columns(conn, "users")
    if "intercept_view_mode" not in cols:
        return "pretty"
    row = conn.execute(
        "SELECT intercept_view_mode FROM users WHERE id=?",
        (int(user_id),),
    ).fetchone()
    mode = str(row["intercept_view_mode"] or "") if row else ""
    return mode if mode in {"pretty", "plain"} else "pretty"


def set_user_intercept_view_mode(
    conn: sqlite3.Connection, *, user_id: int, mode: str
) -> str:
    init_portal_db(conn)
    cols = _portal_table_columns(conn, "users")
    if "intercept_view_mode" not in cols:
        return "pretty"
    next_mode = str(mode or "").strip().lower()
    if next_mode not in {"pretty", "plain"}:
        next_mode = "pretty"
    conn.execute(
        "UPDATE users SET intercept_view_mode=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (next_mode, int(user_id)),
    )
    conn.commit()
    return next_mode


def get_user_intercept_unit_order(
    conn: sqlite3.Connection, *, user_id: int
) -> list[str]:
    import json

    init_portal_db(conn)
    cols = _portal_table_columns(conn, "users")
    if "intercept_unit_order" not in cols:
        return []
    row = conn.execute(
        "SELECT intercept_unit_order FROM users WHERE id=?",
        (int(user_id),),
    ).fetchone()
    raw = str(row["intercept_unit_order"] or "") if row else ""
    try:
        arr = json.loads(raw)
        if isinstance(arr, list):
            return [str(x) for x in arr if str(x).strip()]
    except Exception:
        _log.debug("get_user_intercept_unit_order: suppressed error", exc_info=True)
    return []


def set_user_intercept_unit_order(
    conn: sqlite3.Connection, *, user_id: int, order: list[str]
) -> list[str]:
    import json

    init_portal_db(conn)
    cols = _portal_table_columns(conn, "users")
    if "intercept_unit_order" not in cols:
        return []
    cleaned = [str(x).strip() for x in (order or []) if str(x).strip()]
    conn.execute(
        "UPDATE users SET intercept_unit_order=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (json.dumps(cleaned, ensure_ascii=False), int(user_id)),
    )
    conn.commit()
    return cleaned


def _catalog_prefs_entry_key(
    *, catalog_id: int = 0, frequency: str = "", group_code: str = ""
) -> str:
    cid = int(catalog_id or 0)
    if cid > 0:
        return f"id:{cid}"
    freq = str(frequency or "").strip()
    grp = str(group_code or "").strip()
    if freq and grp:
        return f"pair:{freq}|{grp}"
    return ""


def _normalize_catalog_prefs_entry(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    cid = int(raw.get("catalog_id") or raw.get("id") or 0)
    freq = str(raw.get("frequency") or "").strip()
    grp = str(raw.get("group_code") or raw.get("group") or "").strip()
    key = _catalog_prefs_entry_key(catalog_id=cid, frequency=freq, group_code=grp)
    if not key:
        return {}
    return {
        "key": key,
        "catalog_id": str(cid) if cid > 0 else "",
        "frequency": freq,
        "group_code": grp,
    }


def _parse_intercept_catalog_prefs(raw: str) -> dict[str, list[dict[str, str]]]:
    import json

    out: dict[str, list[dict[str, str]]] = {"favorites": [], "archived": []}
    try:
        data = json.loads(raw or "{}")
        if not isinstance(data, dict):
            return out
    except Exception:
        return out
    seen_fav: set[str] = set()
    seen_arc: set[str] = set()
    for item in data.get("favorites") or []:
        norm = _normalize_catalog_prefs_entry(item)
        k = norm.get("key") or ""
        if not k or k in seen_fav:
            continue
        seen_fav.add(k)
        out["favorites"].append(
            {
                "catalog_id": int(norm["catalog_id"] or 0),
                "frequency": norm["frequency"],
                "group_code": norm["group_code"],
            }
        )
    for item in data.get("archived") or []:
        norm = _normalize_catalog_prefs_entry(item)
        k = norm.get("key") or ""
        if not k or k in seen_arc:
            continue
        seen_arc.add(k)
        out["archived"].append(
            {
                "catalog_id": int(norm["catalog_id"] or 0),
                "frequency": norm["frequency"],
                "group_code": norm["group_code"],
            }
        )
    return out


def get_user_intercept_catalog_prefs(
    conn: sqlite3.Connection, *, user_id: int
) -> dict[str, list[dict[str, object]]]:
    import json

    init_portal_db(conn)
    cols = _portal_table_columns(conn, "users")
    if "intercept_catalog_prefs" not in cols:
        return {"favorites": [], "archived": []}
    row = conn.execute(
        "SELECT intercept_catalog_prefs FROM users WHERE id=?",
        (int(user_id),),
    ).fetchone()
    raw = str(row["intercept_catalog_prefs"] or "") if row else ""
    parsed = _parse_intercept_catalog_prefs(raw)
    return {
        "favorites": parsed.get("favorites") or [],
        "archived": parsed.get("archived") or [],
    }


def set_user_intercept_catalog_prefs(
    conn: sqlite3.Connection, *, user_id: int, prefs: dict[str, list]
) -> dict[str, list[dict[str, object]]]:
    import json

    init_portal_db(conn)
    cols = _portal_table_columns(conn, "users")
    if "intercept_catalog_prefs" not in cols:
        return {"favorites": [], "archived": []}
    current = get_user_intercept_catalog_prefs(conn, user_id=int(user_id))
    fav_in = prefs.get("favorites") if isinstance(prefs.get("favorites"), list) else current["favorites"]
    arc_in = prefs.get("archived") if isinstance(prefs.get("archived"), list) else current["archived"]
    cleaned = _parse_intercept_catalog_prefs(
        json.dumps({"favorites": fav_in, "archived": arc_in}, ensure_ascii=False)
    )
    conn.execute(
        "UPDATE users SET intercept_catalog_prefs=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (json.dumps(cleaned, ensure_ascii=False), int(user_id)),
    )
    conn.commit()
    return {
        "favorites": cleaned.get("favorites") or [],
        "archived": cleaned.get("archived") or [],
    }


def _entry_in_list(entries: list[dict], key: str) -> bool:
    for e in entries or []:
        cid = int(e.get("catalog_id") or 0)
        freq = str(e.get("frequency") or "").strip()
        grp = str(e.get("group_code") or "").strip()
        if _catalog_prefs_entry_key(catalog_id=cid, frequency=freq, group_code=grp) == key:
            return True
    return False


def toggle_intercept_catalog_favorite(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    catalog_id: int = 0,
    frequency: str = "",
    group_code: str = "",
    max_items: int = 5,
) -> tuple[dict[str, list[dict[str, object]]], bool]:
    key = _catalog_prefs_entry_key(
        catalog_id=int(catalog_id or 0),
        frequency=str(frequency or "").strip(),
        group_code=str(group_code or "").strip(),
    )
    if not key:
        raise ValueError("Нужны catalog_id или частота и группа")
    prefs = get_user_intercept_catalog_prefs(conn, user_id=int(user_id))
    favs: list[dict] = list(prefs.get("favorites") or [])
    if _entry_in_list(favs, key):
        favs = [
            e
            for e in favs
            if _catalog_prefs_entry_key(
                catalog_id=int(e.get("catalog_id") or 0),
                frequency=str(e.get("frequency") or ""),
                group_code=str(e.get("group_code") or ""),
            )
            != key
        ]
        saved = set_user_intercept_catalog_prefs(
            conn, user_id=int(user_id), prefs={"favorites": favs, "archived": prefs.get("archived") or []}
        )
        return saved, False
    if len(favs) >= int(max_items or 5):
        raise ValueError(f"В избранное можно добавить не больше {int(max_items or 5)} чатов")
    favs.append(
        {
            "catalog_id": int(catalog_id or 0),
            "frequency": str(frequency or "").strip(),
            "group_code": str(group_code or "").strip(),
        }
    )
    saved = set_user_intercept_catalog_prefs(
        conn, user_id=int(user_id), prefs={"favorites": favs, "archived": prefs.get("archived") or []}
    )
    return saved, True


def toggle_intercept_catalog_archive(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    catalog_id: int = 0,
    frequency: str = "",
    group_code: str = "",
) -> tuple[dict[str, list[dict[str, object]]], bool]:
    key = _catalog_prefs_entry_key(
        catalog_id=int(catalog_id or 0),
        frequency=str(frequency or "").strip(),
        group_code=str(group_code or "").strip(),
    )
    if not key:
        raise ValueError("Нужны catalog_id или частота и группа")
    prefs = get_user_intercept_catalog_prefs(conn, user_id=int(user_id))
    archived: list[dict] = list(prefs.get("archived") or [])
    if _entry_in_list(archived, key):
        archived = [
            e
            for e in archived
            if _catalog_prefs_entry_key(
                catalog_id=int(e.get("catalog_id") or 0),
                frequency=str(e.get("frequency") or ""),
                group_code=str(e.get("group_code") or ""),
            )
            != key
        ]
        archived_now = False
    else:
        archived.append(
            {
                "catalog_id": int(catalog_id or 0),
                "frequency": str(frequency or "").strip(),
                "group_code": str(group_code or "").strip(),
            }
        )
        archived_now = True
    saved = set_user_intercept_catalog_prefs(
        conn,
        user_id=int(user_id),
        prefs={"favorites": prefs.get("favorites") or [], "archived": archived},
    )
    return saved, archived_now


def ensure_default_admin(conn: sqlite3.Connection) -> tuple[bool, str]:
    """
    Если пользователей нет — создаёт admin/admin.
    Возвращает (created, message).
    """
    init_portal_db(conn)
    cur = conn.cursor()
    cnt = cur.execute("SELECT COUNT(*) FROM users;").fetchone()[0]
    if int(cnt or 0) > 0:
        return (False, "")
    cur.execute(
        "INSERT INTO users (username, callsign, role, password_hash) VALUES (?, ?, ?, ?)",
        ("admin", "admin", ROLE_ADMIN, generate_password_hash("admin")),
    )
    conn.commit()
    return (True, "Создан пользователь admin / admin (поменяйте пароль после входа).")


def get_user_permissions(conn: sqlite3.Connection, role: str) -> frozenset[str]:
    """Разрешения пользователя по роли: встроенная или кастомная."""
    role = str(role or "").strip()
    if role in ROLE_PERMS:
        return frozenset(ROLE_PERMS[role])
    return get_custom_role_permissions(conn, role)


def get_custom_role_permissions(
    conn: sqlite3.Connection, role_name: str
) -> frozenset[str]:
    """Разрешения кастомной роли по имени."""
    init_portal_db(conn)
    row = conn.execute(
        "SELECT permissions FROM custom_roles WHERE name=?",
        (str(role_name or "").strip(),),
    ).fetchone()
    if not row or not row["permissions"]:
        return frozenset()
    try:
        data = json.loads(row["permissions"])
        return frozenset(str(p) for p in (data if isinstance(data, list) else []))
    except (TypeError, ValueError):
        return frozenset()


def list_custom_roles(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    init_portal_db(conn)
    rows = conn.execute(
        "SELECT id, name, permissions, created_at, updated_at FROM custom_roles ORDER BY name"
    ).fetchall()
    out = []
    for r in rows:
        perms = []
        try:
            data = json.loads(r["permissions"] or "[]")
            perms = [str(p) for p in data] if isinstance(data, list) else []
        except (TypeError, ValueError):
            pass
        out.append(
            {
                "id": int(r["id"]),
                "name": str(r["name"] or ""),
                "permissions": perms,
                "created_at": str(r["created_at"] or ""),
                "updated_at": str(r["updated_at"] or ""),
            }
        )
    return out


def get_custom_role_by_name(
    conn: sqlite3.Connection, name: str
) -> dict[str, Any] | None:
    init_portal_db(conn)
    row = conn.execute(
        "SELECT id, name, permissions FROM custom_roles WHERE name=?",
        (str(name or "").strip(),),
    ).fetchone()
    if not row:
        return None
    perms = []
    try:
        data = json.loads(row["permissions"] or "[]")
        perms = [str(p) for p in data] if isinstance(data, list) else []
    except (TypeError, ValueError):
        pass
    return {
        "id": int(row["id"]),
        "name": str(row["name"] or ""),
        "permissions": perms,
    }


def create_custom_role(
    conn: sqlite3.Connection, name: str, permissions: list[str]
) -> int:
    init_portal_db(conn)
    name = (name or "").strip()
    if not name:
        raise ValueError("Имя роли обязательно")
    if name in ROLE_PERMS:
        raise ValueError("Имя роли совпадает со встроенной ролью")
    perms = [str(p).strip() for p in (permissions or []) if str(p).strip()]
    conn.execute(
        "INSERT INTO custom_roles (name, permissions) VALUES (?, ?)",
        (name, json.dumps(perms)),
    )
    conn.commit()
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def update_custom_role(
    conn: sqlite3.Connection, role_id: int, name: str, permissions: list[str]
) -> None:
    init_portal_db(conn)
    name = (name or "").strip()
    if not name:
        raise ValueError("Имя роли обязательно")
    if name in ROLE_PERMS:
        raise ValueError("Имя роли совпадает со встроенной ролью")
    row = conn.execute(
        "SELECT name FROM custom_roles WHERE id=?", (int(role_id),)
    ).fetchone()
    old_name = str(row["name"] or "").strip() if row else ""
    perms = [str(p).strip() for p in (permissions or []) if str(p).strip()]
    conn.execute(
        "UPDATE custom_roles SET name=?, permissions=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (name, json.dumps(perms), int(role_id)),
    )
    if old_name and old_name != name:
        conn.execute(
            "UPDATE users SET role=?, updated_at=CURRENT_TIMESTAMP WHERE role=?",
            (name, old_name),
        )
    conn.commit()


def delete_custom_role(conn: sqlite3.Connection, role_id: int) -> None:
    init_portal_db(conn)
    row = conn.execute(
        "SELECT name FROM custom_roles WHERE id=?", (int(role_id),)
    ).fetchone()
    if row:
        role_name = str(row["name"] or "")
        conn.execute(
            "UPDATE users SET role=?, updated_at=CURRENT_TIMESTAMP WHERE role=?",
            (ROLE_VIEWER, role_name),
        )
    conn.execute("DELETE FROM custom_roles WHERE id=?", (int(role_id),))
    conn.commit()


def get_user_by_id(conn: sqlite3.Connection, user_id: int) -> UserRecord | None:
    init_portal_db(conn)
    row = conn.execute(
        "SELECT id, username, callsign, role FROM users WHERE id=?",
        (int(user_id),),
    ).fetchone()
    if not row:
        return None
    role = str(row["role"] or ROLE_VIEWER)
    perms = get_user_permissions(conn, role)
    return UserRecord(
        id=int(row["id"]),
        username=str(row["username"]),
        callsign=str(row["callsign"] or ""),
        role=role,
        permissions=perms,
    )


def get_user_by_username(
    conn: sqlite3.Connection, username: str
) -> tuple[UserRecord | None, str | None]:
    init_portal_db(conn)
    row = conn.execute(
        "SELECT id, username, callsign, role, password_hash FROM users WHERE username=?",
        (username,),
    ).fetchone()
    if not row:
        return (None, None)
    role = str(row["role"] or ROLE_VIEWER)
    perms = get_user_permissions(conn, role)
    u = UserRecord(
        id=int(row["id"]),
        username=str(row["username"]),
        callsign=str(row["callsign"] or ""),
        role=role,
        permissions=perms,
    )
    return (u, str(row["password_hash"]))


def verify_login(
    conn: sqlite3.Connection, username: str, password: str
) -> UserRecord | None:
    u, password_hash = get_user_by_username(conn, username)
    if not u or not password_hash:
        return None
    if not check_password_hash(password_hash, password):
        return None
    return u


def list_users(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    init_portal_db(conn)
    rows = conn.execute(
        "SELECT id, username, callsign, role, created_at FROM users ORDER BY id DESC"
    ).fetchall()
    # positions map (LEFT JOIN: «битая» ссылка на удалённую позицию всё равно видна в админке)
    pos_rows = conn.execute(
        """
        SELECT up.user_id, p.name AS pos_name, up.role, up.position_id
        FROM user_positions up
        LEFT JOIN positions p ON p.id = up.position_id
        ORDER BY COALESCE(p.name, '')
        """
    ).fetchall()
    user_pos: dict[int, list[dict[str, str]]] = {}
    for r in pos_rows:
        uid = int(r["user_id"])
        nm = str(r["pos_name"] or "").strip()
        if not nm:
            nm = f"(id позиции {int(r['position_id'] or 0)})"
        user_pos.setdefault(uid, []).append(
            {"name": nm, "role": str(r["role"] or POS_ROLE_OPERATOR)}
        )
    return [
        {
            "id": int(r["id"]),
            "username": str(r["username"]),
            "callsign": str(r["callsign"] or ""),
            "role": str(r["role"] or ROLE_VIEWER),
            "created_at": str(r["created_at"] or ""),
            "positions": user_pos.get(int(r["id"]), []),
        }
        for r in rows
    ]


def create_user(
    conn: sqlite3.Connection, username: str, callsign: str, role: str, password: str
) -> int:
    init_portal_db(conn)
    username = (username or "").strip()
    if not username:
        raise ValueError("username обязателен")
    role = (role or "").strip()
    if role in ROLE_PERMS:
        pass
    elif get_custom_role_by_name(conn, role):
        pass
    else:
        role = ROLE_VIEWER
    conn.execute(
        "INSERT INTO users (username, callsign, role, password_hash) VALUES (?, ?, ?, ?)",
        (username, callsign or "", role, generate_password_hash(password)),
    )
    conn.commit()
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def ensure_ai_assistant_user(conn: sqlite3.Connection) -> int:
    """Системный пользователь для ответов локальной нейросети в чате."""
    init_portal_db(conn)
    username = "__eavc_ai_manager__"
    callsign = "EAVC Manager"
    row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if row:
        conn.execute(
            """
            UPDATE users
            SET callsign=?, role=?
            WHERE id=?
            """,
            (callsign, ROLE_VIEWER, int(row["id"])),
        )
        conn.commit()
        return int(row["id"])
    conn.execute(
        """
        INSERT INTO users (username, callsign, role, password_hash)
        VALUES (?, ?, ?, ?)
        """,
        (
            username,
            callsign,
            ROLE_VIEWER,
            generate_password_hash(os.urandom(32).hex()),
        ),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    return int(row["id"])


def list_positions(conn: sqlite3.Connection) -> list[str]:
    init_portal_db(conn)
    rows = conn.execute("SELECT name FROM positions ORDER BY name;").fetchall()
    return [str(r["name"]) for r in rows]


def ensure_position(conn: sqlite3.Connection, name: str) -> int:
    init_portal_db(conn)
    name = (name or "").strip()
    if not name:
        raise ValueError("Позиция пустая")
    conn.execute("INSERT OR IGNORE INTO positions (name) VALUES (?)", (name,))
    conn.commit()
    row = conn.execute("SELECT id FROM positions WHERE name=?", (name,)).fetchone()
    return int(row["id"])


def _parse_position_token(token: str) -> tuple[str, str]:
    """
    Принимаем:
      - "Москва" -> ("Москва", "operator")
      - "Москва:operator" / "Москва:chief"
    """
    t = str(token or "").strip()
    if not t:
        return ("", POS_ROLE_OPERATOR)
    if ":" not in t:
        return (t, POS_ROLE_OPERATOR)
    name, role = t.split(":", 1)
    name = name.strip()
    role = role.strip().lower()
    if role not in {POS_ROLE_OPERATOR, POS_ROLE_CHIEF}:
        role = POS_ROLE_OPERATOR
    return (name, role)


def set_user_positions(
    conn: sqlite3.Connection, user_id: int, positions: list[str]
) -> None:
    init_portal_db(conn)
    uid = int(user_id)
    # нормализуем
    cleaned: list[tuple[str, str]] = []
    for p in positions or []:
        name, role = _parse_position_token(p)
        if name:
            cleaned.append((name, role))
    # unique by name, keep last role
    m: dict[str, str] = {}
    for name, role in cleaned:
        m[name] = role
    cleaned2 = sorted(m.items(), key=lambda x: x[0].lower())

    cur = conn.cursor()
    cur.execute("DELETE FROM user_positions WHERE user_id=?", (uid,))
    cols = _portal_table_columns(conn, "user_positions")
    has_role = "role" in cols
    has_updated_at = "updated_at" in cols
    for name, role in cleaned2:
        pid = ensure_position(conn, name)
        # Backward-compatible insert for older portal.sqlite schemas
        if has_role and has_updated_at:
            cur.execute(
                """
            INSERT OR REPLACE INTO user_positions (user_id, position_id, role, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """,
                (uid, pid, role),
            )
        elif has_role:
            cur.execute(
                """
                INSERT OR REPLACE INTO user_positions (user_id, position_id, role)
                VALUES (?, ?, ?)
                """,
                (uid, pid, role),
            )
        elif has_updated_at:
            cur.execute(
                """
                INSERT OR REPLACE INTO user_positions (user_id, position_id, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                (uid, pid),
            )
        else:
            cur.execute(
                """
                INSERT OR REPLACE INTO user_positions (user_id, position_id)
                VALUES (?, ?)
                """,
                (uid, pid),
            )
    # фиксируем изменение пользователя (позиции/роли)
    try:
        conn.execute("UPDATE users SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (uid,))
    except Exception:
        _log.debug("set_user_positions: suppressed error", exc_info=True)
    conn.commit()


def get_user_positions(conn: sqlite3.Connection, user_id: int) -> list[str]:
    init_portal_db(conn)
    rows = conn.execute(
        """
        SELECT p.name
        FROM user_positions up
        JOIN positions p ON p.id = up.position_id
        WHERE up.user_id=?
        ORDER BY p.name
        """,
        (int(user_id),),
    ).fetchall()
    return [str(r["name"]) for r in rows]


def get_user_position_role(
    conn: sqlite3.Connection, user_id: int, position_name: str
) -> str | None:
    init_portal_db(conn)
    position_name = (position_name or "").strip()
    if not position_name:
        return None
    r = conn.execute(
        """
        SELECT up.role
        FROM user_positions up
        JOIN positions p ON p.id = up.position_id
        WHERE up.user_id=? AND p.name=?
        """,
        (int(user_id), position_name),
    ).fetchone()
    if not r:
        return None
    role = str(r["role"] or POS_ROLE_OPERATOR).lower()
    return role if role in {POS_ROLE_OPERATOR, POS_ROLE_CHIEF} else POS_ROLE_OPERATOR


def update_user_role(conn: sqlite3.Connection, user_id: int, role: str) -> None:
    init_portal_db(conn)
    role = (role or "").strip()
    if role in ROLE_PERMS:
        pass
    elif get_custom_role_by_name(conn, role):
        pass
    else:
        role = ROLE_VIEWER
    conn.execute(
        "UPDATE users SET role=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (role, int(user_id)),
    )
    conn.commit()


def update_user_password(conn: sqlite3.Connection, user_id: int, password: str) -> None:
    init_portal_db(conn)
    conn.execute(
        "UPDATE users SET password_hash=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (generate_password_hash(password), int(user_id)),
    )
    conn.commit()


def list_users_since(
    conn: sqlite3.Connection, *, since_ts: str
) -> list[dict[str, Any]]:
    """
    Инкрементальная выдача пользователей для sync pull (server -> hub).
    Включает password_hash (защищено X-Sync-Key).
    """
    init_portal_db(conn)
    # Повторно: init мог оборваться на старых БД до _ensure; перед SELECT гарантируем колонки.
    _ensure_portal_columns(conn)
    try:
        conn.commit()
    except Exception:
        _log.debug("list_users_since: suppressed error", exc_info=True)
    since = str(since_ts or "").strip() or "1970-01-01 00:00:00"
    user_cols = _portal_table_columns(conn, "users")
    if "updated_at" in user_cols:
        rows = conn.execute(
            """
            SELECT id, username, callsign, role, password_hash, created_at, updated_at
            FROM users
            WHERE COALESCE(updated_at,'') >= ?
            ORDER BY COALESCE(updated_at,'') ASC, id ASC
            """,
            (since,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, username, callsign, role, password_hash, created_at, created_at AS updated_at
            FROM users
            WHERE COALESCE(created_at,'') >= ?
            ORDER BY COALESCE(created_at,'') ASC, id ASC
            """,
            (since,),
        ).fetchall()
    up_cols = _portal_table_columns(conn, "user_positions")
    if "updated_at" in up_cols:
        pos_rows = conn.execute(
            """
            SELECT u.username as username, p.name as name, up.role as role, up.updated_at as updated_at
            FROM user_positions up
            JOIN users u ON u.id = up.user_id
            JOIN positions p ON p.id = up.position_id
            WHERE COALESCE(up.updated_at,'') >= ?
            ORDER BY COALESCE(up.updated_at,'') ASC
            """,
            (since,),
        ).fetchall()
    else:
        pos_rows = conn.execute(
            """
            SELECT u.username as username, p.name as name, up.role as role, '' as updated_at
            FROM user_positions up
            JOIN users u ON u.id = up.user_id
            JOIN positions p ON p.id = up.position_id
            """
        ).fetchall()
    m: dict[str, list[str]] = {}
    for r in pos_rows or []:
        uname = str(r["username"] or "")
        nm = str(r["name"] or "")
        rl = str(r["role"] or POS_ROLE_OPERATOR)
        if uname and nm:
            m.setdefault(uname, []).append(f"{nm}:{rl}")
    out: list[dict[str, Any]] = []
    for r in rows or []:
        uname = str(r["username"] or "")
        out.append(
            {
                "username": uname,
                "callsign": str(r["callsign"] or ""),
                "role": str(r["role"] or ROLE_VIEWER),
                "password_hash": str(r["password_hash"] or ""),
                "created_at": str(r["created_at"] or ""),
                "_updated_at": str(r["updated_at"] or ""),
                "positions": m.get(uname, []),
            }
        )
    return out


# --- Sync helpers (hub -> central server) ---
def get_user_sync_payload_by_id(
    conn: sqlite3.Connection, user_id: int
) -> dict[str, Any] | None:
    init_portal_db(conn)
    r = conn.execute(
        """
        SELECT username, callsign, role, password_hash, created_at
        FROM users
        WHERE id=?
        """,
        (int(user_id),),
    ).fetchone()
    if not r:
        return None
    return {
        "username": str(r["username"] or ""),
        "callsign": str(r["callsign"] or ""),
        "role": str(r["role"] or ROLE_VIEWER),
        "password_hash": str(r["password_hash"] or ""),
        "created_at": str(r["created_at"] or ""),
    }


def get_user_sync_payload_by_username(
    conn: sqlite3.Connection, username: str
) -> dict[str, Any] | None:
    init_portal_db(conn)
    u = str(username or "").strip()
    if not u:
        return None
    r = conn.execute(
        """
        SELECT username, callsign, role, password_hash, created_at
        FROM users
        WHERE username=?
        """,
        (u,),
    ).fetchone()
    if not r:
        return None
    return {
        "username": str(r["username"] or ""),
        "callsign": str(r["callsign"] or ""),
        "role": str(r["role"] or ROLE_VIEWER),
        "password_hash": str(r["password_hash"] or ""),
        "created_at": str(r["created_at"] or ""),
    }


def upsert_user_from_sync(conn: sqlite3.Connection, *, payload: dict[str, Any]) -> int:
    """
    Upsert пользователя по username. Возвращает local user_id.
    """
    init_portal_db(conn)
    p = payload or {}
    username = str(p.get("username") or "").strip()
    if not username:
        raise ValueError("username обязателен")
    callsign = str(p.get("callsign") or "")
    role = str(p.get("role") or ROLE_VIEWER)
    role = role if role in ROLE_PERMS else ROLE_VIEWER
    password_hash = str(p.get("password_hash") or "")
    created_at = str(p.get("created_at") or "").strip()
    updated_at = str(p.get("_updated_at") or p.get("updated_at") or "").strip()
    if not password_hash:
        # если хеша нет — оставляем как есть (или ставим заглушку)
        password_hash = generate_password_hash("change-me")
    # если есть updated_at — не перезатираем более новое локальное
    try:
        r0 = conn.execute(
            "SELECT id, COALESCE(updated_at,'') as updated_at FROM users WHERE username=?",
            (username,),
        ).fetchone()
        if r0:
            local_ts = str(r0["updated_at"] or "").strip()
            if updated_at and local_ts and local_ts >= updated_at:
                # позиции могут прийти отдельно — но тут тоже можно применить
                try:
                    positions = p.get("positions") or []
                    if isinstance(positions, list) and positions:
                        set_user_positions(
                            conn, int(r0["id"]), [str(x) for x in positions]
                        )
                except Exception:
                    _log.debug("upsert_user_from_sync: suppressed error", exc_info=True)
                return int(r0["id"])
    except Exception:
        _log.debug("upsert_user_from_sync: suppressed error", exc_info=True)
    conn.execute(
        """
        INSERT INTO users (username, callsign, role, password_hash, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, COALESCE(NULLIF(?,''), CURRENT_TIMESTAMP))
        ON CONFLICT(username) DO UPDATE SET
          callsign=excluded.callsign,
          role=excluded.role,
          password_hash=excluded.password_hash,
          updated_at=excluded.updated_at
        """,
        (username, callsign, role, password_hash, created_at or None, updated_at),
    )
    conn.commit()
    r = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    uid = int(r["id"])
    try:
        positions = p.get("positions") or []
        if isinstance(positions, list) and positions:
            set_user_positions(conn, uid, [str(x) for x in positions])
    except Exception:
        _log.debug("upsert_user_from_sync: suppressed error", exc_info=True)
    return uid


def create_targeting(
    conn: sqlite3.Connection,
    *,
    title: str,
    message: str,
    target_type: str,
    target_position: str = "",
    target_user_ids: list[int] | None = None,
    created_by: str = "",
    expires_at: str | None = None,
) -> int:
    """Создать нацеливание."""
    import uuid as uuid_lib

    init_portal_db(conn)
    new_uuid = str(uuid_lib.uuid4())
    target_user_ids_json = json.dumps(target_user_ids or [], ensure_ascii=False)

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO targeting (uuid, title, message, target_type, target_position, target_user_ids, created_by, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_uuid,
            str(title or "").strip(),
            str(message or "").strip(),
            str(target_type or "all"),
            str(target_position or "").strip(),
            target_user_ids_json,
            str(created_by or "").strip(),
            expires_at if expires_at else None,
        ),
    )
    conn.commit()
    return cur.lastrowid


def list_targeting(
    conn: sqlite3.Connection,
    *,
    user_id: int | None = None,
    position_name: str | None = None,
    include_read: bool = False,
) -> list[dict[str, Any]]:
    """Получить список активных нацеливаний для пользователя или позиции."""
    init_portal_db(conn)

    from datetime import datetime

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    # Получаем активные нацеливания
    query = """
        SELECT id, uuid, title, message, target_type, target_position, target_user_ids,
               created_by, created_at, expires_at
        FROM targeting
        WHERE is_active = 1
          AND (expires_at IS NULL OR expires_at > ?)
        ORDER BY created_at DESC
    """
    rows = conn.execute(query, (now,)).fetchall()

    result = []
    for row in rows:
        target_type = str(row["target_type"] or "")
        target_position = str(row["target_position"] or "")
        target_user_ids_json = str(row["target_user_ids"] or "[]")

        # Проверяем, подходит ли нацеливание
        matches = False

        if target_type == "all":
            matches = True
        elif target_type == "position":
            # Если указана позиция, проверяем, есть ли у пользователя эта позиция
            if position_name and target_position:
                matches = target_position == position_name
            elif target_position:
                # Если позиция указана в нацеливании, но у пользователя нет выбранной позиции,
                # проверяем все позиции пользователя
                if user_id:
                    user_positions = get_user_positions(conn, user_id)
                    matches = target_position in user_positions
                else:
                    matches = False
            else:
                matches = False
        elif target_type == "users" and user_id:
            try:
                user_ids = json.loads(target_user_ids_json)
                matches = user_id in [int(uid) for uid in user_ids]
            except Exception:
                _log.debug("list_targeting: suppressed error", exc_info=True)

        if not matches:
            continue

        # Проверяем, прочитано ли (всегда проверяем, если есть user_id)
        is_read = False
        if user_id:
            read_row = conn.execute(
                "SELECT read_at FROM targeting_reads WHERE targeting_id = ? AND user_id = ?",
                (int(row["id"]), user_id),
            ).fetchone()
            is_read = read_row is not None

        # Если include_read=False, пропускаем прочитанные
        if not include_read and is_read:
            continue

        result.append(
            {
                "id": int(row["id"]),
                "uuid": str(row["uuid"] or ""),
                "title": str(row["title"] or ""),
                "message": str(row["message"] or ""),
                "target_type": target_type,
                "target_position": target_position,
                "target_user_ids": json.loads(target_user_ids_json),
                "created_by": str(row["created_by"] or ""),
                "created_at": str(row["created_at"] or ""),
                "expires_at": (
                    str(row["expires_at"] or "") if row["expires_at"] else None
                ),
                "is_read": is_read,
            }
        )

    return result


def mark_targeting_read(
    conn: sqlite3.Connection, *, targeting_id: int, user_id: int
) -> None:
    """Отметить нацеливание как прочитанное."""
    init_portal_db(conn)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO targeting_reads (targeting_id, user_id)
        VALUES (?, ?)
        """,
        (int(targeting_id), int(user_id)),
    )
    conn.commit()


def delete_targeting(conn: sqlite3.Connection, targeting_id: int) -> bool:
    """Удалить нацеливание (деактивировать)."""
    init_portal_db(conn)
    cur = conn.cursor()
    cur.execute(
        "UPDATE targeting SET is_active = 0 WHERE id = ?",
        (int(targeting_id),),
    )
    conn.commit()
    return cur.rowcount > 0


def get_targeting_sync_payload(
    conn: sqlite3.Connection, targeting_id: int
) -> dict[str, Any] | None:
    """Получить payload нацеливания для синхронизации."""
    init_portal_db(conn)
    row = conn.execute(
        """
        SELECT uuid, title, message, target_type, target_position, target_user_ids,
               created_by, created_at, expires_at, is_active
        FROM targeting
        WHERE id = ?
        """,
        (targeting_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "uuid": str(row[0] or ""),
        "title": str(row[1] or ""),
        "message": str(row[2] or ""),
        "target_type": str(row[3] or ""),
        "target_position": str(row[4] or ""),
        "target_user_ids": str(row[5] or "[]"),
        "created_by": str(row[6] or ""),
        "created_at": str(row[7] or ""),
        "expires_at": str(row[8] or "") if row[8] else None,
        "is_active": int(row[9] or 0),
    }


def upsert_targeting_from_sync(
    conn: sqlite3.Connection, *, payload: dict[str, Any]
) -> int:
    """Upsert нацеливания из синхронизации."""
    init_portal_db(conn)
    d = payload or {}
    u = str(d.get("uuid") or "").strip()
    title = str(d.get("title") or "").strip()
    message = str(d.get("message") or "").strip()
    target_type = str(d.get("target_type") or "all").strip()
    target_position = str(d.get("target_position") or "").strip()
    target_user_ids = str(d.get("target_user_ids") or "[]")
    created_by = str(d.get("created_by") or "").strip()
    created_at = str(d.get("created_at") or "").strip()
    expires_at = d.get("expires_at")
    is_active = int(d.get("is_active") or 1)

    if not u or not title:
        raise ValueError("uuid/title обязательны")

    cur = conn.cursor()
    # Проверяем по UUID
    r = cur.execute("SELECT id FROM targeting WHERE uuid = ?", (u,)).fetchone()
    if r:
        cid = int(r[0])
        cur.execute(
            """
            UPDATE targeting
            SET title = ?, message = ?, target_type = ?, target_position = ?,
                target_user_ids = ?, created_by = ?, created_at = ?, expires_at = ?, is_active = ?
            WHERE id = ?
            """,
            (
                title,
                message,
                target_type,
                target_position,
                target_user_ids,
                created_by,
                created_at or None,
                expires_at,
                is_active,
                cid,
            ),
        )
        conn.commit()
        return cid

    # Создаем новое
    cur.execute(
        """
        INSERT INTO targeting (uuid, title, message, target_type, target_position,
                              target_user_ids, created_by, created_at, expires_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            u,
            title,
            message,
            target_type,
            target_position,
            target_user_ids,
            created_by,
            created_at or None,
            expires_at,
            is_active,
        ),
    )
    conn.commit()
    return cur.lastrowid


def list_targeting_since(
    conn: sqlite3.Connection, *, since_ts: str
) -> list[dict[str, Any]]:
    """Получить список нацеливаний, созданных после указанного времени."""
    init_portal_db(conn)
    since = str(since_ts or "").strip() or "1970-01-01 00:00:00"
    rows = conn.execute(
        """
        SELECT uuid, title, message, target_type, target_position, target_user_ids,
               created_by, created_at, expires_at, is_active
        FROM targeting
        WHERE created_at > ?
        ORDER BY created_at ASC
        """,
        (since,),
    ).fetchall()
    return [
        {
            "uuid": str(r[0] or ""),
            "title": str(r[1] or ""),
            "message": str(r[2] or ""),
            "target_type": str(r[3] or ""),
            "target_position": str(r[4] or ""),
            "target_user_ids": str(r[5] or "[]"),
            "created_by": str(r[6] or ""),
            "created_at": str(r[7] or ""),
            "expires_at": str(r[8] or "") if r[8] else None,
            "is_active": int(r[9] or 0),
        }
        for r in rows
    ]


def set_user_positions_by_username_from_sync(
    conn: sqlite3.Connection, *, username: str, positions: list[str]
) -> None:
    init_portal_db(conn)
    u = str(username or "").strip()
    if not u:
        raise ValueError("username обязателен")
    r = conn.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()
    if not r:
        raise ValueError("user not found")
    set_user_positions(conn, int(r["id"]), [str(x) for x in (positions or [])])


# ===== Hub Activity Tracking =====


def update_hub_activity(
    conn: sqlite3.Connection,
    *,
    hub_id: str,
    hub_name: str = "",
    position_name: str = "",
    ip_address: str = "",
    last_push: bool = False,
    last_pull: bool = False,
) -> None:
    """Обновить активность Hub."""
    init_portal_db(conn)
    hub_id = str(hub_id or "").strip()
    if not hub_id:
        return

    from datetime import datetime

    now_ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    # Проверяем, есть ли уже запись
    existing = conn.execute(
        "SELECT id FROM hub_activity WHERE hub_id=?", (hub_id,)
    ).fetchone()

    if existing:
        updates = ["last_seen=?"]
        params = [now_ts, hub_id]

        if hub_name:
            updates.append("hub_name=?")
            params.insert(-1, hub_name)
        if position_name:
            updates.append("position_name=?")
            params.insert(-1, position_name)
        if ip_address:
            updates.append("ip_address=?")
            params.insert(-1, ip_address)
        if last_push:
            updates.append("last_push=?")
            params.insert(-1, now_ts)
        if last_pull:
            updates.append("last_pull=?")
            params.insert(-1, now_ts)

        conn.execute(
            f"UPDATE hub_activity SET {', '.join(updates)} WHERE hub_id=?",
            tuple(params),
        )
    else:
        conn.execute(
            """
            INSERT INTO hub_activity (hub_id, hub_name, position_name, ip_address, last_seen, last_push, last_pull)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hub_id,
                hub_name or hub_id,
                position_name,
                ip_address,
                now_ts,
                now_ts if last_push else None,
                now_ts if last_pull else None,
            ),
        )
    conn.commit()


def list_hub_activity(
    conn: sqlite3.Connection, *, max_age_minutes: int = 60
) -> list[dict[str, Any]]:
    """Получить список активных Hub'ов."""
    init_portal_db(conn)
    from datetime import datetime, timedelta

    cutoff = (datetime.utcnow() - timedelta(minutes=max_age_minutes)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    rows = conn.execute(
        """
        SELECT id, hub_id, hub_name, position_name, ip_address, last_seen, last_push, last_pull, created_at
        FROM hub_activity
        WHERE last_seen >= ?
        ORDER BY last_seen DESC
        """,
        (cutoff,),
    ).fetchall()

    return [
        {
            "id": int(r["id"]),
            "hub_id": str(r["hub_id"] or ""),
            "hub_name": str(r["hub_name"] or r["hub_id"] or ""),
            "position_name": str(r["position_name"] or ""),
            "ip_address": str(r["ip_address"] or ""),
            "last_seen": str(r["last_seen"] or ""),
            "last_push": str(r["last_push"] or "") if r["last_push"] else None,
            "last_pull": str(r["last_pull"] or "") if r["last_pull"] else None,
            "created_at": str(r["created_at"] or ""),
        }
        for r in rows
    ]


# ===== Chat Functions =====

# Имена каналов чата
CHAT_CHANNEL_GENERAL = "general"
CHAT_CHANNEL_WORK_ATMOSPHERE = "work_atmosphere"
CHAT_CHANNEL_AI_ASSISTANT = "ai_assistant"

# Подписи каналов для UI
CHAT_CHANNEL_LABELS: dict[str, str] = {
    CHAT_CHANNEL_GENERAL: "Общий чат",
    CHAT_CHANNEL_WORK_ATMOSPHERE: "Рабочая атмосфера",
    CHAT_CHANNEL_AI_ASSISTANT: "AI-ассистент",
}


def get_chat_channel_roles(conn: sqlite3.Connection, channel_name: str) -> list[str]:
    """Список ролей, которым разрешён доступ к каналу чата."""
    init_portal_db(conn)
    name = str(channel_name or "").strip()
    if not name:
        return []
    rows = conn.execute(
        "SELECT role FROM chat_channel_roles WHERE channel_name = ? ORDER BY role",
        (name,),
    ).fetchall()
    return [str(r["role"] or "") for r in rows]


def set_chat_channel_roles(
    conn: sqlite3.Connection, channel_name: str, roles: list[str]
) -> None:
    """Задать список ролей с доступом к каналу чата."""
    init_portal_db(conn)
    name = str(channel_name or "").strip()
    if not name:
        return
    conn.execute("DELETE FROM chat_channel_roles WHERE channel_name = ?", (name,))
    for role in roles:
        r = str(role or "").strip()
        if r:
            conn.execute(
                "INSERT OR IGNORE INTO chat_channel_roles (channel_name, role) VALUES (?, ?)",
                (name, r),
            )
    conn.commit()


def user_can_access_chat_channel(
    conn: sqlite3.Connection, channel_name: str, user_role: str
) -> bool:
    """Проверить, есть ли у пользователя с данной ролью доступ к каналу."""
    name = str(channel_name or "").strip()
    if not name:
        return False
    if name == CHAT_CHANNEL_GENERAL:
        return True
    if name == CHAT_CHANNEL_AI_ASSISTANT:
        return True
    if name == CHAT_CHANNEL_WORK_ATMOSPHERE:
        allowed = get_chat_channel_roles(conn, name)
        return bool(allowed and str(user_role or "").strip() in allowed)
    return False


def list_chat_channels_for_user(
    conn: sqlite3.Connection, user_role: str
) -> list[dict[str, Any]]:
    """Список каналов чата, доступных пользователю с данной ролью."""
    init_portal_db(conn)
    role = str(user_role or "").strip()
    result = []
    for ch_name, ch_label in CHAT_CHANNEL_LABELS.items():
        if not user_can_access_chat_channel(conn, ch_name, role):
            continue
        group_id = ensure_chat_group(conn, name=ch_name)
        result.append({"id": group_id, "name": ch_name, "title": ch_label})
    return result


def get_chat_group_name(conn: sqlite3.Connection, group_id: int) -> str | None:
    """Имя канала по id группы."""
    init_portal_db(conn)
    r = conn.execute(
        "SELECT name FROM chat_groups WHERE id = ?", (int(group_id),)
    ).fetchone()
    return str(r["name"]).strip() if r and r["name"] else None


def ensure_chat_group(conn: sqlite3.Connection, *, name: str = "general") -> int:
    """Создать или получить группу чата."""
    init_portal_db(conn)
    name = str(name or "general").strip()
    if not name:
        name = "general"

    r = conn.execute("SELECT id FROM chat_groups WHERE name=?", (name,)).fetchone()
    if r:
        return int(r["id"])

    desc = CHAT_CHANNEL_LABELS.get(name, f"Общий чат {name}")
    conn.execute(
        "INSERT INTO chat_groups (name, description, is_global) VALUES (?, ?, ?)",
        (name, desc, 1),
    )
    conn.commit()
    r = conn.execute("SELECT id FROM chat_groups WHERE name=?", (name,)).fetchone()
    return int(r["id"])


def create_chat_message(
    conn: sqlite3.Connection,
    *,
    group_id: int | None = None,
    user_id: int,
    message_text: str,
    file_id: int | None = None,
) -> int:
    """Создать сообщение в чате."""
    init_portal_db(conn)
    import uuid as uuid_lib

    if group_id is None:
        group_id = ensure_chat_group(conn, name="general")

    msg_uuid = str(uuid_lib.uuid4())
    conn.execute(
        """
        INSERT INTO chat_messages (uuid, group_id, user_id, message_text, file_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (msg_uuid, group_id, int(user_id), str(message_text or "").strip(), file_id),
    )
    conn.commit()
    r = conn.execute(
        "SELECT id FROM chat_messages WHERE uuid=?", (msg_uuid,)
    ).fetchone()
    return int(r["id"])


def list_chat_messages(
    conn: sqlite3.Connection,
    *,
    group_id: int | None = None,
    since_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Получить список сообщений чата."""
    init_portal_db(conn)

    if group_id is None:
        group_id = ensure_chat_group(conn, name="general")

    query = """
        SELECT m.id, m.uuid, m.group_id, m.user_id, m.message_text, m.file_id,
               m.created_at, m.updated_at,
               u.username, u.callsign,
               f.original_filename, f.stored_filename, f.file_size, f.mime_type
        FROM chat_messages m
        JOIN users u ON u.id = m.user_id
        LEFT JOIN chat_files f ON f.id = m.file_id
        WHERE m.group_id = ?
    """
    params = [group_id]

    if since_id:
        query += " AND m.id > ?"
        params.append(since_id)

    # `created_at` has second precision, so user and AI messages can share
    # the same timestamp. Order by id as the deterministic tie-breaker.
    query += " ORDER BY m.created_at DESC, m.id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, tuple(params)).fetchall()

    result = []
    for r in reversed(rows):  # реверс для хронологического порядка
        result.append(
            {
                "id": int(r["id"]),
                "uuid": str(r["uuid"] or ""),
                "group_id": int(r["group_id"]) if r["group_id"] else None,
                "user_id": int(r["user_id"]),
                "username": str(r["username"] or ""),
                "callsign": str(r["callsign"] or ""),
                "message_text": str(r["message_text"] or ""),
                "file": None,
                "created_at": str(r["created_at"] or ""),
                "updated_at": str(r["updated_at"] or ""),
            }
        )
        if r["file_id"]:
            result[-1]["file"] = {
                "id": int(r["file_id"]),
                "original_filename": str(r["original_filename"] or ""),
                "stored_filename": str(r["stored_filename"] or ""),
                "file_size": int(r["file_size"] or 0),
                "mime_type": str(r["mime_type"] or ""),
            }

    return result


def clear_chat_user_ai_history(
    conn: sqlite3.Connection,
    *,
    group_id: int,
    user_id: int,
) -> int:
    """Удалить сообщения пользователя в канале и ответы EAVC Manager на них."""
    init_portal_db(conn)
    ai_uid = ensure_ai_assistant_user(conn)
    rows = conn.execute(
        """
        SELECT id, user_id
        FROM chat_messages
        WHERE group_id = ?
        ORDER BY id ASC
        """,
        (int(group_id),),
    ).fetchall()
    delete_ids: list[int] = []
    for idx, row in enumerate(rows):
        if int(row["user_id"]) != int(user_id):
            continue
        msg_id = int(row["id"])
        delete_ids.append(msg_id)
        if idx + 1 < len(rows) and int(rows[idx + 1]["user_id"]) == ai_uid:
            delete_ids.append(int(rows[idx + 1]["id"]))
    if not delete_ids:
        return 0
    placeholders = ",".join("?" * len(delete_ids))
    cur = conn.execute(
        f"DELETE FROM chat_messages WHERE id IN ({placeholders})",
        tuple(delete_ids),
    )
    conn.commit()
    return int(cur.rowcount or 0)


def get_ai_chat_feedback_map(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    message_ids: list[int],
) -> dict[int, int]:
    """Оценки текущего пользователя для списка id сообщений (-1 / 1)."""
    init_portal_db(conn)
    if not message_ids:
        return {}
    ids = [int(x) for x in message_ids]
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"""
        SELECT message_id, rating FROM ai_chat_message_feedback
        WHERE user_id = ? AND message_id IN ({placeholders})
        """,
        (int(user_id), *ids),
    ).fetchall()
    return {int(r["message_id"]): int(r["rating"]) for r in rows}


def set_ai_chat_message_feedback(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    message_id: int,
    group_id: int,
    rating: int,
    comment: str = "",
) -> None:
    """Сохранить или сбросить оценку ответа AI в канале ai_assistant (rating: -1, 0 сброс, 1)."""
    init_portal_db(conn)
    rating_i = int(rating)
    if rating_i not in (-1, 0, 1):
        raise ValueError("rating")

    row = conn.execute(
        "SELECT group_id, user_id FROM chat_messages WHERE id = ?",
        (int(message_id),),
    ).fetchone()
    if not row:
        raise ValueError("message_not_found")
    if int(row["group_id"]) != int(group_id):
        raise ValueError("group_mismatch")

    gname = get_chat_group_name(conn, int(group_id))
    if gname != CHAT_CHANNEL_AI_ASSISTANT:
        raise ValueError("not_ai_channel")

    ai_uid = ensure_ai_assistant_user(conn)
    if int(row["user_id"]) != int(ai_uid):
        raise ValueError("not_ai_message")

    cmt = str(comment or "").strip()[:2000]
    if rating_i == 0:
        conn.execute(
            """
            DELETE FROM ai_chat_message_feedback
            WHERE user_id = ? AND message_id = ?
            """,
            (int(user_id), int(message_id)),
        )
    else:
        conn.execute(
            """
            INSERT INTO ai_chat_message_feedback
                (user_id, message_id, rating, comment, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, message_id) DO UPDATE SET
                rating = excluded.rating,
                comment = excluded.comment,
                updated_at = CURRENT_TIMESTAMP
            """,
            (int(user_id), int(message_id), rating_i, cmt),
        )
    conn.commit()


def get_ai_chat_feedback_admin_overview(
    conn: sqlite3.Connection,
    *,
    recent_limit: int = 50,
) -> dict[str, Any]:
    """Сводка и последние оценки ответов EAVC Manager в AI-чате (для админки)."""
    init_portal_db(conn)
    lim = max(1, min(int(recent_limit or 50), 200))

    by_rating: dict[int, int] = {}
    for r in conn.execute(
        "SELECT rating, COUNT(*) AS c FROM ai_chat_message_feedback GROUP BY rating"
    ).fetchall():
        by_rating[int(r["rating"])] = int(r["c"])
    up = by_rating.get(1, 0)
    down = by_rating.get(-1, 0)
    total = up + down

    urow = conn.execute(
        """
        SELECT COUNT(DISTINCT user_id) AS voters,
               COUNT(DISTINCT message_id) AS messages
        FROM ai_chat_message_feedback
        """
    ).fetchone()
    unique_voters = int(urow["voters"] or 0) if urow else 0
    unique_messages = int(urow["messages"] or 0) if urow else 0

    recent_rows = conn.execute(
        """
        SELECT f.updated_at, f.user_id, f.message_id, f.rating,
               f.comment, u.username, u.callsign,
               substr(COALESCE(m.message_text, ''), 1, 400) AS message_preview
        FROM ai_chat_message_feedback f
        JOIN users u ON u.id = f.user_id
        JOIN chat_messages m ON m.id = f.message_id
        ORDER BY f.updated_at DESC, f.message_id DESC
        LIMIT ?
        """,
        (lim,),
    ).fetchall()

    recent: list[dict[str, Any]] = []
    for r in recent_rows:
        recent.append(
            {
                "updated_at": str(r["updated_at"] or ""),
                "user_id": int(r["user_id"]),
                "message_id": int(r["message_id"]),
                "rating": int(r["rating"]),
                "comment": str(r["comment"] or "")[:2000],
                "voter_username": str(r["username"] or ""),
                "voter_callsign": str(r["callsign"] or ""),
                "message_preview": str(r["message_preview"] or ""),
            }
        )

    return {
        "stats": {
            "total_ratings": total,
            "thumbs_up": up,
            "thumbs_down": down,
            "net_score": up - down,
            "helpful_ratio": (up / total) if total else None,
            "unique_voters": unique_voters,
            "unique_messages_rated": unique_messages,
        },
        "recent": recent,
    }


def get_ai_agent_memory(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    scope: str = "ai_assistant",
) -> dict[str, Any]:
    init_portal_db(conn)
    row = conn.execute(
        """
        SELECT memory_json
        FROM ai_agent_memory
        WHERE user_id=? AND scope=?
        """,
        (int(user_id), str(scope or "ai_assistant")),
    ).fetchone()
    if not row:
        return {}
    try:
        obj = json.loads(str(row["memory_json"] or "{}"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def set_ai_agent_memory(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    scope: str = "ai_assistant",
    memory: dict[str, Any] | None = None,
) -> None:
    init_portal_db(conn)
    payload = json.dumps(memory or {}, ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO ai_agent_memory (user_id, scope, memory_json, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, scope) DO UPDATE SET
            memory_json=excluded.memory_json,
            updated_at=CURRENT_TIMESTAMP
        """,
        (int(user_id), str(scope or "ai_assistant"), payload),
    )
    conn.commit()


def log_ai_agent_action(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    message_id: int | None,
    goal: str,
    tool: str,
    risk: str,
    args: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    confirmed: bool = False,
    changed: bool = False,
) -> int:
    init_portal_db(conn)
    conn.execute(
        """
        INSERT INTO ai_agent_actions (
            user_id, message_id, goal, tool, risk, args_json, result_json, confirmed, changed
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(user_id),
            int(message_id) if message_id else None,
            str(goal or ""),
            str(tool or ""),
            str(risk or ""),
            json.dumps(args or {}, ensure_ascii=False),
            json.dumps(result or {}, ensure_ascii=False),
            1 if confirmed else 0,
            1 if changed else 0,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
    return int(row["id"] if row and "id" in row.keys() else 0)


def list_ai_agent_actions(
    conn: sqlite3.Connection,
    *,
    user_id: int | None = None,
    limit: int = 100,
    tool: str = "",
) -> list[dict[str, Any]]:
    init_portal_db(conn)
    clauses: list[str] = []
    params: list[Any] = []
    if user_id:
        clauses.append("a.user_id=?")
        params.append(int(user_id))
    if tool:
        clauses.append("a.tool=?")
        params.append(str(tool))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT
          a.id, a.user_id, u.username, u.callsign, a.message_id, a.goal, a.tool, a.risk,
          a.args_json, a.result_json, a.confirmed, a.changed, a.created_at
        FROM ai_agent_actions a
        LEFT JOIN users u ON u.id = a.user_id
        {where}
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT ?
        """,
        (*params, max(1, min(int(limit or 100), 500))),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            args = json.loads(str(row["args_json"] or "{}"))
        except Exception:
            args = {}
        try:
            result = json.loads(str(row["result_json"] or "{}"))
        except Exception:
            result = {}
        out.append(
            {
                "id": int(row["id"]),
                "user_id": int(row["user_id"]),
                "username": str(row["username"] or ""),
                "callsign": str(row["callsign"] or ""),
                "message_id": int(row["message_id"] or 0),
                "goal": str(row["goal"] or ""),
                "tool": str(row["tool"] or ""),
                "risk": str(row["risk"] or ""),
                "args": args,
                "result": result,
                "confirmed": bool(row["confirmed"]),
                "changed": bool(row["changed"]),
                "created_at": str(row["created_at"] or ""),
            }
        )
    return out


def create_chat_file(
    conn: sqlite3.Connection,
    *,
    original_filename: str,
    stored_filename: str,
    file_size: int,
    mime_type: str,
    uploaded_by: int,
) -> int:
    """Создать запись о файле в чате."""
    init_portal_db(conn)
    import uuid as uuid_lib

    file_uuid = str(uuid_lib.uuid4())
    conn.execute(
        """
        INSERT INTO chat_files (uuid, original_filename, stored_filename, file_size, mime_type, uploaded_by)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            file_uuid,
            str(original_filename or "").strip(),
            str(stored_filename or "").strip(),
            int(file_size or 0),
            str(mime_type or "application/octet-stream").strip(),
            int(uploaded_by),
        ),
    )
    conn.commit()
    r = conn.execute("SELECT id FROM chat_files WHERE uuid=?", (file_uuid,)).fetchone()
    return int(r["id"])


def get_chat_file(conn: sqlite3.Connection, file_id: int) -> dict[str, Any] | None:
    """Получить информацию о файле чата."""
    init_portal_db(conn)
    r = conn.execute(
        """
        SELECT id, uuid, original_filename, stored_filename, file_size, mime_type, uploaded_by, created_at
        FROM chat_files
        WHERE id = ?
        """,
        (int(file_id),),
    ).fetchone()
    if not r:
        return None
    return {
        "id": int(r["id"]),
        "uuid": str(r["uuid"] or ""),
        "original_filename": str(r["original_filename"] or ""),
        "stored_filename": str(r["stored_filename"] or ""),
        "file_size": int(r["file_size"] or 0),
        "mime_type": str(r["mime_type"] or ""),
        "uploaded_by": int(r["uploaded_by"]),
        "created_at": str(r["created_at"] or ""),
    }


def list_chat_messages_since(
    conn: sqlite3.Connection, *, since_ts: str, group_id: int | None = None
) -> list[dict[str, Any]]:
    """Получить сообщения чата для синхронизации."""
    init_portal_db(conn)
    since = str(since_ts or "").strip() or "1970-01-01 00:00:00"

    if group_id is None:
        group_id = ensure_chat_group(conn, name="general")

    rows = conn.execute(
        """
        SELECT m.uuid, m.group_id, m.user_id, m.message_text, m.file_id, m.created_at,
               u.username, u.callsign,
               f.uuid as file_uuid, f.original_filename, f.stored_filename, f.file_size, f.mime_type
        FROM chat_messages m
        JOIN users u ON u.id = m.user_id
        LEFT JOIN chat_files f ON f.id = m.file_id
        WHERE m.group_id = ? AND m.created_at > ?
        ORDER BY m.created_at ASC
        """,
        (group_id, since),
    ).fetchall()

    result = []
    for r in rows:
        msg = {
            "uuid": str(r["uuid"] or ""),
            "group_id": int(r["group_id"]) if r["group_id"] else None,
            "user_id": int(r["user_id"]),
            "username": str(r["username"] or ""),
            "callsign": str(r["callsign"] or ""),
            "message_text": str(r["message_text"] or ""),
            "created_at": str(r["created_at"] or ""),
        }
        if r["file_id"]:
            msg["file"] = {
                "uuid": str(r["file_uuid"] or ""),
                "original_filename": str(r["original_filename"] or ""),
                "stored_filename": str(r["stored_filename"] or ""),
                "file_size": int(r["file_size"] or 0),
                "mime_type": str(r["mime_type"] or ""),
            }
        result.append(msg)

    return result


def upsert_chat_message_from_sync(
    conn: sqlite3.Connection, *, payload: dict[str, Any]
) -> int:
    """Upsert сообщения чата из синхронизации."""
    init_portal_db(conn)
    p = payload or {}
    msg_uuid = str(p.get("uuid") or "").strip()
    if not msg_uuid:
        raise ValueError("uuid обязателен")

    # Проверяем по UUID
    r = conn.execute(
        "SELECT id FROM chat_messages WHERE uuid=?", (msg_uuid,)
    ).fetchone()
    if r:
        return int(r["id"])

    # Находим user_id по username
    username = str(p.get("username") or "").strip()
    if not username:
        raise ValueError("username обязателен")

    user_row = conn.execute(
        "SELECT id FROM users WHERE username=?", (username,)
    ).fetchone()
    if not user_row:
        raise ValueError(f"user not found: {username}")
    user_id = int(user_row["id"])

    group_id = None
    if p.get("group_id"):
        group_id = int(p.get("group_id"))
    if group_id is None:
        group_id = ensure_chat_group(conn, name="general")

    file_id = None
    if p.get("file") and isinstance(p["file"], dict):
        file_info = p["file"]
        file_uuid = str(file_info.get("uuid") or "").strip()
        if file_uuid:
            file_row = conn.execute(
                "SELECT id FROM chat_files WHERE uuid=?", (file_uuid,)
            ).fetchone()
            if file_row:
                file_id = int(file_row["id"])

    conn.execute(
        """
        INSERT INTO chat_messages (uuid, group_id, user_id, message_text, file_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            msg_uuid,
            group_id,
            user_id,
            str(p.get("message_text") or "").strip(),
            file_id,
            str(p.get("created_at") or "").strip() or None,
        ),
    )
    conn.commit()
    r = conn.execute(
        "SELECT id FROM chat_messages WHERE uuid=?", (msg_uuid,)
    ).fetchone()
    return int(r["id"])
