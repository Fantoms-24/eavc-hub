"""Экспорт смены в DOCX (GET /api/intercepts/export-docx)."""

from __future__ import annotations

from datetime import datetime
import sqlite3
import tempfile
from pathlib import Path

from web_portal.lib.db import (
    get_intercept_session,
    list_intercept_catalog,
    list_intercept_items_for_session,
)
from web_portal.lib.intercepts_report import InterceptsReport

from web_portal.application.intercepts.errors import InterceptsUseCaseHTTP


def build_intercepts_export_docx_file(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    session_id: int,
) -> tuple[Path, str]:
    if not session_id:
        raise InterceptsUseCaseHTTP(
            400, {"ok": False, "error": "session_id обязателен"}
        )
    sess = get_intercept_session(conn, session_id)
    if not sess or sess.get("position_name") != position_name:
        raise InterceptsUseCaseHTTP(
            404, {"ok": False, "error": "Смена не найдена"}
        )
    items = [
        x
        for x in list_intercept_items_for_session(conn, session_id)
        if (x.get("content") or "").strip()
    ]
    started_at = str(sess.get("started_at") or "")
    ended_at = str(sess.get("ended_at") or "") or None
    report = InterceptsReport(
        position_name=position_name, started_at=started_at, ended_at=ended_at
    )

    catalog_map: dict[tuple[str, str], dict] = {}
    try:
        catalog = list_intercept_catalog(conn, position_name)
        for cat in catalog or []:
            key = (
                str(cat.get("frequency") or "").strip(),
                str(cat.get("group_code") or "").strip(),
            )
            catalog_map[key] = cat
    except Exception:
        catalog_map = {}

    for i, it in enumerate(items, start=1):
        freq = str(it.get("frequency") or "").strip()
        grp = str(it.get("group_code") or "").strip()
        cat_item = catalog_map.get((freq, grp), {}) or {}
        location = str(cat_item.get("location") or "").strip()
        item_id = int(it.get("id") or 0)
        report.add_item(
            i,
            unit_name=str(it.get("unit_name") or ""),
            frequency=freq,
            group_code=grp,
            content=str(it.get("content") or ""),
            item_id=item_id,
            location=location,
        )

    safe_date = (
        started_at.split(" ")[0] if started_at else datetime.now().strftime("%Y-%m-%d")
    )
    sid = int(sess.get("id") or session_id or 0)
    filename = f"merged_intercepts_{safe_date}_shift{sid}.docx"
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        report.save(str(tmp_path))
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return tmp_path, filename
