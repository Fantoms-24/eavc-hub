"""Каталог/смены/пункты перехватов (физически из ``_impl``)."""
from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any

from web_portal.lib.intercept_blocks import (
    StoredBlock,
    day_offset as _block_day_offset,
    parse_blocks as _parse_intercept_blocks,
    reconcile as _reconcile_intercept_blocks,
    sort_key as _block_sort_key,
)
from web_portal.lib.uuid7 import new_uuid7

from web_portal.lib.db.ai import init_ai_tables
from web_portal.lib.db.connection import _commit_if_needed, init_db
from web_portal.lib.db.seans_schema import _table_exists, init_daily_aggregates
from web_portal.lib.db.sql_util import _in_clause, _table_columns
from web_portal.lib.db.sync import _sync_blocks_quietly

_log = logging.getLogger("web_portal.db")


def init_intercepts(conn: sqlite3.Connection) -> None:
    """
    Таблицы для вкладки "Перехваты":
      - intercept_catalog: справочник (позиция -> подразделение/частота/группа)
      - intercept_sessions: смены (позиция -> start/end)
      - intercept_items: записи внутри смены по частоте/группе
    """
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS intercept_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_name TEXT NOT NULL,
            unit_name TEXT NOT NULL,
            frequency TEXT NOT NULL,
            group_code TEXT NOT NULL,
            uuid TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(position_name, frequency, group_code)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS intercept_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_name TEXT NOT NULL,
            uuid TEXT NOT NULL DEFAULT '',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            created_by TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS intercept_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            session_uuid TEXT NOT NULL DEFAULT '',
            unit_name TEXT NOT NULL,
            frequency TEXT NOT NULL,
            group_code TEXT NOT NULL,
            uuid TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            updated_by TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(session_id, frequency, group_code),
            FOREIGN KEY(session_id) REFERENCES intercept_sessions(id) ON DELETE CASCADE
        );
        """
    )
    # Блоки бланка: у каждого блока времени неизменяемый UUIDv7, который переживает
    # правку его текста и времени. Нужен, чтобы правка блока оставалась правкой,
    # а не парой «удалить и создать» — это видит оператор в Telegram.
    # Текст бланка (intercept_items.content) остаётся источником для всех выгрузок.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS intercept_blocks (
            uuid TEXT PRIMARY KEY,
            item_uuid TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            time_key INTEGER,
            day_offset INTEGER NOT NULL DEFAULT 0,
            ord INTEGER NOT NULL DEFAULT 0,
            header TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            text_hash TEXT NOT NULL DEFAULT '',
            updated_by TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            deleted_at TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS intercept_sessions_archive (
            id INTEGER PRIMARY KEY,
            position_name TEXT NOT NULL,
            uuid TEXT NOT NULL DEFAULT '',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            created_by TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS intercept_items_archive (
            id INTEGER PRIMARY KEY,
            session_id INTEGER NOT NULL,
            session_uuid TEXT NOT NULL DEFAULT '',
            unit_name TEXT NOT NULL,
            frequency TEXT NOT NULL,
            group_code TEXT NOT NULL,
            uuid TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            updated_by TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS intercept_callsigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_name TEXT NOT NULL,
            label TEXT NOT NULL,
            code TEXT NOT NULL,
            tag TEXT NOT NULL DEFAULT '',
            tag_desc TEXT NOT NULL DEFAULT '',
            tag_color TEXT NOT NULL DEFAULT '',
            unit_name TEXT NOT NULL DEFAULT '',
            frequency TEXT NOT NULL DEFAULT '',
            group_code TEXT NOT NULL DEFAULT '',
            uuid TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(position_name, code, frequency, group_code)
        );
        """
    )
    # миграции: теги/описание для позывных
    try:
        cur.execute(
            "ALTER TABLE intercept_callsigns ADD COLUMN tag TEXT NOT NULL DEFAULT '';"
        )
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute(
            "ALTER TABLE intercept_callsigns ADD COLUMN tag_desc TEXT NOT NULL DEFAULT '';"
        )
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute(
            "ALTER TABLE intercept_callsigns ADD COLUMN tag_color TEXT NOT NULL DEFAULT '';"
        )
    except sqlite3.OperationalError:
        pass
    # Состояние отправки в "Парсер WORD" (слать только новые записи после сохранения)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS intercept_word_push_state (
            item_uuid TEXT PRIMARY KEY,
            last_sent_min INTEGER NOT NULL DEFAULT 0,
            last_sent_at TIMESTAMP,
            last_error TEXT NOT NULL DEFAULT ''
        );
        """
    )
    # Состояние отправки TXT (слать только новые записи после сохранения) — отдельно от WORD.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS intercept_txt_push_state (
            item_uuid TEXT PRIMARY KEY,
            last_sent_min INTEGER NOT NULL DEFAULT 0,
            last_sent_at TIMESTAMP,
            last_error TEXT NOT NULL DEFAULT ''
        );
        """
    )
    # tombstones для удалений из intercept_catalog (нужно для двустороннего синка)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS intercept_catalog_deletes (
            position_name TEXT NOT NULL,
            frequency TEXT NOT NULL,
            group_code TEXT NOT NULL,
            uuid TEXT NOT NULL DEFAULT '',
            deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (position_name, frequency, group_code)
        );
        """
    )
    # миграции для intercept_audio_tasks
    _migrate_intercept_audio_tasks(conn)
    # Состояние аудиоперехватов (последнее время/папка/флаги)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS intercept_audio_state (
            position_name TEXT NOT NULL,
            folder_path TEXT NOT NULL DEFAULT '',
            tasks_only INTEGER NOT NULL DEFAULT 0,
            last_time_ts REAL NOT NULL DEFAULT 0,
            is_running INTEGER NOT NULL DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (position_name)
        );
        """
    )
    try:
        cur.execute(
            "ALTER TABLE intercept_audio_state ADD COLUMN is_running INTEGER NOT NULL DEFAULT 1;"
        )
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute(
            "ALTER TABLE intercept_audio_state ADD COLUMN layout_mode TEXT NOT NULL DEFAULT 'dmr';"
        )
    except sqlite3.OperationalError:
        pass
    # Задание поста для аудиоперехватов (по частоте)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS intercept_audio_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_name TEXT NOT NULL,
            frequency TEXT NOT NULL,
            unit_name TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(position_name, frequency)
        );
        """
    )
    # Прослушанные аудиоперехваты (персонально для пользователя)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS intercept_audio_listened (
            user_id INTEGER NOT NULL,
            file_key TEXT NOT NULL,
            listened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, file_key)
        );
        """
    )
    # миграции для intercept_audio_listened
    _migrate_intercept_audio_listened(conn)
    # ASR: расшифровки аудио, обучающие выборки, модели и настройки
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS intercept_audio_transcripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_name TEXT NOT NULL,
            file_key TEXT NOT NULL,
            folder_path TEXT NOT NULL DEFAULT '',
            file_rel TEXT NOT NULL DEFAULT '',
            frequency TEXT NOT NULL DEFAULT '',
            group_code TEXT NOT NULL DEFAULT '',
            correspondent_id TEXT NOT NULL DEFAULT '',
            recorded_at TEXT NOT NULL DEFAULT '',
            duration_sec REAL NOT NULL DEFAULT 0,
            ua_text TEXT NOT NULL DEFAULT '',
            ru_text TEXT NOT NULL DEFAULT '',
            formatted_text TEXT NOT NULL DEFAULT '',
            segments_json TEXT NOT NULL DEFAULT '[]',
            confidence REAL NOT NULL DEFAULT 0,
            model_version TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'done',
            error_text TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(position_name, file_key)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS asr_train_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_name TEXT NOT NULL,
            file_key TEXT NOT NULL,
            audio_path TEXT NOT NULL DEFAULT '',
            start_ts REAL NOT NULL DEFAULT 0,
            end_ts REAL NOT NULL DEFAULT 0,
            frequency TEXT NOT NULL DEFAULT '',
            group_code TEXT NOT NULL DEFAULT '',
            correspondent_id TEXT NOT NULL DEFAULT '',
            source_text TEXT NOT NULL DEFAULT '',
            target_text TEXT NOT NULL DEFAULT '',
            alignment_score REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'validated',
            meta_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS asr_models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_name TEXT NOT NULL,
            model_version TEXT NOT NULL,
            base_model TEXT NOT NULL DEFAULT 'openai/whisper-small',
            artifact_path TEXT NOT NULL DEFAULT '',
            metrics_json TEXT NOT NULL DEFAULT '{}',
            is_active INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            activated_at TEXT NOT NULL DEFAULT '',
            UNIQUE(position_name, model_version)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS asr_training_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_name TEXT NOT NULL,
            run_id TEXT NOT NULL UNIQUE,
            model_version TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            params_json TEXT NOT NULL DEFAULT '{}',
            metrics_json TEXT NOT NULL DEFAULT '{}',
            error_text TEXT NOT NULL DEFAULT '',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TEXT NOT NULL DEFAULT ''
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS asr_settings (
            position_name TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (position_name, key)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS asr_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_name TEXT NOT NULL,
            file_key TEXT NOT NULL,
            prediction_text TEXT NOT NULL DEFAULT '',
            corrected_text TEXT NOT NULL DEFAULT '',
            feedback_label TEXT NOT NULL DEFAULT '',
            reviewer TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'validated',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_intercepts_catalog_deletes_ts ON intercept_catalog_deletes(deleted_at);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_intercepts_catalog_pos ON intercept_catalog(position_name);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_intercepts_audio_tasks_pos ON intercept_audio_tasks(position_name);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_audio_transcripts_pos_key ON intercept_audio_transcripts(position_name, file_key);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_audio_transcripts_time ON intercept_audio_transcripts(position_name, recorded_at);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_asr_samples_pos_status ON asr_train_samples(position_name, status, created_at);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_asr_samples_lookup ON asr_train_samples(position_name, frequency, group_code);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_asr_models_pos_active ON asr_models(position_name, is_active, created_at);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_asr_runs_pos_status ON asr_training_runs(position_name, status, started_at);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_asr_feedback_pos_time ON asr_feedback(position_name, created_at);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_intercepts_sessions_pos ON intercept_sessions(position_name, started_at);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_intercepts_sessions_pos_ended_started ON intercept_sessions(position_name, ended_at, started_at);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_intercepts_sessions_archive_pos ON intercept_sessions_archive(position_name, started_at);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_intercepts_sessions_archive_ended ON intercept_sessions_archive(ended_at);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_intercepts_sessions_period ON intercept_sessions(started_at, ended_at, position_name);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_intercepts_sessions_archive_period ON intercept_sessions_archive(started_at, ended_at, position_name);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_intercepts_items_session ON intercept_items(session_id);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_intercepts_items_session_freq_group ON intercept_items(session_id, frequency, group_code);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_intercept_blocks_item_uuid ON intercept_blocks(item_uuid, deleted_at);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_intercept_blocks_item_id ON intercept_blocks(item_id, deleted_at);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_intercepts_items_archive_session ON intercept_items_archive(session_id);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_intercepts_items_archive_session_freq_group ON intercept_items_archive(session_id, frequency, group_code);"
    )
    # миграции UUID/служебных колонок для синхронизации (важно ДО создания unique-index по uuid)
    _migrate_intercepts_sync_fields(conn)
    # миграции (важно сделать ДО создания индексов по новым колонкам)
    _migrate_intercept_callsigns(conn)
    cur = conn.cursor()
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_intercepts_callsigns_pos ON intercept_callsigns(position_name);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_intercepts_callsigns_pair ON intercept_callsigns(position_name, frequency, group_code);"
    )
    # unique индексы по uuid (после миграции, чтобы не было дублей пустых строк)
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_intercepts_catalog_uuid ON intercept_catalog(uuid);"
    )
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_intercepts_sessions_uuid ON intercept_sessions(uuid);"
    )
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_intercepts_items_uuid ON intercept_items(uuid);"
    )
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_intercepts_callsigns_uuid ON intercept_callsigns(uuid);"
    )
    # Блоки бланка: после того как у записей появились uuid (см. _migrate_intercepts_sync_fields).
    _migrate_intercept_blocks_backfill(conn)
    # Анализ: назначения главных корреспондентов по частота/группа
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis_assignments (
            position_name TEXT NOT NULL,
            frequency TEXT NOT NULL,
            group_code TEXT NOT NULL,
            role_type TEXT NOT NULL, -- duty (legacy: battalion/company)
            callsign_code TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (position_name, frequency, group_code, role_type)
        );
        """
    )
    # ML: события/датасет/модели/прогнозы/feedback
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ml_event_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_name TEXT NOT NULL,
            start_ts TEXT NOT NULL,
            end_ts TEXT NOT NULL,
            label TEXT NOT NULL,
            tag TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'validated',
            validated_by TEXT NOT NULL DEFAULT '',
            validated_at TEXT NOT NULL DEFAULT '',
            meta_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ml_feature_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_name TEXT NOT NULL,
            start_ts TEXT NOT NULL,
            end_ts TEXT NOT NULL,
            window_minutes INTEGER NOT NULL DEFAULT 60,
            feature_json TEXT NOT NULL DEFAULT '{}',
            label TEXT NOT NULL DEFAULT '',
            tag TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'dataset-build',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ml_models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_version TEXT NOT NULL UNIQUE,
            framework TEXT NOT NULL DEFAULT 'pytorch',
            task_type TEXT NOT NULL DEFAULT 'multiclass_event',
            labels_json TEXT NOT NULL DEFAULT '[]',
            feature_spec_json TEXT NOT NULL DEFAULT '{}',
            metrics_json TEXT NOT NULL DEFAULT '{}',
            artifact_path TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            activated_at TEXT NOT NULL DEFAULT ''
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ml_training_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            model_version TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            params_json TEXT NOT NULL DEFAULT '{}',
            metrics_json TEXT NOT NULL DEFAULT '{}',
            error_text TEXT NOT NULL DEFAULT '',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TEXT NOT NULL DEFAULT ''
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ml_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_name TEXT NOT NULL,
            start_ts TEXT NOT NULL,
            end_ts TEXT NOT NULL,
            model_version TEXT NOT NULL,
            top_label TEXT NOT NULL,
            top_probability REAL NOT NULL DEFAULT 0,
            probabilities_json TEXT NOT NULL DEFAULT '{}',
            reasons_json TEXT NOT NULL DEFAULT '[]',
            hotspots_json TEXT NOT NULL DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ml_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prediction_id INTEGER NOT NULL,
            position_name TEXT NOT NULL,
            feedback_label TEXT NOT NULL,
            corrected_label TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            reviewer TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ml_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ml_event_tags_pos_time ON ml_event_tags(position_name, start_ts, end_ts);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ml_event_tags_label ON ml_event_tags(label);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ml_snapshots_pos_time ON ml_feature_snapshots(position_name, start_ts, end_ts);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ml_snapshots_label ON ml_feature_snapshots(label);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ml_predictions_pos_time ON ml_predictions(position_name, start_ts, end_ts);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ml_predictions_model ON ml_predictions(model_version, created_at);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ml_feedback_prediction ON ml_feedback(prediction_id, created_at);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ml_runs_status ON ml_training_runs(status, started_at);"
    )
    conn.commit()
    init_ai_tables(conn)
    init_daily_aggregates(conn)


def get_intercept_word_push_state(conn: sqlite3.Connection, *, item_uuid: str) -> int:
    init_db(conn)
    u = str(item_uuid or "").strip()
    if not u:
        return 0
    try:
        r = conn.execute(
            "SELECT last_sent_min FROM intercept_word_push_state WHERE item_uuid=?",
            (u,),
        ).fetchone()
        return int(r["last_sent_min"] or 0) if r else 0
    except Exception:
        return 0


def set_intercept_word_push_state(
    conn: sqlite3.Connection,
    *,
    item_uuid: str,
    last_sent_min: int,
    last_error: str = "",
) -> None:
    init_db(conn)
    u = str(item_uuid or "").strip()
    if not u:
        return
    conn.execute(
        """
        INSERT INTO intercept_word_push_state (item_uuid, last_sent_min, last_sent_at, last_error)
        VALUES (?, ?, CURRENT_TIMESTAMP, ?)
        ON CONFLICT(item_uuid) DO UPDATE SET
          last_sent_min=excluded.last_sent_min,
          last_sent_at=CURRENT_TIMESTAMP,
          last_error=excluded.last_error
        """,
        (u, int(last_sent_min or 0), str(last_error or "")[:500]),
    )
    conn.commit()


def get_intercept_txt_push_state(conn: sqlite3.Connection, *, item_uuid: str) -> int:
    init_db(conn)
    u = str(item_uuid or "").strip()
    if not u:
        return 0
    try:
        r = conn.execute(
            "SELECT last_sent_min FROM intercept_txt_push_state WHERE item_uuid=?",
            (u,),
        ).fetchone()
        return int(r["last_sent_min"] or 0) if r else 0
    except Exception:
        return 0


def set_intercept_txt_push_state(
    conn: sqlite3.Connection,
    *,
    item_uuid: str,
    last_sent_min: int,
    last_error: str = "",
) -> None:
    init_db(conn)
    u = str(item_uuid or "").strip()
    if not u:
        return
    conn.execute(
        """
        INSERT INTO intercept_txt_push_state (item_uuid, last_sent_min, last_sent_at, last_error)
        VALUES (?, ?, CURRENT_TIMESTAMP, ?)
        ON CONFLICT(item_uuid) DO UPDATE SET
          last_sent_min=excluded.last_sent_min,
          last_sent_at=CURRENT_TIMESTAMP,
          last_error=excluded.last_error
        """,
        (u, int(last_sent_min or 0), str(last_error or "")[:500]),
    )
    conn.commit()


def compute_intercept_word_delta(
    *,
    content: str,
    last_sent_min: int,
) -> tuple[str, int]:
    """
    Возвращает (delta_text, new_last_sent_min).

    Логика как в AutoMonitorService:
    - отправляем только начиная с ПЕРВОГО нового времени (> last_sent_min)
    - если произошла "смена дня" (max_time < last_sent_min) — считаем всё новым, берём с первого времени
    """
    import re

    text = str(content or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    # indices of time headers and their minutes
    times: list[tuple[int, int]] = []
    for idx, ln in enumerate(lines):
        s = ln.strip()
        m = re.match(r"^(\d{1,2})[:.](\d{2})$", s)
        if not m:
            continue
        hh = int(m.group(1))
        mm = int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            times.append((idx, hh * 60 + mm))

    if not times:
        return ("", int(last_sent_min or 0))

    last_sent = int(last_sent_min or 0)
    max_min = max(t[1] for t in times)

    # day boundary
    start_line_idx: int | None = None
    if last_sent and max_min < last_sent:
        start_line_idx = times[0][0]
    else:
        for li, mm in times:
            if mm > last_sent:
                start_line_idx = li
                break

    if start_line_idx is None:
        return ("", max_min)

    delta = "\n".join(lines[start_line_idx:]).strip()
    return (delta, max_min)


def record_intercept_catalog_delete(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    frequency: str,
    group_code: str,
    uuid: str = "",
) -> None:
    """
    Записывает tombstone об удалении записи справочника Перехватов.
    Нужно, чтобы /api/sync/pull мог передавать удаления на HUB.
    """
    init_db(conn)
    pos = (position_name or "").strip()
    freq = (frequency or "").strip()
    grp = (group_code or "").strip()
    u = (uuid or "").strip()
    if not pos or not freq or not grp:
        return
    conn.execute(
        """
        INSERT INTO intercept_catalog_deletes (position_name, frequency, group_code, uuid, deleted_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(position_name, frequency, group_code)
        DO UPDATE SET uuid=excluded.uuid, deleted_at=CURRENT_TIMESTAMP
        """,
        (pos, freq, grp, u),
    )
    conn.commit()


def list_intercept_catalog_deletes_since(
    conn: sqlite3.Connection, *, since_ts: str, position_names: list[str] | None = None
) -> list[dict[str, Any]]:
    init_db(conn)
    since = str(since_ts or "").strip() or "1970-01-01 00:00:00"
    where_pos, params_pos = _in_clause("position_name", position_names or [])
    rows = conn.execute(
        """
        SELECT position_name, frequency, group_code, uuid, deleted_at
        FROM intercept_catalog_deletes
        WHERE COALESCE(deleted_at,'') >= ?{where_pos}
        ORDER BY deleted_at ASC
        """.format(where_pos=where_pos),
        [since] + params_pos,
    ).fetchall()
    return [
        {
            "position_name": str(r["position_name"] or ""),
            "frequency": str(r["frequency"] or ""),
            "group_code": str(r["group_code"] or ""),
            "uuid": str(r["uuid"] or ""),
            "deleted_at": str(r["deleted_at"] or ""),
        }
        for r in rows
    ]


def apply_intercept_catalog_delete_from_sync(
    conn: sqlite3.Connection, *, payload: dict[str, Any]
) -> bool:
    """
    Применяет удаление справочника Перехватов из sync (push или pull).
    Возвращает True, если обработали (даже если нечего удалять).
    """
    init_db(conn)
    u = str((payload or {}).get("uuid") or "").strip()
    pos = str((payload or {}).get("position_name") or "").strip()
    freq = str((payload or {}).get("frequency") or "").strip()
    grp = str((payload or {}).get("group_code") or "").strip()
    if u:
        conn.execute("DELETE FROM intercept_catalog WHERE uuid=?", (u,))
    elif pos and freq and grp:
        conn.execute(
            """
            DELETE FROM intercept_catalog
            WHERE position_name=? AND frequency=? AND group_code=?
            """,
            (pos, freq, grp),
        )
    # пишем tombstone в любом случае (для дальнейшего pull)
    record_intercept_catalog_delete(
        conn, position_name=pos, frequency=freq, group_code=grp, uuid=u
    )
    _commit_if_needed(conn)
    return True


def list_intercept_catalog_since(
    conn: sqlite3.Connection, *, since_ts: str, position_names: list[str] | None = None
) -> list[dict[str, Any]]:
    init_db(conn)
    _migrate_intercepts_sync_fields(conn)
    since = str(since_ts or "").strip() or "1970-01-01 00:00:00"
    # Проверяем наличие колонки location
    cols = _table_columns(conn, "intercept_catalog")
    has_location = "location" in cols

    if has_location:
        where_pos, params_pos = _in_clause("position_name", position_names or [])
        rows = conn.execute(
            """
            SELECT uuid, position_name, unit_name, frequency, group_code, location, updated_at
            FROM intercept_catalog
            WHERE COALESCE(updated_at,'') >= ?{where_pos}
            ORDER BY updated_at ASC, id ASC
            """.format(where_pos=where_pos),
            [since] + params_pos,
        ).fetchall()
        return [
            {
                "uuid": str(r["uuid"] or ""),
                "position_name": str(r["position_name"] or ""),
                "unit_name": str(r["unit_name"] or ""),
                "frequency": str(r["frequency"] or ""),
                "group_code": str(r["group_code"] or ""),
                "location": str(r["location"] or ""),
                "updated_at": str(r["updated_at"] or ""),
            }
            for r in rows
        ]
    else:
        # Если колонка location еще не существует
        where_pos, params_pos = _in_clause("position_name", position_names or [])
        rows = conn.execute(
            """
            SELECT uuid, position_name, unit_name, frequency, group_code, updated_at
            FROM intercept_catalog
            WHERE COALESCE(updated_at,'') >= ?{where_pos}
            ORDER BY updated_at ASC, id ASC
            """.format(where_pos=where_pos),
            [since] + params_pos,
        ).fetchall()
        return [
            {
                "uuid": str(r["uuid"] or ""),
                "position_name": str(r["position_name"] or ""),
                "unit_name": str(r["unit_name"] or ""),
                "frequency": str(r["frequency"] or ""),
                "group_code": str(r["group_code"] or ""),
                "location": "",
                "updated_at": str(r["updated_at"] or ""),
            }
            for r in rows
        ]


def list_intercept_callsigns_since(
    conn: sqlite3.Connection, *, since_ts: str, position_names: list[str] | None = None
) -> list[dict[str, Any]]:
    init_db(conn)
    since = str(since_ts or "").strip() or "1970-01-01 00:00:00"
    where_pos, params_pos = _in_clause("position_name", position_names or [])
    rows = conn.execute(
        """
        SELECT uuid, position_name, label, code, tag, tag_desc, tag_color, unit_name, frequency, group_code, updated_at
        FROM intercept_callsigns
        WHERE COALESCE(updated_at,'') >= ?{where_pos}
        ORDER BY updated_at ASC, id ASC
        """.format(where_pos=where_pos),
        [since] + params_pos,
    ).fetchall()
    return [
        {
            "uuid": str(r["uuid"] or ""),
            "position_name": str(r["position_name"] or ""),
            "label": str(r["label"] or ""),
            "code": str(r["code"] or ""),
            "tag": str(r["tag"] or ""),
            "tag_desc": str(r["tag_desc"] or ""),
            "tag_color": str(r["tag_color"] or ""),
            "unit_name": str(r["unit_name"] or ""),
            "frequency": str(r["frequency"] or ""),
            "group_code": str(r["group_code"] or ""),
            "updated_at": str(r["updated_at"] or ""),
        }
        for r in rows
    ]


def list_intercept_sessions_since(
    conn: sqlite3.Connection, *, since_ts: str, position_names: list[str] | None = None
) -> list[dict[str, Any]]:
    init_db(conn)
    since = str(since_ts or "").strip() or "1970-01-01 00:00:00"
    where_pos, params_pos = _in_clause("position_name", position_names or [])
    rows = conn.execute(
        """
        SELECT uuid, position_name, started_at, ended_at, created_by
        FROM intercept_sessions
        WHERE (COALESCE(started_at,'') >= ? OR COALESCE(ended_at,'') >= ?){where_pos}
        ORDER BY started_at ASC, id ASC
        """.format(where_pos=where_pos),
        [since, since] + params_pos,
    ).fetchall()
    return [
        {
            "uuid": str(r["uuid"] or ""),
            "position_name": str(r["position_name"] or ""),
            "started_at": str(r["started_at"] or ""),
            "ended_at": str(r["ended_at"] or ""),
            "created_by": str(r["created_by"] or ""),
        }
        for r in rows
    ]


def list_intercept_items_since(
    conn: sqlite3.Connection, *, since_ts: str, position_names: list[str] | None = None
) -> list[dict[str, Any]]:
    init_db(conn)
    since = str(since_ts or "").strip() or "1970-01-01 00:00:00"
    where_pos, params_pos = _in_clause("s.position_name", position_names or [])
    rows = conn.execute(
        """
        SELECT
          i.uuid as uuid,
          i.session_uuid as session_uuid,
          s.uuid as session_uuid_fallback,
          s.position_name as position_name,
          s.started_at as session_started_at,
          s.ended_at as session_ended_at,
          i.unit_name as unit_name,
          i.frequency as frequency,
          i.group_code as group_code,
          i.content as content,
          i.updated_by as updated_by,
          i.updated_at as updated_at
        FROM intercept_items i
        JOIN intercept_sessions s ON s.id=i.session_id
        WHERE COALESCE(i.updated_at,'') >= ?{where_pos}
        ORDER BY i.updated_at ASC, i.id ASC
        """.format(where_pos=where_pos),
        [since] + params_pos,
    ).fetchall()
    return [
        {
            "uuid": str(r["uuid"] or ""),
            "session_uuid": str(r["session_uuid"] or r["session_uuid_fallback"] or ""),
            "position_name": str(r["position_name"] or ""),
            "session_started_at": str(r["session_started_at"] or ""),
            "session_ended_at": str(r["session_ended_at"] or ""),
            "unit_name": str(r["unit_name"] or ""),
            "frequency": str(r["frequency"] or ""),
            "group_code": str(r["group_code"] or ""),
            "content": str(r["content"] or ""),
            "updated_by": str(r["updated_by"] or ""),
            "updated_at": str(r["updated_at"] or ""),
        }
        for r in rows
    ]


def upsert_intercept_session_from_sync(
    conn: sqlite3.Connection, *, data: dict[str, Any]
) -> int:
    """
    Upsert смены по uuid. Возвращает local session_id.
    """
    init_db(conn)
    u = str((data or {}).get("uuid") or "").strip()
    pos = str((data or {}).get("position_name") or "").strip()
    started_at = str((data or {}).get("started_at") or "").strip()
    ended_at = (data or {}).get("ended_at")
    ended_at_s = str(ended_at or "").strip()
    created_by = str((data or {}).get("created_by") or "").strip()
    if not u or not pos:
        raise ValueError("uuid/position_name обязательны")

    r = conn.execute(
        "SELECT id, ended_at FROM intercept_sessions WHERE uuid=?", (u,)
    ).fetchone()
    if r:
        sid = int(r["id"])
        # обновляем ended_at только если он пришёл и локально пусто
        local_ended = str(r["ended_at"] or "").strip()
        if ended_at_s and (not local_ended or local_ended < ended_at_s):
            conn.execute(
                "UPDATE intercept_sessions SET ended_at=? WHERE id=?",
                (ended_at_s, sid),
            )
            _commit_if_needed(conn)
        return sid

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO intercept_sessions (position_name, uuid, started_at, ended_at, created_by)
        VALUES (?, ?, ?, ?, ?)
        """,
        (pos, u, started_at or None, ended_at_s or None, created_by),
    )
    _commit_if_needed(conn)
    return int(cur.lastrowid)


