"""Обновление тега/цвета позывного в анализе + HUB outbox."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from web_portal.lib.db import enqueue_sync_outbox, update_intercept_callsign_tag

from web_portal.application.analysis.errors import AnalysisUseCaseHTTP

_log = logging.getLogger("web_portal.analysis.callsign_tags")


def execute_analysis_callsign_tag_update(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    callsign_id: int,
    tag: str,
    tag_desc: str,
    tag_color: str,
    sync_hub: bool,
) -> dict[str, Any]:
    callsign_id = int(callsign_id or 0)
    if callsign_id <= 0:
        raise AnalysisUseCaseHTTP(
            400, {"ok": False, "error": "callsign_id обязателен"}
        )
    try:
        update_intercept_callsign_tag(
            conn,
            position_name=position_name,
            callsign_id=callsign_id,
            tag=str(tag or ""),
            tag_desc=str(tag_desc or ""),
            tag_color=str(tag_color or ""),
        )
    except Exception as e:
        raise AnalysisUseCaseHTTP(400, {"ok": False, "error": str(e)}) from e
    if sync_hub:
        try:
            row = conn.execute(
                """
                SELECT uuid, position_name, label, code, tag, tag_desc, tag_color,
                       unit_name, frequency, group_code, updated_at
                FROM intercept_callsigns
                WHERE id=? AND position_name=?
                """,
                (callsign_id, str(position_name)),
            ).fetchone()
            if row:
                enqueue_sync_outbox(
                    conn,
                    kind="intercepts:callsign",
                    payload={
                        "uuid": str(row["uuid"] or ""),
                        "position_name": str(row["position_name"] or ""),
                        "label": str(row["label"] or ""),
                        "code": str(row["code"] or ""),
                        "tag": str(row["tag"] or ""),
                        "tag_desc": str(row["tag_desc"] or ""),
                        "tag_color": str(row["tag_color"] or ""),
                        "unit_name": str(row["unit_name"] or ""),
                        "frequency": str(row["frequency"] or ""),
                        "group_code": str(row["group_code"] or ""),
                        "updated_at": str(row["updated_at"] or ""),
                    },
                )
        except Exception:
            _log.debug(
                "execute_analysis_callsign_tag_update: suppressed sync error",
                exc_info=True,
            )
    return {"ok": True}
