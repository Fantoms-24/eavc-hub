"""Снимок TTL-кэшей для /api/admin/perf-metrics (без Flask)."""

from __future__ import annotations

from typing import Any


def assemble_admin_perf_caches() -> dict[str, Any]:
    """Размеры всех TTL-кэшей (для диагностики «прогрева»)."""
    try:
        from web_portal.app_runtime_caches import (
            _ANALYSIS_RESP_CACHE,
            _ANALYSIS_RESP_CACHE_TTL_SEC,
            _ASSIGNMENTS_CACHE,
            _ASSIGNMENTS_CACHE_TTL_SEC,
            _CALLSIGNS_CACHE,
            _CALLSIGNS_CACHE_TTL_SEC,
            _DOC_STATS_CACHE,
            _DOC_STATS_CACHE_TTL_SEC,
            _INTERCEPTS_STATE_CACHE,
            _INTERCEPTS_STATE_CACHE_TTL_SEC,
            _UNITS_TREE_CACHE,
            _UNITS_TREE_CACHE_TTL_SEC,
        )

        return {
            "analysis": {
                "size": len(_ANALYSIS_RESP_CACHE),
                "ttl_sec": _ANALYSIS_RESP_CACHE_TTL_SEC,
            },
            "intercepts_state": {
                "size": len(_INTERCEPTS_STATE_CACHE),
                "ttl_sec": _INTERCEPTS_STATE_CACHE_TTL_SEC,
            },
            "doc_stats": {
                "size": len(_DOC_STATS_CACHE),
                "ttl_sec": _DOC_STATS_CACHE_TTL_SEC,
            },
            "callsigns": {
                "size": len(_CALLSIGNS_CACHE),
                "ttl_sec": _CALLSIGNS_CACHE_TTL_SEC,
            },
            "units_tree": {
                "size": len(_UNITS_TREE_CACHE),
                "ttl_sec": _UNITS_TREE_CACHE_TTL_SEC,
            },
            "assignments": {
                "size": len(_ASSIGNMENTS_CACHE),
                "ttl_sec": _ASSIGNMENTS_CACHE_TTL_SEC,
            },
        }
    except Exception:
        return {}
