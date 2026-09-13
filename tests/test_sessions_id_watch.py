from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from web_portal.lib.collect_seanses_from_dir import SeansEntry
from web_portal.lib.db import connect, init_db, save_seans_entries
from web_portal.lib.sessions_id_watch import (
    add_watched_correspondent_id,
    list_id_watch_alerts_since,
    list_watched_correspondent_ids,
    parse_correspondent_id_list,
    process_new_seans_for_watch,
    remove_watched_correspondent_id,
    seans_entries_not_in_database,
)


def test_parse_correspondent_id_list() -> None:
    assert parse_correspondent_id_list("1341839, 222501\n333") == [
        "1341839",
        "222501",
        "333",
    ]
    assert parse_correspondent_id_list("bad 12abc") == []


def test_id_watch_add_remove(tmp_path: Path) -> None:
    conn = connect(tmp_path / "main.sqlite")
    init_db(conn)
    assert add_watched_correspondent_id(conn, "1341839", created_by="tester")
    assert remove_watched_correspondent_id(conn, "1341839")
    items = list_watched_correspondent_ids(conn)
    assert items == []


def test_id_watch_alert_on_new_seans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "main.sqlite"
    alerts_file = tmp_path / "alerts.json"
    monkeypatch.setattr(
        "web_portal.lib.sessions_id_watch._ALERTS_PATH",
        alerts_file,
    )
    monkeypatch.setattr(
        "web_portal.lib.sessions_id_watch.db_path",
        lambda _name: db_file,
    )

    conn = connect(db_file)
    init_db(conn)
    init_db(conn)  # idempotent
    from web_portal.lib.db import init_seans_tables

    init_seans_tables(conn)
    add_watched_correspondent_id(conn, "1341839", created_by="tester")

    entry = SeansEntry(
        date_time="2026-06-15 12:49:00",
        frequency="160.8260",
        group="G1687326",
        id="1341839",
        aes_key=None,
    )
    assert seans_entries_not_in_database(conn, [entry]) == [entry]
    save_seans_entries(conn, [entry], client_name="hub", commit=True)

    payload = list_id_watch_alerts_since(0)
    assert payload["latest_seq"] == 1
    alerts = payload["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["correspondent_id"] == "1341839"
    assert alerts[0]["frequency"] == "160.8260"
    assert alerts[0]["group_"] == "G1687326"
    assert alerts[0]["date_time"] == "2026-06-15 12:49:00"

    assert seans_entries_not_in_database(conn, [entry]) == []
    save_seans_entries(conn, [entry], client_name="hub", commit=True)
    assert list_id_watch_alerts_since(1)["alerts"] == []


def test_id_watch_alert_on_save_without_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Автопоиск вызывает save_seans_entries(commit=False) — оповещение всё равно должно создаваться."""
    db_file = tmp_path / "main.sqlite"
    alerts_file = tmp_path / "alerts2.json"
    monkeypatch.setattr("web_portal.lib.sessions_id_watch._ALERTS_PATH", alerts_file)
    monkeypatch.setattr("web_portal.lib.sessions_id_watch.db_path", lambda _name: db_file)

    conn = connect(db_file)
    init_db(conn)
    from web_portal.lib.db import init_seans_tables

    init_seans_tables(conn)
    add_watched_correspondent_id(conn, "7777777", created_by="tester")
    entry = SeansEntry(
        date_time="2026-06-15 13:00:00",
        frequency="151.0000",
        group="G100",
        id="7777777",
        aes_key=None,
    )
    save_seans_entries(conn, [entry], client_name="hub", commit=False)
    conn.commit()

    payload = list_id_watch_alerts_since(0)
    assert payload["latest_seq"] == 1
    assert payload["alerts"][0]["correspondent_id"] == "7777777"
