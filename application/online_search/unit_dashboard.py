"""Сводка радиосети для карточки подразделения."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from itertools import combinations
import sqlite3
from typing import Any

from web_portal.lib.db.seans_archive import resolve_seans_conn_for_queries
from web_portal.lib.db.seans_schema import seanses_union_source_sql
from web_portal.lib.db.units import get_unit_family_by_parent_key


def _in(values: list[str]) -> tuple[str, list[str]]:
    clean = [str(v).strip() for v in values if str(v).strip()]
    return ",".join("?" for _ in clean), clean


def assemble_online_search_unit_dashboard_payload(
    search_conn: sqlite3.Connection,
    main_conn: sqlite3.Connection,
    parent_key: str,
    *,
    period_days: int = 7,
) -> dict[str, Any]:
    """Показатели за 7, 14 или 30 суток для родителя и его подгрупп."""
    family = get_unit_family_by_parent_key(search_conn, parent_key)
    if not family:
        return {"ok": False, "error": "подразделение не найдено"}
    names = [str(family.get("parent_key") or "").strip()]
    names.extend(str(x.get("unit_key") or "").strip() for x in family.get("children") or [])
    marks, names = _in(names)
    days_count = period_days if period_days in (7, 14, 30) else 7
    end = datetime.now().replace(microsecond=0)
    start = (end - timedelta(days=days_count - 1)).replace(hour=0, minute=0, second=0)
    day_keys = [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_count)]
    if not names:
        return _empty(family, day_keys, start, end)
    pairs = main_conn.execute(f"SELECT DISTINCT TRIM(frequency), TRIM(group_) FROM unit WHERE TRIM(COALESCE(name, '')) IN ({marks}) AND TRIM(COALESCE(frequency, '')) <> '' AND TRIM(COALESCE(group_, '')) <> ''", names).fetchall()
    pair_set = {(str(r[0] or ""), str(r[1] or "")) for r in pairs}
    if not pair_set:
        return _empty(family, day_keys, start, end)

    seans_conn = resolve_seans_conn_for_queries(main_conn, None)
    try:
        pair_where = " OR ".join("(TRIM(frequency)=? AND TRIM(group_)=?)" for _ in pair_set)
        params: list[Any] = [start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")]
        for frequency, group in sorted(pair_set):
            params.extend([frequency, group])
        source = seanses_union_source_sql(seans_conn)
        rows = seans_conn.execute(f"SELECT date_time, TRIM(frequency), TRIM(group_), TRIM(id) FROM ({source}) WHERE date_time >= ? AND date_time <= ? AND ({pair_where}) ORDER BY date_time DESC", params).fetchall()
    finally:
        if seans_conn is not main_conn:
            seans_conn.close()

    per_day_sessions: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    per_day_calls: dict[str, set[str]] = defaultdict(set)
    per_call: Counter[str] = Counter()
    per_frequency: Counter[tuple[str, str]] = Counter()
    ticks: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    last_pair: dict[str, tuple[str, str]] = {}
    for row in rows:
        dt, frequency, group, call = (str(row[i] or "").strip() for i in range(4))
        if not call: continue
        day = dt[:10]
        per_day_sessions[day].add((dt, frequency, group))
        per_day_calls[day].add(call)
        per_call[call] += 1
        per_frequency[(frequency, group)] += 1
        ticks[(dt, frequency, group)].add(call)
        last_pair.setdefault(call, (frequency, group))

    labels = _labels(main_conn, names)
    callsigns = [
        {
            "id": code,
            "correspondent_id": code,
            "label": labels.get(code, code),
            "sessions": int(count),
            "frequency": last_pair[code][0],
            "group": last_pair[code][1],
        }
        for code, count in per_call.most_common(500)
    ]
    latest = _last_intercepts(main_conn, names, callsigns)
    for item in callsigns:
        item["last_intercept"] = latest.get(str(item["id"]))
    allowed = {str(x["id"]) for x in callsigns[:50]}; weights: Counter[tuple[str, str]] = Counter()
    for ids in ticks.values():
        for a, b in combinations(sorted(ids & allowed)[:25], 2): weights[(a, b)] += 1
    children = [
        {
            "unit_key": str(item.get("unit_key") or ""),
            "label": str(item.get("label") or ""),
            "row_count": int(item.get("row_count") or 0),
        }
        for item in family.get("children") or []
    ]
    return {
        "ok": True,
        "parent_key": family.get("parent_key"),
        "parent_label": family.get("parent_label"),
        "children": children,
        "period": {
            "start": start.strftime("%Y-%m-%d"),
            "end": end.strftime("%Y-%m-%d"),
            "days": days_count,
        },
        "last_updated": str(rows[0][0] or "") if rows else "",
        "summary": {
            "sessions": sum(len(items) for items in per_day_sessions.values()),
            "correspondents": len(per_call),
            "callsigns": len(per_call),
            "frequencies": len(per_frequency),
        },
        "days": [
            {
                "date": day,
                "sessions": len(per_day_sessions[day]),
                "correspondents": len(per_day_calls[day]),
            }
            for day in day_keys
        ],
        "callsigns": callsigns,
        "frequencies": [
            {"frequency": frequency, "group": group, "sessions": int(count)}
            for (frequency, group), count in per_frequency.most_common()
        ],
        "graph": {
            "nodes": callsigns[:50],
            "edges": [
                {"source": source, "target": target, "weight": int(weight)}
                for (source, target), weight in weights.most_common(250)
            ],
        },
    }


def _empty(family: dict[str, Any], days: list[str], start: datetime, end: datetime) -> dict[str, Any]:
    return {
        "ok": True,
        "parent_key": family.get("parent_key"),
        "parent_label": family.get("parent_label"),
        "children": family.get("children") or [],
        "period": {
            "start": start.strftime("%Y-%m-%d"),
            "end": end.strftime("%Y-%m-%d"),
            "days": len(days),
        },
        "last_updated": "",
        "summary": {"sessions": 0, "correspondents": 0, "callsigns": 0, "frequencies": 0},
        "days": [{"date": day, "sessions": 0, "correspondents": 0} for day in days],
        "callsigns": [],
        "frequencies": [],
        "graph": {"nodes": [], "edges": []},
    }


def _labels(conn: sqlite3.Connection, names: list[str]) -> dict[str, str]:
    marks, values = _in(names)
    rows = conn.execute(f"SELECT TRIM(code), TRIM(label) FROM intercept_callsigns WHERE TRIM(COALESCE(unit_name, '')) IN ({marks})", values).fetchall()
    return {str(r[0] or ""): str(r[1] or "") for r in rows if str(r[0] or "").strip() and str(r[1] or "").strip()}


def _last_intercepts(
    conn: sqlite3.Connection,
    names: list[str],
    callsigns: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    """Находит последние перехваты всех позывных одним запросом вместо N+1."""
    if not callsigns:
        return {}
    marks, values = _in(names)
    pairs = sorted({(str(item.get("frequency") or ""), str(item.get("group") or "")) for item in callsigns})
    pair_sql = " OR ".join("(TRIM(frequency)=? AND TRIM(group_code)=?)" for _ in pairs)
    params: list[Any] = [*values]
    for frequency, group in pairs:
        params.extend([frequency, group])
    rows = conn.execute(
        f"SELECT content, updated_at, TRIM(frequency), TRIM(group_code) "
        f"FROM intercept_items WHERE TRIM(COALESCE(unit_name, '')) IN ({marks}) "
        f"AND ({pair_sql}) ORDER BY updated_at DESC, id DESC LIMIT 5000",
        params,
    ).fetchall()
    pending: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in callsigns:
        pending[(str(item.get("frequency") or ""), str(item.get("group") or ""))].append(item)
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        content = str(row[0] or "")
        pair = (str(row[2] or ""), str(row[3] or ""))
        unresolved = pending.get(pair) or []
        if not unresolved:
            continue
        keep: list[dict[str, Any]] = []
        for item in unresolved:
            code = str(item.get("id") or "")
            label = str(item.get("label") or "")
            if (code and code in content) or (label and label in content):
                result[code] = {
                    "content": content.strip()[:500],
                    "updated_at": str(row[1] or ""),
                    "frequency": pair[0],
                    "group": pair[1],
                }
            else:
                keep.append(item)
        pending[pair] = keep
        if all(not items for items in pending.values()):
            break
    return result
