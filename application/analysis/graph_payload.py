"""Сборка payload для /api/analysis/graph (без Flask)."""

from __future__ import annotations

import logging
import re
import sqlite3
from collections import defaultdict, deque
from datetime import datetime, timedelta
from itertools import combinations
from typing import Any

from web_portal.lib.db import seanses_union_source_sql

from web_portal.application.analysis.period_bounds import (
    fmt_analysis_dt,
    parse_analysis_datetime,
)

_log = logging.getLogger("web_portal.analysis.graph_payload")


def normalize_analysis_freq_str(v: str) -> str:
    s = str(v or "").strip().replace(",", ".")
    if not s:
        return ""
    try:
        f = float(s)
    except Exception:
        return s
    out = f"{f:.5f}"
    out = out.rstrip("0").rstrip(".")
    return out or s


def normalize_analysis_group_key(g: str) -> str:
    s = str(g or "").strip()
    digits = re.findall(r"\d+", s)
    if not digits:
        return s
    joined = "".join(digits)
    try:
        return str(int(joined))
    except Exception:
        return joined.lstrip("0") or "0"


def _unique_pairs(rows: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for fr, gr in rows:
        key = (str(fr), str(gr))
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def build_pair_to_unit_map(
    conn: sqlite3.Connection,
    *,
    frequency: str = "",
    group_code: str = "",
    unit_name: str = "",
    unit_query: str = "",
    max_unit_rows: int = 20000,
) -> tuple[dict[tuple[str, str], str], dict[str, list[tuple[str, str]]]]:
    unit_where = ""
    unit_params: list[object] = []
    if frequency and group_code:
        unit_where = "WHERE frequency=? AND group_=?"
        unit_params = [frequency, group_code]
    elif unit_name:
        unit_where = "WHERE name=?"
        unit_params = [unit_name]
    elif unit_query:
        unit_where = "WHERE name LIKE ?"
        unit_params = [f"%{unit_query}%"]
    unit_rows = conn.execute(
        f"""
        SELECT frequency, group_, name, COALESCE(manual, 0) AS manual, COALESCE(updated_at, '') AS updated_at
        FROM unit
        {unit_where}
        ORDER BY COALESCE(manual, 0) DESC, COALESCE(updated_at, '') DESC
        LIMIT ?
        """,
        [*unit_params, max_unit_rows],
    ).fetchall()
    pair_to_unit: dict[tuple[str, str], str] = {}
    unit_pairs_by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r in unit_rows or []:
        freq = str(r["frequency"] or "")
        grp = str(r["group_"] or "")
        freq_norm = normalize_analysis_freq_str(freq)
        grp_norm = normalize_analysis_group_key(grp)
        name = str(r["name"] or "").strip()
        key = (freq, grp)
        if key not in pair_to_unit:
            pair_to_unit[key] = name
        if freq_norm and key not in pair_to_unit:
            pair_to_unit[(freq_norm, grp)] = name
        if grp_norm:
            pair_to_unit[(freq, grp_norm)] = name
            if grp_norm and not grp.startswith("G"):
                pair_to_unit[(freq, f"G{grp_norm}")] = name
            if freq_norm:
                pair_to_unit[(freq_norm, grp_norm)] = name
                if grp_norm and not grp.startswith("G"):
                    pair_to_unit[(freq_norm, f"G{grp_norm}")] = name
        if name:
            unit_pairs_by_name.setdefault(name, []).append(key)
    return pair_to_unit, unit_pairs_by_name


def pairs_for_unit_exact(
    unit_pairs_by_name: dict[str, list[tuple[str, str]]], unit: str
) -> list[tuple[str, str]]:
    u = str(unit or "").strip()
    if not u:
        return []
    return _unique_pairs(unit_pairs_by_name.get(u, []))


def pairs_for_unit_query(conn: sqlite3.Connection, q: str) -> list[tuple[str, str]]:
    qq = str(q or "").strip()
    if not qq:
        return []
    rows = conn.execute(
        """
        SELECT frequency, group_
        FROM unit
        WHERE name LIKE ?
        ORDER BY COALESCE(manual, 0) DESC, COALESCE(updated_at, '') DESC
        """,
        (f"%{qq}%",),
    ).fetchall()
    return _unique_pairs([(r[0], r[1]) for r in rows or []])


def fetch_graph_groups(
    seans_conn: sqlite3.Connection,
    *,
    start_s: str,
    end_s: str,
    position_name: str | None = None,
    group_query: str | None = None,
    pairs_filter: list[tuple[str, str]] | None = None,
    ids_filter: list[str] | None = None,
) -> list[tuple[str, str, str, str, str]]:
    """Возвращает активность, сохраняя источник (позицию) каждой строки.

    Для центрального SERVER позиции не должны исчезать при агрегации: один и
    тот же момент и канал может быть принят несколькими HUB. Дальше строки
    объединяются в единый граф, но происхождение остаётся доступным в узлах и
    связях.
    """
    seans_src = seanses_union_source_sql(seans_conn)
    where = "date_time BETWEEN ? AND ?"
    params: list[object] = [start_s, end_s]
    if position_name:
        where += " AND client_name=?"
        params.append(position_name)
    if group_query:
        where += " AND group_ LIKE ?"
        params.append(f"%{group_query}%")
    if pairs_filter:
        pairs_filter = pairs_filter[:500]
        parts = []
        for fr, gr in pairs_filter:
            fr_s = str(fr or "")
            gr_s = str(gr or "")
            gr_norm = normalize_analysis_group_key(gr_s)
            parts.append(
                "("
                "(frequency=? AND group_=?) OR "
                "(CAST(frequency AS REAL)=CAST(? AS REAL) AND (group_=? OR (CASE WHEN group_ LIKE 'G%' THEN substr(group_,2) ELSE group_ END)=?))"
                ")"
            )
            params.extend([fr_s, gr_s, fr_s, gr_s, gr_norm])
        where += " AND (" + " OR ".join(parts) + ")"
    if ids_filter:
        ids_filter = ids_filter[:300]
        placeholders = ",".join(["?"] * len(ids_filter))
        where += f" AND id IN ({placeholders})"
        params.extend(ids_filter)
    rows = seans_conn.execute(
        f"""
        SELECT date_time, COALESCE(client_name, ''), frequency, group_, GROUP_CONCAT(id)
        FROM ({seans_src}) s
        WHERE {where}
        GROUP BY date_time, COALESCE(client_name, ''), frequency, group_
        """,
        tuple(params),
    ).fetchall()
    out: list[tuple[str, str, str, str, str]] = []
    for r in rows or []:
        out.append(
            (
                str(r[0] or ""),
                str(r[1] or ""),
                str(r[2] or ""),
                str(r[3] or ""),
                str(r[4] or "") if r[4] is not None else "",
            )
        )
    return out


def _parse_ids_csv(ids_csv: str) -> set[str]:
    ids: set[str] = set()
    for x in (ids_csv or "").split(","):
        s = str(x or "").strip()
        if s:
            ids.add(s)
    return ids


def _merge_group_rows(
    groups: dict[tuple[str, str, str, str], set[str]],
    rows: list[tuple[str, str, str, str, str]],
    *,
    pair_to_unit: dict[tuple[str, str], str],
    node_counts: dict[str, int],
    node_unit_counts: dict[str, dict[str, int]],
    node_group_counts: dict[str, dict[str, int]],
    node_position_counts: dict[str, dict[str, int]],
    group_positions: dict[tuple[str, str, str, str], set[str]],
    merge_existing: bool = False,
) -> None:
    for dt, position, fr, gr, ids_csv in rows:
        key = (dt, position, fr, gr)
        ids = _parse_ids_csv(ids_csv)
        if not ids:
            continue
        if position:
            group_positions[key].add(position)
        if merge_existing and key in groups:
            groups[key] |= ids
        else:
            groups[key] = ids
        unit = pair_to_unit.get((fr, gr), "")
        for cid in ids:
            node_counts[cid] += 1
            if unit:
                node_unit_counts[cid][unit] += 1
            if gr:
                node_group_counts[cid][str(gr)] += 1
            if position:
                node_position_counts[cid][position] += 1


def betweenness_unweighted(
    graph_adj: dict[str, set[str]], ids: list[str]
) -> dict[str, float]:
    result = {i: 0.0 for i in ids}
    n = len(ids)
    if n < 3:
        return result
    if n > 220:
        max_d = max([len(graph_adj.get(i, set())) for i in ids] or [1])
        for i in ids:
            result[i] = float(len(graph_adj.get(i, set()))) / float(max_d or 1)
        return result
    for s in ids:
        stack: list[str] = []
        preds: dict[str, list[str]] = {v: [] for v in ids}
        sigma: dict[str, float] = {v: 0.0 for v in ids}
        dist: dict[str, int] = {v: -1 for v in ids}
        sigma[s] = 1.0
        dist[s] = 0
        q: deque[str] = deque([s])
        while q:
            v = q.popleft()
            stack.append(v)
            for w in graph_adj.get(v, set()):
                if w not in dist:
                    continue
                if dist[w] < 0:
                    q.append(w)
                    dist[w] = dist[v] + 1
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    preds[w].append(v)
        delta: dict[str, float] = {v: 0.0 for v in ids}
        while stack:
            w = stack.pop()
            if sigma[w] <= 0:
                continue
            for v in preds[w]:
                delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != s:
                result[w] += delta[w]
    scale = 2.0
    if n > 2:
        scale = (n - 1) * (n - 2)
    for k in list(result.keys()):
        result[k] = round((result[k] / 2.0) / float(scale or 1), 6)
    return result


def build_simple_analysis_graph(
    rows: list[tuple[str, str, str, str]],
    *,
    pair_to_unit: dict[tuple[str, str], str],
    cluster_by: str,
    min_weight: int,
    max_nodes: int,
    max_edges: int,
    end_dt: datetime,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    groups: dict[tuple[str, str, str, str], set[str]] = {}
    node_counts: dict[str, int] = defaultdict(int)
    node_unit_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    node_group_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for dt, fr, gr, cid in rows or []:
        if not cid:
            continue
        key = (str(dt or ""), str(fr or ""), str(gr or ""))
        groups.setdefault(key, set()).add(str(cid))
    for (_dt, fr, gr), ids in groups.items():
        unit = pair_to_unit.get((fr, gr), "")
        for cid in ids:
            node_counts[cid] += 1
            if unit:
                node_unit_counts[cid][unit] += 1
            if gr:
                node_group_counts[cid][str(gr)] += 1

    ordered_nodes = sorted(node_counts.items(), key=lambda x: (-x[1], x[0]))[
        : max(20, min(500, int(max_nodes or 200)))
    ]
    allowed_nodes = {k for k, _ in ordered_nodes}
    edge_map: dict[tuple[str, str], dict[str, object]] = {}
    recent_threshold = end_dt - timedelta(minutes=30)
    for (dt, fr, gr), ids in groups.items():
        ids_list = [x for x in ids if x in allowed_nodes]
        if len(ids_list) < 2:
            continue
        ids_list = sorted(ids_list)[:40]
        unit = pair_to_unit.get((fr, gr), "")
        for a, b in combinations(ids_list, 2):
            k = (a, b)
            if k not in edge_map:
                edge_map[k] = {
                    "weight": 0,
                    "unit": unit,
                    "last_dt": "",
                    "recent_activity": 0,
                }
            edge_map[k]["weight"] = int(edge_map[k]["weight"] or 0) + 1
            if dt and str(dt) > str(edge_map[k].get("last_dt") or ""):
                edge_map[k]["last_dt"] = str(dt)
            d = parse_analysis_datetime(str(dt or ""))
            if d and d >= recent_threshold:
                edge_map[k]["recent_activity"] = (
                    int(edge_map[k].get("recent_activity") or 0) + 1
                )

    filtered_edges = [
        (k, v)
        for k, v in edge_map.items()
        if int(v.get("weight") or 0) >= max(1, int(min_weight or 1))
    ]
    filtered_edges = sorted(
        filtered_edges, key=lambda x: -int(x[1].get("weight") or 0)
    )[: max(50, min(2500, int(max_edges or 800)))]
    max_w = max([int(v.get("weight") or 0) for _, v in filtered_edges] or [1])

    nodes: list[dict[str, object]] = []
    for cid, cnt in ordered_nodes:
        unit_counts = node_unit_counts.get(cid) or {}
        group_counts = node_group_counts.get(cid) or {}
        unit = ""
        units: list[str] = []
        group = ""
        if unit_counts:
            ou = sorted(unit_counts.items(), key=lambda x: (-x[1], x[0]))
            unit = str(ou[0][0] or "")
            units = [str(u) for u, _ in ou]
        if group_counts:
            og = sorted(group_counts.items(), key=lambda x: (-x[1], x[0]))
            group = str(og[0][0] or "")
        cluster_key = unit if cluster_by == "unit" else (group or "без группы")
        nodes.append(
            {
                "id": cid,
                "count": int(cnt),
                "unit_name": unit,
                "units": units,
                "group": group,
                "cluster_key": cluster_key,
            }
        )

    edges: list[dict[str, object]] = []
    for (a, b), meta in filtered_edges:
        if a not in allowed_nodes or b not in allowed_nodes:
            continue
        w = int(meta.get("weight") or 0)
        edges.append(
            {
                "source": a,
                "target": b,
                "weight": w,
                "normalized_weight": round(float(w) / float(max_w or 1), 6),
                "recent_activity": int(meta.get("recent_activity") or 0),
                "last_activity": str(meta.get("last_dt") or ""),
                "unit_name": str(meta.get("unit") or ""),
            }
        )
    n_count = len(nodes)
    e_count = len(edges)
    density = (
        float(2 * e_count) / float(n_count * (n_count - 1)) if n_count > 1 else 0.0
    )
    metrics: dict[str, object] = {
        "density": round(density, 6),
        "components": 0,
        "top_hubs": [],
        "top_bridges": [],
    }
    return nodes, edges, metrics


def assemble_analysis_graph_payload(
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
    minutes: int,
    start: datetime,
    end: datetime,
    start_s: str,
    end_s: str,
    max_nodes: int,
    max_edges: int,
    min_weight: int,
    cluster_by: str,
    layout_hint: str,
    focus_id: str,
    max_nodes_mode: str,
    max_unit_rows: int = 20000,
) -> dict[str, Any]:
    pair_to_unit, unit_pairs_by_name = build_pair_to_unit_map(
        conn,
        frequency=frequency,
        group_code=group_code,
        unit_name=unit_name,
        unit_query=unit_query,
        max_unit_rows=max_unit_rows,
    )

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

    groups: dict[tuple[str, str, str], set[str]] = {}
    node_counts: dict[str, int] = defaultdict(int)
    node_unit_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    node_group_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    node_position_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    group_positions: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)

    rows = fetch_graph_groups(
        seans_conn,
        start_s=start_s,
        end_s=end_s,
        position_name=pos,
        group_query=group_query or None,
        pairs_filter=scope_pairs or None,
    )
    _merge_group_rows(
        groups,
        rows,
        pair_to_unit=pair_to_unit,
        node_counts=node_counts,
        node_unit_counts=node_unit_counts,
        node_group_counts=node_group_counts,
        node_position_counts=node_position_counts,
        group_positions=group_positions,
    )

    scope_ids: list[str] = []
    if node_counts:
        scope_ids = [
            k for k, _ in sorted(node_counts.items(), key=lambda x: (-x[1], x[0]))
        ]

    if include_other and scope_ids:
        extra_rows = fetch_graph_groups(
            seans_conn,
            start_s=start_s,
            end_s=end_s,
            position_name=pos,
            group_query=group_query or None,
            ids_filter=scope_ids,
        )
        _merge_group_rows(
            groups,
            extra_rows,
            pair_to_unit=pair_to_unit,
            node_counts=node_counts,
            node_unit_counts=node_unit_counts,
            node_group_counts=node_group_counts,
            node_position_counts=node_position_counts,
            group_positions=group_positions,
            merge_existing=True,
        )

    current_active_ids = set(node_counts.keys())
    window_delta = end - start
    prev_end = start
    prev_start = start - window_delta
    prev_start_s = fmt_analysis_dt(prev_start)
    prev_end_s = fmt_analysis_dt(prev_end)
    prev_rows = fetch_graph_groups(
        seans_conn,
        start_s=prev_start_s,
        end_s=prev_end_s,
        position_name=pos,
        group_query=group_query or None,
        pairs_filter=scope_pairs or None,
    )
    prev_groups: dict[tuple[str, str, str, str], set[str]] = {}
    prev_scope_ids: set[str] = set()
    for dt, position, fr, gr, ids_csv in prev_rows:
        key = (dt, position, fr, gr)
        ids = _parse_ids_csv(ids_csv)
        if ids:
            prev_groups[key] = ids
            prev_scope_ids |= ids
    if include_other and prev_scope_ids:
        prev_extra_rows = fetch_graph_groups(
            seans_conn,
            start_s=prev_start_s,
            end_s=prev_end_s,
            position_name=pos,
            group_query=group_query or None,
            ids_filter=list(prev_scope_ids),
        )
        for dt, position, fr, gr, ids_csv in prev_extra_rows:
            key = (dt, position, fr, gr)
            ids = _parse_ids_csv(ids_csv)
            if not ids:
                continue
            if key in prev_groups:
                prev_groups[key] |= ids
            else:
                prev_groups[key] = ids
    prev_active_ids: set[str] = set()
    for ids in prev_groups.values():
        prev_active_ids |= ids

    ordered_nodes = sorted(node_counts.items(), key=lambda x: (-x[1], x[0]))[
        :max_nodes
    ]
    allowed_nodes = {k for k, _ in ordered_nodes}

    edge_map: dict[tuple[str, str], dict[str, object]] = {}
    recent_threshold = end - timedelta(minutes=30)
    for (dt, position, fr, gr), ids in groups.items():
        ids_list = [x for x in ids if x in allowed_nodes]
        if len(ids_list) < 2:
            continue
        if len(ids_list) > 40:
            ids_list = ids_list[:40]
        unit = pair_to_unit.get((fr, gr), "")
        for a, b in combinations(sorted(ids_list), 2):
            key = (a, b)
            if key not in edge_map:
                edge_map[key] = {
                    "weight": 0,
                    "unit_counts": defaultdict(int),
                    "position_counts": defaultdict(int),
                    "last_dt": "",
                    "recent_activity": 0,
                }
            edge_map[key]["weight"] = int(edge_map[key]["weight"]) + 1
            if unit:
                edge_map[key]["unit_counts"][unit] += 1
            for source_position in group_positions.get((dt, position, fr, gr), set()):
                edge_map[key]["position_counts"][source_position] += 1
            last_dt = str(edge_map[key].get("last_dt") or "")
            if dt and dt > last_dt:
                edge_map[key]["last_dt"] = dt
            dt_obj = parse_analysis_datetime(dt)
            if dt_obj and dt_obj >= recent_threshold:
                edge_map[key]["recent_activity"] = (
                    int(edge_map[key]["recent_activity"] or 0) + 1
                )

    edges_filtered = [
        (k, v)
        for k, v in edge_map.items()
        if int(v.get("weight") or 0) >= min_weight
    ]
    edges_sorted = sorted(edges_filtered, key=lambda x: -int(x[1]["weight"]))[
        :max_edges
    ]

    nodes: list[dict[str, object]] = []
    for cid, cnt in ordered_nodes:
        unit_counts = node_unit_counts.get(cid) or {}
        group_counts = node_group_counts.get(cid) or {}
        position_counts = node_position_counts.get(cid) or {}
        unit = ""
        units: list[str] = []
        group = ""
        if unit_counts:
            ordered_units = sorted(unit_counts.items(), key=lambda x: (-x[1], x[0]))
            unit = ordered_units[0][0]
            units = [u for u, _ in ordered_units]
        if group_counts:
            ordered_groups = sorted(group_counts.items(), key=lambda x: (-x[1], x[0]))
            group = ordered_groups[0][0]
        cluster_key = unit if cluster_by == "unit" else (group or "без группы")
        nodes.append(
            {
                "id": cid,
                "count": int(cnt),
                "unit_name": unit,
                "units": units,
                "group": group,
                "positions": [
                    {"name": name, "count": int(count)}
                    for name, count in sorted(
                        position_counts.items(), key=lambda x: (-x[1], x[0])
                    )
                ],
                "cluster_key": cluster_key,
            }
        )

    edges: list[dict[str, object]] = []
    max_edge_weight = max(
        [int(meta.get("weight") or 0) for _, meta in edges_sorted] or [1]
    )
    for (a, b), meta in edges_sorted:
        if a not in allowed_nodes or b not in allowed_nodes:
            continue
        unit_counts_meta = meta.get("unit_counts") or {}
        unit = ""
        if unit_counts_meta:
            unit = sorted(unit_counts_meta.items(), key=lambda x: (-x[1], x[0]))[0][0]
        position_counts_meta = meta.get("position_counts") or {}
        edges.append(
            {
                "source": a,
                "target": b,
                "weight": int(meta.get("weight") or 0),
                "normalized_weight": round(
                    float(int(meta.get("weight") or 0)) / float(max_edge_weight),
                    6,
                ),
                "recent_activity": int(meta.get("recent_activity") or 0),
                "last_activity": str(meta.get("last_dt") or ""),
                "unit_name": unit,
                "positions": [
                    {"name": name, "count": int(count)}
                    for name, count in sorted(
                        position_counts_meta.items(), key=lambda x: (-x[1], x[0])
                    )
                ],
            }
        )

    adj: dict[str, set[str]] = defaultdict(set)
    weighted_degree: dict[str, int] = defaultdict(int)
    degree: dict[str, int] = defaultdict(int)
    for e in edges:
        a = str(e["source"])
        b = str(e["target"])
        w = int(e.get("weight") or 0)
        adj[a].add(b)
        adj[b].add(a)
        weighted_degree[a] += w
        weighted_degree[b] += w
    for k, v in adj.items():
        degree[k] = len(v)

    node_ids = [str(n.get("id") or "") for n in nodes]
    node_set = set(node_ids)
    if focus_id and focus_id in node_set:
        focus_neighbors = set(adj.get(focus_id, set()))
        focus_neighbors.add(focus_id)
    else:
        focus_neighbors: set[str] = set()

    betweenness = betweenness_unweighted(adj, node_ids)
    for n in nodes:
        nid = str(n.get("id") or "")
        n["degree"] = int(degree.get(nid, 0))
        n["weighted_degree"] = int(weighted_degree.get(nid, 0))
        n["betweenness_approx"] = float(betweenness.get(nid, 0.0))
        if focus_neighbors:
            n["is_focus_related"] = nid in focus_neighbors

    parent: dict[str, str] = {nid: nid for nid in node_ids}

    def _find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: str, b: str) -> None:
        ra = _find(a)
        rb = _find(b)
        if ra != rb:
            parent[rb] = ra

    for e in edges:
        a = str(e["source"])
        b = str(e["target"])
        if a in parent and b in parent:
            _union(a, b)

    components = len({_find(x) for x in node_ids}) if node_ids else 0
    n_count = len(node_ids)
    e_count = len(edges)
    density = 0.0
    if n_count > 1:
        density = float(2 * e_count) / float(n_count * (n_count - 1))

    top_hubs = sorted(
        [
            {
                "id": nid,
                "degree": int(degree.get(nid, 0)),
                "weighted_degree": int(weighted_degree.get(nid, 0)),
            }
            for nid in node_ids
        ],
        key=lambda x: (-x["weighted_degree"], -x["degree"], x["id"]),
    )[:12]
    top_bridges = sorted(
        [
            {
                "id": nid,
                "betweenness_approx": float(betweenness.get(nid, 0.0)),
            }
            for nid in node_ids
        ],
        key=lambda x: (-x["betweenness_approx"], x["id"]),
    )[:12]
    node_unit_map = {
        str(n.get("id") or ""): str(n.get("unit_name") or "") for n in nodes
    }
    cross_unit_edges = 0
    for e in edges:
        su = node_unit_map.get(str(e.get("source") or ""), "")
        tu = node_unit_map.get(str(e.get("target") or ""), "")
        if su and tu and su != tu:
            cross_unit_edges += 1
    cross_unit_ratio = float(cross_unit_edges) / float(len(edges) or 1)
    recent_edge_ratio = float(
        len([e for e in edges if int(e.get("recent_activity") or 0) > 0])
    ) / float(len(edges) or 1)
    total_weighted = float(sum(weighted_degree.values()) or 0.0)
    top_weighted = float(max(weighted_degree.values()) if weighted_degree else 0.0)
    hub_concentration = (top_weighted / total_weighted) if total_weighted > 0 else 0.0
    new_ids_count = len(current_active_ids - prev_active_ids)
    gone_ids_count = len(prev_active_ids - current_active_ids)
    new_ids_ratio = float(new_ids_count) / float(len(current_active_ids) or 1)
    gone_ids_ratio = float(gone_ids_count) / float(len(prev_active_ids) or 1)

    risk_score = 0
    risk_reasons: list[str] = []
    if new_ids_ratio >= 0.35:
        risk_score += 25
        risk_reasons.append(f"всплеск новых ID: {new_ids_count}")
    if gone_ids_ratio >= 0.35:
        risk_score += 15
        risk_reasons.append(f"резкий уход ID: {gone_ids_count}")
    if hub_concentration >= 0.45:
        risk_score += 20
        risk_reasons.append("сильная концентрация вокруг одного хаба")
    if cross_unit_ratio >= 0.5:
        risk_score += 15
        risk_reasons.append("высокая доля межподразделенческих связей")
    if recent_edge_ratio >= 0.6:
        risk_score += 10
        risk_reasons.append("большая доля свежей активности")
    if components >= max(4, int(n_count / 35) + 1):
        risk_score += 10
        risk_reasons.append("граф фрагментирован (много компонент)")
    if density >= 0.12:
        risk_score += 10
        risk_reasons.append("аномально высокая плотность связей")
    risk_score = max(0, min(100, int(risk_score)))
    if risk_score >= 65:
        risk_level = "high"
    elif risk_score >= 35:
        risk_level = "medium"
    else:
        risk_level = "low"

    ml_model_ready = False
    ml_model_version = ""
    try:
        mrow = conn.execute(
            """
            SELECT model_version
            FROM ml_models
            WHERE is_active=1
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        if mrow:
            ml_model_ready = True
            ml_model_version = str(mrow["model_version"] or "")
    except Exception:
        ml_model_ready = False
        ml_model_version = ""

    unit_counts = defaultdict(int)
    for n in nodes:
        uname = str(n.get("unit_name") or "").strip()
        if uname:
            unit_counts[uname] += 1
    group_counts = defaultdict(int)
    for (_dt, _position, fr, gr), ids in groups.items():
        if gr:
            group_counts[str(gr)] += len(ids)

    unit_counts_list = [
        {"name": k, "count": int(v)}
        for k, v in sorted(unit_counts.items(), key=lambda x: (-x[1], x[0]))
    ][:12]
    group_counts_list = [
        {"name": k, "count": int(v)}
        for k, v in sorted(group_counts.items(), key=lambda x: (-x[1], x[0]))
    ][:12]
    position_counts_list = [
        {"name": k, "count": int(v)}
        for k, v in sorted(
            (
                (position, sum(counts.get(position, 0) for counts in node_position_counts.values()))
                for position in {p for counts in node_position_counts.values() for p in counts}
            ),
            key=lambda x: (-x[1], x[0]),
        )
    ]

    return {
        "ok": True,
        "position": pos,
        "all_positions": all_positions,
        "unit_name": unit_name,
        "frequency": frequency,
        "group": group_code,
        "minutes": minutes,
        "start": start_s,
        "end": end_s,
        "nodes": nodes,
        "edges": edges,
        "unit_counts": unit_counts_list,
        "group_counts": group_counts_list,
        "position_counts": position_counts_list,
        "metrics": {
            "density": round(density, 6),
            "components": int(components),
            "top_hubs": top_hubs,
            "top_bridges": top_bridges,
            "cluster_by": cluster_by,
            "layout_hint": layout_hint,
            "max_nodes_mode": max_nodes_mode,
            "min_weight": min_weight,
            "focus_id": focus_id,
            "risk": {
                "score": risk_score,
                "level": risk_level,
                "reasons": risk_reasons[:4],
                "signals": {
                    "new_ids_count": int(new_ids_count),
                    "gone_ids_count": int(gone_ids_count),
                    "new_ids_ratio": round(new_ids_ratio, 6),
                    "gone_ids_ratio": round(gone_ids_ratio, 6),
                    "hub_concentration": round(hub_concentration, 6),
                    "cross_unit_ratio": round(cross_unit_ratio, 6),
                    "recent_edge_ratio": round(recent_edge_ratio, 6),
                },
            },
            "ml_risk": {
                "model_ready": ml_model_ready,
                "model_version": ml_model_version,
                "fallback_source": "rule-based",
                "score": risk_score,
                "level": risk_level,
                "top_label": risk_level,
                "probability": round(float(risk_score) / 100.0, 6),
            },
        },
    }
