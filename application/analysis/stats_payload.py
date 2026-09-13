"""Сборка строк статистики по кодам для /api/analysis/stats."""

from __future__ import annotations

from typing import Any


def assemble_analysis_pair_stats_rows(
    counts: dict[str, int] | dict[Any, int],
    callsigns: list[dict[str, object]] | None,
    *,
    frequency: str,
    group_code: str,
) -> list[dict[str, object]]:
    """Полный список корреспондентов: seanses counts + позывные пары частота/группа."""
    frequency = str(frequency or "").strip()
    group_code = str(group_code or "").strip()
    cs_map = {str(c["code"]): c for c in (callsigns or [])}

    pair_codes: set[str] = set()
    for cs in callsigns or []:
        try:
            if (
                str(cs.get("frequency") or "").strip() == frequency
                and str(cs.get("group_code") or "").strip() == group_code
            ):
                pair_codes.add(str(cs.get("code") or "").strip())
        except Exception:
            continue

    all_codes: set[str] = set(str(c) for c in counts.keys()) | pair_codes

    def _sort_key(code: str) -> tuple[int, str]:
        cnt = int(counts.get(code, 0) or 0)
        return (-cnt, str(code))

    rows: list[dict[str, object]] = []
    for code in sorted(all_codes, key=_sort_key):
        cnt = int(counts.get(code, 0) or 0)
        cs = cs_map.get(code)
        rows.append(
            {
                "code": code,
                "count": cnt,
                "label": (cs.get("label") if cs else "") or "",
            }
        )
    return rows


def assemble_analysis_unit_stats_rows(
    counts: dict[str, int] | dict[Any, int],
    callsigns: list[dict[str, object]] | None,
) -> list[dict[str, object]]:
    cs_map = {str(c["code"]): c for c in (callsigns or [])}
    rows: list[dict[str, object]] = []
    for code, cnt in sorted(counts.items(), key=lambda x: x[1], reverse=True):
        cs = cs_map.get(str(code))
        rows.append(
            {
                "code": str(code),
                "count": int(cnt),
                "label": (cs.get("label") if cs else "") or "",
            }
        )
    return rows
