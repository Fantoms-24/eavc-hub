"""Общие объекты карты (физически из ``_impl``)."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from web_portal.lib.db.connection import init_db



def get_map_shared_objects(
    conn: sqlite3.Connection, position_names: list[str]
) -> dict[str, Any]:
    """Общие метки/папки карты для списка позиций ('' — глобальные)."""
    init_db(conn)
    names = list(dict.fromkeys([str(p or "") for p in (position_names or [])]))
    if "" not in names:
        names.append("")
    placeholders = ",".join(["?"] * len(names))
    rows = conn.execute(
        f"""
        SELECT kind, obj_id, payload, updated_at
        FROM map_shared_objects
        WHERE position_name IN ({placeholders})
        ORDER BY updated_at, obj_id
        """,
        names,
    ).fetchall()
    annotations: list[dict[str, Any]] = []
    folders: list[dict[str, Any]] = []
    latest = ""
    for r in rows:
        try:
            payload = json.loads(str(r[2] or "{}"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        updated_at = str(r[3] or "")
        if updated_at > latest:
            latest = updated_at
        if str(r[0]) == "folder":
            folders.append(payload)
        else:
            annotations.append(payload)
    return {"annotations": annotations, "folders": folders, "latest": latest}


def get_map_shared_objects_all(conn: sqlite3.Connection) -> dict[str, Any]:
    """Все общие метки/папки карты (все позиции; при дубликате id — новее updated_at)."""
    init_db(conn)
    rows = conn.execute(
        """
        SELECT kind, obj_id, payload, updated_at
        FROM map_shared_objects
        ORDER BY updated_at, obj_id
        """
    ).fetchall()
    ann_by_id: dict[str, dict[str, Any]] = {}
    folder_by_id: dict[str, dict[str, Any]] = {}
    latest = ""
    for r in rows:
        try:
            payload = json.loads(str(r[2] or "{}"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        obj_id = str(r[1] or "").strip()
        if not obj_id:
            continue
        updated_at = str(r[3] or "")
        if updated_at > latest:
            latest = updated_at
        bucket = folder_by_id if str(r[0]) == "folder" else ann_by_id
        prev = bucket.get(obj_id)
        if prev is None or str(prev.get("_updated_at") or "") <= updated_at:
            merged = dict(payload)
            merged["_updated_at"] = updated_at
            bucket[obj_id] = merged

    def _strip_meta(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in items:
            row = dict(item)
            row.pop("_updated_at", None)
            out.append(row)
        return out

    return {
        "annotations": _strip_meta(list(ann_by_id.values())),
        "folders": _strip_meta(list(folder_by_id.values())),
        "latest": latest,
    }


def save_map_shared_objects(
    conn: sqlite3.Connection,
    position_name: str,
    upsert_annotations: list[dict[str, Any]] | None = None,
    upsert_folders: list[dict[str, Any]] | None = None,
    delete_annotation_ids: list[str] | None = None,
    delete_folder_ids: list[str] | None = None,
    updated_by: str = "",
) -> dict[str, int]:
    """Применяет изменения общих меток/папок карты (upsert + delete)."""
    init_db(conn)
    from datetime import datetime as _dt

    pos = str(position_name or "")
    cur = conn.cursor()
    upserted = 0
    deleted = 0
    now = _dt.now().strftime("%Y-%m-%d %H:%M:%S")

    def _apply_upserts(kind: str, items: list[dict[str, Any]] | None) -> None:
        nonlocal upserted
        for item in items or []:
            if not isinstance(item, dict):
                continue
            obj_id = str(item.get("id") or "").strip()
            if not obj_id:
                continue
            # id метки уникален для всей карты — убираем старые копии с других позиций
            cur.execute(
                "DELETE FROM map_shared_objects WHERE kind = ? AND obj_id = ? AND position_name != ?",
                (kind, obj_id, pos),
            )
            cur.execute(
                """
                INSERT INTO map_shared_objects
                    (position_name, kind, obj_id, payload, updated_at, updated_by)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(position_name, kind, obj_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (pos, kind, obj_id, json.dumps(item, ensure_ascii=False), now, updated_by),
            )
            upserted += 1

    def _apply_deletes(kind: str, ids: list[str] | None) -> None:
        nonlocal deleted
        for raw_id in ids or []:
            obj_id = str(raw_id or "").strip()
            if not obj_id:
                continue
            if pos == "":
                cur.execute(
                    "DELETE FROM map_shared_objects WHERE kind = ? AND obj_id = ?",
                    (kind, obj_id),
                )
            else:
                cur.execute(
                    "DELETE FROM map_shared_objects WHERE position_name = ? AND kind = ? AND obj_id = ?",
                    (pos, kind, obj_id),
                )
            deleted += cur.rowcount

    _apply_upserts("annotation", upsert_annotations)
    _apply_upserts("folder", upsert_folders)
    _apply_deletes("annotation", delete_annotation_ids)
    _apply_deletes("folder", delete_folder_ids)
    conn.commit()
    return {"upserted": upserted, "deleted": deleted}


__all__ = [
    "get_map_shared_objects",
    "get_map_shared_objects_all",
    "save_map_shared_objects",
]