def upsert_intercept_item_from_sync(
    conn: sqlite3.Connection, *, data: dict[str, Any]
) -> int:
    """
    Upsert записи бланка по uuid + защита по updated_at (не затирать более свежие локальные правки).
    Возвращает local item_id.
    """
    init_db(conn)
    d = data or {}
    item_uuid = str(d.get("uuid") or "").strip()
    sess_uuid = str(d.get("session_uuid") or "").strip()
    pos = str(d.get("position_name") or "").strip()
    freq = str(d.get("frequency") or "").strip()
    grp = str(d.get("group_code") or "").strip()
    unit = str(d.get("unit_name") or "").strip()
    content = str(d.get("content") or "")
    updated_by = str(d.get("updated_by") or "").strip()
    updated_at = str(d.get("updated_at") or "").strip()
    started_at = str(d.get("session_started_at") or "").strip()
    ended_at = str(d.get("session_ended_at") or "").strip()
    if not item_uuid or not sess_uuid or not pos or not freq or not grp:
        raise ValueError(
            "uuid/session_uuid/position_name/frequency/group_code обязательны"
        )

    # Нормализуем время в шапках блоков (для совместимости со старыми клиентами):
    # `13:01` -> `13.01` (только если строка целиком равна времени)
    try:
        import re

        norm_lines: list[str] = []
        for ln in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            s = ln.strip()
            m = re.match(r"^(\d{1,2}):(\d{2})$", s)
            if m:
                hh = int(m.group(1))
                mm = int(m.group(2))
                if 0 <= hh <= 23 and 0 <= mm <= 59:
                    norm_lines.append(f"{hh}.{mm:02d}")
                    continue
            norm_lines.append(ln)
        content = "\n".join(norm_lines)
    except Exception:
        _log.debug("upsert_intercept_item_from_sync: suppressed error", exc_info=True)

    sid = upsert_intercept_session_from_sync(
        conn,
        data={
            "uuid": sess_uuid,
            "position_name": pos,
            "started_at": started_at,
            "ended_at": ended_at,
            "created_by": "",
        },
    )

    r = conn.execute(
        "SELECT id, updated_at, content FROM intercept_items WHERE uuid=?",
        (item_uuid,),
    ).fetchone()
    if r:
        iid = int(r["id"])
        local_updated = str(r["updated_at"] or "").strip()
        local_content = str(r["content"] or "")
        if updated_at and local_updated:
            if local_updated > updated_at:
                return iid
            if local_updated == updated_at and local_content == content:
                return iid
        conn.execute(
            """
            UPDATE intercept_items
            SET session_id=?, session_uuid=?, unit_name=?, frequency=?, group_code=?, content=?,
                updated_by=?, updated_at=?
            WHERE id=?
            """,
            (
                sid,
                sess_uuid,
                unit,
                freq,
                grp,
                content,
                updated_by,
                updated_at or None,
                iid,
            ),
        )
        _commit_if_needed(conn)
        _sync_blocks_quietly(conn, iid, content)
        return iid

    # если uuid не найден, пробуем по естественному ключу в рамках сессии
    r2 = conn.execute(
        """
        SELECT id, uuid, updated_at, content
        FROM intercept_items
        WHERE session_id=? AND frequency=? AND group_code=?
        """,
        (sid, freq, grp),
    ).fetchone()
    if r2:
        iid = int(r2["id"])
        local_updated = str(r2["updated_at"] or "").strip()
        local_content = str(r2["content"] or "")
        if updated_at and local_updated:
            if local_updated > updated_at:
                return iid
            if local_updated == updated_at and local_content == content:
                return iid
        conn.execute(
            """
            UPDATE intercept_items
            SET uuid=?, session_uuid=?, unit_name=?, content=?, updated_by=?, updated_at=?
            WHERE id=?
            """,
            (item_uuid, sess_uuid, unit, content, updated_by, updated_at or None, iid),
        )
        _commit_if_needed(conn)
        _sync_blocks_quietly(conn, iid, content)
        return iid

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO intercept_items
          (session_id, session_uuid, unit_name, frequency, group_code, uuid, content, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sid,
            sess_uuid,
            unit,
            freq,
            grp,
            item_uuid,
            content,
            updated_by,
            updated_at or None,
        ),
    )
    _commit_if_needed(conn)
    new_id = int(cur.lastrowid)
    _sync_blocks_quietly(conn, new_id, content)
    return new_id


