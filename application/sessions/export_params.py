"""Парсинг окна даты/времени для экспорта и таблицы сеансов."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SessionsExportWindow:
    date_from: str
    date_to: str
    datetime_from: str
    datetime_to: str


def build_sessions_export_datetime_window(
    *,
    date_from: str = "",
    time_from: str = "00:00",
    date_to: str = "",
    time_to: str = "23:59",
) -> SessionsExportWindow:
    """Строит date_from/date_to и datetime_from/datetime_to из полей запроса."""
    date_from = str(date_from or "").strip()
    date_to = str(date_to or "").strip()
    time_from = str(time_from or "00:00").strip() or "00:00"
    time_to = str(time_to or "23:59").strip() or "23:59"

    if not date_from or not date_to:
        today = datetime.now().strftime("%Y-%m-%d")
        date_from = date_from or today
        date_to = date_to or today

    try:
        datetime_from = f"{date_from} {time_from}:00"
        datetime_to = f"{date_to} {time_to}:59"
        datetime.strptime(datetime_from, "%Y-%m-%d %H:%M:%S")
        datetime.strptime(datetime_to, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        datetime_from = f"{date_from} 00:00:00"
        datetime_to = f"{date_to} 23:59:59"

    return SessionsExportWindow(
        date_from=date_from,
        date_to=date_to,
        datetime_from=datetime_from,
        datetime_to=datetime_to,
    )
