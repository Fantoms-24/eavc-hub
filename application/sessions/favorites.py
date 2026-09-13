"""Избранное сеансов: list / add / remove."""

from __future__ import annotations

import sqlite3
from typing import Any

from web_portal.lib.db import (
    _get_unit_name_for_pair,
    add_sessions_favorite,
    get_pairs_for_unit_name,
    get_sessions_favorites,
    remove_sessions_favorite,
    sessions_favorite_matches_row,
)

from web_portal.application.sessions.errors import SessionsUseCaseHTTP


def assemble_sessions_favorites_list(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    with_unit_names: bool = False,
    include_units: bool = False,
) -> list[dict[str, Any]]:
    favorites = get_sessions_favorites(conn, user_id)
    if with_unit_names:
        out: list[dict[str, Any]] = []
        for f in favorites:
            freq = str(f.get("frequency") or "").strip()
            grp = str(f.get("group") or "").strip()
            if freq == "__unit__":
                name = grp
            else:
                name = _get_unit_name_for_pair(conn, freq, grp).strip()
            out.append(
                {
                    "frequency": freq,
                    "group": grp,
                    "unit_name": name or None,
                }
            )
        return out
    if include_units:
        return favorites
    out_pairs: list[dict[str, Any]] = []
    for f in favorites:
        freq = str(f.get("frequency") or "").strip()
        if freq == "__unit__":
            continue
        out_pairs.append(f)
    return out_pairs


def execute_sessions_add_favorite(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    frequency: str,
    group: str,
    unit_name: str,
) -> dict[str, Any]:
    frequency = str(frequency or "").strip()
    group = str(group or "").strip()
    unit_name = str(unit_name or "").strip()

    if unit_name:
        pairs = get_pairs_for_unit_name(conn, unit_name)
        added = 0
        if add_sessions_favorite(conn, user_id, "__unit__", unit_name):
            added += 1
        for pair in pairs:
            if add_sessions_favorite(
                conn, user_id, pair["frequency"], pair["group"]
            ):
                added += 1
        return {"ok": True, "message": "Добавлено в избранное", "added": added}

    if not frequency or not group:
        raise SessionsUseCaseHTTP(
            400,
            {"ok": False, "error": "Укажите frequency и group или unit_name"},
        )
    success = add_sessions_favorite(conn, user_id, frequency, group)
    if success:
        return {"ok": True, "message": "Добавлено в избранное"}
    raise SessionsUseCaseHTTP(
        500, {"ok": False, "error": "Не удалось добавить в избранное"}
    )


def execute_sessions_remove_favorite(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    frequency: str,
    group: str,
    unit_name: str,
) -> dict[str, Any]:
    frequency = str(frequency or "").strip()
    group = str(group or "").strip()
    unit_name = str(unit_name or "").strip()

    if unit_name:
        pairs = get_pairs_for_unit_name(conn, unit_name)
        removed = 0
        if remove_sessions_favorite(conn, user_id, "__unit__", unit_name):
            removed += 1
        for pair in pairs:
            if remove_sessions_favorite(
                conn, user_id, pair["frequency"], pair["group"]
            ):
                removed += 1
        return {
            "ok": True,
            "message": "Удалено из избранного",
            "removed": removed,
        }

    if not frequency or not group:
        raise SessionsUseCaseHTTP(
            400,
            {"ok": False, "error": "Укажите frequency и group или unit_name"},
        )

    all_favorites = get_sessions_favorites(conn, user_id)
    success = remove_sessions_favorite(conn, user_id, frequency, group)
    if not success:
        for fav in all_favorites:
            if sessions_favorite_matches_row(frequency, group, fav):
                success = remove_sessions_favorite(
                    conn,
                    user_id,
                    str(fav.get("frequency") or ""),
                    str(fav.get("group") or ""),
                )
                if success:
                    break

    if success:
        return {"ok": True, "message": "Удалено из избранного"}
    raise SessionsUseCaseHTTP(
        404, {"ok": False, "error": "Запись не найдена в избранном"}
    )
