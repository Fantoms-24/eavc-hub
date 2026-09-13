"""Параметры полного отчёта анализа (без Flask)."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from web_portal.application.analysis.errors import AnalysisUseCaseHTTP


@dataclass(frozen=True)
class FullReportPeriod:
    start_s: str
    end_s: str
    report_month: str


def resolve_full_report_period(raw: Mapping[str, Any]) -> FullReportPeriod:
    report_month = str(raw.get("report_month") or "").strip()
    start_s = str(raw.get("start") or "").strip()
    end_s = str(raw.get("end") or "").strip()

    if report_month:
        try:
            month_dt = datetime.strptime(report_month[:7], "%Y-%m")
        except ValueError as e:
            raise AnalysisUseCaseHTTP(
                400,
                {
                    "ok": False,
                    "error": "report_month должен быть в формате YYYY-MM",
                },
            ) from e
        next_month = (
            datetime(month_dt.year + 1, 1, 1)
            if month_dt.month == 12
            else datetime(month_dt.year, month_dt.month + 1, 1)
        )
        start_s = month_dt.strftime("%Y-%m-01 00:00:00")
        end_s = (next_month - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
    elif not start_s or not end_s:
        now = datetime.now()
        month_dt = datetime(now.year, now.month, 1)
        next_month = (
            datetime(month_dt.year + 1, 1, 1)
            if month_dt.month == 12
            else datetime(month_dt.year, month_dt.month + 1, 1)
        )
        report_month = month_dt.strftime("%Y-%m")
        start_s = month_dt.strftime("%Y-%m-01 00:00:00")
        end_s = (next_month - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
    else:
        if len(start_s) == 10:
            start_s += " 00:00:00"
        if len(end_s) == 10:
            end_s += " 23:59:59"

    return FullReportPeriod(
        start_s=start_s,
        end_s=end_s,
        report_month=report_month,
    )


def build_full_report_job_params(
    raw: Mapping[str, Any],
    *,
    position_key: str,
    user_id: int,
    period: FullReportPeriod,
) -> dict[str, Any]:
    return {
        "position_name": position_key,
        "user_id": int(user_id),
        "start": period.start_s,
        "end": period.end_s,
        "report_month": period.report_month,
        "days": raw.get("days"),
        "minutes": raw.get("minutes"),
        "unit_name": raw.get("unit_name")
        or raw.get("unit_query")
        or raw.get("units_only")
        or "",
        "unit_query": raw.get("unit_query") or "",
        "frequency": raw.get("frequency") or "",
        "group": raw.get("group") or raw.get("group_code") or "",
        "group_query": raw.get("group_query") or "",
        "include_other": bool(raw.get("include_other", True)),
        "min_weight": raw.get("min_weight"),
        "cluster_by": raw.get("cluster_by") or "",
        "mode": raw.get("mode") or "",
    }


def save_full_report_graph_png(
    graph_png_base64: str,
    *,
    export_dir: Path,
    job_id: int,
) -> str | None:
    """Сохраняет PNG графа для job; возвращает путь или None."""
    graph_png_raw = str(graph_png_base64 or "").strip()
    if not graph_png_raw:
        return None
    if "," in graph_png_raw:
        graph_png_raw = graph_png_raw.split(",", 1)[1]
    try:
        png_bytes = base64.b64decode(graph_png_raw, validate=False)
        if not png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return None
        png_path = export_dir / f"job_{job_id}_graph.png"
        png_path.write_bytes(png_bytes)
        return str(png_path)
    except Exception:
        return None
