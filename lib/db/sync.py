"""Outbox и sync meta — физический доменный модуль."""
from __future__ import annotations

import logging
from typing import Any
import sqlite3

_log = logging.getLogger("web_portal.db")

_SYNC_OUTBOX_PRIORITY_KINDS: tuple[str, ...] = (
    "intercepts:item",
    "intercepts:session",
    "intercepts:catalog",
    "intercepts:catalog_delete",
    "intercepts:callsign",
    "analysis:assignment",
    "chat:message",
)


def init_sync(conn: sqlite3.Connection) -> None:
    """
    Таблицы для синхронизации (hub <-> server):
      - sync_outbox: очередь изменений, которые нужно отправить на апстрим
      - sync_meta: курсоры (last_pull_ts и т.п.)
    """
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sent_at TIMESTAMP,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT ''
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        );
        """
    )
    conn.commit()


def enqueue_sync_outbox(
    conn: sqlite3.Connection, *, kind: str, payload: dict[str, Any]
) -> int:
    """
    Кладёт событие в outbox. Используется на HUB, чтобы переживать офлайн.
    """
    import json as _json

    init_sync(conn)
    k = str(kind or "").strip()
    if not k:
        raise ValueError("kind обязателен")
    payload_json = _json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sync_outbox (kind, payload_json) VALUES (?, ?)",
        (k, payload_json),
    )
    conn.commit()
    return int(cur.lastrowid)


def _sync_outbox_priority_order_sql() -> str:
    parts = [f"WHEN '{k}' THEN {i}" for i, k in enumerate(_SYNC_OUTBOX_PRIORITY_KINDS)]
    return "CASE kind " + " ".join(parts) + " ELSE 100 END"


def list_sync_outbox_pending(
    conn: sqlite3.Connection,
    *,
    limit: int = 200,
    priority_only: bool = False,
) -> list[dict[str, Any]]:
    init_sync(conn)
    limit = max(1, min(int(limit), 1000))
    order_sql = _sync_outbox_priority_order_sql()
    where_extra = ""
    params: list[Any] = []
    if priority_only:
        placeholders = ",".join(["?"] * len(_SYNC_OUTBOX_PRIORITY_KINDS))
        where_extra = f" AND kind IN ({placeholders})"
        params.extend(_SYNC_OUTBOX_PRIORITY_KINDS)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT id, kind, payload_json, attempts, created_at
        FROM sync_outbox
        WHERE sent_at IS NULL{where_extra}
        ORDER BY {order_sql}, id ASC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows or []:
        out.append(
            {
                "id": int(r["id"]),
                "kind": str(r["kind"] or ""),
                "payload_json": str(r["payload_json"] or ""),
                "attempts": int(r["attempts"] or 0),
                "created_at": str(r["created_at"] or ""),
            }
        )
    return out


def mark_sync_outbox_sent(conn: sqlite3.Connection, ids: list[int]) -> None:
    init_sync(conn)
    xs = [int(x) for x in (ids or []) if int(x) > 0]
    if not xs:
        return
    q = ",".join(["?"] * len(xs))
    conn.execute(
        f"UPDATE sync_outbox SET sent_at=CURRENT_TIMESTAMP WHERE id IN ({q})",
        tuple(xs),
    )
    conn.commit()


def mark_sync_outbox_failed(
    conn: sqlite3.Connection, *, outbox_id: int, error: str
) -> None:
    init_sync(conn)
    conn.execute(
        """
        UPDATE sync_outbox
        SET attempts=attempts+1, last_error=?
        WHERE id=?
        """,
        (str(error or "")[:500], int(outbox_id)),
    )
    conn.commit()


def get_sync_meta(conn: sqlite3.Connection, key: str) -> str:
    init_sync(conn)
    k = str(key or "").strip()
    if not k:
        return ""
    r = conn.execute("SELECT value FROM sync_meta WHERE key=?", (k,)).fetchone()
    return str(r["value"] or "") if r else ""


def set_sync_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    init_sync(conn)
    k = str(key or "").strip()
    if not k:
        return
    v = str(value or "")
    conn.execute(
        """
        INSERT INTO sync_meta (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (k, v),
    )
    conn.commit()


