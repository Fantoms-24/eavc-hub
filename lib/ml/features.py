from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Any
import math


def parse_ts(v: str) -> datetime:
    raw = str(v or "").strip()
    if not raw:
        raise ValueError("empty datetime")
    try:
        return datetime.fromisoformat(raw.replace("Z", ""))
    except Exception:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")


@dataclass
class BucketSnapshot:
    start: str
    end: str
    features: dict[str, float]
    top_units: list[dict[str, Any]]
    top_groups: list[dict[str, Any]]
    top_ids: list[dict[str, Any]]


FEATURE_ORDER = [
    "active_ids",
    "sessions",
    "new_ids",
    "gone_ids",
    "new_ratio",
    "gone_ratio",
    "edges",
    "density",
    "components",
    "hub_concentration",
    "cross_group_ratio",
    "recent_edge_ratio",
    "activity_per_id",
]


def _safe_div(a: float, b: float) -> float:
    return float(a) / float(b or 1.0)


def _coerce_window(window_minutes: int) -> int:
    return max(5, min(720, int(window_minutes or 60)))


def _sessionize(rows: list[tuple[str, str, str, str]]) -> dict[tuple[str, str, str], set[str]]:
    sessions: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for dt, fr, gr, cid in rows:
        sessions[(str(dt), str(fr), str(gr))].add(str(cid))
    return sessions


def _iter_windows(start: datetime, end: datetime, minutes: int) -> list[tuple[datetime, datetime]]:
    out: list[tuple[datetime, datetime]] = []
    cur = start
    step = timedelta(minutes=minutes)
    while cur < end:
        nxt = min(end, cur + step)
        out.append((cur, nxt))
        cur = nxt
    return out


def _window_rows(
    rows: list[tuple[str, str, str, str]],
    start: datetime,
    end: datetime,
) -> list[tuple[str, str, str, str]]:
    out: list[tuple[str, str, str, str]] = []
    for r in rows:
        try:
            ts = parse_ts(r[0])
        except Exception:
            continue
        if start <= ts < end:
            out.append(r)
    return out


