"""Избранные и архив каталога перехватов (на пользователя)."""

from __future__ import annotations

import sqlite3
from typing import Any

from web_portal.application.intercepts.errors import InterceptsUseCaseHTTP
from web_portal.lib.auth_db import (
    get_user_intercept_catalog_prefs,
    toggle_intercept_catalog_archive,
    toggle_intercept_catalog_favorite,
)

MAX_INTERCEPT_CATALOG_FAVORITES = 5


def execute_intercepts_catalog_favorite_toggle(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    catalog_id: int = 0,
    frequency: str = "",
    group_code: str = "",
) -> dict[str, Any]:
    try:
        prefs, added = toggle_intercept_catalog_favorite(
            conn,
            user_id=int(user_id),
            catalog_id=int(catalog_id or 0),
            frequency=str(frequency or "").strip(),
            group_code=str(group_code or "").strip(),
            max_items=MAX_INTERCEPT_CATALOG_FAVORITES,
        )
        return {"ok": True, "catalog_prefs": prefs, "added": added}
    except ValueError as e:
        raise InterceptsUseCaseHTTP(400, {"ok": False, "error": str(e)}) from e
    except Exception as e:
        raise InterceptsUseCaseHTTP(500, {"ok": False, "error": str(e)}) from e


def execute_intercepts_catalog_archive_toggle(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    catalog_id: int = 0,
    frequency: str = "",
    group_code: str = "",
) -> dict[str, Any]:
    try:
        prefs, archived = toggle_intercept_catalog_archive(
            conn,
            user_id=int(user_id),
            catalog_id=int(catalog_id or 0),
            frequency=str(frequency or "").strip(),
            group_code=str(group_code or "").strip(),
        )
        return {"ok": True, "catalog_prefs": prefs, "archived": archived}
    except Exception as e:
        raise InterceptsUseCaseHTTP(500, {"ok": False, "error": str(e)}) from e


def load_intercept_catalog_prefs_for_user(
    conn: sqlite3.Connection, *, user_id: int
) -> dict[str, Any]:
    return get_user_intercept_catalog_prefs(conn, user_id=int(user_id))