def upsert_analysis_assignment_from_sync(
    conn: sqlite3.Connection, *, payload: dict[str, Any]
) -> None:
    from web_portal.lib.db.connection import init_db
    from web_portal.lib.db.connection import _commit_if_needed
    init_db(conn)
    d = payload or {}
    pos = str(d.get("position_name") or "").strip()
    freq = str(d.get("frequency") or "").strip()
    grp = str(d.get("group_code") or "").strip()
    role_type = str(d.get("role_type") or "").strip().lower()
    code = str(d.get("callsign_code") or "").strip()
    updated_at = str(d.get("updated_at") or "").strip()
    if not pos or not freq or not grp or not role_type:
        raise ValueError("position_name/frequency/group_code/role_type обязательны")

    r = conn.execute(
        """
        SELECT updated_at, callsign_code
        FROM analysis_assignments
        WHERE position_name=? AND frequency=? AND group_code=? AND role_type=?
        """,
        (pos, freq, grp, role_type),
    ).fetchone()
    if r:
        local_updated = str(r["updated_at"] or "").strip()
        if updated_at and local_updated and local_updated >= updated_at:
            return
        # пустой code = снять назначение
        if not code:
            conn.execute(
                """
                DELETE FROM analysis_assignments
                WHERE position_name=? AND frequency=? AND group_code=? AND role_type=?
                """,
                (pos, freq, grp, role_type),
            )
            _commit_if_needed(conn)
            return
        conn.execute(
            """
            UPDATE analysis_assignments
            SET callsign_code=?, updated_at=?
            WHERE position_name=? AND frequency=? AND group_code=? AND role_type=?
            """,
            (code, updated_at or None, pos, freq, grp, role_type),
        )
        _commit_if_needed(conn)
        return
    # нет записи
    if not code:
        return
    conn.execute(
        """
        INSERT INTO analysis_assignments (position_name, frequency, group_code, role_type, callsign_code, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (pos, freq, grp, role_type, code, updated_at or None),
    )
    _commit_if_needed(conn)


def upsert_unit_rows_from_sync(
    conn: sqlite3.Connection, *, rows: list[dict[str, Any]]
) -> dict[str, int]:
    """
    Применение unit на принимающей стороне.
    Держим инвариант: для (frequency, group_) должна быть одна строка name.

    В синхронизации SERVER и HUB могут прислать одну и ту же строку обратно
    друг другу. Не переписываем совпадающее значение и не затираем локальную
    более свежую правку устаревшим пакетом.
    """
    from web_portal.lib.db.connection import init_db
    from web_portal.lib.db.connection import _commit_if_needed
    init_db(conn)
    if not rows:
        return {"applied": 0}
    applied = 0
    unchanged = 0
    skipped_newer = 0
    cur = conn.cursor()
    for r in rows or []:
        f = str(r.get("frequency") or "")
        g = str(r.get("group_") or "")
        n = str(r.get("name") or "")
        manual = int(r.get("manual") or 0)
        ts = str(r.get("updated_at") or "").strip()
        if not f or not g:
            continue
        existing = cur.execute(
            """
            SELECT name, COALESCE(manual, 0), COALESCE(updated_at, '')
            FROM unit
            WHERE frequency=? AND group_=?
            LIMIT 1
            """,
            (f, g),
        ).fetchone()
        if existing is not None:
            current_name = str(existing[0] or "")
            current_manual = int(existing[1] or 0)
            current_ts = str(existing[2] or "").strip()
            if current_name == n and current_manual == manual:
                unchanged += 1
                continue
            # SQLite CURRENT_TIMESTAMP и синхронный updated_at имеют один
            # лексикографически сортируемый UTC-формат. Пустой timestamp у
            # старого отправителя считаем более старым, чем локальная правка.
            if current_ts and (not ts or current_ts > ts):
                skipped_newer += 1
                continue
        # заменяем все варианты имени на новое
        cur.execute("DELETE FROM unit WHERE frequency=? AND group_=?", (f, g))
        cur.execute(
            "INSERT OR IGNORE INTO unit (frequency, group_, name, manual, updated_at) VALUES (?, ?, ?, ?, ?)",
            (f, g, n, manual, ts or None),
        )
        applied += 1
    _commit_if_needed(conn)
    return {
        "applied": applied,
        "unchanged": unchanged,
        "skipped_newer": skipped_newer,
    }


def _sync_blocks_quietly(
    conn: sqlite3.Connection, item_id: int, content: str, updated_by: str = ""
) -> None:
    """Пересчёт блоков бланка «без шума».

    Блоки — производная от текста бланка, поэтому сбой здесь не должен ронять
    сохранение: блоки просто останутся неактуальными до следующей записи, а сам
    бланк и все выгрузки из него не пострадают.
    """
    from web_portal.lib.db.intercepts import sync_intercept_item_blocks

    try:
        sync_intercept_item_blocks(conn, int(item_id), content, updated_by)
    except Exception:
        _log.debug("_sync_blocks_quietly: suppressed error", exc_info=True)


__all__ = [
    "init_sync",
    "enqueue_sync_outbox",
    "list_sync_outbox_pending",
    "mark_sync_outbox_sent",
    "mark_sync_outbox_failed",
    "get_sync_meta",
    "set_sync_meta",
    "upsert_analysis_assignment_from_sync",
    "upsert_unit_rows_from_sync",
    "_SYNC_OUTBOX_PRIORITY_KINDS",
]
