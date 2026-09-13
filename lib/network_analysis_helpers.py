from __future__ import annotations

from datetime import datetime, timedelta

from web_portal.lib.db import _build_unit_name_map_for_pairs


def normalize_unit_filter_text(s: str) -> str:
    return " ".join(str(s or "").lower().replace("ё", "е").split())


def unit_name_matches(row_name: str, unit_filter: str) -> bool:
    needle = normalize_unit_filter_text(unit_filter)
    if not needle:
        return True
    hay = normalize_unit_filter_text(row_name)
    if not hay:
        return False
    return needle in hay or hay in needle


def network_analysis_period_bounds(start: datetime, end: datetime) -> dict[str, datetime]:
    start_clean = start.replace(second=0, microsecond=0)
    end_clean = end.replace(second=0, microsecond=0)
    delta = end_clean - start_clean
    if delta <= timedelta(0):
        delta = end - start

    if end.second == 0 and end.microsecond == 0:
        end_query = end.replace(second=59, microsecond=0)
    else:
        end_query = end

    prev_start = start_clean - delta
    if start_clean.second == 0 and start_clean.microsecond == 0:
        prev_end_query = start_clean.replace(second=59, microsecond=0)
    else:
        prev_end_query = start_clean

    return {
        "start_clean": start_clean,
        "end_clean": end_clean,
        "end_query": end_query,
        "prev_start": prev_start,
        "prev_end_query": prev_end_query,
    }


def network_favorite_units_from_sessions(
    conn,
    favorites,
    extra_units: list[str] | None = None,
) -> set[str]:
    favorite_units: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for f in favorites or []:
        freq = str(f.get("frequency") or "").strip()
        grp = str(f.get("group") or "").strip()
        if freq == "__unit__":
            if grp:
                favorite_units.add(grp)
            continue
        if not freq or not grp:
            continue
        pairs.append((freq, grp))
    if pairs:
        unit_map = _build_unit_name_map_for_pairs(conn, pairs)
        for freq, grp in pairs:
            name = str(unit_map.get((freq, grp)) or "").strip()
            if name:
                favorite_units.add(name)
    for n in extra_units or []:
        s = str(n or "").strip()
        if s:
            favorite_units.add(s)
    return favorite_units
