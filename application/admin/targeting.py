"""Нацеливания админки (без Flask)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Mapping

import sqlite3

from web_portal.application.admin.errors import AdminUseCaseHTTP
from web_portal.config import DEFAULT_DB_NAME, db_path
from web_portal.lib.auth_db import create_targeting, get_targeting_sync_payload
from web_portal.lib.db import connect, enqueue_sync_outbox, ensure_db

_log = logging.getLogger("web_portal.application.admin.targeting")


@dataclass(frozen=True)
class CreateTargetingInput:
    title: str
    message: str
    target_type: str
    target_position: str
    target_user_ids: list[int] | None
    expires_at: str | None
    created_by: str


def assemble_admin_targeting_list(
    conn: sqlite3.Connection,
    *,
    now_iso: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, uuid, title, message, target_type, target_position, target_user_ids,
               created_by, created_at, expires_at
        FROM targeting
        WHERE is_active = 1
          AND (expires_at IS NULL OR expires_at > ?)
        ORDER BY created_at DESC
        """,
        (now_iso,),
    ).fetchall()

    targeting: list[dict[str, Any]] = []
    for row in rows:
        target_user_ids_json = str(row["target_user_ids"] or "[]")
        targeting.append(
            {
                "id": int(row["id"]),
                "uuid": str(row["uuid"] or ""),
                "title": str(row["title"] or ""),
                "message": str(row["message"] or ""),
                "target_type": str(row["target_type"] or ""),
                "target_position": str(row["target_position"] or ""),
                "target_user_ids": json.loads(target_user_ids_json),
                "created_by": str(row["created_by"] or ""),
                "created_at": str(row["created_at"] or ""),
                "expires_at": (
                    str(row["expires_at"] or "") if row["expires_at"] else None
                ),
                "is_read": False,
            }
        )
    return targeting


def parse_create_targeting_input(
    data: Mapping[str, Any],
    *,
    created_by: str,
) -> CreateTargetingInput:
    title = (data.get("title") or "").strip()
    message = (data.get("message") or "").strip()
    target_type = (data.get("target_type") or "all").strip()
    target_position = (data.get("target_position") or "").strip()
    target_user_ids_raw = data.get("target_user_ids") or []
    expires_at = data.get("expires_at") or None

    if not title or not message:
        raise AdminUseCaseHTTP(
            400,
            {"ok": False, "error": "title и message обязательны"},
        )

    if target_type not in ["all", "position", "users"]:
        raise AdminUseCaseHTTP(
            400,
            {"ok": False, "error": "Неверный target_type"},
        )

    if target_type == "position" and not target_position:
        raise AdminUseCaseHTTP(
            400,
            {
                "ok": False,
                "error": "target_position обязателен для типа position",
            },
        )

    if target_type == "users" and not target_user_ids_raw:
        raise AdminUseCaseHTTP(
            400,
            {"ok": False, "error": "target_user_ids обязателен для типа users"},
        )

    target_user_ids = None
    if target_user_ids_raw:
        target_user_ids = [int(uid) for uid in target_user_ids_raw]

    return CreateTargetingInput(
        title=title,
        message=message,
        target_type=target_type,
        target_position=target_position,
        target_user_ids=target_user_ids,
        expires_at=expires_at,
        created_by=created_by,
    )


def execute_create_targeting(
    conn: sqlite3.Connection,
    params: CreateTargetingInput,
    *,
    is_sync_hub: bool,
) -> dict[str, Any]:
    targeting_id = create_targeting(
        conn,
        title=params.title,
        message=params.message,
        target_type=params.target_type,
        target_position=params.target_position,
        target_user_ids=params.target_user_ids,
        created_by=params.created_by,
        expires_at=params.expires_at,
    )

    if not is_sync_hub:
        try:
            p = db_path(DEFAULT_DB_NAME)
            ensure_db(p)
            mconn = connect(p)
            try:
                payload = get_targeting_sync_payload(conn, targeting_id=targeting_id)
                if payload:
                    enqueue_sync_outbox(mconn, kind="targeting", payload=payload)
            finally:
                mconn.close()
        except Exception:
            _log.debug("execute_create_targeting: suppressed error", exc_info=True)

    return {"ok": True, "targeting_id": targeting_id}
