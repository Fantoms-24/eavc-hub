"""Справочники пользователей и ролей (без Flask)."""

from __future__ import annotations

from typing import Any

import sqlite3

from web_portal.lib.auth_db import (
    PERM_LABELS,
    ROLE_LABELS,
    ROLE_PERMS,
    TAB_CATEGORIES,
    list_custom_roles,
    list_users,
)


def assemble_admin_users_list_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    custom = list_custom_roles(conn)
    roles_for_assignment = [
        {"role": r, "label": ROLE_LABELS.get(r, r), "builtin": True}
        for r in sorted(ROLE_PERMS.keys())
    ]
    roles_for_assignment += [
        {"role": cr["name"], "label": cr["name"], "builtin": False}
        for cr in custom
    ]
    return {
        "ok": True,
        "users": list_users(conn),
        "roles": sorted(ROLE_PERMS.keys()),
        "roles_for_assignment": roles_for_assignment,
    }


def assemble_admin_roles_payload(custom_roles: list[dict[str, Any]]) -> dict[str, Any]:
    roles: list[dict[str, Any]] = []
    for role in sorted(ROLE_PERMS.keys()):
        perms = sorted(ROLE_PERMS.get(role, set()))
        roles.append(
            {
                "role": role,
                "label": ROLE_LABELS.get(role, role),
                "builtin": True,
                "permissions": [
                    {"perm": p, "label": PERM_LABELS.get(p, p)} for p in perms
                ],
            }
        )
    for cr in custom_roles:
        roles.append(
            {
                "role": cr["name"],
                "label": cr["name"],
                "id": cr["id"],
                "builtin": False,
                "permissions": [
                    {"perm": p, "label": PERM_LABELS.get(p, p)}
                    for p in cr["permissions"]
                ],
            }
        )
    tab_categories = [{"id": tid, "label": lbl} for tid, lbl in TAB_CATEGORIES]
    roles_for_assignment = [
        {"role": r["role"], "label": r["label"], "builtin": r.get("builtin", True)}
        for r in roles
    ]
    all_perms = sorted({p for perms in ROLE_PERMS.values() for p in perms})
    return {
        "ok": True,
        "roles": roles,
        "custom_roles": custom_roles,
        "tab_categories": tab_categories,
        "roles_for_assignment": roles_for_assignment,
        "all_permissions": [
            {"perm": p, "label": PERM_LABELS.get(p, p)} for p in all_perms
        ],
    }
