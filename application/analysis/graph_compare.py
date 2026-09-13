"""Сборка payload для /api/analysis/graph-compare (без Flask)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from web_portal.application.analysis.graph_timeline import (
    collect_scoped_seans_rows,
    load_unit_pairs_by_name,
    resolve_analysis_scope_pairs,
    resolve_graph_timeline_window,
)
from web_portal.application.analysis.period_bounds import (
    fmt_analysis_dt,
    parse_analysis_datetime,
)


def _build_compare_series(
    seans_conn: sqlite3.Connection,
    *,
    start_s: str,
    end_s: str,
    start_dt: datetime,
    end_dt: datetime,
    bucket_minutes: int,
    position_name: str | None,
    scope_pairs: list[tuple[str, str]] | None,
    group_query: str | None,
    include_other: bool,
) -> list[dict[str, object]]:
    rows = collect_scoped_seans_rows(
        seans_conn,
        start_s=start_s,
        end_s=end_s,
        position_name=position_name,
        scope_pairs=scope_pairs or None,
        group_query=group_query or None,
        include_other=include_other,
    )

    total_minutes = int((end_dt - start_dt).total_seconds() / 60)
    bucket_count = max(1, (total_minutes + bucket_minutes - 1) // bucket_minutes)
    buckets: list[dict[str, Any]] = [
        {
            "start": fmt_analysis_dt(
                start_dt + timedelta(minutes=i * bucket_minutes)
            ),
            "end": fmt_analysis_dt(
                min(
                    end_dt,
                    start_dt + timedelta(minutes=(i + 1) * bucket_minutes),
                )
            ),
            "ids": set(),
            "sessions": set(),
        }
        for i in range(bucket_count)
    ]
    for r in rows or []:
        dt = parse_analysis_datetime(str(r[0] or ""))
        if not dt:
            continue
        idx = int((dt - start_dt).total_seconds() / 60) // bucket_minutes
        if idx < 0 or idx >= bucket_count:
            continue
        cid = str(r[3] or "").strip()
        if not cid:
            continue
        buckets[idx]["ids"].add(cid)
        buckets[idx]["sessions"].add(str(r[0] or ""))

    return [
        {
            "start": b["start"],
            "end": b["end"],
            "active_ids": len(b["ids"]),
            "sessions": len(b["sessions"]),
        }
        for b in buckets
    ]


def assemble_analysis_graph_compare_payload(
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
    prev_start: datetime,
    prev_end: datetime,
    prev_start_s: str,
    prev_end_s: str,
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
    curr_series = _build_compare_series(
        seans_conn,
        start_s=start_s,
        end_s=end_s,
        start_dt=start,
        end_dt=end,
        bucket_minutes=bucket_minutes,
        position_name=pos,
        scope_pairs=scope_pairs or None,
        group_query=group_query or None,
        include_other=include_other,
    )
    prev_series = _build_compare_series(
        seans_conn,
        start_s=prev_start_s,
        end_s=prev_end_s,
        start_dt=prev_start,
        end_dt=prev_end,
        bucket_minutes=bucket_minutes,
        position_name=pos,
        scope_pairs=scope_pairs or None,
        group_query=group_query or None,
        include_other=include_other,
    )
    return {
        "ok": True,
        "position": pos,
        "all_positions": all_positions,
        "days": days,
        "bucket_minutes": bucket_minutes,
        "current": curr_series,
        "previous": prev_series,
        "start": start_s,
        "end": end_s,
        "prev_start": prev_start_s,
        "prev_end": prev_end_s,
    }


__all__ = [
    "assemble_analysis_graph_compare_payload",
    "resolve_graph_timeline_window",
]
