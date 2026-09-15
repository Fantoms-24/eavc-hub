"""Server-side unread activity markers for data received from HUBs."""

from __future__ import annotations

import sqlite3
from typing import Any


def ensure_sync_activity_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS sync_activity_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        section TEXT NOT NULL CHECK(section IN ('intercepts', 'aviation')),
        unit_name TEXT NOT NULL DEFAULT '', source_hub TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS sync_activity_notification_reads (
        user_id INTEGER NOT NULL, section TEXT NOT NULL CHECK(section IN ('intercepts', 'aviation')),
        last_notification_id INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (user_id, section))""")


def record_sync_activity(conn: sqlite3.Connection, *, kind: str, payload: dict[str, Any], source_hub: str) -> None:
    """Store only actual text updates, never catalog or service changes."""
    data = payload if isinstance(payload, dict) else {}
    if not str(data.get("content") or "").strip():
        return
    if kind == "intercepts:item":
        section, unit_name = "intercepts", str(data.get("unit_name") or "").strip()
    elif kind in {"aviation:intercept", "aviation:daily_intercept"}:
        section, unit_name = "aviation", str(source_hub or "").strip()
    else:
        return
    ensure_sync_activity_tables(conn)
    conn.execute("INSERT INTO sync_activity_notifications (section, unit_name, source_hub) VALUES (?, ?, ?)",
                 (section, unit_name, str(source_hub or "").strip()))


def get_unread_sync_activity(conn: sqlite3.Connection, *, user_id: int) -> dict[str, dict[str, Any]]:
    ensure_sync_activity_tables(conn)
    rows = conn.execute("""SELECT n.section, MAX(n.id) AS latest_id, COUNT(*) AS count,
               GROUP_CONCAT(DISTINCT NULLIF(n.unit_name, '')) AS units
        FROM sync_activity_notifications n LEFT JOIN sync_activity_notification_reads r
          ON r.user_id=? AND r.section=n.section
        WHERE n.id > COALESCE(r.last_notification_id, 0) GROUP BY n.section""", (int(user_id),)).fetchall()
    return {str(row["section"]): {"latest_id": int(row["latest_id"] or 0), "count": int(row["count"] or 0),
            "units": [u for u in str(row["units"] or "").split(",") if u]} for row in rows}


def mark_sync_activity_read(conn: sqlite3.Connection, *, user_id: int, section: str) -> None:
    if section not in {"intercepts", "aviation"}:
        raise ValueError("unknown activity section")
    ensure_sync_activity_tables(conn)
    row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM sync_activity_notifications WHERE section=?", (section,)).fetchone()
    last_id = int(row[0] or 0) if row else 0
    conn.execute("""INSERT INTO sync_activity_notification_reads (user_id, section, last_notification_id)
        VALUES (?, ?, ?) ON CONFLICT(user_id, section) DO UPDATE SET last_notification_id=excluded.last_notification_id""",
        (int(user_id), section, last_id))