def _build_snapshot(
    bucket_rows: list[tuple[str, str, str, str]],
    prev_ids: set[str] | None = None,
) -> tuple[dict[str, float], set[str], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    prev_ids = prev_ids or set()
    sessions = _sessionize(bucket_rows)
    ids = set()
    id_degree: dict[str, int] = defaultdict(int)
    group_by_id: dict[str, set[str]] = defaultdict(set)
    group_size: dict[str, int] = defaultdict(int)
    unit_size: dict[str, int] = defaultdict(int)
    edges = 0
    cross_group_edges = 0
    recent_edges = 0

    for (dt, fr, gr), members in sessions.items():
        g = str(gr or "").strip()
        group_size[g] += len(members)
        edges += max(0, len(members) - 1)
        if len(members) > 0:
            recent_edges += 1
        for cid in members:
            ids.add(cid)
            group_by_id[cid].add(g)
            id_degree[cid] += len(members) - 1
        if len({x for x in members}) > 1 and g:
            cross_group_edges += 1

    # pseudo-unit from frequency+group keeps localization usable even without explicit unit joins
    for _, fr, gr, _ in bucket_rows:
        unit_size[f"{fr}:{gr}"] += 1

    active_ids = len(ids)
    new_ids = len(ids - prev_ids)
    gone_ids = len(prev_ids - ids)
    sessions_count = len(sessions)
    max_edges = (active_ids * (active_ids - 1)) / 2 if active_ids > 1 else 1.0
    density = _safe_div(edges, max_edges)
    total_degree = float(sum(id_degree.values()) or 0.0)
    top_degree = float(max(id_degree.values()) if id_degree else 0.0)
    hub_concentration = _safe_div(top_degree, total_degree) if total_degree > 0 else 0.0
    components = max(1, int(math.sqrt(max(1, active_ids - edges)))) if active_ids else 0
    cross_group_ratio = _safe_div(cross_group_edges, sessions_count)
    recent_edge_ratio = _safe_div(recent_edges, sessions_count)
    activity_per_id = _safe_div(sessions_count, active_ids)
    new_ratio = _safe_div(new_ids, active_ids)
    gone_ratio = _safe_div(gone_ids, len(prev_ids))

    feats = {
        "active_ids": float(active_ids),
        "sessions": float(sessions_count),
        "new_ids": float(new_ids),
        "gone_ids": float(gone_ids),
        "new_ratio": float(new_ratio),
        "gone_ratio": float(gone_ratio),
        "edges": float(edges),
        "density": float(density),
        "components": float(components),
        "hub_concentration": float(hub_concentration),
        "cross_group_ratio": float(cross_group_ratio),
        "recent_edge_ratio": float(recent_edge_ratio),
        "activity_per_id": float(activity_per_id),
    }
    top_units = [
        {"name": k, "count": int(v)}
        for k, v in sorted(unit_size.items(), key=lambda x: (-x[1], x[0]))[:6]
    ]
    top_groups = [
        {"name": k, "count": int(v)}
        for k, v in sorted(group_size.items(), key=lambda x: (-x[1], x[0]))[:6]
    ]
    top_ids = [
        {"id": k, "score": float(v)}
        for k, v in sorted(id_degree.items(), key=lambda x: (-x[1], x[0]))[:8]
    ]
    return feats, ids, top_units, top_groups, top_ids


def build_snapshots(
    rows: list[tuple[str, str, str, str]],
    *,
    start_s: str,
    end_s: str,
    window_minutes: int = 60,
) -> list[BucketSnapshot]:
    start = parse_ts(start_s)
    end = parse_ts(end_s)
    window = _coerce_window(window_minutes)
    all_windows = _iter_windows(start, end, window)
    out: list[BucketSnapshot] = []
    prev_ids: set[str] = set()
    for ws, we in all_windows:
        bucket_rows = _window_rows(rows, ws, we)
        feats, active_ids, top_units, top_groups, top_ids = _build_snapshot(bucket_rows, prev_ids)
        out.append(
            BucketSnapshot(
                start=ws.strftime("%Y-%m-%d %H:%M:%S"),
                end=we.strftime("%Y-%m-%d %H:%M:%S"),
                features=feats,
                top_units=top_units,
                top_groups=top_groups,
                top_ids=top_ids,
            )
        )
        prev_ids = active_ids
    return out


def vectorize_feature_dict(feature_dict: dict[str, float]) -> list[float]:
    return [float(feature_dict.get(name, 0.0)) for name in FEATURE_ORDER]


def build_forecast_samples(
    rows: list[tuple[str, str, str, str]],
    *,
    start_s: str,
    end_s: str,
    window_minutes: int,
    tag_rows: list[tuple[str, str, str]],
    horizons: list[int] | tuple[int, ...] = (30, 60, 120),
) -> dict[int, list[tuple[BucketSnapshot, str]]]:
    snapshots = build_snapshots(
        rows,
        start_s=start_s,
        end_s=end_s,
        window_minutes=window_minutes,
    )
    parsed_tags: list[tuple[datetime, datetime, str]] = []
    for ts, te, lb in tag_rows or []:
        try:
            s = parse_ts(str(ts or ""))
            e = parse_ts(str(te or ""))
        except Exception:
            continue
        if e <= s:
            continue
        parsed_tags.append((s, e, str(lb or "").strip()))

    out: dict[int, list[tuple[BucketSnapshot, str]]] = {
        int(h): [] for h in horizons if int(h) > 0
    }
    for snap in snapshots:
        try:
            base_end = parse_ts(snap.end)
        except Exception:
            continue
        for h in list(out.keys()):
            hs = base_end
            he = base_end + timedelta(minutes=int(h))
            best_label = ""
            best_overlap = 0.0
            for ts, te, lb in parsed_tags:
                left = max(hs, ts)
                right = min(he, te)
                overlap = (right - left).total_seconds()
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_label = lb
            if best_overlap > 0 and best_label:
                out[h].append((snap, best_label))
    return out

