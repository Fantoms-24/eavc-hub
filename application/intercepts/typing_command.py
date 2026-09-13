"""POST /api/intercepts/typing — in-memory статус набора текста."""

from __future__ import annotations

from collections.abc import Callable
import re
from typing import Any

from web_portal.application.intercepts.errors import InterceptsUseCaseHTTP


TypingStore = dict[tuple[str, int, int], dict[str, dict[str, Any]]]


def execute_intercepts_typing(
    *,
    typing_store: TypingStore,
    typing_cleanup: Callable[[float], None],
    now_ts: float,
    position_name: str,
    username: str,
    session_id: int,
    catalog_id: int,
    is_typing: bool,
    time_header: str,
) -> dict[str, Any]:
    if not session_id or not catalog_id:
        raise InterceptsUseCaseHTTP(
            400, {"ok": False, "error": "session_id и catalog_id обязательны"}
        )
    typing_cleanup(now_ts)
    key = (str(position_name).strip(), int(session_id), int(catalog_id))
    m: dict[str, dict[str, Any]] = typing_store.get(key, {}) or {}
    if is_typing:
        u = str(username)
        prev = m.get(u, {}) or {}
        prev_th = str(prev.get("time_header") or "").strip()
        th = str(time_header or "").strip()
        try:
            th = th.replace(":", ".")
            if not re.match(r"^\d{1,2}\.\d{2}$", th):
                th = ""
        except Exception:
            th = ""
        m[u] = {"ts": now_ts, "time_header": th or prev_th}
        typing_store[key] = m
    else:
        m.pop(str(username), None)
        if m:
            typing_store[key] = m
        else:
            typing_store.pop(key, None)
    return {"ok": True}