def upsert_intercept_catalog_from_sync(
    conn: sqlite3.Connection, *, data: dict[str, Any]
) -> int:
    init_db(conn)
    d = data or {}
    u = str(d.get("uuid") or "").strip()
    pos = str(d.get("position_name") or "").strip()
    unit = str(d.get("unit_name") or "").strip()
    freq = str(d.get("frequency") or "").strip()
    grp = str(d.get("group_code") or "").strip()
    loc = str(d.get("location") or "").strip()
    updated_at = str(d.get("updated_at") or "").strip()
    if not u or not pos or not freq or not grp:
        raise ValueError("uuid/position_name/frequency/group_code обязательны")

    # Проверяем, не была ли запись удалена (tombstone)
    tombstone = conn.execute(
        """
        SELECT deleted_at FROM intercept_catalog_deletes
        WHERE (uuid = ? AND uuid != '') OR (position_name = ? AND frequency = ? AND group_code = ?)
        ORDER BY deleted_at DESC
        LIMIT 1
        """,
        (u, pos, freq, grp),
    ).fetchone()
    if tombstone:
        # Запись была удалена, не восстанавливаем её
        return 0

    r = conn.execute(
        "SELECT id, updated_at FROM intercept_catalog WHERE uuid=?",
        (u,),
    ).fetchone()
    if r:
        cid = int(r["id"])
        local_updated = str(r["updated_at"] or "").strip()
        if updated_at and local_updated and local_updated >= updated_at:
            return cid
        conn.execute(
            """
            UPDATE intercept_catalog
            SET position_name=?, unit_name=?, frequency=?, group_code=?, location=?, updated_at=?
            WHERE id=?
            """,
            (pos, unit, freq, grp, loc, updated_at or None, cid),
        )
        _commit_if_needed(conn)
        return cid
    # по естественному ключу
    r2 = conn.execute(
        "SELECT id, uuid, updated_at FROM intercept_catalog WHERE position_name=? AND frequency=? AND group_code=?",
        (pos, freq, grp),
    ).fetchone()
    if r2:
        cid = int(r2["id"])
        local_updated = str(r2["updated_at"] or "").strip()
        if updated_at and local_updated and local_updated >= updated_at:
            return cid
        conn.execute(
            """
            UPDATE intercept_catalog
            SET unit_name=?, location=?, uuid=?, updated_at=?
            WHERE id=?
            """,
            (unit, loc, u, updated_at or None, cid),
        )
        _commit_if_needed(conn)
        return cid
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO intercept_catalog (position_name, unit_name, frequency, group_code, location, uuid, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (pos, unit, freq, grp, loc, u, updated_at or None),
    )
    _commit_if_needed(conn)
    return int(cur.lastrowid)


def upsert_intercept_callsign_from_sync(
    conn: sqlite3.Connection, *, data: dict[str, Any]
) -> int:
    init_db(conn)
    d = data or {}
    u = str(d.get("uuid") or "").strip()
    pos = str(d.get("position_name") or "").strip()
    label = str(d.get("label") or "").strip()
    code = str(d.get("code") or "").strip()
    tag = str(d.get("tag") or "").strip()
    tag_desc = str(d.get("tag_desc") or "").strip()
    tag_color = str(d.get("tag_color") or "").strip()
    unit = str(d.get("unit_name") or "").strip()
    freq = str(d.get("frequency") or "").strip()
    grp = str(d.get("group_code") or "").strip()
    updated_at = str(d.get("updated_at") or "").strip()
    if not u or not pos or not code:
        raise ValueError("uuid/position_name/code обязательны")
    r = conn.execute(
        "SELECT id, updated_at FROM intercept_callsigns WHERE uuid=?",
        (u,),
    ).fetchone()
    if r:
        cid = int(r["id"])
        local_updated = str(r["updated_at"] or "").strip()
        if updated_at and local_updated and local_updated >= updated_at:
            return cid
        conn.execute(
            """
            UPDATE intercept_callsigns
            SET position_name=?, label=?, code=?, tag=?, tag_desc=?, tag_color=?,
                unit_name=?, frequency=?, group_code=?, updated_at=?
            WHERE id=?
            """,
            (
                pos,
                label,
                code,
                tag,
                tag_desc,
                tag_color,
                unit,
                freq,
                grp,
                updated_at or None,
                cid,
            ),
        )
        _commit_if_needed(conn)
        return cid
    # по естественному ключу
    r2 = conn.execute(
        """
        SELECT id, uuid, updated_at
        FROM intercept_callsigns
        WHERE position_name=? AND code=? AND frequency=? AND group_code=?
        """,
        (pos, code, freq, grp),
    ).fetchone()
    if r2:
        cid = int(r2["id"])
        local_updated = str(r2["updated_at"] or "").strip()
        if updated_at and local_updated and local_updated >= updated_at:
            return cid
        conn.execute(
            """
            UPDATE intercept_callsigns
            SET label=?, tag=?, tag_desc=?, tag_color=?, unit_name=?, uuid=?, updated_at=?
            WHERE id=?
            """,
            (label, tag, tag_desc, tag_color, unit, u, updated_at or None, cid),
        )
        _commit_if_needed(conn)
        return cid
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO intercept_callsigns
          (position_name, label, code, tag, tag_desc, tag_color, unit_name, frequency, group_code, uuid, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pos,
            label,
            code,
            tag,
            tag_desc,
            tag_color,
            unit,
            freq,
            grp,
            u,
            updated_at or None,
        ),
    )
    _commit_if_needed(conn)
    return int(cur.lastrowid)


def _migrate_intercepts_sync_fields(conn: sqlite3.Connection) -> None:
    """
    Миграции для добавления uuid/session_uuid в существующие БД.
    """
    import uuid as _uuid

    def _ensure_col(table: str, col: str, ddl: str) -> None:
        cols = _table_columns(conn, table)
        if col in cols:
            return
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl};")
        except Exception:
            return

    # добавляем колонки, если их нет (для старых БД)
    _ensure_col("intercept_catalog", "uuid", "uuid TEXT NOT NULL DEFAULT ''")
    _ensure_col("intercept_sessions", "uuid", "uuid TEXT NOT NULL DEFAULT ''")
    _ensure_col("intercept_items", "uuid", "uuid TEXT NOT NULL DEFAULT ''")
    _ensure_col(
        "intercept_items", "session_uuid", "session_uuid TEXT NOT NULL DEFAULT ''"
    )
    _ensure_col("intercept_callsigns", "uuid", "uuid TEXT NOT NULL DEFAULT ''")
    # Добавляем поле location (населенный пункт) для intercept_catalog
    _ensure_col("intercept_catalog", "location", "location TEXT NOT NULL DEFAULT ''")

    # заполняем uuid там, где он пустой
    try:
        rows = conn.execute("SELECT id, uuid FROM intercept_catalog;").fetchall()
        for r in rows or []:
            rid = int(r["id"])
            u = str(r["uuid"] or "")
            if u.strip():
                continue
            conn.execute(
                "UPDATE intercept_catalog SET uuid=? WHERE id=?",
                (str(_uuid.uuid4()), rid),
            )
    except Exception:
        _log.debug("_migrate_intercepts_sync_fields: suppressed error", exc_info=True)

    try:
        rows = conn.execute("SELECT id, uuid FROM intercept_sessions;").fetchall()
        for r in rows or []:
            rid = int(r["id"])
            u = str(r["uuid"] or "")
            if u.strip():
                continue
            conn.execute(
                "UPDATE intercept_sessions SET uuid=? WHERE id=?",
                (str(_uuid.uuid4()), rid),
            )
    except Exception:
        _log.debug("_migrate_intercepts_sync_fields: suppressed error", exc_info=True)

    try:
        rows = conn.execute("SELECT id, uuid FROM intercept_items;").fetchall()
        for r in rows or []:
            rid = int(r["id"])
            u = str(r["uuid"] or "")
            if u.strip():
                continue
            conn.execute(
                "UPDATE intercept_items SET uuid=? WHERE id=?",
                (str(_uuid.uuid4()), rid),
            )
    except Exception:
        _log.debug("_migrate_intercepts_sync_fields: suppressed error", exc_info=True)

    # session_uuid в items заполняем из sessions
    try:
        rows = conn.execute(
            """
            SELECT i.id as id, i.session_uuid as session_uuid, s.uuid as sess_uuid
            FROM intercept_items i
            JOIN intercept_sessions s ON s.id=i.session_id
            """
        ).fetchall()
        for r in rows or []:
            rid = int(r["id"])
            su = str(r["session_uuid"] or "").strip()
            sess_uuid = str(r["sess_uuid"] or "").strip()
            if su:
                continue
            if not sess_uuid:
                continue
            conn.execute(
                "UPDATE intercept_items SET session_uuid=? WHERE id=?",
                (sess_uuid, rid),
            )
    except Exception:
        _log.debug("_migrate_intercepts_sync_fields: suppressed error", exc_info=True)

    try:
        rows = conn.execute("SELECT id, uuid FROM intercept_callsigns;").fetchall()
        for r in rows or []:
            rid = int(r["id"])
            u = str(r["uuid"] or "")
            if u.strip():
                continue
            conn.execute(
                "UPDATE intercept_callsigns SET uuid=? WHERE id=?",
                (str(_uuid.uuid4()), rid),
            )
    except Exception:
        _log.debug("_migrate_intercepts_sync_fields: suppressed error", exc_info=True)

    conn.commit()


