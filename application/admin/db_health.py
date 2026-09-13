"""DB health и отчёты по сеансам (без Flask)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import sqlite3

from web_portal.application.admin.errors import AdminUseCaseHTTP
from web_portal.config import DEFAULT_DB_NAME, db_path, safe_db_name
from web_portal.lib.admin_db_health import (
    run_admin_db_health_checks,
    run_seanses_multi_channel_day_report,
)


@dataclass(frozen=True)
class DbHealthParams:
    db_name: str
    correspondent_id: str | None
    aes_followup_mode: str
    aes_followup_hours: int
    aes_after_id_hours: int


@dataclass(frozen=True)
class SeansesMultiChannelDayParams:
    db_name: str
    calendar_date: str
    only_id: str | None


def _clamp_int(raw: Any, default: int, *, lo: int, hi: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(lo, min(value, hi))


def parse_db_health_params(raw: Mapping[str, Any]) -> DbHealthParams:
    try:
        db_name = safe_db_name(str(raw.get("db") or DEFAULT_DB_NAME))
    except ValueError as e:
        raise AdminUseCaseHTTP(400, {"ok": False, "error": str(e)}) from e

    correspondent_id = str(raw.get("correspondent_id") or "").strip() or None
    aes_followup_mode = str(raw.get("aes_followup_mode") or "calendar_day").strip().lower()
    if aes_followup_mode not in ("calendar_day", "rolling"):
        aes_followup_mode = "calendar_day"

    return DbHealthParams(
        db_name=db_name,
        correspondent_id=correspondent_id,
        aes_followup_mode=aes_followup_mode,
        aes_followup_hours=_clamp_int(raw.get("aes_followup_hours"), 24, lo=1, hi=168),
        aes_after_id_hours=_clamp_int(raw.get("aes_after_id_hours"), 0, lo=0, hi=168),
    )


def parse_seanses_multi_channel_day_params(
    raw: Mapping[str, Any],
) -> SeansesMultiChannelDayParams:
    try:
        db_name = safe_db_name(str(raw.get("db") or DEFAULT_DB_NAME))
    except ValueError as e:
        raise AdminUseCaseHTTP(400, {"ok": False, "error": str(e)}) from e

    date_s = str(raw.get("date") or "").strip()[:10]
    if not date_s:
        raise AdminUseCaseHTTP(
            400,
            {"ok": False, "error": "Укажите date в формате YYYY-MM-DD"},
        )

    only_id = str(raw.get("correspondent_id") or "").strip() or None
    return SeansesMultiChannelDayParams(
        db_name=db_name,
        calendar_date=date_s,
        only_id=only_id,
    )


def resolve_main_db_path(db_name: str) -> Path:
    p = db_path(db_name)
    if not p.is_file():
        raise AdminUseCaseHTTP(
            404,
            {"ok": False, "error": f"Файл БД не найден: {p.name}"},
        )
    return p


def execute_admin_db_health(
    conn: sqlite3.Connection,
    params: DbHealthParams,
) -> dict[str, Any]:
    report = run_admin_db_health_checks(
        conn,
        correspondent_id=params.correspondent_id,
        aes_followup_mode=params.aes_followup_mode,
        aes_followup_hours=params.aes_followup_hours,
        aes_after_id_hours=params.aes_after_id_hours,
    )
    return {"ok": True, "db": params.db_name, **report}


def execute_seanses_multi_channel_day_report(
    conn: sqlite3.Connection,
    params: SeansesMultiChannelDayParams,
) -> tuple[dict[str, Any], int]:
    report = run_seanses_multi_channel_day_report(
        conn,
        calendar_date=params.calendar_date,
        only_id=params.only_id,
    )
    payload = {"db": params.db_name, **report}
    if report.get("error"):
        return {"ok": False, **payload}, 400
    return {"ok": True, **payload}, 200
