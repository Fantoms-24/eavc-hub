"""Админ-сценарии AI-агента / LLM training export (без Flask)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import sqlite3

from web_portal.lib.llm_dataset import (
    build_ai_chat_preference_hint_records,
    build_ai_chat_sft_records,
    sft_jsonl_from_records,
)


def _truthy_flag(raw: Any) -> bool:
    return str(raw or "") in ("1", "true", "yes")


def _clamp_min_len(raw: Any, default: int = 1) -> int:
    try:
        return max(1, int(raw if raw is not None else default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class LlmTrainingExportParams:
    only_rated: bool
    only_positive: bool
    min_user_len: int
    min_assistant_len: int


def parse_llm_training_export_params(raw: Mapping[str, Any]) -> LlmTrainingExportParams:
    return LlmTrainingExportParams(
        only_rated=_truthy_flag(raw.get("only_rated")),
        only_positive=_truthy_flag(raw.get("only_positive")),
        min_user_len=_clamp_min_len(raw.get("min_user_len"), 1),
        min_assistant_len=_clamp_min_len(raw.get("min_assistant_len"), 1),
    )


def execute_llm_training_export(
    conn: sqlite3.Connection,
    params: LlmTrainingExportParams,
) -> str:
    records = build_ai_chat_sft_records(
        conn,
        min_user_len=params.min_user_len,
        min_assistant_len=params.min_assistant_len,
        only_with_rating=params.only_rated,
        only_positive=params.only_positive,
    )
    return sft_jsonl_from_records(records)


def assemble_llm_training_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    all_recs = build_ai_chat_sft_records(
        conn,
        only_with_rating=False,
        only_positive=False,
    )
    pos_recs = build_ai_chat_sft_records(
        conn,
        only_with_rating=True,
        only_positive=True,
    )
    neg_hints = build_ai_chat_preference_hint_records(conn, limit=5000)
    return {
        "ok": True,
        "total_pairs": len(all_recs),
        "positive_rated_pairs": len(pos_recs),
        "negative_preference_hints": len(neg_hints),
    }


def execute_llm_preference_hints_export(
    conn: sqlite3.Connection,
    *,
    limit: int = 5000,
) -> str:
    try:
        lim = int(limit)
    except (TypeError, ValueError):
        lim = 5000
    records = build_ai_chat_preference_hint_records(conn, limit=lim)
    return sft_jsonl_from_records(records)


def assemble_ai_agent_watch_payload(
    conn: sqlite3.Connection,
    *,
    persist: bool = False,
) -> dict[str, Any]:
    from web_portal.lib.ai_agent_watch import (
        build_watch_snapshot,
        default_main_db_path,
        load_watch_state,
        save_watch_state,
    )

    snap = build_watch_snapshot(conn, default_main_db_path())
    if persist:
        save_watch_state(snap)
    return {
        "ok": True,
        "snapshot": snap,
        "persisted": load_watch_state(),
    }
