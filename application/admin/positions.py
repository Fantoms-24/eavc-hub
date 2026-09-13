"""Назначения позиций пользователей (без Flask)."""

from __future__ import annotations

from typing import Any, Mapping

import sqlite3

from web_portal.application.admin.errors import AdminUseCaseHTTP
from web_portal.lib.auth_db import init_portal_db


def parse_positions_map_assignments(assignments: Any) -> list[str]:
    """Преобразует { \"Москва\": \"operator\" } → [\"Москва:operator\", ...]."""
    if not isinstance(assignments, dict):
        raise AdminUseCaseHTTP(
            400,
            {"ok": False, "error": "assignments должен быть dict"},
        )
    tokens: list[str] = []
    for k, v in assignments.items():
        name = str(k or "").strip()
        role = str(v or "").strip().lower()
        if not name:
            continue
        if role not in {"operator", "chief"}:
            role = "operator"
        tokens.append(f"{name}:{role}")
    return tokens


def assemble_user_positions_map(
    conn: sqlite3.Connection,
    user_id: int,
) -> dict[str, Any]:
    if not user_id:
        raise AdminUseCaseHTTP(
            400,
            {"ok": False, "error": "user_id обязателен"},
        )
    init_portal_db(conn)
    rows = conn.execute(
        """
        SELECT p.name AS name, up.role AS role
        FROM user_positions up
        JOIN positions p ON p.id = up.position_id
        WHERE up.user_id=?
        ORDER BY p.name
        """,
        (int(user_id),),
    ).fetchall()
    assignments = {
        str(r["name"] or ""): str(r["role"] or "operator") for r in rows
    }
    return {
        "ok": True,
        "user_id": int(user_id),
        "assignments": assignments,
    }


def require_user_id(raw: Mapping[str, Any] | int | None) -> int:
    if isinstance(raw, int):
        user_id = raw
    elif isinstance(raw, Mapping):
        try:
            user_id = int(raw.get("user_id") or 0)
        except (TypeError, ValueError):
            user_id = 0
    else:
        user_id = 0
    if not user_id:
        raise AdminUseCaseHTTP(
            400,
            {"ok": False, "error": "user_id обязателен"},
        )
    return user_id
