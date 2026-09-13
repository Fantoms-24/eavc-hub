"""Хелперы «Общего анализа радиосети», вынесены из app.py."""

from __future__ import annotations

from datetime import datetime

from web_portal.lib.db import _build_unit_name_map_for_pairs


def _network_analysis_period_bounds(start: datetime, end: datetime) -> dict[str, datetime]:
    """
    Границы периодов для «Общий анализ радиосети».

    Длительность считается по границам минут (без +59 с к концу), иначе при выборе 08:00–10:00
    «предыдущий» интервал сдвигался на ~1 минуту и не совпадал с прямым запросом за 06:00–08:00.
    Верхняя граница текущего периода в SQL — включительно до конца минуты (XX:XX:59).
    """
    from datetime import timedelta

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


def _network_favorite_units_from_sessions(
    conn,
    favorites,
    extra_units: list[str] | None = None,
) -> set[str]:
    """Имена подразделений из избранного сеансов (пакетный lookup unit)."""
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
