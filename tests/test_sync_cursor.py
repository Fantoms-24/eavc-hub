from __future__ import annotations

from web_portal.lib.sync_agent import _next_pull_cursor


def test_completed_pull_uses_small_overlap_not_full_history() -> None:
    cursor = _next_pull_cursor(
        {
            "now": "2026-09-13 12:00:10",
            "pagination": {
                "seanses_truncated": False,
                "unit_rows_truncated": False,
                "online_search_truncated": False,
            },
        },
        "2026-09-13 11:00:00",
        "2026-09-13 11:59:59",
    )
    assert cursor == "2026-09-13 12:00:08"


def test_limited_initial_pull_keeps_timestamp_pagination() -> None:
    cursor = _next_pull_cursor(
        {
            "now": "2026-09-13 12:00:10",
            "pagination": {"seanses_truncated": True},
        },
        "1970-01-01 00:00:00",
        "2026-09-13 11:59:59",
    )
    assert cursor == "2026-09-13 11:59:59"


def test_old_server_response_keeps_legacy_safe_cursor() -> None:
    assert (
        _next_pull_cursor(
            {"now": "2026-09-13 12:00:10"},
            "2026-09-13 11:00:00",
            "2026-09-13 11:59:59",
        )
        == "2026-09-13 11:59:59"
    )
