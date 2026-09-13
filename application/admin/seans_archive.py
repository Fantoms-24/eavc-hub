"""Архивация сеансов (без Flask)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import sqlite3

from web_portal.application.admin.errors import AdminUseCaseHTTP
from web_portal.config import DATA_DIR
from web_portal.lib.db import (
    archive_all_seanses_to_archive,
    archive_seanses_before_date_to_file,
    archive_seanses_outside_current_day,
)


@dataclass(frozen=True)
class ArchiveSeansesToFileParams:
    before_date: str
    archive_path: Path
    batch_size: int
    vacuum: bool
    overwrite: bool
    include_seanses_archive_table: bool


def execute_archive_seanses(
    conn: sqlite3.Connection,
    *,
    mode: str,
    batch_size: int,
    keep_date: str | None,
) -> dict[str, Any]:
    mode = str(mode or "day").strip().lower()
    batch_size = int(batch_size or 5000)
    if mode == "all":
        res = archive_all_seanses_to_archive(conn, batch_size=batch_size)
    else:
        res = archive_seanses_outside_current_day(
            conn,
            keep_date=keep_date,
            batch_size=batch_size,
        )
    return {"ok": True, **res}


def parse_archive_seanses_to_file_params(
    data: Mapping[str, Any],
) -> ArchiveSeansesToFileParams:
    before_date = str(data.get("before_date") or "").strip()[:10]
    if not before_date:
        raise AdminUseCaseHTTP(
            400,
            {
                "ok": False,
                "error": (
                    "Укажите before_date (YYYY-MM-DD) — в main останутся "
                    "сеансы с этой датой и новее"
                ),
            },
        )

    filename = str(data.get("filename") or "").strip()
    if not filename:
        filename = f"seanses_{datetime.now().strftime('%d_%m_%Y')}.sqlite"
    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename:
        raise AdminUseCaseHTTP(
            400,
            {"ok": False, "error": "Укажите только имя файла, без путей"},
        )
    if not safe_name.lower().endswith((".sqlite", ".db")):
        safe_name = f"{safe_name}.sqlite"

    archive_path = (DATA_DIR / safe_name).resolve()
    try:
        archive_path.relative_to(DATA_DIR.resolve())
    except ValueError as e:
        raise AdminUseCaseHTTP(
            400,
            {"ok": False, "error": "Недопустимый путь файла"},
        ) from e

    include_arch = data.get("include_seanses_archive")
    if include_arch is None:
        include_arch = True

    return ArchiveSeansesToFileParams(
        before_date=before_date,
        archive_path=archive_path,
        batch_size=int(data.get("batch_size") or 5000),
        vacuum=bool(data.get("vacuum")),
        overwrite=bool(data.get("overwrite")),
        include_seanses_archive_table=bool(include_arch),
    )


def execute_archive_seanses_to_file(
    params: ArchiveSeansesToFileParams,
    *,
    main_db_path: Path,
) -> dict[str, Any]:
    try:
        res = archive_seanses_before_date_to_file(
            main_db_path=main_db_path,
            archive_path=params.archive_path,
            before_date_exclusive=params.before_date,
            batch_size=params.batch_size,
            vacuum_main=params.vacuum,
            include_seanses_archive_table=params.include_seanses_archive_table,
            overwrite=params.overwrite,
        )
    except ValueError as e:
        raise AdminUseCaseHTTP(400, {"ok": False, "error": str(e)}) from e
    return {"ok": True, **res}