def _migrate_intercept_callsigns(conn: sqlite3.Connection) -> None:
    """
    Миграция со старой схемы intercept_callsigns:
      UNIQUE(position_name, code)
    на новую:
      unit_name/frequency/group_code + UNIQUE(position_name, code, frequency, group_code)
    """
    try:
        cols = conn.execute("PRAGMA table_info(intercept_callsigns);").fetchall()
    except Exception:
        return
    if not cols:
        return
    col_names = {str(c[1]) for c in cols}
    # если таблица уже новая (есть frequency и group_code) — ничего не делаем
    if "frequency" in col_names and "group_code" in col_names:
        # но проверим, что нет уникального индекса только по (position_name, code)
        try:
            idxs = conn.execute("PRAGMA index_list(intercept_callsigns);").fetchall()
            for idx in idxs or []:
                name = idx[1]
                unique = int(idx[2] or 0) == 1
                if not unique:
                    continue
                info = conn.execute(f"PRAGMA index_info({name});").fetchall()
                cols_idx = [str(r[2]) for r in info or []]
                if cols_idx == ["position_name", "code"]:
                    # старая уникальность всё ещё существует → нужна миграция
                    break
            else:
                return
        except Exception:
            return

    # делаем полноценную миграцию через новую таблицу
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS intercept_callsigns_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_name TEXT NOT NULL,
            label TEXT NOT NULL,
            code TEXT NOT NULL,
            tag TEXT NOT NULL DEFAULT '',
            tag_desc TEXT NOT NULL DEFAULT '',
            tag_color TEXT NOT NULL DEFAULT '',
            unit_name TEXT NOT NULL DEFAULT '',
            frequency TEXT NOT NULL DEFAULT '',
            group_code TEXT NOT NULL DEFAULT '',
            uuid TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(position_name, code, frequency, group_code)
        );
        """
    )
    # переносим данные (старые записи считаем "общими": frequency/group_code пустые)
    try:
        rows = cur.execute(
            "SELECT id, position_name, label, code, created_at, updated_at FROM intercept_callsigns;"
        ).fetchall()
    except Exception:
        rows = []
    import uuid as _uuid

    for r in rows or []:
        cur.execute(
            """
            INSERT OR IGNORE INTO intercept_callsigns_new
              (id, position_name, label, code, tag, tag_desc, tag_color, unit_name, frequency, group_code, uuid, created_at, updated_at)
            VALUES (?, ?, ?, ?, '', '', '', '', '', '', ?, ?, ?)
            """,
            (
                int(r[0]),
                str(r[1] or ""),
                str(r[2] or ""),
                str(r[3] or ""),
                str(_uuid.uuid4()),
                str(r[4] or ""),
                str(r[5] or ""),
            ),
        )
    cur.execute("DROP TABLE intercept_callsigns;")
    cur.execute("ALTER TABLE intercept_callsigns_new RENAME TO intercept_callsigns;")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_intercepts_callsigns_pos ON intercept_callsigns(position_name);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_intercepts_callsigns_pair ON intercept_callsigns(position_name, frequency, group_code);"
    )
    conn.commit()


def list_intercept_catalog(
    conn: sqlite3.Connection, position_name: str
) -> list[dict[str, Any]]:
    init_db(conn)
    # Убеждаемся, что миграция выполнена
    _migrate_intercepts_sync_fields(conn)
    pos = (position_name or "").strip()
    # Проверяем наличие колонки location через _table_columns
    cols = _table_columns(conn, "intercept_catalog")
    has_location = "location" in cols

    # Строки с пустым position_name (старые данные / до заполнения поля) показываем для любой выбранной позиции
    pos_where = """(
            position_name = ?
            OR TRIM(COALESCE(position_name, '')) = ''
        )"""

    if has_location:
        rows = conn.execute(
            f"""
            SELECT id, unit_name, frequency, group_code, location, updated_at
            FROM intercept_catalog
            WHERE {pos_where}
            ORDER BY unit_name,
                     CAST(REPLACE(COALESCE(frequency, ''), ',', '.') AS REAL) DESC,
                     group_code
            """,
            (pos,),
        ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "unit_name": str(r["unit_name"] or ""),
                "frequency": str(r["frequency"] or ""),
                "group_code": str(r["group_code"] or ""),
                "location": str(r["location"] or ""),
                "updated_at": str(r["updated_at"] or ""),
            }
            for r in rows
        ]
    else:
        # Если колонка location еще не существует, делаем запрос без неё
        rows = conn.execute(
            f"""
            SELECT id, unit_name, frequency, group_code, updated_at
            FROM intercept_catalog
            WHERE {pos_where}
            ORDER BY unit_name,
                     CAST(REPLACE(COALESCE(frequency, ''), ',', '.') AS REAL) DESC,
                     group_code
            """,
            (pos,),
        ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "unit_name": str(r["unit_name"] or ""),
                "frequency": str(r["frequency"] or ""),
                "group_code": str(r["group_code"] or ""),
                "location": "",
                "updated_at": str(r["updated_at"] or ""),
            }
            for r in rows
        ]


def upsert_intercept_catalog(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    unit_name: str,
    frequency: str,
    group_code: str,
    location: str = "",
) -> int:
    import uuid as _uuid

    init_db(conn)
    pos = (position_name or "").strip()
    unit = (unit_name or "").strip()
    freq = (frequency or "").strip()
    grp = (group_code or "").strip()
    loc = (location or "").strip()
    if not pos or not unit or not freq or not grp:
        raise ValueError("position_name/unit_name/frequency/group_code обязательны")
    r = conn.execute(
        """
        SELECT id FROM intercept_catalog
        WHERE position_name=? AND frequency=? AND group_code=?
        """,
        (pos, freq, grp),
    ).fetchone()
    if r:
        cid = int(r["id"])
        # гарантируем uuid для старых записей
        try:
            u0 = conn.execute(
                "SELECT uuid FROM intercept_catalog WHERE id=?",
                (cid,),
            ).fetchone()
            if u0 and not str(u0["uuid"] or "").strip():
                conn.execute(
                    "UPDATE intercept_catalog SET uuid=? WHERE id=?",
                    (str(_uuid.uuid4()), cid),
                )
        except Exception:
            _log.debug("upsert_intercept_catalog: suppressed error", exc_info=True)
        conn.execute(
            """
            UPDATE intercept_catalog
            SET unit_name=?, location=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (unit, loc, cid),
        )
        conn.commit()
        return cid
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO intercept_catalog (position_name, unit_name, frequency, group_code, location, uuid)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (pos, unit, freq, grp, loc, str(_uuid.uuid4())),
    )
    conn.commit()
    return int(cur.lastrowid)


def delete_intercept_catalog(conn: sqlite3.Connection, catalog_id: int) -> bool:
    """Удалить запись каталога. Возвращает True, если запись была удалена."""
    init_db(conn)
    cur = conn.cursor()
    cur.execute("DELETE FROM intercept_catalog WHERE id=?", (int(catalog_id),))
    conn.commit()
    return cur.rowcount > 0


def list_intercept_sessions(
    conn: sqlite3.Connection, position_name: str, limit: int = 50
) -> list[dict[str, Any]]:
    init_db(conn)
    pos = (position_name or "").strip()
    limit = max(1, min(int(limit), 200))
    pos_or_empty = """(
            position_name = ?
            OR TRIM(COALESCE(position_name, '')) = ''
        )"""
    rows = conn.execute(
        f"""
        SELECT id, started_at, ended_at, created_by
        FROM (
            SELECT id, started_at, ended_at, created_by
            FROM intercept_sessions
            WHERE {pos_or_empty}
            UNION ALL
            SELECT id, started_at, ended_at, created_by
            FROM intercept_sessions_archive
            WHERE {pos_or_empty}
        ) t
        ORDER BY started_at DESC
        LIMIT ?
        """,
        (pos, pos, limit),
    ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "started_at": str(r["started_at"] or ""),
            "ended_at": str(r["ended_at"] or ""),
            "created_by": str(r["created_by"] or ""),
        }
        for r in rows
    ]


def list_intercept_sessions_ordered(
    conn: sqlite3.Connection, position_name: str, *, limit: int = 80
) -> list[dict[str, Any]]:
    """Смены по позиции (как list_intercept_sessions) или все смены, если position пустой или __all__."""
    init_db(conn)
    pos = (position_name or "").strip()
    limit = max(1, min(int(limit), 200))
    if pos and pos != "__all__":
        return list_intercept_sessions(conn, pos, limit=limit)
    rows = conn.execute(
        """
        SELECT id, started_at, ended_at, created_by
        FROM (
            SELECT id, started_at, ended_at, created_by FROM intercept_sessions
            UNION ALL
            SELECT id, started_at, ended_at, created_by FROM intercept_sessions_archive
        ) t
        ORDER BY started_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "started_at": str(r["started_at"] or ""),
            "ended_at": str(r["ended_at"] or ""),
            "created_by": str(r["created_by"] or ""),
        }
        for r in rows
    ]


def get_or_create_active_intercept_session(
    conn: sqlite3.Connection, position_name: str, created_by: str
) -> dict[str, Any]:
    import uuid as _uuid

    init_db(conn)
    pos = (position_name or "").strip()
    # Сначала смена с точным position_name, иначе «общая» с пустым position_name (старые БД)
    r = conn.execute(
        """
        SELECT id, uuid, started_at, ended_at, created_by
        FROM intercept_sessions
        WHERE ended_at IS NULL
          AND (
            position_name = ?
            OR TRIM(COALESCE(position_name, '')) = ''
          )
        ORDER BY CASE WHEN position_name = ? THEN 0 ELSE 1 END,
                 started_at DESC
        LIMIT 1
        """,
        (pos, pos),
    ).fetchone()
    if r:
        # гарантируем uuid для старых записей
        sess_uuid = str(r["uuid"] or "").strip()
        if not sess_uuid:
            sess_uuid = str(_uuid.uuid4())
            conn.execute(
                "UPDATE intercept_sessions SET uuid=? WHERE id=?",
                (sess_uuid, int(r["id"])),
            )
            conn.commit()
        return {
            "id": int(r["id"]),
            "uuid": str(sess_uuid),
            "started_at": str(r["started_at"] or ""),
            "ended_at": str(r["ended_at"] or ""),
            "created_by": str(r["created_by"] or ""),
        }
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO intercept_sessions (position_name, created_by, uuid)
        VALUES (?, ?, ?)
        """,
        (pos, str(created_by or ""), str(_uuid.uuid4())),
    )
    conn.commit()
    sid = int(cur.lastrowid)
    r2 = conn.execute(
        "SELECT id, uuid, started_at, ended_at, created_by FROM intercept_sessions WHERE id=?",
        (sid,),
    ).fetchone()
    return {
        "id": int(r2["id"]),
        "uuid": str(r2["uuid"] or ""),
        "started_at": str(r2["started_at"] or ""),
        "ended_at": str(r2["ended_at"] or ""),
        "created_by": str(r2["created_by"] or ""),
    }


def close_active_and_start_new_intercept_session(
    conn: sqlite3.Connection, position_name: str, created_by: str
) -> dict[str, Any]:
    init_db(conn)
    pos = (position_name or "").strip()
    conn.execute(
        """
        UPDATE intercept_sessions
        SET ended_at=CURRENT_TIMESTAMP
        WHERE position_name=? AND ended_at IS NULL
        """,
        (pos,),
    )
    _archive_closed_intercept_sessions(conn, pos)
    conn.commit()
    return get_or_create_active_intercept_session(conn, pos, created_by)


def _archive_closed_intercept_sessions(
    conn: sqlite3.Connection, position_name: str, batch_size: int = 200
) -> int:
    """
    Переносит закрытые смены и их записи в архивные таблицы.
    Выполняется пакетно, чтобы не создавать длинных блокировок.
    """
    pos = str(position_name or "").strip()
    moved = 0
    while True:
        rows = conn.execute(
            """
            SELECT id
            FROM intercept_sessions
            WHERE position_name=? AND ended_at IS NOT NULL
            ORDER BY ended_at ASC, id ASC
            LIMIT ?
            """,
            (pos, max(1, int(batch_size))),
        ).fetchall()
        if not rows:
            break
        for r in rows:
            sid = int(r["id"])
            conn.execute(
                """
                INSERT OR IGNORE INTO intercept_sessions_archive
                (id, position_name, uuid, started_at, ended_at, created_by, created_at, archived_at)
                SELECT id, position_name, uuid, started_at, ended_at, created_by, created_at, CURRENT_TIMESTAMP
                FROM intercept_sessions
                WHERE id=? AND ended_at IS NOT NULL
                """,
                (sid,),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO intercept_items_archive
                (id, session_id, session_uuid, unit_name, frequency, group_code, uuid, content, updated_by, updated_at, archived_at)
                SELECT id, session_id, session_uuid, unit_name, frequency, group_code, uuid, content, updated_by, updated_at, CURRENT_TIMESTAMP
                FROM intercept_items
                WHERE session_id=?
                """,
                (sid,),
            )
            # Блоки живут только у активных смен: в архиве источником остаётся текст.
            conn.execute(
                """
                DELETE FROM intercept_blocks
                WHERE item_id IN (SELECT id FROM intercept_items WHERE session_id=?)
                """,
                (sid,),
            )
            conn.execute("DELETE FROM intercept_items WHERE session_id=?", (sid,))
            conn.execute("DELETE FROM intercept_sessions WHERE id=?", (sid,))
            moved += 1
    return moved


def get_or_create_intercept_item(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    catalog_id: int,
    create_if_missing: bool = True,
) -> dict[str, Any]:
    import uuid as _uuid

    init_db(conn)
    sid = int(session_id)
    sess = conn.execute(
        "SELECT uuid FROM intercept_sessions WHERE id=?",
        (sid,),
    ).fetchone()
    sess_uuid = str(sess["uuid"] or "").strip() if sess else ""
    cat = conn.execute(
        "SELECT unit_name, frequency, group_code FROM intercept_catalog WHERE id=?",
        (int(catalog_id),),
    ).fetchone()
    if not cat:
        raise ValueError("catalog not found")
    unit = str(cat["unit_name"] or "")
    freq = str(cat["frequency"] or "")
    grp = str(cat["group_code"] or "")
    r = conn.execute(
        """
        SELECT id, uuid, session_uuid, content, updated_at
        FROM intercept_items
        WHERE session_id=? AND frequency=? AND group_code=?
        """,
        (sid, freq, grp),
    ).fetchone()
    if r:
        # гарантируем uuid/session_uuid для старых записей
        item_uuid = str(r["uuid"] or "").strip()
        item_su = str(r["session_uuid"] or "").strip()
        if not item_uuid:
            item_uuid = str(_uuid.uuid4())
            conn.execute(
                "UPDATE intercept_items SET uuid=? WHERE id=?",
                (item_uuid, int(r["id"])),
            )
        if not item_su and sess_uuid:
            conn.execute(
                "UPDATE intercept_items SET session_uuid=? WHERE id=?",
                (sess_uuid, int(r["id"])),
            )
        if (not str(r["uuid"] or "").strip()) or (
            not str(r["session_uuid"] or "").strip()
        ):
            conn.commit()
        return {
            "id": int(r["id"]),
            "session_id": sid,
            "session_uuid": str(item_su or sess_uuid or ""),
            "uuid": str(item_uuid),
            "unit_name": unit,
            "frequency": freq,
            "group_code": grp,
            "content": str(r["content"] or ""),
            "updated_at": str(r["updated_at"] or ""),
        }
    if not create_if_missing:
        # Закрытая смена: данные могли уйти в архив — проверяем intercept_items_archive
        r_arch = conn.execute(
            """
            SELECT id, content, updated_at
            FROM intercept_items_archive
            WHERE session_id=? AND frequency=? AND group_code=?
            """,
            (sid, freq, grp),
        ).fetchone()
        if r_arch:
            return {
                "id": int(r_arch["id"]),
                "session_id": sid,
                "unit_name": unit,
                "frequency": freq,
                "group_code": grp,
                "content": str(r_arch["content"] or ""),
                "updated_at": str(r_arch["updated_at"] or ""),
            }
        return {
            "id": 0,
            "session_id": sid,
            "unit_name": unit,
            "frequency": freq,
            "group_code": grp,
            "content": "",
            "updated_at": "",
        }
    cur = conn.cursor()
    item_uuid = str(_uuid.uuid4())
    cur.execute(
        """
        INSERT OR IGNORE INTO intercept_items (session_id, session_uuid, unit_name, frequency, group_code, uuid)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (sid, sess_uuid, unit, freq, grp, item_uuid),
    )
    conn.commit()
    r = conn.execute(
        """
        SELECT id, uuid, session_uuid, content, updated_at
        FROM intercept_items
        WHERE session_id=? AND frequency=? AND group_code=?
        """,
        (sid, freq, grp),
    ).fetchone()
    if not r:
        raise ValueError("intercept item insert failed")
    item_uuid = str(r["uuid"] or "").strip() or item_uuid
    item_su = str(r["session_uuid"] or "").strip()
    if not item_uuid:
        item_uuid = str(_uuid.uuid4())
        conn.execute(
            "UPDATE intercept_items SET uuid=? WHERE id=?",
            (item_uuid, int(r["id"])),
        )
    if not item_su and sess_uuid:
        conn.execute(
            "UPDATE intercept_items SET session_uuid=? WHERE id=?",
            (sess_uuid, int(r["id"])),
        )
        item_su = sess_uuid
    if (not str(r["uuid"] or "").strip()) or (
        not str(r["session_uuid"] or "").strip() and sess_uuid
    ):
        conn.commit()
    return {
        "id": int(r["id"]),
        "session_id": sid,
        "session_uuid": str(item_su or sess_uuid or ""),
        "uuid": str(item_uuid),
        "unit_name": unit,
        "frequency": freq,
        "group_code": grp,
        "content": str(r["content"] or ""),
        "updated_at": str(r["updated_at"] or ""),
    }


