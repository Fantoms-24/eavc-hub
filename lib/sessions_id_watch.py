"""Отслеживание ID корреспондентов в сеансах и оповещение всех клиентов."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from web_portal.config import DATA_DIR, DEFAULT_DB_NAME, db_path
from web_portal.lib.collect_seanses_from_dir import SeansEntry
from web_portal.lib.db import _get_unit_name_for_pair, connect, ensure_db, init_db

_log = logging.getLogger("web_portal.lib.sessions_id_watch")

LOG = logging.getLogger("web_portal.sessions_id_watch")

_ALERTS_MAX = 250
_ALERTS_PATH = (DATA_DIR / "sessions_id_watch_alerts.json").resolve()
_ALERTS_LOCK = threading.Lock()
_ID_RE = re.compile(r"^\d{1,10}$")


def _normalize_correspondent_id(raw: object) -> str:
    s = str(raw or "").strip()
    if not s or not _ID_RE.match(s):
        return ""
    return s


def init_sessions_id_watch_tables(conn) -> None:
    init_db(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions_id_watch (
            correspondent_id TEXT NOT NULL PRIMARY KEY,
            created_by TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_id_watch_created ON sessions_id_watch (created_at DESC);"
    )


def list_watched_correspondent_ids(conn) -> list[dict[str, str]]:
    init_sessions_id_watch_tables(conn)
    rows = conn.execute(
        """
        SELECT correspondent_id, created_by, created_at
        FROM sessions_id_watch
        ORDER BY created_at DESC, correspondent_id ASC
        """
    ).fetchall()
    out: list[dict[str, str]] = []
    for row in rows or []:
        cid = _normalize_correspondent_id(row["correspondent_id"])
        if not cid:
            continue
        out.append(
            {
                "correspondent_id": cid,
                "created_by": str(row["created_by"] or ""),
                "created_at": str(row["created_at"] or ""),
            }
        )
    return out


def get_watched_id_set(conn) -> set[str]:
    init_sessions_id_watch_tables(conn)
    rows = conn.execute("SELECT correspondent_id FROM sessions_id_watch").fetchall()
    out: set[str] = set()
    for row in rows or []:
        cid = _normalize_correspondent_id(row["correspondent_id"])
        if cid:
            out.add(cid)
    return out


def add_watched_correspondent_id(
    conn, correspondent_id: str, *, created_by: str = ""
) -> bool:
    cid = _normalize_correspondent_id(correspondent_id)
    if not cid:
        return False
    init_sessions_id_watch_tables(conn)
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO sessions_id_watch (correspondent_id, created_by)
        VALUES (?, ?)
        """,
        (cid, str(created_by or "").strip()),
    )
    conn.commit()
    return int(cur.rowcount or 0) > 0


