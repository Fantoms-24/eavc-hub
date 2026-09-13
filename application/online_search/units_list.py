"""Сборка ответа GET /api/online-search/units."""

from __future__ import annotations

from collections.abc import Callable
import sqlite3
from typing import Any

from web_portal.lib.db import (
    list_distinct_online_search_units,
    list_online_search_unit_avatar_files,
    list_online_search_unit_families,
)
from web_portal.webapp.online_search_filters import (
    _filter_os_families_by_q,
    _filter_os_units_by_q,
)

from web_portal.application.online_search.media_urls import (
    collect_family_unit_keys,
    resolve_family_avatar_url,
)


def assemble_online_search_units_list_payload(
    conn: sqlite3.Connection,
    *,
    q_filter: str = "",
    build_avatar_url: Callable[[str], str],
) -> dict[str, Any]:
    units = list_distinct_online_search_units(conn)
    families = list_online_search_unit_families(conn)
    if q_filter:
        families = _filter_os_families_by_q(families, q_filter)
        units = _filter_os_units_by_q(units, q_filter)

    ukeys = collect_family_unit_keys(families)
    av_files = list_online_search_unit_avatar_files(conn, ukeys)
    for fam in families:
        fam["avatar_url"] = resolve_family_avatar_url(
            fam, av_files, build_url=build_avatar_url
        )

    return {"ok": True, "units": units, "families": families}
