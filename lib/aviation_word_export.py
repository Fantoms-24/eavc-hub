from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from web_portal.config import DEFAULT_DB_NAME, db_path
from web_portal.lib.aviation_db import (
    get_aviation_callsigns,
    get_aviation_frequency,
    get_aviation_intercept,
    get_intercept_content_by_date,
    normalize_aviation_work_date,
)
from web_portal.lib.aviation_report import AviationReport
from web_portal.lib.db import connect, ensure_db

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def build_aviation_word_docx(out_path: Path, params: dict[str, Any]) -> dict[str, object]:
    frequency_id = int(params.get("frequency_id") or 0)
    work_day = normalize_aviation_work_date(params.get("date"))
    if not frequency_id:
        raise ValueError("frequency_id обязателен")

    p = db_path(DEFAULT_DB_NAME)
    ensure_db(p)
    conn = connect(p)
    try:
        freq_data = get_aviation_frequency(conn, frequency_id=frequency_id)
        if not freq_data:
            raise ValueError("Частота не найдена")

        if work_day:
            blob = get_intercept_content_by_date(
                conn, frequency_id=frequency_id, date=work_day
            )
        else:
            intercept = get_aviation_intercept(conn, frequency_id=frequency_id)
            blob = (intercept or {}).get("content") if intercept else ""

        if not blob or not str(blob).strip():
            raise ValueError("Бланк пуст")

        callsigns_list = get_aviation_callsigns(conn, frequency_id=frequency_id)
        callsign_labels = [c["label"] for c in callsigns_list]

        report = AviationReport(
            frequency=freq_data["frequency"],
            aviation_type=freq_data["aviation_type"],
            content=str(blob),
            callsigns=callsign_labels,
        )

        safe_freq = freq_data["frequency"].replace("/", "_").replace(" ", "_")
        day_part = work_day if work_day else datetime.now().strftime("%Y-%m-%d")
        filename = f"aviation_{safe_freq}_{day_part}.docx"
    finally:
        conn.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    report.save(str(out_path))
    return {"path": str(out_path), "filename": filename, "mimetype": DOCX_MIME}
