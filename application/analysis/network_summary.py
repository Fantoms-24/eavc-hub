"""Сборка payload для /api/analysis/network-summary (без Flask)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from web_portal.application.analysis.errors import AnalysisUseCaseHTTP
from web_portal.lib.auth_db import get_position_setting
from web_portal.lib.db import (
    canonical_intensity_unit_key,
    get_network_intensity_clusters_dual,
    get_network_intensity_clusters_dual_daily,
    get_sessions_favorites,
)
from web_portal.lib.network_analysis_helpers import (
    network_analysis_period_bounds,
    network_favorite_units_from_sessions,
)

_log = logging.getLogger("web_portal.analysis.network_summary")


def parse_analysis_order_list(raw: object) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        out: list[str] = []
        seen: set[str] = set()
        for x in raw:
            s = str(x or "").strip()
            if not s or s in seen:
                continue
            out.append(s)
            seen.add(s)
        return out
    try:
        parsed = json.loads(str(raw))
        if isinstance(parsed, list):
            out = []
            seen: set[str] = set()
            for x in parsed:
                s = str(x or "").strip()
                if not s or s in seen:
                    continue
                out.append(s)
                seen.add(s)
            return out
    except Exception:
        _log.debug("parse_analysis_order_list: suppressed error", exc_info=True)
    return []


def parse_analysis_custom_units(raw: str) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x or "").strip() for x in parsed if str(x or "").strip()]
    except Exception:
        _log.debug("parse_analysis_custom_units: suppressed error", exc_info=True)
    return [x.strip() for x in raw.split(",") if x.strip()]


def clusters_to_unit_map(lst: list[dict[str, object]] | None) -> dict[str, dict[str, object]]:
    return {
        str(x.get("unit_name") or "").strip().lower(): x
        for x in (lst or [])
        if str(x.get("unit_name") or "").strip()
    }


def merge_network_summary_unit_names(
    cur_clusters: list[dict[str, object]] | None,
    prev_clusters: list[dict[str, object]] | None,
    *,
    custom_units: list[str] | None = None,
    favorite_units: set[str] | None = None,
    favorites_only: bool = False,
    units_only: list[str] | None = None,
) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for lst in (cur_clusters, prev_clusters):
        for c in lst or []:
            n = str(c.get("unit_name") or "")
            if not n or n in seen:
                continue
            seen.add(n)
            names.append(n)

    lower_map = {str(n).strip().lower(): n for n in names}
    for c in custom_units or []:
        key = str(c).strip().lower()
        if not key or key in lower_map:
            continue
        names.append(str(c).strip())
        lower_map[key] = str(c).strip()

    fav_set = set(favorite_units or set())
    if favorites_only and fav_set:
        fav_keys = {canonical_intensity_unit_key(x) for x in fav_set}
        names = [
            n
            for n in names
            if canonical_intensity_unit_key(str(n or "")) in fav_keys
        ]

    if units_only:
        from web_portal.lib.network_analysis_helpers import unit_name_matches

        names = [
            n
            for n in names
            if any(unit_name_matches(str(n or ""), u) for u in units_only)
        ]

    return sorted(names, key=lambda x: str(x or "").strip().lower())


def assemble_network_summary_payload(
    *,
    names: list[str],
    cur_clusters: list[dict[str, object]] | None,
    prev_clusters: list[dict[str, object]] | None,
    position_filter: str | None,
    all_positions: bool,
    shared_order: list[str],
    column_order: list[str],
    start_clean: datetime,
    end_clean: datetime,
    prev_start: datetime,
) -> dict[str, Any]:
    cur_map = clusters_to_unit_map(cur_clusters)
    prev_map = clusters_to_unit_map(prev_clusters)

    def _metrics(cluster_map: dict[str, dict[str, object]], unit_name: str) -> dict[str, int]:
        row = cluster_map.get(str(unit_name).strip().lower(), {})
        return {
            "sessions": int(row.get("sessions") or 0),
            "correspondents": int(row.get("correspondents") or 0),
        }

    return {
        "ok": True,
        "position": position_filter,
        "all_positions": all_positions,
        "shared_order": shared_order,
        "column_order": column_order,
        "start": start_clean.isoformat(timespec="minutes"),
        "end": end_clean.isoformat(timespec="minutes"),
        "prev_start": prev_start.isoformat(timespec="minutes"),
        "prev_end": start_clean.isoformat(timespec="minutes"),
        "clusters": names,
        "current": {n: _metrics(cur_map, n) for n in names},
        "previous": {n: _metrics(prev_map, n) for n in names},
    }


def parse_network_summary_range(
    start_s: str,
    end_s: str,
) -> tuple[datetime, datetime]:
    start_s = str(start_s or "").strip()
    end_s = str(end_s or "").strip()
    if not start_s or not end_s:
        raise AnalysisUseCaseHTTP(
            400, {"ok": False, "error": "start/end обязательны"}
        )
    try:
        start = datetime.fromisoformat(start_s)
        end = datetime.fromisoformat(end_s)
    except Exception as exc:
        raise AnalysisUseCaseHTTP(
            400,
            {"ok": False, "error": "Неверный формат start/end (ISO)"},
        ) from exc
    if end <= start:
        raise AnalysisUseCaseHTTP(
            400, {"ok": False, "error": "end должен быть > start"}
        )
    return start, end


def execute_network_summary(
    main_conn,
    seans_conn,
    *,
    position_filter: str | None,
    position_key: str,
    all_positions: bool,
    start: datetime,
    end: datetime,
    favorites_only: bool,
    favorite_units_raw: str,
    custom_units_raw: str,
    units_only_raw: str,
    user_id: int,
) -> dict[str, Any]:
    bounds = network_analysis_period_bounds(start, end)
    start_clean = bounds["start_clean"]
    end_clean = bounds["end_clean"]
    end_query = bounds["end_query"]
    prev_start = bounds["prev_start"]
    prev_end_query = bounds["prev_end_query"]

    daily_clusters = get_network_intensity_clusters_dual_daily(
        main_conn,
        seans_conn=seans_conn,
        cur_start_dt=start_clean.strftime("%Y-%m-%d %H:%M:%S"),
        cur_end_dt=end_query.strftime("%Y-%m-%d %H:%M:%S"),
        prev_start_dt=prev_start.strftime("%Y-%m-%d %H:%M:%S"),
        prev_end_dt=prev_end_query.strftime("%Y-%m-%d %H:%M:%S"),
        position_name=position_filter,
    )
    if daily_clusters is None:
        cur_clusters, prev_clusters = get_network_intensity_clusters_dual(
            main_conn,
            seans_conn=seans_conn,
            cur_start_dt=start_clean.strftime("%Y-%m-%d %H:%M:%S"),
            cur_end_dt=end_query.strftime("%Y-%m-%d %H:%M:%S"),
            prev_start_dt=prev_start.strftime("%Y-%m-%d %H:%M:%S"),
            prev_end_dt=prev_end_query.strftime("%Y-%m-%d %H:%M:%S"),
            position_name=position_filter,
        )
    else:
        cur_clusters, prev_clusters = daily_clusters

    favorite_units: set[str] = set()
    if favorites_only:
        try:
            favorites = get_sessions_favorites(main_conn, int(user_id))
        except Exception:
            favorites = []
        favorite_units = network_favorite_units_from_sessions(main_conn, favorites)

    shared_order = parse_analysis_order_list(
        get_position_setting(
            main_conn,
            position_name=position_key,
            key="analysis_network_shared_order",
        )
    )
    column_order = parse_analysis_order_list(
        get_position_setting(
            main_conn,
            position_name=position_key,
            key="analysis_network_column_order",
        )
    )
    custom_units = parse_analysis_custom_units(custom_units_raw)
    favorite_units_arg = parse_analysis_custom_units(favorite_units_raw)
    for n in favorite_units_arg:
        favorite_units.add(n)
    units_only = parse_analysis_custom_units(units_only_raw)
    names = merge_network_summary_unit_names(
        cur_clusters,
        prev_clusters,
        custom_units=custom_units,
        favorite_units=favorite_units,
        favorites_only=favorites_only,
        units_only=units_only or None,
    )
    return assemble_network_summary_payload(
        names=names,
        cur_clusters=cur_clusters,
        prev_clusters=prev_clusters,
        position_filter=position_filter,
        all_positions=all_positions,
        shared_order=shared_order,
        column_order=column_order,
        start_clean=start_clean,
        end_clean=end_clean,
        prev_start=prev_start,
    )
