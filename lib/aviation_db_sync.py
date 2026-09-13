"""
Функции синхронизации для модуля авиации.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from web_portal.lib.aviation_db import init_aviation


def get_aviation_frequency_sync_payload(
    conn: sqlite3.Connection, frequency_id: int
) -> dict[str, Any]:
    """Получить payload для синхронизации частоты авиации."""
    import uuid
    cur = conn.cursor()
    cur.execute(
        """
        SELECT uuid, frequency, aviation_type, updated_at
        FROM aviation_frequencies
        WHERE id = ?
        """,
        (frequency_id,),
    )
    row = cur.fetchone()
    if not row:
        raise ValueError("frequency not found")
    row_uuid = str(row[0] or "").strip()
    if not row_uuid:
        row_uuid = str(uuid.uuid4())
        cur.execute(
            """
            UPDATE aviation_frequencies
            SET uuid = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (row_uuid, frequency_id),
        )
        conn.commit()
        cur.execute(
            """
            SELECT uuid, frequency, aviation_type, updated_at
            FROM aviation_frequencies
            WHERE id = ?
            """,
            (frequency_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("frequency not found")
    return {
        "uuid": str(row[0] or ""),
        "frequency": str(row[1] or ""),
        "aviation_type": str(row[2] or ""),
        "updated_at": str(row[3] or ""),
    }


def get_aviation_intercept_sync_payload(
    conn: sqlite3.Connection, intercept_id: int
) -> dict[str, Any]:
    """Получить payload для синхронизации бланка перехвата авиации."""
    import uuid
    cur = conn.cursor()
    cur.execute(
        """
        SELECT i.uuid, i.frequency_id, i.content, i.updated_at, f.uuid as frequency_uuid
        FROM aviation_intercepts i
        JOIN aviation_frequencies f ON i.frequency_id = f.id
        WHERE i.id = ?
        """,
        (intercept_id,),
    )
    row = cur.fetchone()
    if not row:
        raise ValueError("intercept not found")
    intercept_uuid = str(row[0] or "").strip()
    frequency_uuid = str(row[4] or "").strip()
    if not intercept_uuid:
        intercept_uuid = str(uuid.uuid4())
        cur.execute(
            """
            UPDATE aviation_intercepts
            SET uuid = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (intercept_uuid, intercept_id),
        )
        conn.commit()
    if not frequency_uuid:
        frequency_id = int(row[1] or 0)
        if not frequency_id:
            raise ValueError("intercept frequency not found")
        frequency_payload = get_aviation_frequency_sync_payload(conn, frequency_id=frequency_id)
        frequency_uuid = str(frequency_payload.get("uuid") or "").strip()
    cur.execute(
        """
        SELECT i.uuid, i.content, i.updated_at
        FROM aviation_intercepts i
        WHERE i.id = ?
        """,
        (intercept_id,),
    )
    irow = cur.fetchone()
    if not irow:
        raise ValueError("intercept not found")
    return {
        "uuid": str(irow[0] or ""),
        "frequency_uuid": frequency_uuid,
        "content": str(irow[1] or ""),
        "updated_at": str(irow[2] or ""),
    }


def get_aviation_callsign_sync_payload(
    conn: sqlite3.Connection, callsign_id: int
) -> dict[str, Any]:
    """Получить payload для синхронизации позывного авиации."""
    import uuid
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.uuid, c.frequency_id, c.label, c.card_type, c.updated_at,
               f.uuid as frequency_uuid
        FROM aviation_callsigns c
        LEFT JOIN aviation_frequencies f ON c.frequency_id = f.id
        WHERE c.id = ?
        """,
        (callsign_id,),
    )
    row = cur.fetchone()
    if not row:
        raise ValueError("callsign not found")
    callsign_uuid = str(row[0] or "").strip()
    if not callsign_uuid:
        callsign_uuid = str(uuid.uuid4())
        cur.execute(
            """
            UPDATE aviation_callsigns
            SET uuid = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (callsign_uuid, callsign_id),
        )
        conn.commit()
        cur.execute(
            """
            SELECT c.uuid, c.frequency_id, c.label, c.card_type, c.updated_at,
                   f.uuid as frequency_uuid
            FROM aviation_callsigns c
            LEFT JOIN aviation_frequencies f ON c.frequency_id = f.id
            WHERE c.id = ?
            """,
            (callsign_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("callsign not found")
    freq_uuid = str(row[5] or "").strip() if row[5] else ""
    if row[1] and not freq_uuid:
        frequency_payload = get_aviation_frequency_sync_payload(conn, frequency_id=int(row[1]))
        freq_uuid = str(frequency_payload.get("uuid") or "").strip()
    return {
        "uuid": str(row[0] or ""),
        "frequency_uuid": freq_uuid if freq_uuid else None,
        "label": str(row[2] or ""),
        "card_type": str(row[3] or ""),
        "updated_at": str(row[4] or ""),
    }


def upsert_aviation_frequency_from_sync(
    conn: sqlite3.Connection, *, data: dict[str, Any]
) -> int:
    """Upsert частоты авиации из синхронизации."""
    init_aviation(conn)
    d = data or {}
    u = str(d.get("uuid") or "").strip()
    freq = str(d.get("frequency") or "").strip()
    av_type = str(d.get("aviation_type") or "").strip()
    updated_at = str(d.get("updated_at") or "").strip()
    
    if not u or not freq or not av_type:
        raise ValueError("uuid/frequency/aviation_type обязательны")
    
    cur = conn.cursor()
    # Проверяем по UUID
    r = cur.execute("SELECT id, updated_at FROM aviation_frequencies WHERE uuid = ?", (u,)).fetchone()
    if r:
        cid = int(r[0])
        local_updated = str(r[1] or "").strip()
        if updated_at and local_updated and local_updated >= updated_at:
            return cid
        cur.execute(
            """
            UPDATE aviation_frequencies
            SET frequency = ?, aviation_type = ?, updated_at = ?
            WHERE id = ?
            """,
            (freq, av_type, updated_at or None, cid),
        )
        conn.commit()
        return cid
    
    # Проверяем по естественному ключу
    r2 = cur.execute(
        "SELECT id, uuid, updated_at FROM aviation_frequencies WHERE frequency = ? AND aviation_type = ?",
        (freq, av_type),
    ).fetchone()
    if r2:
        cid = int(r2[0])
        local_updated = str(r2[2] or "").strip()
        if updated_at and local_updated and local_updated >= updated_at:
            return cid
        cur.execute(
            """
            UPDATE aviation_frequencies
            SET uuid = ?, updated_at = ?
            WHERE id = ?
            """,
            (u, updated_at or None, cid),
        )
        conn.commit()
        return cid
    
    # Создаем новую
    cur.execute(
        """
        INSERT INTO aviation_frequencies (uuid, frequency, aviation_type, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (u, freq, av_type, updated_at or None),
    )
    conn.commit()
    return cur.lastrowid


def upsert_aviation_intercept_from_sync(
    conn: sqlite3.Connection, *, data: dict[str, Any]
) -> int:
    """Upsert бланка перехвата авиации из синхронизации."""
    init_aviation(conn)
    d = data or {}
    u = str(d.get("uuid") or "").strip()
    freq_uuid = str(d.get("frequency_uuid") or "").strip()
    content = str(d.get("content") or "")
    updated_at = str(d.get("updated_at") or "").strip()
    
    if not u or not freq_uuid:
        raise ValueError("uuid/frequency_uuid обязательны")
    
    # Находим frequency_id по UUID
    cur = conn.cursor()
    freq_row = cur.execute("SELECT id FROM aviation_frequencies WHERE uuid = ?", (freq_uuid,)).fetchone()
    if not freq_row:
        raise ValueError(f"frequency with uuid {freq_uuid} not found")
    frequency_id = int(freq_row[0])
    
    # Проверяем по UUID
    r = cur.execute("SELECT id, updated_at FROM aviation_intercepts WHERE uuid = ?", (u,)).fetchone()
    if r:
        iid = int(r[0])
        local_updated = str(r[1] or "").strip()
        if updated_at and local_updated and local_updated >= updated_at:
            return iid
        cur.execute(
            """
            UPDATE aviation_intercepts
            SET frequency_id = ?, content = ?, updated_at = ?
            WHERE id = ?
            """,
            (frequency_id, content, updated_at or None, iid),
        )
        conn.commit()
        return iid
    
    # Проверяем по frequency_id (может быть только один бланк на частоту)
    r2 = cur.execute(
        "SELECT id, uuid, updated_at FROM aviation_intercepts WHERE frequency_id = ?",
        (frequency_id,),
    ).fetchone()
    if r2:
        iid = int(r2[0])
        local_updated = str(r2[2] or "").strip()
        if updated_at and local_updated and local_updated >= updated_at:
            return iid
        cur.execute(
            """
            UPDATE aviation_intercepts
            SET uuid = ?, content = ?, updated_at = ?
            WHERE id = ?
            """,
            (u, content, updated_at or None, iid),
        )
        conn.commit()
        return iid
    
    # Создаем новый
    cur.execute(
        """
        INSERT INTO aviation_intercepts (uuid, frequency_id, content, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (u, frequency_id, content, updated_at or None),
    )
    conn.commit()
    return cur.lastrowid


def upsert_aviation_callsign_from_sync(
    conn: sqlite3.Connection, *, data: dict[str, Any]
) -> int:
    """Upsert позывного авиации из синхронизации."""
    init_aviation(conn)
    d = data or {}
    u = str(d.get("uuid") or "").strip()
    freq_uuid = d.get("frequency_uuid")
    label = str(d.get("label") or "").strip()
    card_type = str(d.get("card_type") or "").strip()
    updated_at = str(d.get("updated_at") or "").strip()
    
    if not u or not label:
        raise ValueError("uuid/label обязательны")
    
    cur = conn.cursor()
    frequency_id = None
    if freq_uuid:
        freq_row = cur.execute("SELECT id FROM aviation_frequencies WHERE uuid = ?", (freq_uuid,)).fetchone()
        if freq_row:
            frequency_id = int(freq_row[0])
    
    # Проверяем по UUID
    r = cur.execute("SELECT id, updated_at FROM aviation_callsigns WHERE uuid = ?", (u,)).fetchone()
    if r:
        cid = int(r[0])
        local_updated = str(r[1] or "").strip()
        if updated_at and local_updated and local_updated >= updated_at:
            return cid
        cur.execute(
            """
            UPDATE aviation_callsigns
            SET frequency_id = ?, label = ?, card_type = ?, updated_at = ?
            WHERE id = ?
            """,
            (frequency_id, label, card_type, updated_at or None, cid),
        )
        conn.commit()
        return cid
    
    # Создаем новый
    cur.execute(
        """
        INSERT INTO aviation_callsigns (uuid, frequency_id, label, card_type, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (u, frequency_id, label, card_type, updated_at or None),
    )
    conn.commit()
    return cur.lastrowid


def list_aviation_frequencies_after(
    conn: sqlite3.Connection, *, after_updated_at: str, limit: int = 500
) -> list[dict[str, Any]]:
    """Получить список частот авиации, обновленных после указанного времени."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT uuid, frequency, aviation_type, updated_at
        FROM aviation_frequencies
        WHERE updated_at > ?
        ORDER BY updated_at ASC
        LIMIT ?
        """,
        (after_updated_at, limit),
    )
    rows = cur.fetchall()
    return [
        {
            "uuid": str(r[0] or ""),
            "frequency": str(r[1] or ""),
            "aviation_type": str(r[2] or ""),
            "updated_at": str(r[3] or ""),
        }
        for r in rows
    ]


def list_aviation_intercepts_after(
    conn: sqlite3.Connection, *, after_updated_at: str, limit: int = 500
) -> list[dict[str, Any]]:
    """Получить список бланков перехвата авиации, обновленных после указанного времени."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT i.uuid, f.uuid as frequency_uuid, i.content, i.updated_at
        FROM aviation_intercepts i
        JOIN aviation_frequencies f ON i.frequency_id = f.id
        WHERE i.updated_at > ?
        ORDER BY i.updated_at ASC
        LIMIT ?
        """,
        (after_updated_at, limit),
    )
    rows = cur.fetchall()
    return [
        {
            "uuid": str(r[0] or ""),
            "frequency_uuid": str(r[1] or ""),
            "content": str(r[2] or ""),
            "updated_at": str(r[3] or ""),
        }
        for r in rows
    ]


def list_aviation_callsigns_after(
    conn: sqlite3.Connection, *, after_updated_at: str, limit: int = 500
) -> list[dict[str, Any]]:
    """Получить список позывных авиации, обновленных после указанного времени."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.uuid, f.uuid as frequency_uuid, c.label, c.card_type, c.updated_at
        FROM aviation_callsigns c
        LEFT JOIN aviation_frequencies f ON c.frequency_id = f.id
        WHERE c.updated_at > ?
        ORDER BY c.updated_at ASC
        LIMIT ?
        """,
        (after_updated_at, limit),
    )
    rows = cur.fetchall()
    return [
        {
            "uuid": str(r[0] or ""),
            "frequency_uuid": str(r[1] or "") if r[1] else None,
            "label": str(r[2] or ""),
            "card_type": str(r[3] or ""),
            "updated_at": str(r[4] or ""),
        }
        for r in rows
    ]


def apply_aviation_frequency_delete_from_sync(
    conn: sqlite3.Connection, *, payload: dict[str, Any]
) -> bool:
    """Применить удаление частоты авиации из синхронизации."""
    init_aviation(conn)
    d = payload or {}
    u = str(d.get("uuid") or "").strip()
    freq = str(d.get("frequency") or "").strip()
    av_type = str(d.get("aviation_type") or "").strip()
    
    cur = conn.cursor()
    # Удаляем по UUID
    if u:
        cur.execute("DELETE FROM aviation_frequencies WHERE uuid = ?", (u,))
    # Fallback: удаляем по естественному ключу
    elif freq and av_type:
        cur.execute(
            "DELETE FROM aviation_frequencies WHERE frequency = ? AND aviation_type = ?",
            (freq, av_type),
        )
    else:
        return False
    
    conn.commit()
    return cur.rowcount > 0


def apply_aviation_callsign_delete_from_sync(
    conn: sqlite3.Connection, *, payload: dict[str, Any]
) -> bool:
    """Применить удаление позывного авиации из синхронизации."""
    init_aviation(conn)
    d = payload or {}
    u = str(d.get("uuid") or "").strip()
    label = str(d.get("label") or "").strip()
    freq_uuid = str(d.get("frequency_uuid") or "").strip()
    
    cur = conn.cursor()
    # Удаляем по UUID
    if u:
        cur.execute("DELETE FROM aviation_callsigns WHERE uuid = ?", (u,))
    # Fallback: удаляем по label и frequency_uuid
    elif label:
        if freq_uuid:
            # Находим frequency_id по UUID
            freq_row = cur.execute(
                "SELECT id FROM aviation_frequencies WHERE uuid = ?", (freq_uuid,)
            ).fetchone()
            if freq_row:
                frequency_id = int(freq_row[0])
                cur.execute(
                    "DELETE FROM aviation_callsigns WHERE label = ? AND frequency_id = ?",
                    (label, frequency_id),
                )
        else:
            # Удаляем все позывные с таким label
            cur.execute("DELETE FROM aviation_callsigns WHERE label = ?", (label,))
    else:
        return False
    
    conn.commit()
    return cur.rowcount > 0
