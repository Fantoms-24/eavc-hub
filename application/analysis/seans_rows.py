"""Выборка строк сеансов для графов анализа (без Flask)."""

from __future__ import annotations

import sqlite3

from web_portal.lib.db import seanses_union_source_sql


def collect_seans_rows(
    seans_conn: sqlite3.Connection,
    *,
    start_s: str,
    end_s: str,
    position_name: str | None,
    scope_pairs: list[tuple[str, str]] | None = None,
    group_query: str | None = None,
    ids_filter: list[str] | None = None,
) -> list[tuple[str, str, str, str]]:
    seans_src = seanses_union_source_sql(seans_conn)
    where = "s.date_time BETWEEN ? AND ?"
    params: list[object] = [start_s, end_s]
    use_scope_join = False
    if position_name:
        where += " AND s.client_name=?"
        params.append(position_name)
    if group_query:
        where += " AND s.group_ LIKE ?"
        params.append(f"%{group_query}%")
    if scope_pairs:
        scope_pairs = [
            (str(fr or "").strip(), str(gr or "").strip())
            for fr, gr in (scope_pairs or [])[:5000]
            if str(fr or "").strip() and str(gr or "").strip()
        ]
        if scope_pairs:
            seans_conn.execute(
                "CREATE TEMP TABLE IF NOT EXISTS _tmp_scope_pairs (frequency TEXT, group_ TEXT)"
            )
            seans_conn.execute("DELETE FROM _tmp_scope_pairs")
            seans_conn.executemany(
                "INSERT INTO _tmp_scope_pairs (frequency, group_) VALUES (?, ?)",
                scope_pairs,
            )
            use_scope_join = True
        else:
            return []
    if ids_filter:
        ids_filter = ids_filter[:300]
        placeholders = ",".join(["?"] * len(ids_filter))
        where += f" AND s.id IN ({placeholders})"
        params.extend(ids_filter)
    if use_scope_join:
        sql = f"""
            SELECT s.date_time, s.frequency, s.group_, s.id
            FROM ({seans_src}) s
            JOIN _tmp_scope_pairs p
              ON p.frequency = s.frequency AND p.group_ = s.group_
            WHERE {where}
        """
    else:
        sql = f"""
            SELECT s.date_time, s.frequency, s.group_, s.id
            FROM ({seans_src}) s
            WHERE {where}
        """
    rows = seans_conn.execute(sql, tuple(params)).fetchall()
    return [
        (str(r[0] or ""), str(r[1] or ""), str(r[2] or ""), str(r[3] or ""))
        for r in (rows or [])
    ]
