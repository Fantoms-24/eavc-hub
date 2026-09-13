"""Сборка ответа GET /api/online-search/battalion-spectrum."""

from __future__ import annotations

from collections.abc import Callable
import logging
import sqlite3
from typing import Any

from web_portal.lib.db import (
    _norm_unit_note,
    _parent_merge_key,
    count_online_search_by_unit_key,
    get_online_search_unit_profile,
    list_active_seans_freq_groups_for_unit_name,
    list_archive_freq_by_note,
    list_online_search_unit_avatar_files,
    parse_note_unit_parent_child,
)

from web_portal.application.online_search.errors import OnlineSearchUseCaseHTTP
from web_portal.application.online_search.media_urls import (
    avatar_url_for_file,
    parse_hero_payload,
)
from web_portal.application.online_search.validation import validate_battalion_key

_log = logging.getLogger("web_portal.application.online_search.battalion_spectrum")


def assemble_online_search_battalion_spectrum_payload(
    search_conn: sqlite3.Connection,
    main_conn: sqlite3.Connection,
    unit_key: str,
    *,
    build_avatar_url: Callable[[str], str],
    build_hero_url: Callable[[str], str],
) -> dict[str, Any]:
    validate_battalion_key(unit_key)

    try:
        profile = get_online_search_unit_profile(search_conn, unit_key)
        total = count_online_search_by_unit_key(search_conn, unit_key)
        av_url = avatar_url_for_file(profile.get("avatar_file"), build_url=build_avatar_url)

        ptext, ctail = parse_note_unit_parent_child(unit_key)
        mkey = _parent_merge_key(ptext) if ctail is not None else _parent_merge_key(unit_key)
        pkey_f = mkey
        plab = _norm_unit_note(ptext) if ctail is not None else _norm_unit_note(unit_key)

        av_keys: list[str] = []
        if pkey_f and pkey_f != "__none__":
            av_keys.append(pkey_f)
        if unit_key and unit_key != "__none__" and unit_key not in av_keys:
            av_keys.append(unit_key)
        av_map_bn = list_online_search_unit_avatar_files(search_conn, av_keys)

        parent_av_url = avatar_url_for_file(
            av_map_bn.get(pkey_f) if pkey_f else None,
            build_url=build_avatar_url,
        )
        if not parent_av_url and unit_key and unit_key != pkey_f:
            parent_av_url = avatar_url_for_file(
                av_map_bn.get(unit_key) if unit_key else None,
                build_url=build_avatar_url,
            )

        prof_parent_bn = get_online_search_unit_profile(search_conn, pkey_f)
        parent_hero = parse_hero_payload(
            prof_parent_bn.get("hero_json"),
            build_banner_url=build_hero_url,
        )

        active = list_active_seans_freq_groups_for_unit_name(main_conn, unit_key)
        archive = list_archive_freq_by_note(search_conn, unit_key)
        in_active = {
            (str(x.get("frequency") or ""), str(x.get("group") or "")) for x in active
        }
        archive_out = [
            {**row, "in_seanses": (str(row.get("frequency") or ""), str(row.get("group") or "")) in in_active}
            for row in archive
        ]

        return {
            "ok": True,
            "unit_key": unit_key,
            "total_in_db": total,
            "parent_key": pkey_f,
            "parent_label": plab,
            "parent_avatar_url": parent_av_url,
            "parent_hero": parent_hero,
            "profile": {
                "history": profile.get("history") or "",
                "avatar_url": av_url,
            },
            "active_frequencies": active,
            "archive_frequencies": archive_out,
        }
    except OnlineSearchUseCaseHTTP:
        raise
    except Exception as e:
        _log.exception("battalion-spectrum: %s", e)
        raise OnlineSearchUseCaseHTTP(
            500,
            {
                "ok": False,
                "error": "Ошибка при загрузке данных. Повторите позже.",
            },
        ) from e
