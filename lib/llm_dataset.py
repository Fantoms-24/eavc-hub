"""Датасеты для дообучения LLM (EAVC Manager) из портальной БД."""

from __future__ import annotations

import json
from typing import Any

from web_portal.lib.auth_db import (
    CHAT_CHANNEL_AI_ASSISTANT,
    ensure_ai_assistant_user,
    ensure_chat_group,
    init_portal_db,
)


def build_ai_chat_sft_records(
    conn,
    *,
    min_user_len: int = 1,
    min_assistant_len: int = 1,
    only_with_rating: bool = False,
    only_positive: bool = False,
) -> list[dict[str, Any]]:
    """
    Пары «вопрос пользователя → ответ EAVC Manager» из канала ai_assistant (по порядку id).

    only_with_rating: только пары, где на ответ есть оценка хотя бы от одного пользователя
    (в запись кладётся агрегат: median-style невозможен без user — см. all_ratings).
    only_positive: только оценка +1 (если нет оценок — отбрасывается).
    """
    init_portal_db(conn)
    ai_uid = ensure_ai_assistant_user(conn)
    gid = ensure_chat_group(conn, name=CHAT_CHANNEL_AI_ASSISTANT)
    rows = conn.execute(
        """
        SELECT m.id, m.user_id, m.message_text
        FROM chat_messages m
        WHERE m.group_id = ?
        ORDER BY m.id ASC
        """,
        (int(gid),),
    ).fetchall()

    prev_user: tuple[int, str] | None = None
    raw_pairs: list[dict[str, Any]] = []
    for r in rows:
        uid = int(r["user_id"])
        text = str(r["message_text"] or "").strip()
        if uid == ai_uid:
            if prev_user is None or not text:
                prev_user = None
                continue
            pu, pt = prev_user
            if len(pt) >= min_user_len and len(text) >= min_assistant_len:
                raw_pairs.append(
                    {
                        "user_id": pu,
                        "assistant_message_id": int(r["id"]),
                        "user": pt,
                        "assistant": text,
                    }
                )
            prev_user = None
        else:
            prev_user = (uid, text)

    if not raw_pairs:
        return []

    msg_ids = [p["assistant_message_id"] for p in raw_pairs]
    fb_rows = conn.execute(
        f"""
        SELECT user_id, message_id, rating, comment, updated_at
        FROM ai_chat_message_feedback
        WHERE message_id IN ({",".join("?" * len(msg_ids))})
        """,
        tuple(msg_ids),
    ).fetchall()
    by_msg: dict[int, list[dict[str, Any]]] = {}
    for fr in fb_rows or []:
        mid = int(fr["message_id"])
        by_msg.setdefault(mid, []).append(
            {
                "user_id": int(fr["user_id"]),
                "rating": int(fr["rating"]),
                "comment": str(fr["comment"] or "")[:2000],
                "updated_at": str(fr["updated_at"] or ""),
            }
        )

    out: list[dict[str, Any]] = []
    for p in raw_pairs:
        mid = p["assistant_message_id"]
        ratings = by_msg.get(mid) or []
        if only_with_rating and not ratings:
            continue
        if only_positive:
            if not ratings or not any(x["rating"] == 1 for x in ratings):
                continue
        rec: dict[str, Any] = {
            "messages": [
                {"role": "user", "content": p["user"]},
                {"role": "assistant", "content": p["assistant"]},
            ],
            "metadata": {
                "assistant_message_id": mid,
                "user_author_id": p["user_id"],
            },
        }
        if ratings:
            up = sum(1 for x in ratings if x["rating"] == 1)
            down = sum(1 for x in ratings if x["rating"] == -1)
            rec["metadata"]["ratings"] = {
                "count": len(ratings),
                "thumbs_up": up,
                "thumbs_down": down,
            }
            rec["metadata"]["all_ratings"] = ratings
        out.append(rec)
    return out


def sft_jsonl_from_records(records: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + (
        "\n" if records else ""
    )


def build_ai_chat_preference_hint_records(
    conn,
    *,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    """
    Примеры с thumbs down (+ опционально комментарий и следующее сообщение пользователя)
    для DPO/парного дообучения вне портала.
    """
    init_portal_db(conn)
    ai_uid = ensure_ai_assistant_user(conn)
    gid = ensure_chat_group(conn, name=CHAT_CHANNEL_AI_ASSISTANT)
    rows = conn.execute(
        """
        SELECT id, user_id, message_text
        FROM chat_messages
        WHERE group_id = ?
        ORDER BY id ASC
        """,
        (int(gid),),
    ).fetchall()
    ordered: list[tuple[int, int, str]] = [
        (int(r["id"]), int(r["user_id"]), str(r["message_text"] or "")) for r in rows
    ]
    prev_user_by_ai: dict[int, str] = {}
    next_user_by_ai: dict[int, str] = {}
    for i, (mid, uid, text) in enumerate(ordered):
        if uid == ai_uid and i > 0:
            pmid, puid, ptxt = ordered[i - 1]
            if puid != ai_uid and str(ptxt).strip():
                prev_user_by_ai[mid] = str(ptxt).strip()
        if uid == ai_uid and i + 1 < len(ordered):
            _, nuid, ntxt = ordered[i + 1]
            if nuid != ai_uid and str(ntxt).strip():
                next_user_by_ai[mid] = str(ntxt).strip()

    neg = conn.execute(
        """
        SELECT user_id, message_id, rating, comment, updated_at
        FROM ai_chat_message_feedback
        WHERE rating = -1
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (max(1, min(int(limit), 10000)),),
    ).fetchall()
    ai_text: dict[int, str] = {}
    for mid, uid, text in ordered:
        if uid == ai_uid:
            ai_text[int(mid)] = str(text or "").strip()

    out: list[dict[str, Any]] = []
    for r in neg or []:
        mid = int(r["message_id"])
        assist = ai_text.get(mid, "")
        if not assist:
            continue
        up = prev_user_by_ai.get(mid, "")
        if not up:
            continue
        cmt = str(r["comment"] or "").strip()[:2000]
        rec = {
            "type": "preference_hint",
            "user_prompt": up,
            "assistant_rejected": assist,
            "rater_user_id": int(r["user_id"]),
            "rater_comment": cmt,
            "user_followup": next_user_by_ai.get(mid) or None,
            "metadata": {
                "assistant_message_id": mid,
                "updated_at": str(r["updated_at"] or ""),
            },
        }
        out.append(rec)
    return out
