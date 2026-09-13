"""Переиндексация семантического векторного индекса (без Flask)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import sqlite3

from web_portal.application.admin.errors import AdminUseCaseHTTP
from web_portal.config import DEFAULT_DB_NAME, db_path, safe_db_name


@dataclass(frozen=True)
class AiVectorIndexParams:
    db_name: str
    mode: str  # incremental | full
    max_intercepts: int
    max_seanses: int
    prune: bool
    intercept_limit: int | None
    seanses_limit: int | None


def _opt_int_limit(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return n


def _clamp_int(raw: Any, default: int, *, lo: int, hi: int) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = default
    return max(lo, min(n, hi))


def _as_bool(raw: Any, default: bool = True) -> bool:
    if isinstance(raw, str):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    return bool(raw)


def parse_ai_vector_index_params(raw: Mapping[str, Any]) -> AiVectorIndexParams:
    try:
        db_name = safe_db_name(str(raw.get("db") or DEFAULT_DB_NAME))
    except ValueError as e:
        raise AdminUseCaseHTTP(400, {"ok": False, "error": str(e)}) from e

    mode = str(raw.get("mode") or "incremental").strip().lower()
    if mode not in ("incremental", "full"):
        raise AdminUseCaseHTTP(
            400,
            {"ok": False, "error": "mode: incremental | full"},
        )

    return AiVectorIndexParams(
        db_name=db_name,
        mode=mode,
        max_intercepts=_clamp_int(raw.get("max_intercepts", 400), 400, lo=1, hi=100_000),
        max_seanses=_clamp_int(raw.get("max_seanses", 800), 800, lo=1, hi=200_000),
        prune=_as_bool(raw.get("prune", True), default=True),
        intercept_limit=_opt_int_limit(raw.get("intercept_limit")),
        seanses_limit=_opt_int_limit(raw.get("seanses_limit")),
    )


def resolve_ai_vector_db_path(db_name: str) -> Path:
    p = db_path(db_name)
    if not p.is_file():
        raise AdminUseCaseHTTP(
            404,
            {"ok": False, "error": f"Файл БД не найден: {p.name}"},
        )
    return p


def execute_ai_vector_index(
    conn: sqlite3.Connection,
    params: AiVectorIndexParams,
) -> dict[str, Any]:
    from web_portal.lib.ai_vector_recall import reindex_all, sync_vectors_incremental

    if params.mode == "incremental":
        result = sync_vectors_incremental(
            conn,
            max_intercepts=params.max_intercepts,
            max_seanses=params.max_seanses,
            prune=params.prune,
        )
    else:
        result = reindex_all(
            conn,
            intercept_limit=params.intercept_limit,
            seanses_limit=params.seanses_limit,
        )
    return {
        "ok": True,
        "db": params.db_name,
        "mode": params.mode,
        "result": result,
    }
