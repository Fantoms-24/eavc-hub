"""Пакет доступа к данным (SQLite).

Доменные модули (физически вынесены):

    from web_portal.lib.db.intercepts import list_intercept_catalog
    from web_portal.lib.db.connection import connect

``_impl`` — тонкий re-export для совместимости
``from web_portal.lib.db import …``.
"""
from __future__ import annotations

from . import _impl as _impl

for _name in dir(_impl):
    if _name.startswith("__"):
        continue
    globals()[_name] = getattr(_impl, _name)

__all__ = [n for n in dir(_impl) if not n.startswith("__")]
