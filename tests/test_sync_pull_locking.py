"""Pull must release main storage before writing session storage."""

import pytest

from web_portal.lib import sync_agent, seans_db
from web_portal.lib.db import connect, ensure_db


@pytest.mark.parametrize("separate", [False, True])
def test_pull_releases_main_before_session_write(tmp_path, monkeypatch, separate):
    main_path = tmp_path / "main.sqlite"
    seans_path = tmp_path / "seans.sqlite" if separate else main_path
    ensure_db(main_path)
    ensure_db(seans_path)
    monkeypatch.setattr(sync_agent, "db_path", lambda name: main_path)
    monkeypatch.setattr(sync_agent, "_http_json", lambda *a, **kw: {
        "ok": True,
        "now": "2026-09-13 12:00:00",
        "seanses": [{"date_time": "2026-09-13 11:00:00"}],
    })
    monkeypatch.setattr(seans_db, "connect_seans_storage", lambda: connect(seans_path))

    def write_sessions(conn, *, rows):
        # A watcher can need main while it owns the session writer lock.
        conn.execute("PRAGMA busy_timeout=50")
        conn.execute("BEGIN IMMEDIATE")
        probe = connect(main_path)
        try:
            probe.execute("PRAGMA busy_timeout=50")
            if separate:
                probe.execute("BEGIN IMMEDIATE")
                probe.rollback()
            conn.execute(
                "INSERT INTO seanses (date_time, frequency, group_, id, client_name) "
                "VALUES (?, '151.0000', 'G1', '123', 'pos1')",
                (rows[0]["date_time"],),
            )
            conn.commit()
        finally:
            probe.close()

    monkeypatch.setattr(sync_agent, "upsert_seanses_rows_from_sync", write_sessions)
    result = sync_agent.sync_pull_once(upstream_base="http://test", sync_key="test")
    assert "errors" not in result, result
    assert result["applied"] == 1
    conn = connect(seans_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM seanses").fetchone()[0] == 1
    finally:
        conn.close()
