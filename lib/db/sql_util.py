"""Мелкие SQL-хелперы (общие для доменов)."""
from __future__ import annotations

import sqlite3


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        cols = conn.execute(f"PRAGMA table_info({table});").fetchall()
        out: set[str] = set()
        for c in cols or []:
            # sqlite row: (cid, name, type, notnull, dflt_value, pk)
            name = c[1] if isinstance(c, (tuple, list)) else c["name"]
            out.add(str(name))
        return out
    except Exception:
        return set()


def _pick_first(cols: set[str], candidates: list[str]) -> str | None:
    for c in candidates:
        if c in cols:
            return c
    return None


def _normalize_positions(positions) -> list[str]:
    if not positions:
        return []
    if isinstance(positions, str):
        raw = positions
    else:
        raw = ",".join([str(x) for x in positions if x is not None])
    parts = [str(x).strip() for x in raw.split(",")]
    return [p for p in parts if p]


def _in_clause(field: str, values: list[str]) -> tuple[str, list[str]]:
    vals = _normalize_positions(values)
    if not vals:
        return "", []
    placeholders = ",".join(["?"] * len(vals))
    return f" AND {field} IN ({placeholders})", vals


__all__ = [
    "_table_columns",
    "_pick_first",
    "_normalize_positions",
    "_in_clause",
]
