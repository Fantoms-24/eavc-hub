"""Сборка ответа GET /api/online-search/unit-parent."""

from __future__ import annotations

from collections.abc import Callable
import sqlite3
from typing import Any

from web_portal.lib.db import (
    get_online_search_unit_profile,
    get_unit_family_by_parent_key,
    list_online_search_unit_avatar_files,
)

from web_portal.application.online_search.errors import OnlineSearchUseCaseHTTP
from web_portal.application.online_search.media_urls import (
    avatar_url_for_file,
    parse_hero_payload,
)
from web_portal.application.online_search.validation import validate_parent_key


def assemble_online_search_unit_parent_payload(
    conn: sqlite3.Connection,
    parent_key: str,
    *,
    build_avatar_url: Callable[[str], str],
    build_hero_url: Callable[[str], str],
) -> dict[str, Any]:
    validate_parent_key(parent_key)

    fam = get_unit_family_by_parent_key(conn, parent_key)
    if not fam:
        raise OnlineSearchUseCaseHTTP(
            404, {"ok": False, "error": "подразделение не найдено"}
        )

    ukeys: list[str] = []
    for ch in fam.get("children") or []:
        u = str(ch.get("unit_key") or "").strip()
        if u:
            ukeys.append(u)
    pkey = str(fam.get("parent_key") or "").strip() or parent_key
    ukeys_with_parent = [pkey, *ukeys] if pkey and pkey != "__none__" else ukeys
    av_map = list_online_search_unit_avatar_files(conn, ukeys_with_parent)

    av_url = avatar_url_for_file(av_map.get(pkey) if pkey else None, build_url=build_avatar_url)
    if not av_url:
        for ch in fam.get("children") or []:
            u = str(ch.get("unit_key") or "").strip()
            av_url = avatar_url_for_file(av_map.get(u) if u else None, build_url=build_avatar_url)
            if av_url:
                break

    prof_parent = get_online_search_unit_profile(conn, pkey)
    history = str(prof_parent.get("history") or "").strip()
    if not history:
        for ch in fam.get("children") or []:
            u = str(ch.get("unit_key") or "").strip()
            if not u:
                continue
            prof = get_online_search_unit_profile(conn, u)
            h = str(prof.get("history") or "").strip()
            if h:
                history = h
                break

    hero_payload = parse_hero_payload(
        prof_parent.get("hero_json"),
        build_banner_url=build_hero_url,
    )

    return {
        "ok": True,
        "parent_key": fam.get("parent_key"),
        "parent_label": fam.get("parent_label"),
        "row_count": fam.get("row_count"),
        "children": fam.get("children") or [],
        "avatar_url": av_url,
        "history": history,
        "hero": hero_payload,
    }