def is_intercept_session_closed(conn: sqlite3.Connection, session_id: int) -> bool:
    init_db(conn)
    r = conn.execute(
        "SELECT ended_at FROM intercept_sessions WHERE id=?",
        (int(session_id),),
    ).fetchone()
    if not r:
        r = conn.execute(
            "SELECT ended_at FROM intercept_sessions_archive WHERE id=?",
            (int(session_id),),
        ).fetchone()
    if not r:
        return False
    return bool(r["ended_at"])


def _intercept_session_base_min(
    conn: sqlite3.Connection, item_id: int
) -> int | None:
    """Время старта смены в минутах — опора для сортировки блоков через полночь."""
    from datetime import datetime as _dt

    try:
        r = conn.execute(
            """
            SELECT s.started_at
            FROM intercept_items i
            JOIN intercept_sessions s ON s.id=i.session_id
            WHERE i.id=?
            """,
            (int(item_id),),
        ).fetchone()
        if not r:
            return None
        started_at = str(r["started_at"] or "").strip()
        if not started_at:
            return None
        dt0 = _dt.strptime(started_at, "%Y-%m-%d %H:%M:%S")
        return int(dt0.hour * 60 + dt0.minute)
    except Exception:
        return None


def list_intercept_item_blocks(
    conn: sqlite3.Connection,
    *,
    item_id: int | None = None,
    item_uuid: str | None = None,
) -> list[dict[str, Any]]:
    """Живые блоки бланка в порядке следования."""
    init_db(conn)
    if item_id:
        where, params = "item_id=?", (int(item_id),)
    elif item_uuid:
        where, params = "item_uuid=?", (str(item_uuid),)
    else:
        return []
    rows = conn.execute(
        f"""
        SELECT uuid, item_uuid, item_id, time_key, day_offset, ord,
               header, body, text_hash, updated_by, created_at, updated_at
        FROM intercept_blocks
        WHERE {where} AND deleted_at IS NULL
        ORDER BY day_offset, (time_key IS NULL), time_key, ord
        """,
        params,
    ).fetchall()
    return [
        {
            "uuid": str(r["uuid"]),
            "item_uuid": str(r["item_uuid"] or ""),
            "item_id": int(r["item_id"] or 0),
            "time_key": (None if r["time_key"] is None else int(r["time_key"])),
            "day_offset": int(r["day_offset"] or 0),
            "ord": int(r["ord"] or 0),
            "header": str(r["header"] or ""),
            "body": str(r["body"] or ""),
            "text_hash": str(r["text_hash"] or ""),
            "updated_by": str(r["updated_by"] or ""),
            "created_at": str(r["created_at"] or ""),
            "updated_at": str(r["updated_at"] or ""),
        }
        for r in rows
    ]


def sync_intercept_item_blocks(
    conn: sqlite3.Connection,
    item_id: int,
    content: str,
    updated_by: str = "",
) -> dict[str, int]:
    """Приводит `intercept_blocks` в соответствие с текстом бланка.

    Текст бланка не меняется: блоки — производная от него. Идентификаторы
    существующих блоков сохраняются даже при правке текста или времени,
    исчезнувшие блоки получают надгробие (`deleted_at`), а не удаляются.

    Возвращает сводку по действиям — она полезна в логах и тестах.
    """
    init_db(conn)
    stats = _sync_intercept_item_blocks_unsafe(conn, item_id, content, updated_by)
    # Уважаем режим отложенного commit: при пакетной синхронизации один commit на batch.
    _commit_if_needed(conn)
    return stats


def _sync_intercept_item_blocks_unsafe(
    conn: sqlite3.Connection,
    item_id: int,
    content: str,
    updated_by: str = "",
) -> dict[str, int]:
    """Тело сверки блоков без `init_db` и без commit.

    Отдельная функция нужна, чтобы миграцию можно было вызвать изнутри `init_db`:
    обращение к `init_db` оттуда привело бы к бесконечной рекурсии.
    """
    row = conn.execute(
        "SELECT uuid FROM intercept_items WHERE id=?",
        (int(item_id),),
    ).fetchone()
    if not row:
        return {"created": 0, "changed": 0, "removed": 0, "total": 0}
    item_uuid = str(row["uuid"] or "").strip()
    base_min = _intercept_session_base_min(conn, int(item_id))

    stored_rows = conn.execute(
        """
        SELECT uuid, time_key, header, body, ord
        FROM intercept_blocks
        WHERE item_id=? AND deleted_at IS NULL
        ORDER BY ord, rowid
        """,
        (int(item_id),),
    ).fetchall()
    existing = [
        StoredBlock(
            uuid=str(r["uuid"]),
            time_key=(None if r["time_key"] is None else int(r["time_key"])),
            header=str(r["header"] or ""),
            body=str(r["body"] or ""),
            ord=int(r["ord"] or 0),
        )
        for r in stored_rows
    ]

    incoming = _parse_intercept_blocks(content)
    result = _reconcile_intercept_blocks(existing, incoming)

    # Позиция блока считается по времени, а не по порядку строк в тексте:
    # UUIDv7 упорядочен по моменту создания и для этого не годится.
    order = sorted(
        range(len(result.resolved)),
        key=lambda i: _block_sort_key(
            result.resolved[i].block.time_key, i, base_min=base_min
        ),
    )
    position = {idx: pos for pos, idx in enumerate(order)}

    stats = {"created": 0, "changed": 0, "removed": 0, "total": len(result.resolved)}
    author = str(updated_by or "")

    for i, item in enumerate(result.resolved):
        blk = item.block
        day_off = _block_day_offset(blk.time_key, base_min=base_min)
        if item.uuid is None:
            conn.execute(
                """
                INSERT INTO intercept_blocks
                    (uuid, item_uuid, item_id, time_key, day_offset, ord,
                     header, body, text_hash, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_uuid7(),
                    item_uuid,
                    int(item_id),
                    blk.time_key,
                    day_off,
                    position[i],
                    blk.header,
                    blk.body,
                    blk.text_hash,
                    author,
                ),
            )
            stats["created"] += 1
            continue

        if item.changed:
            conn.execute(
                """
                UPDATE intercept_blocks
                SET item_uuid=?, item_id=?, time_key=?, day_offset=?, ord=?,
                    header=?, body=?, text_hash=?, updated_by=?,
                    updated_at=CURRENT_TIMESTAMP, deleted_at=NULL
                WHERE uuid=?
                """,
                (
                    item_uuid,
                    int(item_id),
                    blk.time_key,
                    day_off,
                    position[i],
                    blk.header,
                    blk.body,
                    blk.text_hash,
                    author,
                    item.uuid,
                ),
            )
            stats["changed"] += 1
        else:
            # Текст тот же — время правки не трогаем, чтобы не создавать
            # ложного признака изменения для потребителей блоков.
            conn.execute(
                """
                UPDATE intercept_blocks
                SET item_uuid=?, item_id=?, day_offset=?, ord=?
                WHERE uuid=?
                """,
                (item_uuid, int(item_id), day_off, position[i], item.uuid),
            )

    for dead in result.removed:
        conn.execute(
            """
            UPDATE intercept_blocks
            SET deleted_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
            WHERE uuid=? AND deleted_at IS NULL
            """,
            (dead,),
        )
        stats["removed"] += 1

    return stats


def _migrate_intercept_blocks_backfill(conn: sqlite3.Connection) -> None:
    """Заводит блоки для бланков активных смен, у которых их ещё нет.

    Идемпотентна: берёт только записи с текстом и без живых блоков. Архив не
    трогаем — там источником остаётся текст бланка.
    """
    try:
        rows = conn.execute(
            """
            SELECT i.id AS id, i.content AS content
            FROM intercept_items i
            WHERE TRIM(COALESCE(i.content, '')) <> ''
              AND NOT EXISTS (
                SELECT 1 FROM intercept_blocks b
                WHERE b.item_id = i.id AND b.deleted_at IS NULL
              )
            """
        ).fetchall()
    except Exception:
        return
    if not rows:
        return
    for r in rows:
        try:
            _sync_intercept_item_blocks_unsafe(
                conn, int(r["id"]), str(r["content"] or "")
            )
        except Exception:
            continue
    try:
        conn.commit()
    except Exception:
        _log.debug("_migrate_intercept_blocks_backfill: suppressed error", exc_info=True)


def update_intercept_item_content(
    conn: sqlite3.Connection, item_id: int, content: str, updated_by: str
) -> dict[str, Any]:
    init_db(conn)
    # совместное редактирование: сливаем контент и сортируем блоки по времени (HH:MM / HH.MM)
    incoming = str(content or "")

    # Для корректной сортировки при переходе через полночь:
    # используем время старта смены как "опорное". Если время блока сильно меньше старта —
    # считаем, что это следующий день.
    from datetime import datetime as _dt

    base_min: int | None = None
    try:
        rbase = conn.execute(
            """
            SELECT s.started_at
            FROM intercept_items i
            JOIN intercept_sessions s ON s.id=i.session_id
            WHERE i.id=?
            """,
            (int(item_id),),
        ).fetchone()
        if rbase:
            started_at = str(rbase["started_at"] or "").strip()
            if started_at:
                dt0 = _dt.strptime(started_at, "%Y-%m-%d %H:%M:%S")
                base_min = int(dt0.hour * 60 + dt0.minute)
    except Exception:
        base_min = None

    ROLLOVER_MIN = 12 * 60

    def _day_off(mins: int | None) -> int:
        if mins is None or base_min is None:
            return 0
        diff = int(base_min) - int(mins)
        return 1 if diff > ROLLOVER_MIN else 0

    def _repair_missing_newlines(text: str) -> str:
        """
        Защита от редкого кейса, когда переносы строк теряются (копипаст/клиент/браузер/IME),
        и бланк превращается в одну строку вида:
          12.10-Привет...(252)12.11-Здравствуй...(151)
        В таком случае пытаемся восстановить переносы по шаблонам времени.
        """
        import re

        t = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        if "\n" in t:
            return t
        # применяем только если строка начинается со времени и содержит 2+ заголовка времени
        if not re.match(r"^\s*\d{1,2}[.:]\d{2}", t):
            return t
        times = list(re.finditer(r"\b(\d{1,2}[.:]\d{2})\b", t))
        if len(times) < 2:
            return t

        out = t
        # 1) вставляем перенос перед каждым заголовком времени (кроме первого),
        # если он "склеен" с предыдущим текстом
        for m in reversed(times[1:]):
            i = m.start()
            # не вставляем если уже есть перенос/пробелы + перенос (но у нас их нет)
            out = out[:i] + "\n" + out[i:]

        # 2) если заголовок времени сразу продолжается текстом/дефисом — вставляем перенос после времени
        out = re.sub(r"(\b\d{1,2}[.:]\d{2}\b)\s*(?=-)", r"\1\n", out)
        return out

    incoming = _repair_missing_newlines(incoming)
    r0 = conn.execute(
        "SELECT content FROM intercept_items WHERE id=?",
        (int(item_id),),
    ).fetchone()
    existing = str(r0["content"] or "") if r0 else ""

    def _parse_time_key(line: str) -> int | None:
        import re

        s = str(line or "").strip()
        m = re.match(r"^(\d{1,2}):(\d{2})$", s)
        if not m:
            m = re.match(r"^(\d{1,2})\.(\d{2})$", s)
        if not m:
            return None
        hh = int(m.group(1))
        mm = int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh * 60 + mm
        return None

    def _normalize_time_header(line: str) -> str:
        """
        Нормализует заголовок времени для "шапок" блоков:
        - `13:01` -> `13.01`
        - `9:05`  -> `9.05`
        Меняем только если строка СТРОГО равна времени (без текста рядом).
        """
        import re

        s0 = str(line or "")
        s = s0.strip()
        m = re.match(r"^(\d{1,2}):(\d{2})$", s)
        if not m:
            return s0
        hh = int(m.group(1))
        mm = int(m.group(2))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return s0
        # сохраняем исходный формат часа (1-2 цифры), минуты всегда 2 цифры
        return f"{hh}.{mm:02d}"

    def _split_blocks(text: str) -> list[tuple[int | None, list[str]]]:
        lines = (text or "").splitlines()
        blocks: list[tuple[int | None, list[str]]] = []
        curr_key: int | None = None
        curr: list[str] = []
        for ln in lines:
            k = _parse_time_key(ln)
            if k is not None:
                # новая шапка времени -> закрываем прошлый блок
                if curr:
                    blocks.append((curr_key, curr))
                curr_key = k
                curr = [_normalize_time_header(ln).rstrip()]
                continue
            # обычная строка
            curr.append(ln.rstrip())
        if curr:
            blocks.append((curr_key, curr))
        return blocks

    def _norm_block(lines: list[str]) -> str:
        # убираем хвостовые пробелы и пустые строки по краям
        xs = [str(x).rstrip() for x in lines]
        while xs and xs[0].strip() == "":
            xs.pop(0)
        while xs and xs[-1].strip() == "":
            xs.pop()
        return "\n".join(xs).strip()

    def _merge(existing_text: str, incoming_text: str) -> str:
        a = _split_blocks(existing_text)
        b = _split_blocks(incoming_text)
        merged: dict[str, tuple[int | None, int, list[str]]] = {}
        order = 0
        for key, lines in a + b:
            norm = _norm_block(lines)
            if not norm:
                continue
            if norm not in merged:
                merged[norm] = (key, order, lines)
                order += 1
            else:
                # если такой блок уже есть, но новый вариант “богаче” (больше строк) — заменим
                prev_key, prev_order, prev_lines = merged[norm]
                if len(lines) > len(prev_lines):
                    merged[norm] = (
                        key if key is not None else prev_key,
                        prev_order,
                        lines,
                    )

        items = list(merged.values())
        items.sort(
            key=lambda t: (
                1 if t[0] is None else 0,  # без времени вниз
                0 if t[0] is None else _day_off(t[0]),
                10**9 if t[0] is None else int(t[0]),
                t[1],  # стабильность
            )
        )
        out_lines: list[str] = []
        for _, __, lines in items:
            # удаляем лишние пустые строки по краям блока
            xs = [str(x).rstrip() for x in lines]
            while xs and xs[0].strip() == "":
                xs.pop(0)
            while xs and xs[-1].strip() == "":
                xs.pop()
            if not xs:
                continue
            # ВАЖНО: не добавляем пустую строку-разделитель автоматически,
            # чтобы при совместной работе не появлялись "лишние пробелы".
            out_lines.extend(xs)
        # сжимаем множественные пустые строки до одной
        compact: list[str] = []
        empty_run = 0
        for ln in out_lines:
            # строка из одних пробелов/табов тоже считается пустой
            if str(ln).strip() == "":
                empty_run += 1
                if empty_run > 1:
                    continue
                compact.append("")
            else:
                empty_run = 0
                compact.append(str(ln).rstrip())
        # убираем пустые строки по краям всего текста
        while compact and str(compact[0]).strip() == "":
            compact.pop(0)
        while compact and str(compact[-1]).strip() == "":
            compact.pop()
        return "\n".join(compact).rstrip() + ("\n" if compact else "")

    def _sort_and_normalize_only(text: str) -> str:
        """
        Применяет обязательную сортировку по времени + нормализацию заголовков времени.
        Используется, когда входящий текст уже включает существующий и мы не хотим merge/dedupe,
        но хотим гарантированно привести "13:11" -> "13.11" и упорядочить блоки.
        """
        blocks = _split_blocks(text or "")
        indexed: list[tuple[int | None, int, list[str]]] = []
        idx = 0
        for k, lines in blocks:
            norm = _norm_block(lines)
            if not norm:
                continue
            indexed.append((k, idx, lines))
            idx += 1
        indexed.sort(
            key=lambda t: (
                1 if t[0] is None else 0,  # без времени вниз
                0 if t[0] is None else _day_off(t[0]),
                10**9 if t[0] is None else int(t[0]),
                t[1],  # стабильность
            )
        )
        out_lines: list[str] = []
        for _, __, lines in indexed:
            xs = [str(x).rstrip() for x in lines]
            while xs and xs[0].strip() == "":
                xs.pop(0)
            while xs and xs[-1].strip() == "":
                xs.pop()
            if not xs:
                continue
            out_lines.extend(xs)
        # сжимаем множественные пустые строки до одной
        compact: list[str] = []
        empty_run = 0
        for ln in out_lines:
            if str(ln).strip() == "":
                empty_run += 1
                if empty_run > 1:
                    continue
                compact.append("")
            else:
                empty_run = 0
                compact.append(str(ln).rstrip())
        while compact and str(compact[0]).strip() == "":
            compact.pop(0)
        while compact and str(compact[-1]).strip() == "":
            compact.pop()
        return "\n".join(compact).rstrip() + ("\n" if compact else "")

    # Частый кейс: UI отправляет полный текст поля (старое+новое).
    # Если входящий контент уже содержит существующий (с учётом нормализации),
    # не пытаемся "умно" мерджить — иначе можно получить дублирование старых блоков
    # при каждом сохранении.
    def _canon(text: str) -> str:
        # нормализуем переносы, тримим пробелы, сжимаем пустые строки
        t = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        lines = [ln.rstrip() for ln in t.split("\n")]
        compact: list[str] = []
        empty_run = 0
        for ln in lines:
            if ln.strip() == "":
                empty_run += 1
                if empty_run > 1:
                    continue
                compact.append("")
            else:
                empty_run = 0
                compact.append(ln)
        # убираем пустые строки по краям
        while compact and compact[0].strip() == "":
            compact.pop(0)
        while compact and compact[-1].strip() == "":
            compact.pop()
        return "\n".join(compact)

    ex_c = _canon(existing)
    in_c = _canon(incoming)
    if ex_c and in_c and (ex_c == in_c or ex_c in in_c):
        merged_content = _sort_and_normalize_only(in_c)
    else:
        merged_content = _merge(existing, incoming)
    conn.execute(
        """
        UPDATE intercept_items
        SET content=?, updated_by=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (merged_content, str(updated_by or ""), int(item_id)),
    )
    conn.commit()
    _sync_blocks_quietly(conn, int(item_id), merged_content, updated_by)
    r = conn.execute(
        """
        SELECT id, session_id, unit_name, frequency, group_code, content, updated_by, updated_at
        FROM intercept_items WHERE id=?
        """,
        (int(item_id),),
    ).fetchone()
    if not r:
        raise ValueError("item not found")
    return {
        "id": int(r["id"]),
        "session_id": int(r["session_id"]),
        "unit_name": str(r["unit_name"] or ""),
        "frequency": str(r["frequency"] or ""),
        "group_code": str(r["group_code"] or ""),
        "content": str(r["content"] or ""),
        "updated_by": str(r["updated_by"] or ""),
        "updated_at": str(r["updated_at"] or ""),
    }


