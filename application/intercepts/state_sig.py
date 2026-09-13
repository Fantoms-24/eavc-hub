"""Сигнатура состояния перехватов — совместима с `intercepts.js` (poll / unchanged)."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _catalog_prefs_fingerprint(prefs: Any) -> str:
    if not isinstance(prefs, dict):
        return ""
    try:
        raw = json.dumps(
            {
                "favorites": prefs.get("favorites") or [],
                "archived": prefs.get("archived") or [],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    except Exception:
        return ""
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def compute_intercepts_state_sig(payload: dict[str, Any]) -> str:
    """
    Строка ревизии для `/api/intercepts/state`.
    Должна совпадать с `_stateSig()` в static/js/intercepts.js.
    """
    cat = payload.get("catalog") if isinstance(payload.get("catalog"), list) else []
    cs = payload.get("callsigns") if isinstance(payload.get("callsigns"), list) else []
    sess = payload.get("sessions") if isinstance(payload.get("sessions"), list) else []

    cat_max = ""
    for c in cat:
        if not isinstance(c, dict):
            continue
        v = str(c.get("updated_at") or "")
        if v > cat_max:
            cat_max = v

    cs_max = ""
    for c in cs:
        if not isinstance(c, dict):
            continue
        v = str(c.get("updated_at") or "")
        if v > cs_max:
            cs_max = v

    sess_max = ""
    for s in sess:
        if not isinstance(s, dict):
            continue
        a = str(s.get("started_at") or "")
        b = str(s.get("ended_at") or "")
        if a > sess_max:
            sess_max = a
        if b > sess_max:
            sess_max = b

    selected = payload.get("selected_session") or payload.get("current_session")
    sid = str((selected or {}).get("id") or 0) if isinstance(selected, dict) else "0"
    assignments = payload.get("assignments") if isinstance(payload.get("assignments"), dict) else {}
    duty = str(assignments.get("duty") or "")
    prefs_fp = _catalog_prefs_fingerprint(payload.get("catalog_prefs"))
    unit_order = payload.get("unit_order") if isinstance(payload.get("unit_order"), list) else []
    unit_order_fp = hashlib.sha1(
        json.dumps(unit_order, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:8]
    items_max = str(payload.get("items_max_updated_at") or "")

    return (
        f"{len(cat)}|{cat_max}|{len(cs)}|{cs_max}|{len(sess)}|{sess_max}|"
        f"{sid}|{duty}|{prefs_fp}|{unit_order_fp}|{items_max}"
    )


def attach_intercepts_state_sig(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out["state_sig"] = compute_intercepts_state_sig(out)
    return out


def compute_intercept_item_content_sig(updated_at: str, content: str) -> str:
    """Совместимо с `_contentSig()` в static/js/intercepts.js."""
    c = str(content or "")
    head = c[:64]
    tail = c[-64:] if len(c) > 64 else c
    return f"{str(updated_at or '')}|{len(c)}|{head}|{tail}"


def normalize_intercept_item_content_sig(value: str) -> str:
    """
    Приводит подпись к сравнимому виду.

    В подпись входит хвост содержимого, а бланк почти всегда заканчивается
    переводом строки. Значит подпись оканчивается пробельным символом, который
    теряется при передаче и разборе. Сравнивать можно только одинаково
    нормализованные подписи, иначе `unchanged` не срабатывает никогда.
    Длина содержимого входит в подпись отдельным полем, поэтому обрезка
    пробелов не может выдать разное содержимое за одинаковое.
    """
    return str(value or "").strip()
