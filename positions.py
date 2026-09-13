"""Позиции пользователя в портале (сессия + БД портала). Вынесено из app.create_app."""

from __future__ import annotations

import logging

from flask import session
from flask_login import current_user

from web_portal.config import portal_db_path
from web_portal.lib.auth_db import (
    connect_portal,
    get_user_position_role,
    get_user_positions,
    list_positions,
)

logger = logging.getLogger(__name__)


def allowed_positions_for_current_user() -> list[str]:
    if not current_user.is_authenticated:
        return []
    if current_user.role == "admin":
        conn = connect_portal(portal_db_path())
        try:
            return list_positions(conn)
        finally:
            conn.close()
    conn = connect_portal(portal_db_path())
    try:
        return get_user_positions(conn, int(current_user.id))
    finally:
        conn.close()


def current_user_position_role(position_name: str) -> str | None:
    if not current_user.is_authenticated:
        return None
    if current_user.role == "admin":
        return "admin"
    conn = connect_portal(portal_db_path())
    try:
        return get_user_position_role(conn, int(current_user.id), position_name)
    finally:
        conn.close()


def require_position_role(position_name: str, need: str) -> bool:
    """
    need: 'view' | 'edit' | 'export' | 'start'
    operator: view/edit
    chief: view/edit/export/start
    admin: all
    """
    pos_role = current_user_position_role(position_name)
    if pos_role == "admin":
        return True
    if pos_role == "chief":
        return True
    if pos_role == "operator":
        return need in {"view", "edit"}
    return False


def get_selected_position() -> str | None:
    if not current_user.is_authenticated:
        logger.debug(
            "[АВТОПОИСК] get_selected_position: пользователь не аутентифицирован"
        )
        return None
    allowed = allowed_positions_for_current_user()
    logger.debug(
        "[АВТОПОИСК] get_selected_position: allowed=%s, current_session_pos=%s, role=%s",
        allowed,
        session.get("position"),
        getattr(current_user, "role", None),
    )

    if len(allowed) == 1:
        session["position"] = allowed[0]
        logger.debug(
            "[АВТОПОИСК] get_selected_position: автоматически выбрана единственная позиция: %s",
            allowed[0],
        )
        return allowed[0]
    if current_user.role == "admin":
        pos = (session.get("position") or "").strip()
        logger.debug(
            "[АВТОПОИСК] get_selected_position: админ, возвращаем позицию из сессии: %s",
            pos,
        )
        return pos or None
    pos = (session.get("position") or "").strip()
    if pos and pos in allowed:
        logger.debug(
            "[АВТОПОИСК] get_selected_position: позиция из сессии доступна: %s", pos
        )
        return pos
    if allowed:
        session["position"] = allowed[0]
        logger.debug(
            "[АВТОПОИСК] get_selected_position: автоматически выбрана первая доступная позиция: %s",
            allowed[0],
        )
        return allowed[0]
    logger.warning(
        "[АВТОПОИСК] get_selected_position: нет доступных позиций для пользователя"
    )
    return None


def can_edit_session_unit_name() -> bool:
    """Право менять название подразделения (unit.name) в таблице сеансов."""
    if not current_user.is_authenticated:
        return False
    if current_user.role == "admin":
        return True
    selected = get_selected_position()
    if selected:
        pos_role = current_user_position_role(selected)
        if pos_role in {"chief", "admin"}:
            return True
    return bool(
        current_user.has_perm("import_folder")
        or current_user.has_perm("edit_search")
        or current_user.has_perm("manage_users")
    )
