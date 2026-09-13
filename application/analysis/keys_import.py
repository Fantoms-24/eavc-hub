"""Импорт analysis_keys из строк XLSX в SQLite."""

from __future__ import annotations

import sqlite3
from typing import Any

from web_portal.lib.db import _normalize_frequency_key, get_sync_meta, set_sync_meta

from web_portal.application.analysis.errors import AnalysisUseCaseHTTP
from web_portal.application.analysis.keys_helpers import (
    AnalysisKeysColumnIndices,
    find_analysis_keys_column_indices,
    parse_analysis_keys_import_row,
)


def execute_analysis_keys_import(
    conn: sqlite3.Connection,
    rows: list[tuple[Any, ...] | list[Any]],
    *,
    now_ts: str,
) -> dict[str, Any]:
    if not rows:
        raise AnalysisUseCaseHTTP(400, {"ok": False, "error": "Пустой файл"})

    indices = find_analysis_keys_column_indices(rows[0])
    inserted = 0
    updated = 0
    skipped = 0
    cur = conn.cursor()
    previous_import = get_sync_meta(conn, "analysis_keys_last_import") or ""
    existing = {
        (r[0], r[1], r[2], r[3])
        for r in cur.execute(
            "SELECT frequency, group_, aes_id, aes_key FROM analysis_keys"
        ).fetchall()
    }
    for row in rows[1:]:
        if not row:
            continue
        parsed = parse_analysis_keys_import_row(row, indices)
        if parsed is None:
            skipped += 1
            continue
        freq_norm = _normalize_frequency_key(parsed.frequency)
        key = (parsed.frequency, parsed.group, parsed.aes_id, parsed.aes_key)
        if key in existing:
            cur.execute(
                """
                UPDATE analysis_keys
                SET unit_name=COALESCE(?, unit_name),
                    added_date=COALESCE(?, added_date),
                    updated_at=CURRENT_TIMESTAMP
                WHERE frequency=? AND group_=? AND aes_id=? AND aes_key=?
                """,
                (
                    parsed.unit_name or None,
                    parsed.added_date or None,
                    parsed.frequency,
                    parsed.group,
                    parsed.aes_id,
                    parsed.aes_key,
                ),
            )
            updated += 1
        else:
            cur.execute(
                """
                INSERT INTO analysis_keys
                (frequency, frequency_norm, group_, aes_id, aes_key, unit_name, added_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    parsed.frequency,
                    freq_norm,
                    parsed.group,
                    parsed.aes_id,
                    parsed.aes_key,
                    parsed.unit_name or None,
                    parsed.added_date or None,
                ),
            )
            inserted += 1
            existing.add(key)
    conn.commit()
    set_sync_meta(conn, "analysis_keys_last_import", now_ts)
    return {
        "ok": True,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "previous_import": previous_import or None,
    }


__all__ = [
    "AnalysisKeysColumnIndices",
    "execute_analysis_keys_import",
    "find_analysis_keys_column_indices",
]
