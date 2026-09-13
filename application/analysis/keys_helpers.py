"""Парсинг заголовков и строк XLSX для импорта analysis_keys (без Flask)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AnalysisKeysColumnIndices:
    freq: int | None
    group: int | None
    aes_id: int | None
    aes_key: int | None
    unit: int | None
    date: int | None


def normalize_analysis_key_header(h: str) -> str:
    s = str(h or "").strip().lower()
    s = s.replace(" ", "").replace("_", "")
    s = re.sub(r"[^0-9a-zа-яё]", "", s)
    return s


def format_analysis_key_date(v: Any) -> str:
    try:
        if isinstance(v, datetime):
            return v.date().isoformat()
        if hasattr(v, "isoformat"):
            return v.isoformat()
    except Exception:
        pass
    return str(v or "").strip()


def build_analysis_keys_header_map(header_row: tuple[Any, ...] | list[Any]) -> dict[str, int]:
    return {
        normalize_analysis_key_header(h): idx for idx, h in enumerate(header_row or [])
    }


def _find_keys_col(header_map: dict[str, int], *names: str) -> int | None:
    for n in names:
        key = normalize_analysis_key_header(n)
        if key in header_map:
            return header_map[key]
    return None


def find_analysis_keys_column_indices(
    header_row: tuple[Any, ...] | list[Any],
) -> AnalysisKeysColumnIndices:
    header_map = build_analysis_keys_header_map(header_row)
    return AnalysisKeysColumnIndices(
        freq=_find_keys_col(header_map, "частота", "frequency", "freq"),
        group=_find_keys_col(header_map, "группа", "group", "gid", "groupid"),
        aes_id=_find_keys_col(header_map, "id", "aesid", "aes_id", "aes"),
        aes_key=_find_keys_col(header_map, "ключ", "key", "aeskey"),
        unit=_find_keys_col(header_map, "подразделение", "unit", "unitname"),
        date=_find_keys_col(header_map, "дата", "датаДобавления", "date", "added"),
    )


def analysis_keys_cell(
    row: tuple[Any, ...] | list[Any],
    idx: int | None,
    fallback_idx: int,
) -> Any:
    if idx is not None and idx < len(row):
        return row[idx]
    if fallback_idx < len(row):
        return row[fallback_idx]
    return None


@dataclass(frozen=True)
class AnalysisKeysImportRow:
    frequency: str
    group: str
    aes_id: str
    aes_key: str
    unit_name: str
    added_date: str


def parse_analysis_keys_import_row(
    row: tuple[Any, ...] | list[Any],
    indices: AnalysisKeysColumnIndices,
) -> AnalysisKeysImportRow | None:
    freq = str(analysis_keys_cell(row, indices.freq, 0) or "").strip()
    group = str(analysis_keys_cell(row, indices.group, 1) or "").strip()
    aes_id = str(analysis_keys_cell(row, indices.aes_id, 2) or "").strip()
    aes_key = str(analysis_keys_cell(row, indices.aes_key, 3) or "").strip()
    if not freq or not group or not aes_id or not aes_key:
        return None
    unit_name = str(analysis_keys_cell(row, indices.unit, 4) or "").strip()
    added_date = format_analysis_key_date(analysis_keys_cell(row, indices.date, 5))
    return AnalysisKeysImportRow(
        frequency=freq,
        group=group,
        aes_id=aes_id,
        aes_key=aes_key,
        unit_name=unit_name,
        added_date=added_date,
    )