def replace_intercept_item_content(
    conn: sqlite3.Connection, item_id: int, content: str, updated_by: str
) -> dict[str, Any]:
    """
    "Обычное сохранение" бланка: входящий текст считается источником истины.
    Применяем только обязательную нормализацию/сортировку по времени.

    Это позволяет корректно удалять строки/блоки: если оператор удалил — при сохранении не "вернётся" обратно.
    """
    init_db(conn)
    incoming = str(content or "")

    def _repair_missing_newlines(text: str) -> str:
        import re

        t = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        if "\n" in t:
            return t
        if not re.match(r"^\s*\d{1,2}[.:]\d{2}", t):
            return t
        times = list(re.finditer(r"\b(\d{1,2}[.:]\d{2})\b", t))
        if len(times) < 2:
            return t
        out = t
        for m in reversed(times[1:]):
            out = out[: m.start()] + "\n" + out[m.start() :]
        out = re.sub(r"(\b\d{1,2}[.:]\d{2}\b)\s*(?=-)", r"\1\n", out)
        return out

    incoming = _repair_missing_newlines(incoming)

    # Для корректной сортировки через полночь используем время старта смены как "опорное"
    from datetime import datetime as _dt

    base_min: int | None = None
    try:
        rbase = conn.execute(
            """
            SELECT s.started_at
            FROM intercept_items i
            JOIN intercept_sessions s ON s.id=i.session_id
            WHERE i.id=?
            """,
            (int(item_id),),
        ).fetchone()
        if rbase:
            started_at = str(rbase["started_at"] or "").strip()
            if started_at:
                dt0 = _dt.strptime(started_at, "%Y-%m-%d %H:%M:%S")
                base_min = int(dt0.hour * 60 + dt0.minute)
    except Exception:
        base_min = None

    ROLLOVER_MIN = 12 * 60

    def _day_off(mins: int | None) -> int:
        if mins is None or base_min is None:
            return 0
        diff = int(base_min) - int(mins)
        return 1 if diff > ROLLOVER_MIN else 0

    # берём helper из update_intercept_item_content логики (копия минимального набора)
    def _parse_time_key(line: str) -> int | None:
        import re

        s = str(line or "").strip()
        m = re.match(r"^(\d{1,2}):(\d{2})$", s)
        if not m:
            m = re.match(r"^(\d{1,2})\.(\d{2})$", s)
        if not m:
            return None
        hh = int(m.group(1))
        mm = int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh * 60 + mm
        return None

    def _normalize_time_header(line: str) -> str:
        import re

        s0 = str(line or "")
        s = s0.strip()
        m = re.match(r"^(\d{1,2}):(\d{2})$", s)
        if not m:
            return s0
        hh = int(m.group(1))
        mm = int(m.group(2))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return s0
        return f"{hh}.{mm:02d}"

    def _split_blocks(text: str) -> list[tuple[int | None, list[str]]]:
        lines = (text or "").splitlines()
        blocks: list[tuple[int | None, list[str]]] = []
        curr_key: int | None = None
        curr: list[str] = []
        for ln in lines:
            k = _parse_time_key(ln)
            if k is not None:
                if curr:
                    blocks.append((curr_key, curr))
                curr_key = k
                curr = [_normalize_time_header(ln).rstrip()]
                continue
            curr.append(ln.rstrip())
        if curr:
            blocks.append((curr_key, curr))
        return blocks

    def _norm_block(lines: list[str]) -> str:
        xs = [str(x).rstrip() for x in lines]
        while xs and xs[0].strip() == "":
            xs.pop(0)
        while xs and xs[-1].strip() == "":
            xs.pop()
        return "\n".join(xs).strip()

    blocks = _split_blocks(incoming)
    indexed: list[tuple[int | None, int, list[str]]] = []
    idx = 0
    for k, lines in blocks:
        norm = _norm_block(lines)
        if not norm:
            continue
        indexed.append((k, idx, lines))
        idx += 1
    indexed.sort(
        key=lambda t: (
            1 if t[0] is None else 0,
            0 if t[0] is None else _day_off(t[0]),
            10**9 if t[0] is None else int(t[0]),
            t[1],
        )
    )
    out_lines: list[str] = []
    for _, __, lines in indexed:
        xs = [str(x).rstrip() for x in lines]
        while xs and xs[0].strip() == "":
            xs.pop(0)
        while xs and xs[-1].strip() == "":
            xs.pop()
        if not xs:
            continue
        out_lines.extend(xs)
    # сжимаем множественные пустые строки до одной
    compact: list[str] = []
    empty_run = 0
    for ln in out_lines:
        if str(ln).strip() == "":
            empty_run += 1
            if empty_run > 1:
                continue
            compact.append("")
        else:
            empty_run = 0
            compact.append(str(ln).rstrip())
    while compact and str(compact[0]).strip() == "":
        compact.pop(0)
    while compact and str(compact[-1]).strip() == "":
        compact.pop()
    normalized = "\n".join(compact).rstrip() + ("\n" if compact else "")

    conn.execute(
        """
        UPDATE intercept_items
        SET content=?, updated_by=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (normalized, str(updated_by or ""), int(item_id)),
    )
    conn.commit()
    _sync_blocks_quietly(conn, int(item_id), normalized, updated_by)
    r = conn.execute(
        """
        SELECT id, session_id, unit_name, frequency, group_code, content, updated_by, updated_at
        FROM intercept_items WHERE id=?
        """,
        (int(item_id),),
    ).fetchone()
    if not r:
        raise ValueError("item not found")
    return {
        "id": int(r["id"]),
        "session_id": int(r["session_id"]),
        "unit_name": str(r["unit_name"] or ""),
        "frequency": str(r["frequency"] or ""),
        "group_code": str(r["group_code"] or ""),
        "content": str(r["content"] or ""),
        "updated_by": str(r["updated_by"] or ""),
        "updated_at": str(r["updated_at"] or ""),
    }


def get_intercept_item_sync_payload(
    conn: sqlite3.Connection, item_id: int
) -> dict[str, Any]:
    """
    Собирает полный payload для синхронизации intercept_items (с join на session).
    """
    init_db(conn)
    r = conn.execute(
        """
        SELECT
          i.uuid as uuid,
          i.session_uuid as session_uuid,
          s.uuid as session_uuid_fallback,
          s.position_name as position_name,
          s.started_at as session_started_at,
          s.ended_at as session_ended_at,
          i.unit_name as unit_name,
          i.frequency as frequency,
          i.group_code as group_code,
          i.content as content,
          i.updated_by as updated_by,
          i.updated_at as updated_at
        FROM intercept_items i
        JOIN intercept_sessions s ON s.id=i.session_id
        WHERE i.id=?
        """,
        (int(item_id),),
    ).fetchone()
    if not r:
        raise ValueError("item not found")
    return {
        "uuid": str(r["uuid"] or ""),
        "session_uuid": str(r["session_uuid"] or r["session_uuid_fallback"] or ""),
        "position_name": str(r["position_name"] or ""),
        "session_started_at": str(r["session_started_at"] or ""),
        "session_ended_at": str(r["session_ended_at"] or ""),
        "unit_name": str(r["unit_name"] or ""),
        "frequency": str(r["frequency"] or ""),
        "group_code": str(r["group_code"] or ""),
        "content": str(r["content"] or ""),
        "updated_by": str(r["updated_by"] or ""),
        "updated_at": str(r["updated_at"] or ""),
    }


def get_intercept_session(
    conn: sqlite3.Connection, session_id: int
) -> dict[str, Any] | None:
    init_db(conn)
    r = conn.execute(
        """
        SELECT id, position_name, started_at, ended_at, created_by
        FROM intercept_sessions
        WHERE id=?
        """,
        (int(session_id),),
    ).fetchone()
    if not r:
        r = conn.execute(
            """
            SELECT id, position_name, started_at, ended_at, created_by
            FROM intercept_sessions_archive
            WHERE id=?
            """,
            (int(session_id),),
        ).fetchone()
    if not r:
        return None
    return {
        "id": int(r["id"]),
        "position_name": str(r["position_name"] or ""),
        "started_at": str(r["started_at"] or ""),
        "ended_at": str(r["ended_at"] or ""),
        "created_by": str(r["created_by"] or ""),
    }


def list_intercept_items_for_session(
    conn: sqlite3.Connection, session_id: int
) -> list[dict[str, Any]]:
    init_db(conn)
    sid = int(session_id)
    rows = conn.execute(
        """
        SELECT id, unit_name, frequency, group_code, content, updated_at
        FROM intercept_items
        WHERE session_id=?
        ORDER BY unit_name,
                 CAST(REPLACE(COALESCE(frequency, ''), ',', '.') AS REAL) DESC,
                 group_code
        """,
        (sid,),
    ).fetchall()
    if not rows:
        rows = conn.execute(
            """
            SELECT id, unit_name, frequency, group_code, content, updated_at
            FROM intercept_items_archive
            WHERE session_id=?
            ORDER BY unit_name,
                     CAST(REPLACE(COALESCE(frequency, ''), ',', '.') AS REAL) DESC,
                     group_code
            """,
            (sid,),
        ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "unit_name": str(r["unit_name"] or ""),
            "frequency": str(r["frequency"] or ""),
            "group_code": str(r["group_code"] or ""),
            "content": str(r["content"] or ""),
            "updated_at": str(r["updated_at"] or ""),
        }
        for r in rows
    ]


def list_intercept_items_for_day(
    conn: sqlite3.Connection,
    frequency: str,
    group_code: str,
    date_ymd: str,
) -> list[dict[str, Any]]:
    """
    Все записи бланков перехвата по паре (frequency, group_code) за сутки date_ymd.
    Берёт сессии, пересекающиеся с днём (started_at <= конец дня, ended_at >= начало дня или NULL),
    и по ним — intercept_items с данной парой.
    Возвращает список с полями: session_id, position_name, started_at, ended_at, unit_name, content, updated_at.
    """
    init_db(conn)
    freq = str(frequency or "").strip()
    grp = str(group_code or "").strip()
    day = str(date_ymd or "").strip()[:10]
    if not day or len(day) < 10:
        return []
    start_of_day = day + " 00:00:00"
    end_of_day = day + " 23:59:59"
    rows = conn.execute(
        """
        SELECT i.id, i.session_id, i.unit_name, i.frequency, i.group_code, i.content, i.updated_at,
               s.position_name, s.started_at, s.ended_at
        FROM intercept_items i
        JOIN intercept_sessions s ON s.id = i.session_id
        WHERE i.frequency = ? AND i.group_code = ?
          AND s.started_at <= ?
          AND (s.ended_at IS NULL OR s.ended_at >= ?)
        ORDER BY s.started_at ASC, i.id ASC
        """,
        (freq, grp, end_of_day, start_of_day),
    ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "session_id": int(r["session_id"]),
            "unit_name": str(r["unit_name"] or ""),
            "frequency": str(r["frequency"] or ""),
            "group_code": str(r["group_code"] or ""),
            "content": str(r["content"] or ""),
            "updated_at": str(r["updated_at"] or ""),
            "position_name": str(r["position_name"] or ""),
            "started_at": str(r["started_at"] or ""),
            "ended_at": str(r["ended_at"] or ""),
        }
        for r in rows
    ]


def search_intercept_items(
    conn: sqlite3.Connection,
    query: str,
    position_name: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """
    Поиск по ключевым словам в содержимом бланков перехватов (intercept_items).
    Сканирует все смены в базе, включая архив; без привязки к выбранной смене в UI.
    Регистронезависимая фильтрация делается в Python, т.к. SQLite LOWER() не обрабатывает кириллицу.
    """
    init_db(conn)
    q = str(query or "").strip()
    if not q:
        return []
    q_lower = q.lower()
    pos_filter = ""
    params: list[Any] = []
    if position_name and position_name != "__all__":
        pos_filter = "AND (s.position_name = ? OR TRIM(COALESCE(s.position_name,'')) = '')"
        params.append(position_name)
    sql_part = """
        SELECT i.id AS item_id, i.session_id, i.unit_name, i.frequency, i.group_code, i.content, i.updated_at,
               s.position_name, s.started_at, s.ended_at
        FROM {items} i
        JOIN {sessions} s ON s.id = i.session_id
        WHERE TRIM(COALESCE(i.content, '')) <> ''
        {pos_filter}
    """
    sql = f"""
        SELECT item_id, session_id, unit_name, frequency, group_code, content, updated_at,
               position_name, started_at, ended_at
        FROM (
            {sql_part.format(items="intercept_items", sessions="intercept_sessions", pos_filter=pos_filter)}
            UNION ALL
            {sql_part.format(items="intercept_items_archive", sessions="intercept_sessions_archive", pos_filter=pos_filter)}
        )
        ORDER BY started_at DESC, item_id DESC
    """
    rows = conn.execute(sql, (*params, *params)).fetchall()
    out: list[dict[str, Any]] = []
    max_out = max(1, min(limit, 1000))
    for r in rows:
        if len(out) >= max_out:
            break
        content = str(r["content"] or "")
        if q_lower not in content.lower():
            continue
        out.append({
            "id": int(r["item_id"]),
            "session_id": int(r["session_id"]),
            "unit_name": str(r["unit_name"] or ""),
            "frequency": str(r["frequency"] or ""),
            "group_code": str(r["group_code"] or ""),
            "content": content,
            "position_name": str(r["position_name"] or ""),
            "started_at": str(r["started_at"] or ""),
            "ended_at": str(r["ended_at"] or ""),
            "updated_at": str(r["updated_at"] or ""),
        })
    return out


def merge_intercept_day_contents(items: list[dict[str, Any]]) -> str:
    """
    Сливает контент нескольких бланков за день в один текст: блоки по времени из всех сессий,
    отсортированные по дате сессии и времени блока (HH.MM). Каждый content разбивается на блоки
    (шапка времени + строки до следующей шапки), сортировка: по started_at сессии, затем по времени блока.
    """
    import re
    from datetime import datetime as _dt

    def parse_time_key(line: str) -> int | None:
        s = str(line or "").strip()
        m = re.match(r"^(\d{1,2}):(\d{2})$", s)
        if not m:
            m = re.match(r"^(\d{1,2})\.(\d{2})$", s)
        if not m:
            m = re.match(r"^(\d{1,2}):(\d{2})\b", s)
        if not m:
            m = re.match(r"^(\d{1,2})\.(\d{2})\b", s)
        if m:
            hh, mm = int(m.group(1)), int(m.group(2))
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                return hh * 60 + mm
        return None

    def normalize_header(line: str) -> str:
        s = str(line or "").strip()
        m = re.match(r"^(\d{1,2}):(\d{2})$", s)
        if m:
            return f"{int(m.group(1))}.{int(m.group(2)):02d}"
        m = re.match(r"^(\d{1,2})\.(\d{2})\b", s)
        if m:
            return f"{int(m.group(1))}.{int(m.group(2)):02d}"
        return s

    def split_blocks(text: str) -> list[tuple[int | None, list[str]]]:
        lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines()
        blocks: list[tuple[int | None, list[str]]] = []
        curr_key: int | None = None
        curr: list[str] = []
        for ln in lines:
            k = parse_time_key(ln)
            if k is not None:
                if curr:
                    blocks.append((curr_key, curr))
                curr_key = k
                curr = [normalize_header(ln).rstrip()]
                continue
            curr.append(ln.rstrip())
        if curr:
            blocks.append((curr_key, curr))
        return blocks

    # (sort_key, lines) где sort_key = (started_at_iso, time_minutes) для стабильной сортировки
    all_blocks: list[tuple[tuple[str, int], list[str]]] = []
    for it in items or []:
        started_at = str(it.get("started_at") or "").strip()[:19]
        content = str(it.get("content") or "")
        for time_key, block_lines in split_blocks(content):
            if not block_lines:
                continue
            # дата сессии для порядка; время блока
            time_min = int(time_key) if time_key is not None else 0
            sort_key = (started_at, time_min)
            all_blocks.append((sort_key, block_lines))
    all_blocks.sort(key=lambda x: (x[0][0], x[0][1]))
    out_lines: list[str] = []
    for _, lines in all_blocks:
        out_lines.extend(lines)
        out_lines.append("")
    while out_lines and out_lines[-1].strip() == "":
        out_lines.pop()
    return "\n".join(out_lines)


def list_intercept_callsigns(
    conn: sqlite3.Connection, position_name: str
) -> list[dict[str, Any]]:
    init_db(conn)
    pos = (position_name or "").strip()
    rows = conn.execute(
        """
        SELECT id, label, code, tag, tag_desc, tag_color, unit_name, frequency, group_code, updated_at
        FROM intercept_callsigns
        WHERE (
            position_name = ?
            OR TRIM(COALESCE(position_name, '')) = ''
        )
        ORDER BY
          CASE WHEN COALESCE(frequency,'')='' AND COALESCE(group_code,'')='' THEN 0 ELSE 1 END DESC,
          unit_name ASC,
          CAST(REPLACE(frequency, ',', '.') AS REAL) DESC,
          group_code ASC,
          CAST(code AS INTEGER) ASC,
          label ASC
        """,
        (pos,),
    ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "label": str(r["label"] or ""),
            "code": str(r["code"] or ""),
            "tag": str(r["tag"] or ""),
            "tag_desc": str(r["tag_desc"] or ""),
            "tag_color": str(r["tag_color"] or ""),
            "unit_name": str(r["unit_name"] or ""),
            "frequency": str(r["frequency"] or ""),
            "group_code": str(r["group_code"] or ""),
            "updated_at": str(r["updated_at"] or ""),
        }
        for r in rows
    ]


def update_intercept_callsign_tag(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    callsign_id: int,
    tag: str,
    tag_desc: str,
    tag_color: str = "",
) -> None:
    init_db(conn)
    pos = str(position_name or "").strip()
    cid = int(callsign_id)
    if not pos or cid <= 0:
        raise ValueError("position_name/callsign_id обязательны")
    tag_v = str(tag or "").strip()[:60]
    desc_v = str(tag_desc or "").strip()[:500]
    color_v = str(tag_color or "").strip()[:32]
    r = conn.execute(
        "SELECT 1 FROM intercept_callsigns WHERE id=? AND position_name=?",
        (cid, pos),
    ).fetchone()
    if not r:
        raise ValueError("callsign not found")
    conn.execute(
        """
        UPDATE intercept_callsigns
        SET tag=?, tag_desc=?, tag_color=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=? AND position_name=?
        """,
        (tag_v, desc_v, color_v, cid, pos),
    )
    conn.commit()


def upsert_intercept_callsign(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    label: str,
    code: str,
    unit_name: str | None = None,
    frequency: str | None = None,
    group_code: str | None = None,
) -> int:
    import uuid as _uuid

    init_db(conn)
    pos = (position_name or "").strip()
    label = (label or "").strip()
    code = (code or "").strip()
    if not pos or not label or not code:
        raise ValueError("position_name/label/code обязательны")
    # нормализуем код: только цифры
    import re

    code = "".join(re.findall(r"\d+", code))
    if not code:
        raise ValueError("code должен содержать цифры")

    unit_name = (unit_name or "").strip()
    frequency = (frequency or "").strip()
    group_code = (group_code or "").strip()

    r = conn.execute(
        """
        SELECT id FROM intercept_callsigns
        WHERE position_name=? AND code=? AND frequency=? AND group_code=?
        """,
        (pos, code, frequency, group_code),
    ).fetchone()
    if r:
        cid = int(r["id"])
        # гарантируем uuid для старых записей
        try:
            u0 = conn.execute(
                "SELECT uuid FROM intercept_callsigns WHERE id=?",
                (cid,),
            ).fetchone()
            if u0 and not str(u0["uuid"] or "").strip():
                conn.execute(
                    "UPDATE intercept_callsigns SET uuid=? WHERE id=?",
                    (str(_uuid.uuid4()), cid),
                )
        except Exception:
            _log.debug("upsert_intercept_callsign: suppressed error", exc_info=True)
        conn.execute(
            """
            UPDATE intercept_callsigns
            SET label=?, unit_name=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (label, unit_name, cid),
        )
        conn.commit()
        return cid
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO intercept_callsigns (position_name, label, code, unit_name, frequency, group_code, uuid)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (pos, label, code, unit_name, frequency, group_code, str(_uuid.uuid4())),
    )
    conn.commit()
    return int(cur.lastrowid)


