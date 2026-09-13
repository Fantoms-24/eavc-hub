"""GET /api/intercepts/day-blank — объединённый бланк за сутки."""

from __future__ import annotations

import sqlite3
from typing import Any

from web_portal.lib.db import list_intercept_items_for_day, merge_intercept_day_contents

from web_portal.application.intercepts.errors import InterceptsUseCaseHTTP


def assemble_intercepts_day_blank_payload(
    conn: sqlite3.Connection,
    *,
    frequency: str,
    group_code: str,
    date_ymd: str,
) -> dict[str, Any]:
    frequency = str(frequency or "").strip()
    group_code = str(group_code or "").strip()
    date_ymd = str(date_ymd or "").strip()[:10]
    if not frequency or not group_code:
        raise InterceptsUseCaseHTTP(
            400, {"ok": False, "error": "frequency и group_code обязательны"}
        )
    if not date_ymd or len(date_ymd) < 10:
        raise InterceptsUseCaseHTTP(
            400, {"ok": False, "error": "date обязателен (YYYY-MM-DD)"}
        )
    items = list_intercept_items_for_day(
        conn, frequency=frequency, group_code=group_code, date_ymd=date_ymd
    )
    merged_content = merge_intercept_day_contents(items)
    unit_name = ""
    if items:
        unit_name = str(items[0].get("unit_name") or "")
    return {
        "ok": True,
        "date": date_ymd,
        "frequency": frequency,
        "group_code": group_code,
        "unit_name": unit_name,
        "items_count": len(items),
        "merged_content": merged_content,
        "items": [
            {
                "session_id": x.get("session_id"),
                "position_name": x.get("position_name"),
                "started_at": x.get("started_at"),
                "ended_at": x.get("ended_at"),
            }
            for x in items
        ],
    }
