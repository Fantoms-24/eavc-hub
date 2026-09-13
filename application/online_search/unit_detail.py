"""Сборка ответа GET /api/online-search/unit-detail."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
import logging
import sqlite3
from typing import Any

from web_portal.lib.db import (
    count_online_search_by_unit_key,
    get_online_search_headers,
    get_online_search_meta,
    get_online_search_unit_profile,
    list_intercept_callsigns_for_unit_pair,
    list_online_search_rows_by_unit_key,
    match_callsign_for_corr,
)

from web_portal.application.online_search.media_urls import avatar_url_for_file
from web_portal.application.online_search.validation import validate_unit_key

_log = logging.getLogger("web_portal.application.online_search.unit_detail")


def _discovery_column(headers: list[str] | None) -> int:
    disc_col = 7
    try:
        hlow = [str(x or "").lower() for x in (headers or [])]
        for i, hx in enumerate(hlow):
            if "обнаруж" in hx or "discovery" in hx:
                disc_col = i + 1
                break
    except Exception:
        _log.debug("assemble_online_search_unit_detail_payload: suppressed error", exc_info=True)
    return disc_col


def assemble_online_search_unit_detail_payload(
    search_conn: sqlite3.Connection,
    main_conn: sqlite3.Connection,
    unit_key: str,
    *,
    build_avatar_url: Callable[[str], str],
) -> dict[str, Any]:
    validate_unit_key(unit_key)

    headers = get_online_search_headers(search_conn)
    meta = get_online_search_meta(search_conn) or {}
    disc_col = _discovery_column(headers)

    rows = list_online_search_rows_by_unit_key(search_conn, unit_key, max_rows=10000)
    total = count_online_search_by_unit_key(search_conn, unit_key)
    truncated = total > len(rows)
    profile = get_online_search_unit_profile(search_conn, unit_key)
    unit_note = "" if unit_key in ("__none__", "") else unit_key

    groups_map: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for r in rows:
        fk = (str(r.get("frequency") or ""), str(r.get("group_id") or ""))
        corr = str(r.get("col4") or "")
        cs = match_callsign_for_corr(
            main_conn,
            unit_note=unit_note,
            frequency=fk[0],
            group_id=fk[1],
            corr=corr,
        )
        disc = ""
        if 1 <= disc_col <= 9:
            disc = str(r.get(f"col{disc_col}") or "")
        groups_map[fk].append(
            {
                "id": r.get("id"),
                "frequency": r.get("frequency"),
                "group_id": r.get("group_id"),
                "col3": r.get("col3"),
                "col4": r.get("col4"),
                "col6": r.get("col6"),
                "col7": r.get("col7"),
                "note": r.get("note"),
                "updated_at": r.get("updated_at"),
                "discovery": disc,
                "callsign": cs,
            }
        )

    groups: list[dict[str, object]] = []
    for freq, gid in sorted(groups_map.keys(), key=lambda x: (str(x[0]), str(x[1]))):
        cs_tab = list_intercept_callsigns_for_unit_pair(
            main_conn,
            unit_note=unit_key,
            frequency=freq,
            group_id=gid,
            limit=500,
        )
        groups.append(
            {
                "frequency": freq,
                "group_id": gid,
                "items": groups_map[(freq, gid)],
                "callsigns": cs_tab,
            }
        )

    avatar_url = avatar_url_for_file(
        profile.get("avatar_file"),
        build_url=build_avatar_url,
    )

    disc_lbl = "Дата обнаружения"
    if (
        headers
        and disc_col
        and disc_col - 1 < len(headers)
        and str(headers[disc_col - 1] or "").strip()
    ):
        disc_lbl = str(headers[disc_col - 1] or disc_lbl)

    return {
        "ok": True,
        "unit_key": unit_key,
        "total_in_db": total,
        "truncated": truncated,
        "headers": headers or [],
        "meta": meta,
        "labels": {
            "id_field": (headers[2] if len(headers) > 2 else "ID") or "ID",
            "correspondent": (headers[3] if len(headers) > 3 else "Корр.") or "Корр.",
            "discovery": disc_lbl,
        },
        "profile": {
            "history": profile.get("history") or "",
            "avatar_url": avatar_url,
        },
        "groups": groups,
    }
