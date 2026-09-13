"""Границы периода анализа (календарь / rolling days) без Flask request."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, time as dtime_cls, timezone
from typing import Any


@dataclass(frozen=True)
class AnalysisPeriodBounds:
    start_naive: datetime
    end_naive: datetime
    meta: dict[str, object]


def msk_now_naive() -> datetime:
    return datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)


def fmt_analysis_dt(d: datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S")


def parse_analysis_datetime(s: str) -> datetime | None:
    if not s:
        return None
    raw = str(s).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", ""))
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            continue
    return None


def parse_msk_date_yyyy_mm_dd(s: str):
    raw = str(s or "").strip()[:10]
    if len(raw) != 10:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except Exception:
        return None


def build_analysis_period_bounds(
    *,
    period_start: str = "",
    period_end: str = "",
    days: str = "1",
) -> AnalysisPeriodBounds | None:
    """
    Совместимость:
    - По умолчанию: последние N суток от текущего момента МСК (days=1|3|7).
    - Календарь: period_start [, period_end] — границы календарных суток МСК,
      конец включающе до 23:59:59.
    """
    ps = str(period_start or "").strip()
    pe = str(period_end or "").strip()
    if ps:
        d1 = parse_msk_date_yyyy_mm_dd(ps)
        if not d1:
            return None
        d2 = parse_msk_date_yyyy_mm_dd(pe) if pe else d1
        if not d2:
            return None
        if d2 < d1:
            d1, d2 = d2, d1
        inclusive = (d2 - d1).days + 1
        if inclusive > 400:
            return None
        start_naive = datetime.combine(d1, dtime_cls.min)
        end_naive = datetime.combine(d2, dtime_cls(23, 59, 59))
        period_key = f"c:{d1.isoformat()}:{d2.isoformat()}"
        meta: dict[str, Any] = {
            "period_mode": "calendar",
            "preset_days": None,
            "days_metric": inclusive,
            "period_start_day": d1.isoformat(),
            "period_end_day": d2.isoformat(),
            "period_key": period_key,
        }
        return AnalysisPeriodBounds(start_naive, end_naive, meta)
    try:
        di = int(str(days or "1"))
    except (TypeError, ValueError):
        di = 1
    di = di if di in (1, 3, 7) else 1
    end = msk_now_naive()
    start = end - timedelta(days=di)
    meta = {
        "period_mode": "rolling",
        "preset_days": di,
        "days_metric": di,
        "period_start_day": None,
        "period_end_day": None,
        "period_key": f"r:{di}",
    }
    return AnalysisPeriodBounds(start, end, meta)