def parse_correspondent_id_list(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for chunk in re.split(r"[\s,;]+", str(text or "")):
        cid = _normalize_correspondent_id(chunk)
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append(cid)
    return out


def add_watched_correspondent_ids(
    conn, correspondent_ids: list[str], *, created_by: str = ""
) -> list[str]:
    added: list[str] = []
    for raw in correspondent_ids:
        if add_watched_correspondent_id(conn, raw, created_by=created_by):
            cid = _normalize_correspondent_id(raw)
            if cid:
                added.append(cid)
    return added


def remove_watched_correspondent_id(conn, correspondent_id: str) -> bool:
    cid = _normalize_correspondent_id(correspondent_id)
    if not cid:
        return False
    init_sessions_id_watch_tables(conn)
    cur = conn.execute(
        "DELETE FROM sessions_id_watch WHERE correspondent_id = ?",
        (cid,),
    )
    conn.commit()
    return int(cur.rowcount or 0) > 0


def seans_entries_not_in_database(
    conn, entries: list[SeansEntry], *, client_name: str | None = None
) -> list[SeansEntry]:
    """Строки сеансов, которых ещё нет в seanses (до UPSERT)."""
    if not entries:
        return []
    from web_portal.lib.db import init_seans_tables

    init_seans_tables(conn)
    position = str(client_name or "").strip()
    unique: dict[tuple[str, str, str, str, str], SeansEntry] = {}
    for entry in entries:
        unique[
            (
                str(entry.date_time),
                str(entry.frequency),
                str(entry.group),
                str(entry.id),
                position,
            )
        ] = entry
    keys = list(unique.keys())
    existing: set[tuple[str, str, str, str, str]] = set()
    chunk_size = 100
    cur = conn.cursor()
    for i in range(0, len(keys), chunk_size):
        chunk = keys[i : i + chunk_size]
        placeholders = ",".join(["(?,?,?,?,?)"] * len(chunk))
        flat: list[str] = []
        for t in chunk:
            flat.extend(t)
        rows = cur.execute(
            f"""
            SELECT date_time, frequency, group_, id, client_name
            FROM seanses
            WHERE (date_time, frequency, group_, id, client_name) IN ({placeholders})
            """,
            flat,
        ).fetchall()
        for row in rows or []:
            existing.add(
                (
                    str(row[0]),
                    str(row[1]),
                    str(row[2]),
                    str(row[3]),
                    str(row[4] or ""),
                )
            )
    return [unique[k] for k in keys if k not in existing]


def _read_alerts_store() -> dict[str, Any]:
    if not _ALERTS_PATH.is_file():
        return {"latest_seq": 0, "alerts": []}
    try:
        raw = _ALERTS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return {"latest_seq": 0, "alerts": []}
    if not isinstance(data, dict):
        return {"latest_seq": 0, "alerts": []}
    alerts = data.get("alerts")
    if not isinstance(alerts, list):
        alerts = []
    try:
        latest = int(data.get("latest_seq") or 0)
    except Exception:
        latest = 0
    return {"latest_seq": latest, "alerts": alerts}


def _write_alerts_store(data: dict[str, Any]) -> None:
    _ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _ALERTS_PATH.with_suffix(_ALERTS_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_ALERTS_PATH)


def append_id_watch_alerts(alerts: list[dict[str, Any]]) -> int:
    if not alerts:
        return 0
    with _ALERTS_LOCK:
        store = _read_alerts_store()
        latest = int(store.get("latest_seq") or 0)
        bucket = list(store.get("alerts") or [])
        added = 0
        now_s = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for item in alerts:
            latest += 1
            bucket.append(
                {
                    "seq": latest,
                    "correspondent_id": str(item.get("correspondent_id") or ""),
                    "frequency": str(item.get("frequency") or ""),
                    "group_": str(item.get("group_") or ""),
                    "unit_name": str(item.get("unit_name") or ""),
                    "date_time": str(item.get("date_time") or ""),
                    "detected_at": str(item.get("detected_at") or now_s),
                }
            )
            added += 1
        if len(bucket) > _ALERTS_MAX:
            bucket = bucket[-_ALERTS_MAX:]
        _write_alerts_store({"latest_seq": latest, "alerts": bucket})
    return added


def list_id_watch_alerts_since(since_seq: int) -> dict[str, Any]:
    since = max(0, int(since_seq or 0))
    with _ALERTS_LOCK:
        store = _read_alerts_store()
    latest = int(store.get("latest_seq") or 0)
    out = []
    for item in store.get("alerts") or []:
        if not isinstance(item, dict):
            continue
        try:
            seq = int(item.get("seq") or 0)
        except Exception:
            continue
        if seq > since:
            out.append(item)
    return {"latest_seq": latest, "alerts": out}


def _recent_alert_dedupe_keys(limit: int = 120) -> set[tuple[str, str, str, str]]:
    with _ALERTS_LOCK:
        store = _read_alerts_store()
    bucket = list(store.get("alerts") or [])
    out: set[tuple[str, str, str, str]] = set()
    for item in bucket[-max(1, int(limit)) :]:
        if not isinstance(item, dict):
            continue
        cid = _normalize_correspondent_id(item.get("correspondent_id"))
        if not cid:
            continue
        out.add(
            (
                cid,
                str(item.get("date_time") or ""),
                str(item.get("frequency") or ""),
                str(item.get("group_") or ""),
            )
        )
    return out


def _build_watch_alerts_for_entries(
    main_conn,
    entries: list[SeansEntry],
    watched: set[str],
    *,
    recent_alert_keys: set[tuple[str, str, str, str]] | None = None,
) -> list[dict[str, Any]]:
    recent = recent_alert_keys if recent_alert_keys is not None else _recent_alert_dedupe_keys()
    pending: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for entry in entries:
        cid = _normalize_correspondent_id(entry.id)
        if not cid or cid not in watched:
            continue
        dedupe_key = (
            cid,
            str(entry.date_time),
            str(entry.frequency),
            str(entry.group),
        )
        if dedupe_key in seen_keys or dedupe_key in recent:
            continue
        seen_keys.add(dedupe_key)
        unit_name = _get_unit_name_for_pair(
            main_conn, str(entry.frequency), str(entry.group)
        ).strip()
        pending.append(
            {
                "correspondent_id": cid,
                "frequency": str(entry.frequency or ""),
                "group_": str(entry.group or ""),
                "unit_name": unit_name,
                "date_time": str(entry.date_time or ""),
                "detected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return pending


def scan_recent_seans_for_watched_ids(
    *,
    correspondent_ids: list[str] | None = None,
    hours: int = 48,
) -> int:
    """При добавлении ID в список — проверить недавние сеансы и создать оповещения."""
    from web_portal.lib.seans_db import connect_seans_storage

    main_path = db_path(DEFAULT_DB_NAME)
    ensure_db(main_path)
    main_conn = connect(main_path)
    seans_conn = connect_seans_storage()
    try:
        init_db(main_conn)
        watched = get_watched_id_set(main_conn)
        if correspondent_ids:
            wanted = {
                _normalize_correspondent_id(x)
                for x in correspondent_ids
                if _normalize_correspondent_id(x)
            }
            watched = {x for x in watched if x in wanted}
        if not watched:
            return 0
        hrs = max(1, min(int(hours or 48), 168))
        cutoff = datetime.now().timestamp() - hrs * 3600
        placeholders = ",".join(["?"] * len(watched))
        rows = seans_conn.execute(
            f"""
            SELECT date_time, frequency, group_, id
            FROM seanses
            WHERE id IN ({placeholders})
            ORDER BY date_time DESC
            LIMIT 500
            """,
            tuple(sorted(watched)),
        ).fetchall()
        entries: list[SeansEntry] = []
        for row in rows or []:
            try:
                dt = datetime.strptime(str(row[0]), "%Y-%m-%d %H:%M:%S")
            except Exception:
                dt = None
            if dt is not None and dt.timestamp() < cutoff:
                continue
            entries.append(
                SeansEntry(
                    date_time=str(row[0]),
                    frequency=str(row[1]),
                    group=str(row[2]),
                    id=str(row[3]),
                    aes_key=None,
                )
            )
        pending = _build_watch_alerts_for_entries(main_conn, entries, watched)
        if not pending:
            return 0
        return append_id_watch_alerts(pending)
    except Exception:
        LOG.exception("scan_recent_seans_for_watched_ids failed")
        return 0
    finally:
        try:
            main_conn.close()
        except Exception:
            _log.debug("scan_recent_seans_for_watched_ids: suppressed error", exc_info=True)
        try:
            seans_conn.close()
        except Exception:
            _log.debug("scan_recent_seans_for_watched_ids: suppressed error", exc_info=True)


def process_new_seans_for_watch(
    new_entries: list[SeansEntry],
    *,
    main_conn: sqlite3.Connection | None = None,
) -> int:
    """После импорта сеансов — оповещение, если ID в списке отслеживания."""
    if not new_entries:
        return 0
    own_conn = main_conn is None
    if own_conn:
        main_path = db_path(DEFAULT_DB_NAME)
        ensure_db(main_path)
        main_conn = connect(main_path)
    try:
        if own_conn:
            init_db(main_conn)
        watched = get_watched_id_set(main_conn)
        if not watched:
            return 0
        pending = _build_watch_alerts_for_entries(main_conn, new_entries, watched)
        if not pending:
            return 0
        added = append_id_watch_alerts(pending)
        if added:
            LOG.info(
                "ID watch: %s alert(s) for %s",
                added,
                sorted({p["correspondent_id"] for p in pending}),
            )
        return added
    except Exception:
        LOG.exception("ID watch alert failed")
        return 0
    finally:
        if own_conn and main_conn is not None:
            try:
                main_conn.close()
            except Exception:
                _log.debug("process_new_seans_for_watch: suppressed error", exc_info=True)
