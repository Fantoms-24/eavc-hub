"""Фильтры поиска онлайн (семьи/юниты по строке запроса), вынесены из app.py."""

from __future__ import annotations


def _os_loose_sub(s: str) -> str:
    t = (s or "").lower()
    for ch in '"\'«»':
        t = t.replace(ch, "")
    return " ".join(t.split())


def _filter_os_families_by_q(families, q: str | None) -> list:
    """Семьи, у которых запрос встречается в названии или в дочерних note (подстрока или все слова)."""
    if not (q or "").strip():
        return list(families or [])
    qq = _os_loose_sub(q)
    if not qq:
        return list(families or [])
    words = [w for w in qq.split() if w]

    def _fam_blob(fam) -> str:
        parts = [
            _os_loose_sub(str(fam.get("parent_label") or "")),
            _os_loose_sub(str(fam.get("parent_key") or "")),
        ]
        for ch in fam.get("children") or []:
            parts.append(_os_loose_sub(str(ch.get("unit_key") or "")))
            parts.append(_os_loose_sub(str(ch.get("label") or "")))
        return " \n ".join(p for p in parts if p)

    def _matches(blob: str) -> bool:
        if qq in blob:
            return True
        if not words:
            return True
        return all(w in blob for w in words)

    out = []
    for fam in families or []:
        if _matches(_fam_blob(fam)):
            out.append(fam)
    return out


def _filter_os_units_by_q(units, q: str | None) -> list:
    if not (q or "").strip():
        return list(units or [])
    qq = _os_loose_sub(q)
    if not qq:
        return list(units or [])
    words = [w for w in qq.split() if w]

    def _um(uk: str) -> bool:
        blob = _os_loose_sub(uk)
        if qq in blob:
            return True
        if not words:
            return True
        return all(w in blob for w in words)

    return [u for u in (units or []) if _um(str(u.get("unit_key") or ""))]
