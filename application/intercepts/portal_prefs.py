"""Настройки пользователя портала для «Перехватов»: режим просмотра, порядок юнитов."""

from __future__ import annotations

import sqlite3
from typing import Any

from web_portal.lib.auth_db import set_user_intercept_unit_order, set_user_intercept_view_mode

from web_portal.application.intercepts.errors import InterceptsUseCaseHTTP


def execute_intercepts_set_view_mode(
    conn: sqlite3.Connection, *, user_id: int, mode: str
) -> dict[str, Any]:
    m = str(mode or "").strip().lower()
    if m not in {"pretty", "plain"}:
        raise InterceptsUseCaseHTTP(400, {"ok": False, "error": "Некорректный режим"})
    try:
        saved = set_user_intercept_view_mode(conn, user_id=int(user_id), mode=m)
        return {"ok": True, "mode": saved}
    except Exception as e:
        raise InterceptsUseCaseHTTP(500, {"ok": False, "error": str(e)}) from e


def execute_intercepts_set_unit_order(
    conn: sqlite3.Connection, *, user_id: int, order: object
) -> dict[str, Any]:
    if not isinstance(order, list):
        raise InterceptsUseCaseHTTP(400, {"ok": False, "error": "order должен быть списком"})
    try:
        saved = set_user_intercept_unit_order(
            conn, user_id=int(user_id), order=[str(x) for x in order]
        )
        return {"ok": True, "order": saved}
    except Exception as e:
        raise InterceptsUseCaseHTTP(500, {"ok": False, "error": str(e)}) from e
