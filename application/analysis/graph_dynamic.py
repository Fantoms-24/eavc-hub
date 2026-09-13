"""Payload для /api/analysis/graph-dynamic/* (без Flask)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from web_portal.application.analysis.graph_payload import build_simple_analysis_graph
from web_portal.application.analysis.graph_timeline import collect_scoped_seans_rows
from web_portal.application.analysis.period_bounds import (
    fmt_analysis_dt,
    msk_now_naive,
    parse_analysis_datetime,
)


def resolve_dynamic_scope_pairs(
    conn: sqlite3.Connection,
    *,
    unit_name: str,
    frequency: str,
    group_code: str,
    unit_query: str,
) -> list[tuple[str, str]]:
    """Простой scope как в прежнем ``_analysis_scope_pairs`` route-helper."""
    if frequency and group_code:
        return [(frequency, group_code)]
    if unit_name:
        rows = conn.execute(
            "SELECT frequency, group_ FROM unit WHERE name=?",
            (unit_name,),
        ).fetchall()
        return [(str(r[0] or ""), str(r[1] or "")) for r in (rows or [])]
    if unit_query:
        rows = conn.execute(
            "SELECT frequency, group_ FROM unit WHERE name LIKE ?",
            (f"%{unit_query}%",),
        ).fetchall()
        return [(str(r[0] or ""), str(r[1] or "")) for r in (rows or [])]
    return []


def assemble_analysis_graph_dynamic_timeline_payload(
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
    start: datetime,
    end: datetime,
    bucket_minutes: int,
) -> dict[str, Any]:
    scope_pairs = resolve_dynamic_scope_pairs(
        conn,
        unit_name=unit_name,
        frequency=frequency,
        group_code=group_code,
        unit_query=unit_query,
    )
    rows = collect_scoped_seans_rows(
        seans_conn,
        start_s=fmt_analysis_dt(start),
        end_s=fmt_analysis_dt(end),
        position_name=pos,
        scope_pairs=scope_pairs or None,
        group_query=group_query or None,
        include_other=include_other,
    )
    total_minutes = max(1, int((end - start).total_seconds() / 60))
    bucket_count = max(1, (total_minutes + bucket_minutes - 1) // bucket_minutes)
    buckets: list[dict[str, Any]] = [
        {
            "start": start + timedelta(minutes=i * bucket_minutes),
            "end": min(end, start + timedelta(minutes=(i + 1) * bucket_minutes)),
            "ids": set(),
            "sessions": set(),
        }
        for i in range(bucket_count)
    ]
    for dt_s, _fr, _gr, cid in rows:
        dt = parse_analysis_datetime(str(dt_s or ""))
        if not dt or not cid:
            continue
        idx = int((dt - start).total_seconds() / 60) // bucket_minutes
        if idx < 0 or idx >= bucket_count:
            continue
        buckets[idx]["ids"].add(str(cid))
        buckets[idx]["sessions"].add(str(dt_s or ""))
    out: list[dict[str, object]] = []
    prev_ids: set[str] = set()
    for b in buckets:
        ids_set = b["ids"]
        out.append(
            {
                "start": fmt_analysis_dt(b["start"]),
                "end": fmt_analysis_dt(b["end"]),
                "active_ids": len(ids_set),
                "sessions": len(b["sessions"]),
                "new_ids": len(ids_set - prev_ids),
                "gone_ids": len(prev_ids - ids_set),
            }
        )
        prev_ids = set(ids_set)
    return {
        "ok": True,
        "position": pos,
        "all_positions": all_positions,
        "start": fmt_analysis_dt(start),
        "end": fmt_analysis_dt(end),
        "bucket_minutes": bucket_minutes,
        "is_live_tail": True,
        "server_ts": fmt_analysis_dt(msk_now_naive()),
        "buckets": out,
    }


def assemble_analysis_graph_dynamic_window_payload(
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
    cluster_by: str,
    min_weight: int,
    max_nodes: int,
    max_edges: int,
    window_minutes: int,
    start_dt: datetime,
    end_dt: datetime,
) -> dict[str, Any]:
    unit_rows = conn.execute("SELECT frequency, group_, name FROM unit").fetchall()
    pair_to_unit: dict[tuple[str, str], str] = {}
    for r in unit_rows or []:
        pair_to_unit[(str(r["frequency"] or ""), str(r["group_"] or ""))] = str(
            r["name"] or ""
        )
    scope_pairs = resolve_dynamic_scope_pairs(
        conn,
        unit_name=unit_name,
        frequency=frequency,
        group_code=group_code,
        unit_query=unit_query,
    )
    rows = collect_scoped_seans_rows(
        seans_conn,
        start_s=fmt_analysis_dt(start_dt),
        end_s=fmt_analysis_dt(end_dt),
        position_name=pos,
        scope_pairs=scope_pairs or None,
        group_query=group_query or None,
        include_other=include_other,
    )
    nodes, edges, metrics = build_simple_analysis_graph(
        list(rows),
        pair_to_unit=pair_to_unit,
        cluster_by=cluster_by,
        min_weight=min_weight,
        max_nodes=max_nodes,
        max_edges=max_edges,
        end_dt=end_dt,
    )
    return {
        "ok": True,
        "position": pos,
        "all_positions": all_positions,
        "start": fmt_analysis_dt(start_dt),
        "end": fmt_analysis_dt(end_dt),
        "window_minutes": window_minutes,
        "nodes": nodes,
        "edges": edges,
        "metrics": metrics,
    }


def assemble_analysis_graph_dynamic_live_payload(
    conn: sqlite3.Connection,
    seans_conn: sqlite3.Connection,
    *,
    pos: str | None,
    unit_name: str,
    frequency: str,
    group_code: str,
    unit_query: str,
    group_query: str,
    include_other: bool,
    bucket_minutes: int,
    start_dt: datetime,
    end_dt: datetime,
) -> dict[str, Any]:
    scope_pairs = resolve_dynamic_scope_pairs(
        conn,
        unit_name=unit_name,
        frequency=frequency,
        group_code=group_code,
        unit_query=unit_query,
    )
    rows = collect_scoped_seans_rows(
        seans_conn,
        start_s=fmt_analysis_dt(start_dt),
        end_s=fmt_analysis_dt(end_dt),
        position_name=pos,
        scope_pairs=scope_pairs or None,
        group_query=group_query or None,
        include_other=include_other,
    )
    buckets: dict[str, dict[str, object]] = {}
    for dt_s, _fr, _gr, cid in list(rows):
        d = parse_analysis_datetime(str(dt_s or ""))
        if not d or not cid:
            continue
        minute = d.replace(second=0, microsecond=0)
        key = fmt_analysis_dt(minute)
        if key not in buckets:
            buckets[key] = {
                "start": key,
                "end": fmt_analysis_dt(minute + timedelta(minutes=bucket_minutes)),
                "ids": set(),
                "sessions": set(),
            }
        buckets[key]["ids"].add(str(cid))
        buckets[key]["sessions"].add(str(dt_s or ""))
    new_buckets = [
        {
            "start": str(v["start"]),
            "end": str(v["end"]),
            "active_ids": len(v["ids"]),  # type: ignore[arg-type]
            "sessions": len(v["sessions"]),  # type: ignore[arg-type]
            "new_ids": 0,
            "gone_ids": 0,
        }
        for _, v in sorted(buckets.items(), key=lambda x: x[0])
    ]
    return {
        "ok": True,
        "server_ts": fmt_analysis_dt(end_dt),
        "new_buckets": new_buckets,
    }