def delete_intercept_callsign(conn: sqlite3.Connection, callsign_id: int) -> None:
    init_db(conn)
    conn.execute("DELETE FROM intercept_callsigns WHERE id=?", (int(callsign_id),))
    conn.commit()


def update_intercept_callsign_label(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    callsign_id: int,
    label: str,
) -> None:
    init_db(conn)
    pos = (position_name or "").strip()
    cid = int(callsign_id or 0)
    label = (label or "").strip()
    if not pos or not cid or not label:
        raise ValueError("position_name/callsign_id/label обязательны")
    row = conn.execute(
        "SELECT 1 FROM intercept_callsigns WHERE id=? AND position_name=?",
        (cid, pos),
    ).fetchone()
    if not row:
        raise ValueError("callsign not found")
    conn.execute(
        """
        UPDATE intercept_callsigns
        SET label=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (label, cid),
    )
    conn.commit()


def list_intercept_audio_tasks(
    conn: sqlite3.Connection, position_name: str
) -> list[dict[str, Any]]:
    init_db(conn)
    cur = conn.cursor()
    pos = str(position_name)
    cur.execute(
        """
        SELECT id, position_name, frequency, unit_name, is_active, created_by, created_at
        FROM intercept_audio_tasks
        WHERE position_name=?
        ORDER BY created_at DESC, id DESC
        """,
        (pos,),
    )
    rows = cur.fetchall()

    # Backward‑compat: если для глобального ключа ещё нет строк,
    # пробуем вернуть задания по любым позициям (настроенные ранее).
    if not rows and pos == "__audio_global__":
        cur.execute(
            """
            SELECT id, position_name, frequency, unit_name, is_active, created_by, created_at
            FROM intercept_audio_tasks
            ORDER BY created_at DESC, id DESC
            """
        )
        rows = cur.fetchall()
    return [
        {
            "id": int(r["id"]),
            "position_name": str(r["position_name"] or ""),
            "frequency": str(r["frequency"] or ""),
            "unit_name": str(r["unit_name"] or ""),
            "is_active": bool(int(r["is_active"] or 0)),
            "created_by": str(r["created_by"] or ""),
            "created_at": str(r["created_at"] or ""),
        }
        for r in rows
    ]


def _migrate_intercept_audio_tasks(conn: sqlite3.Connection) -> None:
    try:
        cur = conn.cursor()
        cols = cur.execute("PRAGMA table_info('intercept_audio_tasks')").fetchall()
        if not cols:
            return
        col_names = {str(c[1]) for c in cols}
        needs_rebuild = "group_code" in col_names or "unit_name" not in col_names
        if not needs_rebuild and "is_active" in col_names:
            return
        if not needs_rebuild and "is_active" not in col_names:
            cur.execute(
                "ALTER TABLE intercept_audio_tasks ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1;"
            )
            conn.commit()
            return
        cur.execute(
            "ALTER TABLE intercept_audio_tasks RENAME TO intercept_audio_tasks_old;"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS intercept_audio_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_name TEXT NOT NULL,
                frequency TEXT NOT NULL,
                unit_name TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_by TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(position_name, frequency)
            );
            """
        )
        try:
            cur.execute(
                """
                INSERT OR IGNORE INTO intercept_audio_tasks (position_name, frequency, unit_name, is_active, created_by, created_at)
                SELECT position_name, frequency, '', 1, created_by, created_at
                FROM intercept_audio_tasks_old
                """
            )
        except Exception:
            _log.debug("_migrate_intercept_audio_tasks: suppressed error", exc_info=True)
        cur.execute("DROP TABLE IF EXISTS intercept_audio_tasks_old;")
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            _log.debug("_migrate_intercept_audio_tasks: suppressed error", exc_info=True)


def _migrate_intercept_audio_listened(conn: sqlite3.Connection) -> None:
    try:
        cur = conn.cursor()
        cols = cur.execute("PRAGMA table_info('intercept_audio_listened')").fetchall()
        if not cols:
            return
        col_names = {str(c[1]) for c in cols}
        if "user_id" in col_names:
            return
        # старая схема без user_id — пересоздаём
        cur.execute(
            "ALTER TABLE intercept_audio_listened RENAME TO intercept_audio_listened_old;"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS intercept_audio_listened (
                user_id INTEGER NOT NULL,
                file_key TEXT NOT NULL,
                listened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, file_key)
            );
            """
        )
        if "file_key" in col_names:
            try:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO intercept_audio_listened (user_id, file_key, listened_at)
                    SELECT 0, file_key, listened_at FROM intercept_audio_listened_old
                    """
                )
            except Exception:
                _log.debug("_migrate_intercept_audio_listened: suppressed error", exc_info=True)
        cur.execute("DROP TABLE IF EXISTS intercept_audio_listened_old;")
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            _log.debug("_migrate_intercept_audio_listened: suppressed error", exc_info=True)


