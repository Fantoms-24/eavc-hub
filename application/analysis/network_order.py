"""Сохранение порядка колонок общего анализа радиосети."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from web_portal.lib.auth_db import set_position_setting

from web_portal.application.analysis.errors import AnalysisUseCaseHTTP


def normalize_network_column_order(order_raw: object) -> list[str]:
    if order_raw is not None and not isinstance(order_raw, list):
        raise AnalysisUseCaseHTTP(
            400, {"ok": False, "error": "order должен быть списком"}
        )
    order: list[str] = []
    seen: set[str] = set()
    for item in order_raw or []:
        name = str(item or "").strip()
        if not name or name in seen:
            continue
        order.append(name)
        seen.add(name)
    return order


def execute_analysis_network_order_shared(
    conn: sqlite3.Connection,
    *,
    position_key: str,
    order_raw: object,
) -> dict[str, Any]:
    order = normalize_network_column_order(order_raw)
    set_position_setting(
        conn,
        position_name=position_key,
        key="analysis_network_shared_order",
        value=json.dumps(order, ensure_ascii=False),
    )
    set_position_setting(
        conn,
        position_name=position_key,
        key="analysis_network_column_order",
        value="[]",
    )
    return {"ok": True, "order": order, "position": position_key}


def execute_analysis_network_order_save(
    conn: sqlite3.Connection,
    *,
    position_key: str,
    order_raw: object,
) -> dict[str, Any]:
    order = normalize_network_column_order(order_raw)
    set_position_setting(
        conn,
        position_name=position_key,
        key="analysis_network_column_order",
        value=json.dumps(order, ensure_ascii=False),
    )
    return {"ok": True, "order": order, "position": position_key}
