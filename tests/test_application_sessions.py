"""Unit tests for application/sessions use cases."""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from web_portal.application.sessions.errors import SessionsUseCaseHTTP
from web_portal.application.sessions.export_params import (
    build_sessions_export_datetime_window,
)
from web_portal.application.sessions.favorites import execute_sessions_add_favorite
from web_portal.lib.db import (
    build_sessions_favorite_match_set,
    get_sessions_favorites,
    init_db,
    sessions_favorite_matches_row,
    sessions_row_is_favorite,
)


def test_build_sessions_export_datetime_window_explicit_dates() -> None:
    window = build_sessions_export_datetime_window(
        date_from="2030-06-01",
        time_from="08:30",
        date_to="2030-06-02",
        time_to="17:45",
    )
    assert window.date_from == "2030-06-01"
    assert window.date_to == "2030-06-02"
    assert window.datetime_from == "2030-06-01 08:30:00"
    assert window.datetime_to == "2030-06-02 17:45:59"


def test_build_sessions_export_datetime_window_defaults_to_today() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    window = build_sessions_export_datetime_window()
    assert window.date_from == today
    assert window.date_to == today
    assert window.datetime_from == f"{today} 00:00:00"
    assert window.datetime_to == f"{today} 23:59:59"


def test_build_sessions_export_datetime_window_invalid_time_falls_back() -> None:
    window = build_sessions_export_datetime_window(
        date_from="2030-01-01",
        time_from="bad",
        date_to="2030-01-02",
        time_to="also-bad",
    )
    assert window.datetime_from == "2030-01-01 00:00:00"
    assert window.datetime_to == "2030-01-02 23:59:59"


def test_sessions_favorite_match_helpers() -> None:
    fav = {"frequency": "123.450", "group": "100"}
    assert sessions_favorite_matches_row("123.456", "100", fav) is True
    assert sessions_favorite_matches_row("123.456", "200", fav) is False

    favorites = [{"frequency": "123.450", "group": "100"}]
    keys = build_sessions_favorite_match_set(favorites)
    assert sessions_row_is_favorite("123.456", "100", keys) is True
    assert sessions_row_is_favorite("124.100", "100", keys) is False


def _main_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_execute_sessions_add_favorite_pair() -> None:
    conn = _main_conn()
    payload = execute_sessions_add_favorite(
        conn, user_id=1, frequency="149.9750", group="2047519", unit_name=""
    )
    assert payload["ok"] is True
    favorites = get_sessions_favorites(conn, 1)
    assert {"frequency": "149.9750", "group": "2047519"} in favorites


def test_execute_sessions_add_favorite_requires_pair_or_unit() -> None:
    conn = _main_conn()
    with pytest.raises(SessionsUseCaseHTTP) as exc:
        execute_sessions_add_favorite(
            conn, user_id=1, frequency="", group="", unit_name=""
        )
    assert exc.value.status_code == 400