def add_intercept_audio_task(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    frequency: str,
    unit_name: str = "",
    created_by: str = "",
) -> int:
    init_db(conn)
    freq = str(frequency or "").strip()
    if not freq:
        raise ValueError("frequency обязательна")
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO intercept_audio_tasks
        (position_name, frequency, unit_name, created_by)
        VALUES (?, ?, ?, ?)
        """,
        (str(position_name), freq, str(unit_name or ""), str(created_by or "")),
    )
    conn.commit()
    if cur.lastrowid:
        return int(cur.lastrowid)
    # если уже было — вернём id существующей записи
    row = cur.execute(
        """
        SELECT id FROM intercept_audio_tasks
        WHERE position_name=? AND frequency=?
        """,
        (str(position_name), freq),
    ).fetchone()
    return int(row["id"] or 0) if row else 0


def delete_intercept_audio_task(
    conn: sqlite3.Connection, *, position_name: str, task_id: int
) -> bool:
    init_db(conn)
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM intercept_audio_tasks WHERE id=? AND position_name=?",
        (int(task_id), str(position_name)),
    )
    conn.commit()
    return cur.rowcount > 0


def set_intercept_audio_task_active(
    conn: sqlite3.Connection, *, position_name: str, task_id: int, is_active: bool
) -> bool:
    init_db(conn)
    cur = conn.cursor()
    cur.execute(
        "UPDATE intercept_audio_tasks SET is_active=? WHERE id=? AND position_name=?",
        (1 if is_active else 0, int(task_id), str(position_name)),
    )
    conn.commit()
    return cur.rowcount > 0


def get_intercept_audio_state(
    conn: sqlite3.Connection, *, position_name: str
) -> dict[str, Any]:
    init_db(conn)
    cur = conn.cursor()
    pos = str(position_name)
    row = cur.execute(
        """
        SELECT folder_path, tasks_only, last_time_ts, is_running, layout_mode
        FROM intercept_audio_state
        WHERE position_name=?
        """,
        (pos,),
    ).fetchone()

    # Backward‑compat: если глобального состояния ещё нет,
    # пробуем использовать любую существующую строку как базовую
    # и сразу сохраняем её под ключом "__audio_global__".
    if not row and pos == "__audio_global__":
        row = cur.execute(
            """
            SELECT folder_path, tasks_only, last_time_ts, is_running, layout_mode
            FROM intercept_audio_state
            ORDER BY updated_at DESC
            LIMIT 1
            """
        ).fetchone()
        if row:
            upsert_intercept_audio_state(
                conn,
                position_name="__audio_global__",
                folder_path=str(row["folder_path"] or ""),
                tasks_only=bool(int(row["tasks_only"] or 0)),
                last_time_ts=float(row["last_time_ts"] or 0.0),
                is_running=bool(int(row["is_running"] or 1)),
                layout_mode=str(row["layout_mode"] or "dmr"),
            )
    if not row:
        return {
            "folder_path": "",
            "tasks_only": False,
            "last_time_ts": 0.0,
            "is_running": True,
            "layout_mode": "dmr",
        }
    layout_raw = ""
    try:
        layout_raw = str(row["layout_mode"] or "")
    except (IndexError, KeyError):
        layout_raw = ""
    layout_mode = "bundle" if layout_raw.strip().lower() == "bundle" else "dmr"
    return {
        "folder_path": str(row["folder_path"] or ""),
        "tasks_only": bool(int(row["tasks_only"] or 0)),
        "last_time_ts": float(row["last_time_ts"] or 0.0),
        "is_running": bool(int(row["is_running"] or 1)),
        "layout_mode": layout_mode,
    }


def upsert_intercept_audio_state(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    folder_path: str,
    tasks_only: bool,
    last_time_ts: float,
    is_running: bool,
    layout_mode: str = "dmr",
) -> None:
    init_db(conn)
    cur = conn.cursor()
    mode = "bundle" if str(layout_mode or "").strip().lower() == "bundle" else "dmr"
    cur.execute(
        """
        INSERT INTO intercept_audio_state (position_name, folder_path, tasks_only, last_time_ts, is_running, layout_mode)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(position_name) DO UPDATE SET
            folder_path=excluded.folder_path,
            tasks_only=excluded.tasks_only,
            last_time_ts=excluded.last_time_ts,
            is_running=excluded.is_running,
            layout_mode=excluded.layout_mode,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            str(position_name),
            str(folder_path or ""),
            1 if tasks_only else 0,
            float(last_time_ts or 0.0),
            1 if is_running else 0,
            mode,
        ),
    )
    conn.commit()


def list_intercept_audio_listened_keys(
    conn: sqlite3.Connection, user_id: int | None = None
) -> set[str]:
    """
    Возвращает набор file_key для уже прослушанных файлов.
    Если user_id указан — только для этого пользователя,
    иначе — для всех пользователей (глобальное состояние "прослушано").
    """
    init_db(conn)
    cur = conn.cursor()
    if user_id is None:
        cur.execute("SELECT DISTINCT file_key FROM intercept_audio_listened")
    else:
        cur.execute(
            "SELECT file_key FROM intercept_audio_listened WHERE user_id=?",
            (int(user_id),),
        )
    return {str(r[0]) for r in cur.fetchall() if r and r[0]}


def mark_intercept_audio_listened(
    conn: sqlite3.Connection, user_id: int, file_key: str
) -> bool:
    init_db(conn)
    key = str(file_key or "").strip()
    if not key:
        return False
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO intercept_audio_listened (user_id, file_key) VALUES (?, ?)",
        (int(user_id), key),
    )
    conn.commit()
    return cur.rowcount > 0


def upsert_intercept_audio_transcript(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    file_key: str,
    folder_path: str = "",
    file_rel: str = "",
    frequency: str = "",
    group_code: str = "",
    correspondent_id: str = "",
    recorded_at: str = "",
    duration_sec: float = 0.0,
    ua_text: str = "",
    ru_text: str = "",
    formatted_text: str = "",
    segments_json: str = "[]",
    confidence: float = 0.0,
    model_version: str = "",
    status: str = "done",
    error_text: str = "",
) -> None:
    init_db(conn)
    pos = str(position_name or "").strip()
    key = str(file_key or "").strip()
    if not pos or not key:
        raise ValueError("position_name и file_key обязательны")
    conn.execute(
        """
        INSERT INTO intercept_audio_transcripts
          (position_name, file_key, folder_path, file_rel, frequency, group_code, correspondent_id,
           recorded_at, duration_sec, ua_text, ru_text, formatted_text, segments_json, confidence,
           model_version, status, error_text, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(position_name, file_key) DO UPDATE SET
          folder_path=excluded.folder_path,
          file_rel=excluded.file_rel,
          frequency=excluded.frequency,
          group_code=excluded.group_code,
          correspondent_id=excluded.correspondent_id,
          recorded_at=excluded.recorded_at,
          duration_sec=excluded.duration_sec,
          ua_text=excluded.ua_text,
          ru_text=excluded.ru_text,
          formatted_text=excluded.formatted_text,
          segments_json=excluded.segments_json,
          confidence=excluded.confidence,
          model_version=excluded.model_version,
          status=excluded.status,
          error_text=excluded.error_text,
          updated_at=CURRENT_TIMESTAMP
        """,
        (
            pos,
            key,
            str(folder_path or ""),
            str(file_rel or ""),
            str(frequency or ""),
            str(group_code or ""),
            str(correspondent_id or ""),
            str(recorded_at or ""),
            float(duration_sec or 0.0),
            str(ua_text or ""),
            str(ru_text or ""),
            str(formatted_text or ""),
            str(segments_json or "[]"),
            float(confidence or 0.0),
            str(model_version or ""),
            str(status or "done"),
            str(error_text or ""),
        ),
    )
    conn.commit()


def get_intercept_audio_transcript(
    conn: sqlite3.Connection, *, position_name: str, file_key: str
) -> dict[str, Any] | None:
    init_db(conn)
    row = conn.execute(
        """
        SELECT *
        FROM intercept_audio_transcripts
        WHERE position_name=? AND file_key=?
        """,
        (str(position_name or ""), str(file_key or "")),
    ).fetchone()
    if not row:
        return None
    return {
        "file_key": str(row["file_key"] or ""),
        "folder_path": str(row["folder_path"] or ""),
        "file_rel": str(row["file_rel"] or ""),
        "frequency": str(row["frequency"] or ""),
        "group_code": str(row["group_code"] or ""),
        "correspondent_id": str(row["correspondent_id"] or ""),
        "recorded_at": str(row["recorded_at"] or ""),
        "duration_sec": float(row["duration_sec"] or 0.0),
        "ua_text": str(row["ua_text"] or ""),
        "ru_text": str(row["ru_text"] or ""),
        "formatted_text": str(row["formatted_text"] or ""),
        "segments_json": str(row["segments_json"] or "[]"),
        "confidence": float(row["confidence"] or 0.0),
        "model_version": str(row["model_version"] or ""),
        "status": str(row["status"] or ""),
        "error_text": str(row["error_text"] or ""),
        "updated_at": str(row["updated_at"] or ""),
    }


def _os_norm_freq(s: str) -> str:
    return (s or "").replace(",", ".").replace(" ", "").strip()


def list_intercept_callsigns_for_unit_pair(
    main_conn: sqlite3.Connection,
    *,
    unit_note: str,
    frequency: str,
    group_id: str,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """
    Позывные из intercept_callsigns по паре (частота, группа) с уточнением по unit_name.
    """
    init_db(main_conn)
    un = (unit_note or "").strip()
    f = (frequency or "").strip()
    g = (group_id or "").strip()
    if not g:
        return []
    limit = max(1, min(int(limit), 2000))
    fn = _os_norm_freq(f)
    cap = min(limit * 4, 8000)
    cur = main_conn.execute(
        f"""
        SELECT id, position_name, label, code, tag, tag_desc, tag_color, unit_name, frequency, group_code, updated_at
        FROM intercept_callsigns
        WHERE TRIM(COALESCE(group_code,'')) = TRIM(?)
          AND (
            ? = ''
            OR REPLACE(REPLACE(TRIM(COALESCE(frequency,'')), ' ', ''), ',', '.') = ?
          )
        ORDER BY label COLLATE NOCASE
        LIMIT {cap}
        """,
        (g, f, fn),
    )
    out: list[dict[str, Any]] = []
    for r in cur.fetchall() or []:
        uu = str(r["unit_name"] or "").strip()
        if un and un != "__none__" and uu and uu != un:
            continue
        if len(out) >= limit:
            break
        out.append(
            {
                "id": int(r["id"]),
                "position_name": str(r["position_name"] or ""),
                "label": str(r["label"] or ""),
                "code": str(r["code"] or ""),
                "tag": str(r["tag"] or ""),
                "tag_desc": str(r["tag_desc"] or ""),
                "tag_color": str(r["tag_color"] or ""),
                "unit_name": str(r["unit_name"] or ""),
                "frequency": str(r["frequency"] or ""),
                "group_code": str(r["group_code"] or ""),
                "updated_at": str(r["updated_at"] or ""),
            }
        )
    return out


def _extract_last_time_block(content: str) -> str:
    """
    Из текста бланка извлекает последний блок времени (шапку вида 13.15 или 13:15).
    Ищет строки, где есть время в начале: отдельная строка "13.15" или "13.15-Текст".
    Возвращает время в формате HH.MM или пустую строку.
    """
    import re

    text = str(content or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.splitlines()
    last_time = ""
    for ln in lines:
        s = str(ln or "").strip()
        # строка только время (13.15 или 13:15)
        m = re.match(r"^(\d{1,2}):(\d{2})$", s)
        if not m:
            m = re.match(r"^(\d{1,2})\.(\d{2})$", s)
        # или время в начале строки (13.15-Текст, 13:15 Текст)
        if not m:
            m = re.match(r"^(\d{1,2}):(\d{2})\b", s)
        if not m:
            m = re.match(r"^(\d{1,2})\.(\d{2})\b", s)
        if m:
            hh = int(m.group(1))
            mm = int(m.group(2))
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                last_time = f"{hh}.{mm:02d}"
    return last_time


def _get_last_recorded_intercept_by_freq_group(
    conn: sqlite3.Connection,
) -> dict[tuple[str, str], str]:
    """
    Последний блок времени + дата записи в бланке перехвата.
    Берётся запись с макс. updated_at, из неё: дата (из updated_at) и последняя шапка времени из content.
    Значение — строка вида "YYYY-MM-DD 13.15" (дата последней записи и последний блок времени).
    """
    init_db(conn)
    if not _table_exists(conn, "intercept_items"):
        return {}
    rows = conn.execute(
        """
        SELECT frequency, group_code, content, COALESCE(updated_at, '') as updated_at
        FROM intercept_items
        ORDER BY frequency, group_code, updated_at DESC
        """
    ).fetchall()
    seen: set[tuple[str, str]] = set()
    out: dict[tuple[str, str], str] = {}
    for r in rows or []:
        key = (str(r["frequency"] or ""), str(r["group_code"] or ""))
        if key in seen:
            continue
        seen.add(key)
        updated_at = str(r["updated_at"] or "").strip()
        content = str(r["content"] or "")
        last_block = _extract_last_time_block(content)
        # дата из updated_at (формат YYYY-MM-DD HH:MM:SS или YYYY-MM-DD)
        date_part = updated_at[:10] if len(updated_at) >= 10 else ""
        if date_part and last_block:
            out[key] = f"{date_part} {last_block}"
        elif date_part:
            out[key] = date_part
        else:
            out[key] = last_block
    return out


__all__ = [
    "init_intercepts",
    "get_intercept_word_push_state",
    "set_intercept_word_push_state",
    "get_intercept_txt_push_state",
    "set_intercept_txt_push_state",
    "compute_intercept_word_delta",
    "record_intercept_catalog_delete",
    "list_intercept_catalog_deletes_since",
    "apply_intercept_catalog_delete_from_sync",
    "list_intercept_catalog_since",
    "list_intercept_callsigns_since",
    "list_intercept_sessions_since",
    "list_intercept_items_since",
    "upsert_intercept_session_from_sync",
    "upsert_intercept_item_from_sync",
    "upsert_intercept_catalog_from_sync",
    "upsert_intercept_callsign_from_sync",
    "list_intercept_catalog",
    "upsert_intercept_catalog",
    "delete_intercept_catalog",
    "list_intercept_sessions",
    "list_intercept_sessions_ordered",
    "get_or_create_active_intercept_session",
    "close_active_and_start_new_intercept_session",
    "get_or_create_intercept_item",
    "is_intercept_session_closed",
    "list_intercept_item_blocks",
    "sync_intercept_item_blocks",
    "update_intercept_item_content",
    "replace_intercept_item_content",
    "get_intercept_item_sync_payload",
    "get_intercept_session",
    "list_intercept_items_for_session",
    "list_intercept_items_for_day",
    "search_intercept_items",
    "merge_intercept_day_contents",
    "list_intercept_callsigns",
    "update_intercept_callsign_tag",
    "upsert_intercept_callsign",
    "delete_intercept_callsign",
    "update_intercept_callsign_label",
    "list_intercept_audio_tasks",
    "add_intercept_audio_task",
    "delete_intercept_audio_task",
    "set_intercept_audio_task_active",
    "get_intercept_audio_state",
    "upsert_intercept_audio_state",
    "list_intercept_audio_listened_keys",
    "mark_intercept_audio_listened",
    "upsert_intercept_audio_transcript",
    "get_intercept_audio_transcript",
    "list_intercept_callsigns_for_unit_pair",
]
