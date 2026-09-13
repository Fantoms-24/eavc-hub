"""
База данных для системы отслеживания авиации.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any
from datetime import datetime


def init_aviation(conn: sqlite3.Connection) -> None:
    """
    Инициализация таблиц для авиации:
    - aviation_frequencies: частоты с типом авиации
    - aviation_intercepts: бланки перехвата (агрегат / совместимость)
    - aviation_daily_intercepts: бланк за календарный рабочий день (frequency + YYYY-MM-DD)
    - aviation_callsigns: позывные с типом карточки (НПУ/Борт)
    - aviation_callsign_history: история выходов позывных
    """
    cur = conn.cursor()
    
    # Таблица частот авиации
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS aviation_frequencies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            frequency TEXT NOT NULL,
            aviation_type TEXT NOT NULL CHECK (aviation_type IN ('Армейская авиация', 'Тактическая авиация')),
            uuid TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(frequency, aviation_type)
        );
        """
    )
    # Миграция: разрешить типы "ЯК", "F-16" (после миграции н/у)
    def _migrate_aviation_types():
        try:
            cur.execute(
                "INSERT INTO aviation_frequencies (frequency, aviation_type, uuid) VALUES ('__migrate_check__', 'F-16', '')"
            )
            cur.execute("DELETE FROM aviation_frequencies WHERE frequency = '__migrate_check__'")
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            cur.execute(
                """
                CREATE TABLE aviation_frequencies_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    frequency TEXT NOT NULL,
                    aviation_type TEXT NOT NULL CHECK (aviation_type IN ('Армейская авиация', 'Тактическая авиация', 'н/у', 'ЯК', 'F-16')),
                    uuid TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(frequency, aviation_type)
                );
                """
            )
            cur.execute(
                """
                INSERT INTO aviation_frequencies_new (id, frequency, aviation_type, uuid, created_at, updated_at)
                SELECT id, frequency, aviation_type, uuid, created_at, updated_at FROM aviation_frequencies
                """
            )
            cur.execute("DROP TABLE aviation_frequencies")
            cur.execute("ALTER TABLE aviation_frequencies_new RENAME TO aviation_frequencies")
            conn.commit()
        except Exception:
            conn.rollback()

    try:
        cur.execute(
            "INSERT INTO aviation_frequencies (frequency, aviation_type, uuid) VALUES ('__migrate_nu__', 'н/у', '')"
        )
        cur.execute("DELETE FROM aviation_frequencies WHERE frequency = '__migrate_nu__'")
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        cur.execute(
            """
            CREATE TABLE aviation_frequencies_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                frequency TEXT NOT NULL,
                aviation_type TEXT NOT NULL CHECK (aviation_type IN ('Армейская авиация', 'Тактическая авиация', 'н/у')),
                uuid TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(frequency, aviation_type)
            );
            """
        )
        cur.execute(
            """
            INSERT INTO aviation_frequencies_new (id, frequency, aviation_type, uuid, created_at, updated_at)
            SELECT id, frequency, aviation_type, uuid, created_at, updated_at FROM aviation_frequencies
            """
        )
        cur.execute("DROP TABLE aviation_frequencies")
        cur.execute("ALTER TABLE aviation_frequencies_new RENAME TO aviation_frequencies")
        conn.commit()
    except Exception:
        conn.rollback()

    _migrate_aviation_types()

    # Таблица бланков перехвата авиации
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS aviation_intercepts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            frequency_id INTEGER NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            uuid TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (frequency_id) REFERENCES aviation_frequencies(id) ON DELETE CASCADE
        );
        """
    )
    # Миграция: для старых БД, где ещё нет колонки uuid у aviation_intercepts,
    # добавляем её, чтобы синхронизация могла работать (используется в upsert_aviation_intercept_from_sync).
    try:
        cur.execute("PRAGMA table_info(aviation_intercepts)")
        columns = [col[1] for col in cur.fetchall()]
        if "uuid" not in columns:
            cur.execute(
                "ALTER TABLE aviation_intercepts ADD COLUMN uuid TEXT NOT NULL DEFAULT ''"
            )
    except Exception:
        # Если по какой-то причине миграция не удалась, не блокируем работу портала;
        # но синхронизация перехватов авиации может не работать до ручного обновления схемы.
        pass
    
    # Таблица позывных авиации
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS aviation_callsigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            frequency_id INTEGER,
            label TEXT NOT NULL,
            card_type TEXT NOT NULL CHECK (card_type IN ('НПУ', 'Борт')),
            uuid TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (frequency_id) REFERENCES aviation_frequencies(id) ON DELETE SET NULL
        );
        """
    )
    
    # Миграция: удаляем колонку code если она существует (для старых БД)
    # SQLite не поддерживает DROP COLUMN напрямую, поэтому создаём новую таблицу
    try:
        # Проверяем, существует ли колонка code
        cur.execute("PRAGMA table_info(aviation_callsigns)")
        columns = [col[1] for col in cur.fetchall()]
        if "code" in columns:
            # Создаём временную таблицу без колонки code
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aviation_callsigns_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    frequency_id INTEGER,
                    label TEXT NOT NULL,
                    card_type TEXT NOT NULL CHECK (card_type IN ('НПУ', 'Борт')),
                    uuid TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (frequency_id) REFERENCES aviation_frequencies(id) ON DELETE SET NULL
                );
            """)
            # Копируем данные без колонки code
            cur.execute("""
                INSERT INTO aviation_callsigns_new (id, frequency_id, label, card_type, uuid, created_at, updated_at)
                SELECT id, frequency_id, label, card_type, uuid, created_at, updated_at
                FROM aviation_callsigns
            """)
            # Удаляем старую таблицу
            cur.execute("DROP TABLE aviation_callsigns")
            # Переименовываем новую таблицу
            cur.execute("ALTER TABLE aviation_callsigns_new RENAME TO aviation_callsigns")
            conn.commit()
    except sqlite3.OperationalError as e:
        # Если ошибка - возможно таблица уже правильная или другой тип ошибки
        conn.rollback()
        pass
    
    # Таблица истории выходов позывных (не синхронизируется, только локально)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS aviation_callsign_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            callsign_id INTEGER NOT NULL,
            frequency_id INTEGER,
            timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            content_snippet TEXT,
            FOREIGN KEY (callsign_id) REFERENCES aviation_callsigns(id) ON DELETE CASCADE,
            FOREIGN KEY (frequency_id) REFERENCES aviation_frequencies(id) ON DELETE SET NULL
        );
        """
    )
    
    # Миграция: добавляем UUID колонки если их нет
    try:
        cur.execute("ALTER TABLE aviation_frequencies ADD COLUMN uuid TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # Колонка уже существует
    
    try:
        cur.execute("ALTER TABLE aviation_intercepts ADD COLUMN uuid TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # Колонка уже существует
    
    try:
        cur.execute("ALTER TABLE aviation_callsigns ADD COLUMN uuid TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # Колонка уже существует

    # Дневные бланки перехвата (рабочий день YYYY-MM-DD) — до этого был один blob на частоту
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS aviation_daily_intercepts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            frequency_id INTEGER NOT NULL,
            work_date TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            uuid TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (frequency_id) REFERENCES aviation_frequencies(id) ON DELETE CASCADE,
            UNIQUE(frequency_id, work_date)
        );
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_aviation_daily_freq_date ON aviation_daily_intercepts(frequency_id, work_date);"
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS aviation_internal_meta (
            k TEXT PRIMARY KEY,
            v TEXT NOT NULL
        );
        """
    )

    # Один раз: перенос старых общих бланков в aviation_daily_intercepts по дате сохранения.
    # До этого миграция вызывалась на КАЖДЫЙ запрос через init_db→init_aviation (полный скан + N проверок)
    # и могла «подвешивать» UI на минуты при больших таблицах.
    cur.execute(
        "SELECT v FROM aviation_internal_meta WHERE k = 'legacy_intercept_daily_v1' LIMIT 1"
    )
    _meta_daily = cur.fetchone()
    if not (_meta_daily and str(_meta_daily[0] or "").strip() == "done"):
        try:
            cur.execute(
                """
                INSERT OR IGNORE INTO aviation_daily_intercepts
                    (frequency_id, work_date, content, uuid, updated_at)
                SELECT
                    i.frequency_id,
                    substr(trim(i.updated_at), 1, 10) AS work_date,
                    i.content,
                    lower(hex(randomblob(16))),
                    i.updated_at
                FROM aviation_intercepts i
                WHERE trim(coalesce(i.content, '')) != ''
                  AND length(trim(coalesce(i.updated_at, ''))) >= 10
                  AND substr(trim(i.updated_at), 5, 1) = '-'
                  AND substr(trim(i.updated_at), 8, 1) = '-'
                """
            )
            cur.execute(
                """
                INSERT OR REPLACE INTO aviation_internal_meta (k, v)
                VALUES ('legacy_intercept_daily_v1', 'done')
                """
            )
            conn.commit()
        except Exception:
            conn.rollback()
    
    # Генерируем UUID для существующих записей без UUID
    import uuid as uuid_lib
    for table in ['aviation_frequencies', 'aviation_intercepts', 'aviation_callsigns']:
        cur.execute(f"SELECT id FROM {table} WHERE uuid = '' OR uuid IS NULL")
        rows = cur.fetchall()
        for row in rows:
            new_uuid = str(uuid_lib.uuid4())
            cur.execute(f"UPDATE {table} SET uuid = ? WHERE id = ?", (new_uuid, row[0]))
    
    # Индексы
    cur.execute("CREATE INDEX IF NOT EXISTS idx_aviation_freq_type ON aviation_frequencies(frequency, aviation_type);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_aviation_freq_uuid ON aviation_frequencies(uuid);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_aviation_intercepts_freq ON aviation_intercepts(frequency_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_aviation_intercepts_uuid ON aviation_intercepts(uuid);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_aviation_callsigns_freq ON aviation_callsigns(frequency_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_aviation_callsigns_uuid ON aviation_callsigns(uuid);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_aviation_callsigns_label ON aviation_callsigns(label);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_aviation_history_callsign ON aviation_callsign_history(callsign_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_aviation_history_timestamp ON aviation_callsign_history(timestamp);")
    
    conn.commit()


def get_aviation_frequencies(
    conn: sqlite3.Connection, *, date: str | None = None
) -> list[dict[str, Any]]:
    """Получить список всех частот авиации (опционально фильтр по дате)."""
    cur = conn.cursor()
    if date:
        # Показываем частоты, которые существовали на эту дату (созданы до или в этот день)
        # и были обновлены в этот день или позже (имеют данные за этот день)
        cur.execute(
            """
            SELECT DISTINCT f.id, f.frequency, f.aviation_type, f.created_at, f.updated_at
            FROM aviation_frequencies f
            LEFT JOIN aviation_intercepts i ON f.id = i.frequency_id
            WHERE DATE(f.created_at) <= ?
              AND (DATE(f.updated_at) >= ? OR DATE(i.updated_at) >= ? OR i.updated_at IS NULL)
            ORDER BY f.frequency, f.aviation_type
            """,
            (date, date, date),
        )
    else:
        cur.execute(
            """
            SELECT id, frequency, aviation_type, created_at, updated_at
            FROM aviation_frequencies
            ORDER BY frequency, aviation_type
            """
        )
    rows = cur.fetchall()
    last_map = _get_aviation_last_records_map(conn)
    frequencies = [
        {
            "id": r[0],
            "frequency": r[1],
            "aviation_type": r[2],
            "created_at": r[3],
            "updated_at": r[4],
        }
        for r in rows
    ]
    for freq in frequencies:
        last = last_map.get(int(freq["id"]), {})
        freq["last_record_at"] = last.get("last_record_at")
        freq["last_work_date"] = last.get("last_work_date")
    return frequencies


def get_aviation_frequency(
    conn: sqlite3.Connection, *, frequency_id: int
) -> dict[str, Any] | None:
    """Получить одну частоту авиации по id без загрузки всего списка."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, frequency, aviation_type, created_at, updated_at
        FROM aviation_frequencies
        WHERE id = ?
        """,
        (int(frequency_id),),
    )
    r = cur.fetchone()
    if not r:
        return None
    return {
        "id": r[0],
        "frequency": r[1],
        "aviation_type": r[2],
        "created_at": r[3],
        "updated_at": r[4],
    }


def create_aviation_frequency(
    conn: sqlite3.Connection, *, frequency: str, aviation_type: str
) -> int:
    """Создать новую частоту авиации."""
    import uuid
    cur = conn.cursor()
    new_uuid = str(uuid.uuid4())
    try:
        cur.execute(
            """
            INSERT INTO aviation_frequencies (frequency, aviation_type, uuid, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (frequency, aviation_type, new_uuid),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        # Частота уже существует
        cur.execute(
            """
            SELECT id, uuid FROM aviation_frequencies
            WHERE frequency = ? AND aviation_type = ?
            """,
            (frequency, aviation_type),
        )
        row = cur.fetchone()
        if not row:
            return 0
        rid = int(row[0])
        existing_uuid = str(row[1] or "").strip() if len(row) > 1 else ""
        if not existing_uuid:
            cur.execute(
                """
                UPDATE aviation_frequencies
                SET uuid = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (str(uuid.uuid4()), rid),
            )
            conn.commit()
        return rid


def delete_aviation_frequency(conn: sqlite3.Connection, *, frequency_id: int) -> bool:
    """Удалить частоту авиации."""
    cur = conn.cursor()
    cur.execute("DELETE FROM aviation_frequencies WHERE id = ?", (frequency_id,))
    conn.commit()
    return cur.rowcount > 0


def update_aviation_frequency(
    conn: sqlite3.Connection, *, frequency_id: int, aviation_type: str
) -> bool:
    """Обновить тип авиации у частоты (например, сменить н/у на Тактическая авиация)."""
    allowed = ("Армейская авиация", "Тактическая авиация", "н/у", "ЯК", "F-16")
    if aviation_type not in allowed:
        return False
    cur = conn.cursor()
    cur.execute(
        "UPDATE aviation_frequencies SET aviation_type = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (aviation_type, frequency_id),
    )
    conn.commit()
    return cur.rowcount > 0


def get_aviation_intercept(
    conn: sqlite3.Connection, *, frequency_id: int
) -> dict[str, Any] | None:
    """Получить бланк перехвата для частоты."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, frequency_id, content, created_at, updated_at
        FROM aviation_intercepts
        WHERE frequency_id = ?
        """,
        (frequency_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "frequency_id": row[1],
        "content": row[2],
        "created_at": row[3],
        "updated_at": row[4],
    }


def normalize_aviation_work_date(date_str: str | None) -> str | None:
    """YYYY-MM-DD или None."""
    s = str(date_str or "").strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return None


def _legacy_intercept_content_for_calendar_day(
    conn: sqlite3.Connection, *, frequency_id: int, work_date: str
) -> tuple[str, str]:
    """
    Старый режим: один бланк на частоту. Показываем его только для календарного дня,
    совпадающего с датой последнего сохранения (до внедрения дневных бланков).
    """
    leg = get_aviation_intercept(conn, frequency_id=frequency_id)
    if not leg:
        return "", ""
    lu = str(leg.get("updated_at") or "").strip()
    if len(lu) >= 10 and lu[:10] == work_date:
        return str(leg.get("content") or ""), lu
    return "", ""


def get_aviation_intercept_for_api(
    conn: sqlite3.Connection, *, frequency_id: int, work_date: str | None
) -> dict[str, Any] | None:
    """
    Бланк для UI: без work_date — aviation_intercepts;
    с work_date — отдельный текст за этот день (таблица aviation_daily_intercepts).
    """
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM aviation_frequencies WHERE id = ?", (frequency_id,))
    if not cur.fetchone():
        return None

    wd = normalize_aviation_work_date(work_date) if work_date else None
    if not wd:
        return get_aviation_intercept(conn, frequency_id=frequency_id)

    cur.execute(
        """
        SELECT id, content, updated_at
        FROM aviation_daily_intercepts
        WHERE frequency_id = ? AND work_date = ?
        """,
        (frequency_id, wd),
    )
    dr = cur.fetchone()
    if dr:
        return {
            "id": dr[0],
            "frequency_id": frequency_id,
            "content": str(dr[1] if dr[1] is not None else ""),
            "updated_at": dr[2],
            "work_date": wd,
        }
    lc, lu = _legacy_intercept_content_for_calendar_day(
        conn, frequency_id=frequency_id, work_date=wd
    )
    return {
        "id": None,
        "frequency_id": frequency_id,
        "content": lc,
        "updated_at": lu or "",
        "work_date": wd,
    }


def upsert_aviation_daily_intercept(
    conn: sqlite3.Connection, *, frequency_id: int, work_date: str, content: str
) -> int:
    import uuid

    wd = normalize_aviation_work_date(work_date)
    if not wd:
        raise ValueError("Некорректная дата рабочего дня")

    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, uuid FROM aviation_daily_intercepts
        WHERE frequency_id = ? AND work_date = ?
        """,
        (frequency_id, wd),
    )
    row = cur.fetchone()
    if row:
        iid = int(row[0])
        existing_uuid = str(row[1] or "").strip() if len(row) > 1 else ""
        if not existing_uuid:
            new_uuid = str(uuid.uuid4())
            cur.execute(
                """
                UPDATE aviation_daily_intercepts
                SET content = ?, uuid = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (content, new_uuid, iid),
            )
        else:
            cur.execute(
                """
                UPDATE aviation_daily_intercepts
                SET content = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (content, iid),
            )
        conn.commit()
        return iid

    new_uuid = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO aviation_daily_intercepts
            (frequency_id, work_date, content, uuid, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (frequency_id, wd, content, new_uuid),
    )
    conn.commit()
    return int(cur.lastrowid)


def create_or_update_aviation_intercept(
    conn: sqlite3.Connection, *, frequency_id: int, content: str
) -> int:
    """Создать или обновить бланк перехвата."""
    import uuid
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, uuid FROM aviation_intercepts WHERE frequency_id = ?
        """,
        (frequency_id,),
    )
    row = cur.fetchone()
    if row:
        intercept_id = row[0]
        existing_uuid = row[1] if len(row) > 1 else None
        # Генерируем UUID если его нет
        if not existing_uuid or existing_uuid == "":
            new_uuid = str(uuid.uuid4())
            cur.execute(
                """
                UPDATE aviation_intercepts
                SET content = ?, uuid = ?, updated_at = CURRENT_TIMESTAMP
                WHERE frequency_id = ?
                """,
                (content, new_uuid, frequency_id),
            )
        else:
            cur.execute(
                """
                UPDATE aviation_intercepts
                SET content = ?, updated_at = CURRENT_TIMESTAMP
                WHERE frequency_id = ?
                """,
                (content, frequency_id),
            )
        conn.commit()
        return intercept_id
    else:
        new_uuid = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO aviation_intercepts (frequency_id, content, uuid, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (frequency_id, content, new_uuid),
        )
        conn.commit()
        return cur.lastrowid


def get_aviation_callsigns(
    conn: sqlite3.Connection, *, frequency_id: int | None = None
) -> list[dict[str, Any]]:
    """Получить список позывных: при frequency_id=None — общий список (все позывные)."""
    cur = conn.cursor()
    if frequency_id:
        cur.execute(
            """
            SELECT id, frequency_id, label, card_type, created_at, updated_at
            FROM aviation_callsigns
            WHERE frequency_id = ?
            ORDER BY label
            """,
            (frequency_id,),
        )
    else:
        cur.execute(
            """
            SELECT id, frequency_id, label, card_type, created_at, updated_at
            FROM aviation_callsigns
            ORDER BY label
            """
        )
    rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "frequency_id": r[1],
            "label": r[2],
            "card_type": r[3],
            "created_at": r[4],
            "updated_at": r[5],
        }
        for r in rows
    ]


def create_aviation_callsign(
    conn: sqlite3.Connection,
    *,
    frequency_id: int | None,
    label: str,
    card_type: str,
) -> int:
    """Создать новый позывной."""
    import uuid
    cur = conn.cursor()
    new_uuid = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO aviation_callsigns (frequency_id, label, card_type, uuid, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (frequency_id, label, card_type, new_uuid),
    )
    conn.commit()
    return cur.lastrowid


def get_aviation_callsign_by_label(
    conn: sqlite3.Connection, *, label: str, frequency_id: int | None = None
) -> dict[str, Any] | None:
    """Найти позывной по label."""
    cur = conn.cursor()
    if frequency_id:
        cur.execute(
            """
            SELECT id, frequency_id, label, card_type, created_at, updated_at
            FROM aviation_callsigns
            WHERE label = ? AND frequency_id = ?
            LIMIT 1
            """,
            (label, frequency_id),
        )
    else:
        cur.execute(
            """
            SELECT id, frequency_id, label, card_type, created_at, updated_at
            FROM aviation_callsigns
            WHERE label = ?
            LIMIT 1
            """,
            (label,),
        )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "frequency_id": row[1],
        "label": row[2],
        "card_type": row[3],
        "created_at": row[4],
        "updated_at": row[5],
    }


def delete_aviation_callsign(conn: sqlite3.Connection, *, label: str, frequency_id: int | None = None) -> bool:
    """Удалить позывной по label."""
    cur = conn.cursor()
    if frequency_id:
        cur.execute(
            "DELETE FROM aviation_callsigns WHERE label = ? AND frequency_id = ?",
            (label, frequency_id),
        )
    else:
        cur.execute(
            "DELETE FROM aviation_callsigns WHERE label = ?",
            (label,),
        )
    conn.commit()
    return cur.rowcount > 0


def add_callsign_history_entry(
    conn: sqlite3.Connection,
    *,
    label: str,
    frequency_id: int | None,
    timestamp: str | None = None,
    content_snippet: str | None = None,
) -> int:
    """Добавить запись в историю выходов позывного по label."""
    cur = conn.cursor()
    # Находим callsign_id по label
    callsign = get_aviation_callsign_by_label(conn, label=label, frequency_id=frequency_id)
    if not callsign:
        # Если позывной не найден, создаем его
        callsign_id = create_aviation_callsign(
            conn,
            frequency_id=frequency_id,
            label=label,
            card_type="НПУ",  # По умолчанию
        )
    else:
        callsign_id = callsign["id"]
    
    if timestamp:
        cur.execute(
            """
            INSERT INTO aviation_callsign_history (callsign_id, frequency_id, timestamp, content_snippet)
            VALUES (?, ?, ?, ?)
            """,
            (callsign_id, frequency_id, timestamp, content_snippet),
        )
    else:
        cur.execute(
            """
            INSERT INTO aviation_callsign_history (callsign_id, frequency_id, content_snippet)
            VALUES (?, ?, ?)
            """,
            (callsign_id, frequency_id, content_snippet),
        )
    conn.commit()
    return cur.lastrowid


def ensure_callsign_exit_for_date(
    conn: sqlite3.Connection,
    *,
    callsign_id: int,
    frequency_id: int | None,
    date_str: str,
) -> bool:
    """
    Гарантировать один выход позывного на частоту в указанную дату (вариант А:
    добавление позывного к частоте = выход на эту дату). Если запись уже есть — не дублировать.
    date_str: YYYY-MM-DD.
    Возвращает True, если добавлена новая запись, False если выход уже был.
    """
    if not date_str or not callsign_id:
        return False
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 1 FROM aviation_callsign_history
        WHERE callsign_id = ? AND (frequency_id = ? OR (frequency_id IS NULL AND ? IS NULL))
        AND DATE(timestamp) = ?
        LIMIT 1
        """,
        (callsign_id, frequency_id, frequency_id, date_str),
    )
    if cur.fetchone():
        return False
    ts = f"{date_str} 12:00:00"
    cur.execute(
        """
        INSERT INTO aviation_callsign_history (callsign_id, frequency_id, timestamp, content_snippet)
        VALUES (?, ?, ?, NULL)
        """,
        (callsign_id, frequency_id, ts),
    )
    conn.commit()
    return True


def get_callsign_history(
    conn: sqlite3.Connection, *, label: str, frequency_id: int | None = None, date: str | None = None
) -> list[dict[str, Any]]:
    """
    Получить историю выходов позывного по label.
    Группирует по частоте и дню - одна частота в один день = один выход.
    Если указан date, фильтрует по этому дню.
    """
    cur = conn.cursor()
    # Находим позывной по label
    callsign = get_aviation_callsign_by_label(conn, label=label, frequency_id=frequency_id)
    if not callsign:
        return []
    
    callsign_id = callsign["id"]
    
    # Группируем по частоте и дню, берем первое время и первый фрагмент для каждой группы
    query = """
        SELECT 
            h.frequency_id,
            f.frequency,
            DATE(h.timestamp) as day,
            MIN(h.timestamp) as first_timestamp,
            MIN(h.content_snippet) as content_snippet,
            COUNT(*) as occurrences
        FROM aviation_callsign_history h
        LEFT JOIN aviation_frequencies f ON h.frequency_id = f.id
        WHERE h.callsign_id = ? AND h.timestamp IS NOT NULL
    """
    params = [callsign_id]
    
    if date:
        query += " AND DATE(h.timestamp) = ?"
        params.append(date)
    
    query += """
        GROUP BY h.frequency_id, DATE(h.timestamp)
        ORDER BY first_timestamp DESC
    """
    
    cur.execute(query, tuple(params))
    rows = cur.fetchall()
    return [
        {
            "frequency_id": r[0],
            "frequency": r[1] or "",
            "day": r[2],
            "timestamp": r[3],
            "content_snippet": r[4] or "",
            "occurrences": r[5],  # Количество вхождений в этот день на этой частоте
        }
        for r in rows
    ]


def parse_aviation_content_for_callsigns(content: str, known_callsigns: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """
    Парсит содержимое бланка и извлекает позывные по их названиям.
    Возвращает список словарей с label и временем (если найдено).
    """
    import re
    results = []
    lines = content.split("\n")
    current_time = None
    
    # Создаем список известных позывных для поиска
    known_labels_map: dict[str, str] = {}
    if known_callsigns:
        for cs in known_callsigns:
            label = cs.get("label", "").strip()
            if label:
                known_labels_map[label.lower()] = label
    
    for line in lines:
        line = line.strip()
        # Проверяем, является ли строка временным заголовком (например, "12.11" или "12:11")
        time_match = re.match(r"^(\d{1,2})[.:](\d{2})$", line)
        if time_match:
            current_time = line
            continue
        
        # Ищем позывные в строке
        if known_labels_map:
            # Ищем известные позывные
            for label_lc, label_original in known_labels_map.items():
                # Ищем слово целиком (с границами слов)
                pattern = r'\b' + re.escape(label_lc) + r'\b'
                if re.search(pattern, line, re.IGNORECASE):
                    results.append({
                        "label": label_original,
                        "time": current_time,
                        "snippet": line[:100] if len(line) > 100 else line,
                    })
                    break  # Нашли один позывной в строке
    
    return results


def _count_aviation_time_blocks(content: str) -> int:
    if not content:
        return 0
    lines = content.split("\n")
    return len([line for line in lines if re.match(r"^\d{1,2}[.:]\d{2}", line.strip())])


def _parse_aviation_dt(value: str | None) -> datetime:
    if not value:
        return datetime.min
    raw = str(value).strip()
    if not raw:
        return datetime.min
    normalized = raw.replace(" ", "T", 1)
    for candidate in (normalized, normalized[:16], normalized[:10]):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return datetime.min


def _get_aviation_last_records_map(conn: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    """Последняя непустая запись по каждой частоте (daily + legacy)."""
    init_aviation(conn)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT f.id,
          COALESCE(
            (SELECT di.updated_at FROM aviation_daily_intercepts di
             WHERE di.frequency_id = f.id AND trim(coalesce(di.content, '')) != ''
             ORDER BY datetime(di.updated_at) DESC, di.id DESC LIMIT 1),
            (SELECT i.updated_at FROM aviation_intercepts i
             WHERE i.frequency_id = f.id AND trim(coalesce(i.content, '')) != ''
             ORDER BY datetime(i.updated_at) DESC, i.id DESC LIMIT 1)
          ) AS last_record_at,
          COALESCE(
            (SELECT di.work_date FROM aviation_daily_intercepts di
             WHERE di.frequency_id = f.id AND trim(coalesce(di.content, '')) != ''
             ORDER BY datetime(di.updated_at) DESC, di.id DESC LIMIT 1),
            (SELECT substr(trim(i.updated_at), 1, 10) FROM aviation_intercepts i
             WHERE i.frequency_id = f.id AND trim(coalesce(i.content, '')) != ''
             ORDER BY datetime(i.updated_at) DESC, i.id DESC LIMIT 1)
          ) AS last_work_date
        FROM aviation_frequencies f
        """
    )
    out: dict[int, dict[str, Any]] = {}
    for row in cur.fetchall():
        if not row[1]:
            continue
        out[int(row[0])] = {
            "last_record_at": row[1],
            "last_work_date": row[2],
        }
    return out


def get_aviation_stats(
    conn: sqlite3.Connection,
    *,
    aviation_type: str | None = None,
    date: str | None = None,
) -> list[dict[str, Any]]:
    """
    Получить статистику по частотам авиации.
    last_record_at — когда в последний раз был непустой бланк (по всем дням).
    Если указан date (YYYY-MM-DD), time_blocks считается только за этот рабочий день.
    """
    init_aviation(conn)
    last_map = _get_aviation_last_records_map(conn)
    cur = conn.cursor()
    if date:
        query = """
            SELECT
                f.id,
                f.frequency,
                f.aviation_type,
                COUNT(DISTINCT c.id) as callsigns_count,
                MAX(COALESCE(di.content, '')) as sample_content
            FROM aviation_frequencies f
            LEFT JOIN aviation_daily_intercepts di
                ON f.id = di.frequency_id AND di.work_date = ?
            LEFT JOIN aviation_callsigns c ON f.id = c.frequency_id
        """
        params: list[Any] = [date]
    else:
        query = """
            SELECT
                f.id,
                f.frequency,
                f.aviation_type,
                COUNT(DISTINCT c.id) as callsigns_count,
                MAX(COALESCE(i.content, '')) as sample_content
            FROM aviation_frequencies f
            LEFT JOIN aviation_intercepts i ON f.id = i.frequency_id
            LEFT JOIN aviation_callsigns c ON f.id = c.frequency_id
        """
        params = []

    conditions = []

    if aviation_type:
        conditions.append("f.aviation_type = ?")
        params.append(aviation_type)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " GROUP BY f.id, f.frequency, f.aviation_type"

    cur.execute(query, params)
    rows = cur.fetchall()

    results = []
    for row in rows:
        frequency_id = int(row[0])
        content = str(row[4] or "")
        last = last_map.get(frequency_id, {})
        last_record_at = last.get("last_record_at")
        results.append(
            {
                "frequency_id": frequency_id,
                "frequency": row[1],
                "aviation_type": row[2],
                "has_content": bool(content.strip()),
                "callsigns_count": row[3] or 0,
                "time_blocks": _count_aviation_time_blocks(content),
                "last_updated": last_record_at,
                "last_record_at": last_record_at,
                "last_work_date": last.get("last_work_date"),
            }
        )

    results.sort(
        key=lambda item: _parse_aviation_dt(item.get("last_record_at")),
        reverse=True,
    )
    return results


def get_callsign_stats_by_days(
    conn: sqlite3.Connection, *, label: str, frequency_id: int | None = None, date: str | None = None
) -> list[dict[str, Any]]:
    """
    Получить статистику позывного по дням с группировкой по label.
    Если указан date, фильтрует по этому дню.
    """
    # Находим позывной по label
    callsign = get_aviation_callsign_by_label(conn, label=label, frequency_id=frequency_id)
    if not callsign:
        return []
    
    callsign_id = callsign["id"]
    
    cur = conn.cursor()
    query = """
        SELECT 
            DATE(h.timestamp) as day,
            f.aviation_type,
            f.frequency,
            h.frequency_id,
            COUNT(*) as entries_count
        FROM aviation_callsign_history h
        LEFT JOIN aviation_frequencies f ON h.frequency_id = f.id
        WHERE h.callsign_id = ? AND h.timestamp IS NOT NULL
    """
    params = [callsign_id]
    
    if date:
        query += " AND DATE(h.timestamp) = ?"
        params.append(date)
    
    query += """
        GROUP BY DATE(h.timestamp), f.aviation_type, f.frequency, h.frequency_id
        ORDER BY day DESC, f.frequency
    """
    
    cur.execute(query, tuple(params))
    rows = cur.fetchall()
    result = []
    for r in rows:
        day = r[0]
        # Проверяем, что день валидный (не NULL и не пустая строка)
        if day and isinstance(day, str) and day.strip() and not day.startswith("-"):
            result.append({
                "day": day,
                "aviation_type": r[1] or "Неизвестно",
                "frequency": r[2] or "",
                "frequency_id": r[3],
                "entries_count": r[4],
            })
    return result


def get_intercept_content_by_date(
    conn: sqlite3.Connection, *, frequency_id: int, date: str
) -> str:
    """Текст бланка за календарный день date (YYYY-MM-DD)."""
    wd = normalize_aviation_work_date(date)
    if not wd:
        return ""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT content FROM aviation_daily_intercepts
        WHERE frequency_id = ? AND work_date = ?
        """,
        (frequency_id, wd),
    )
    r = cur.fetchone()
    if r is not None:
        return str(r[0] if r[0] is not None else "")
    c, _u = _legacy_intercept_content_for_calendar_day(
        conn, frequency_id=frequency_id, work_date=wd
    )
    return c
