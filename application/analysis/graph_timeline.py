"""Сборка payload для /api/analysis/graph-timeline (без Flask)."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from web_portal.application.analysis.graph_payload import (
    pairs_for_unit_exact,
    pairs_for_unit_query,
)
from web_portal.application.analysis.period_bounds import (
    fmt_analysis_dt,
    parse_analysis_datetime,
)
from web_portal.application.analysis.seans_rows import collect_seans_rows


def load_unit_pairs_by_name(
    conn: sqlite3.Connection,
) -> dict[str, list[tuple[str, str]]]:
    unit_rows = conn.execute(
        """
        SELECT frequency, group_, name, COALESCE(manual, 0) AS manual, COALESCE(updated_at, '') AS updated_at
        FROM unit
        ORDER BY COALESCE(manual, 0) DESC, COALESCE(updated_at, '') DESC
        """
    ).fetchall()
    unit_pairs_by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r in unit_rows or []:
        freq = str(r["frequency"] or "")
        grp = str(r["group_"] or "")
        name = str(r["name"] or "").strip()
        if name:
            unit_pairs_by_name.setdefault(name, []).append((freq, grp))
    return unit_pairs_by_name


def resolve_analysis_scope_pairs(
    conn: sqlite3.Connection,
    unit_pairs_by_name: dict[str, list[tuple[str, str]]],
    *,
    unit_name: str,
    frequency: str,
    group_code: str,
    unit_query: str,
) -> list[tuple[str, str]]:
    scope_pairs: list[tuple[str, str]] = []
    if frequency and group_code:
        scope_pairs = [(frequency, group_code)]
    elif unit_name:
        scope_pairs = pairs_for_unit_exact(unit_pairs_by_name, unit_name)
    if unit_query:
        pairs_by_query = pairs_for_unit_query(conn, unit_query)
        if scope_pairs:
            scope_set = set(scope_pairs)
            scope_pairs = [p for p in pairs_by_query if p in scope_set]
        else:
            scope_pairs = pairs_by_query
    return scope_pairs


def default_graph_timeline_bucket_minutes(days: int) -> int:
    if days <= 1:
        return 60
    if days <= 3:
        return 120
    if days <= 7:
        return 360
    return 360


def resolve_graph_timeline_window(
    *,
    days: int,
    start_override: datetime | None,
    end_override: datetime | None,
    now: datetime,
) -> tuple[datetime, datetime, int]:
    bucket_minutes = default_graph_timeline_bucket_minutes(days)
    if start_override and end_override and end_override > start_override:
        start = start_override
        end = end_override
        total_minutes = max(1, int((end - start).total_seconds() / 60))
        bucket_minutes = max(5, min(360, int(total_minutes / 24) or 5))
    else:
        end = now
        start = end - timedelta(days=days)
    return start, end, bucket_minutes


def collect_scoped_seans_rows(
    seans_conn: sqlite3.Connection,
    *,
    start_s: str,
    end_s: str,
    position_name: str | None,
    scope_pairs: list[tuple[str, str]] | None,
    group_query: str | None,
    include_other: bool,
) -> list[tuple[str, str, str, str]]:
    rows = collect_seans_rows(
        seans_conn,
        start_s=start_s,
        end_s=end_s,
        position_name=position_name,
        scope_pairs=scope_pairs or None,
        group_query=group_query or None,
        ids_filter=None,
    )
    rows_set = set(rows)
    if include_other and scope_pairs:
        ids_set = {r[3] for r in rows_set if r[3]}
        if ids_set:
            extra = collect_seans_rows(
                seans_conn,
                start_s=start_s,
                end_s=end_s,
                position_name=position_name,
                scope_pairs=None,
                group_query=group_query or None,
                ids_filter=list(ids_set),
            )
            rows_set |= set(extra)
    return list(rows_set)


def assemble_analysis_graph_timeline_payload(
    conn: sqlite3.Connection,
    seans_conn: sqlite3.Connection,
    *,
    pos: str | None,
    all_positions: bool,
    unit_name: str,
    frequency: str,
    group_code: str,
    unit_query: str,
    group_query: str,
    include_other: bool,
    days: int,
    start: datetime,
    end: datetime,
    bucket_minutes: int,
    start_s: str,
    end_s: str,
) -> dict[str, Any]:
    unit_pairs_by_name = load_unit_pairs_by_name(conn)
    scope_pairs = resolve_analysis_scope_pairs(
        conn,
        unit_pairs_by_name,
        unit_name=unit_name,
        frequency=frequency,
        group_code=group_code,
        unit_query=unit_query,
    )
    rows = collect_scoped_seans_rows(
        seans_conn,
        start_s=start_s,
        end_s=end_s,
        position_name=pos,
        scope_pairs=scope_pairs or None,
        group_query=group_query or None,
        include_other=include_other,
    )

    total_minutes = int((end - start).total_seconds() / 60)
    bucket_count = max(1, (total_minutes + bucket_minutes - 1) // bucket_minutes)
    buckets: list[dict[str, Any]] = [
        {
            "start": fmt_analysis_dt(start + timedelta(minutes=i * bucket_minutes)),
            "end": fmt_analysis_dt(
                min(end, start + timedelta(minutes=(i + 1) * bucket_minutes))
            ),
            "ids": set(),
            "id_counts": defaultdict(int),
            "sessions": set(),
        }
        for i in range(bucket_count)
    ]

    for r in rows or []:
        dt = parse_analysis_datetime(str(r[0] or ""))
        if not dt:
            continue
        idx = int((dt - start).total_seconds() / 60) // bucket_minutes
        if idx < 0 or idx >= bucket_count:
            continue
        cid = str(r[3] or "").strip()
        if not cid:
            continue
        buckets[idx]["ids"].add(cid)
        buckets[idx]["id_counts"][cid] += 1
        buckets[idx]["sessions"].add(str(r[0] or ""))

    out: list[dict[str, object]] = []
    prev_ids: set[str] = set()
    for b in buckets:
        ids_set: set[str] = b["ids"]
        top = sorted(b["id_counts"].items(), key=lambda x: (-x[1], x[0]))[:6]
        new_ids = len(ids_set - prev_ids)
        gone_ids = len(prev_ids - ids_set)
        prev_ids = set(ids_set)
        out.append(
            {
                "start": b["start"],
                "end": b["end"],
                "active_ids": len(ids_set),
                "sessions": len(b["sessions"]),
                "new_ids": new_ids,
                "gone_ids": gone_ids,
                "top_ids": [{"id": k, "count": int(v)} for k, v in top],
            }
        )

    total_counts: defaultdict[str, int] = defaultdict(int)
    for b in buckets:
        for k, v in (b["id_counts"] or {}).items():
            total_counts[k] += int(v or 0)
    top_ids = [
        k
        for k, _ in sorted(total_counts.items(), key=lambda x: (-x[1], x[0]))[:30]
    ]
    heatmap_buckets = [
        {
            "start": b["start"],
            "end": b["end"],
            "counts": [int((b["id_counts"] or {}).get(k, 0)) for k in top_ids],
        }
        for b in buckets
    ]

    return {
        "ok": True,
        "position": pos,
        "all_positions": all_positions,
        "days": days,
        "bucket_minutes": bucket_minutes,
        "start": start_s,
        "end": end_s,
        "buckets": out,
        "heatmap": {"ids": top_ids, "buckets": heatmap_buckets},
    }
