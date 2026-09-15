"""File-backed regressions for independent hub delivery state."""

from contextlib import closing
import sqlite3
import threading

import pytest

from web_portal.lib import seans_db, sync_agent
from web_portal.lib.db import connect, ensure_db, enqueue_sync_outbox
from web_portal.lib.sync_delivery import load_cursor, pending_delivery, read_source, save_cursors


@pytest.fixture
def source(tmp_path, monkeypatch):
    path = tmp_path / "main.sqlite"
    ensure_db(path)
    monkeypatch.setattr(sync_agent, "db_path", lambda name: path)
    monkeypatch.setattr(sync_agent, "session_source", lambda: path)
    monkeypatch.setattr(sync_agent, "search_online_db_path", lambda: path)
    with closing(connect(path)) as conn:
        conn.execute("INSERT INTO seanses (date_time, frequency, group_, id) VALUES ('2026-09-13 11:00:00','151','G1','123')")
        conn.execute("INSERT INTO unit (frequency, group_, name) VALUES ('151','G1','unit1')")
        conn.execute("INSERT INTO online_search (frequency, group_id, updated_at) VALUES ('151','G1','2026-09-13 11:00:00')")
        enqueue_sync_outbox(conn, kind="intercepts:item", payload={"uuid": "item1"})
    return path


@pytest.mark.parametrize("sender", [
    "sync_push_once", "sync_push_priority_once", "sync_push_seanses_once",
    "sync_push_online_search_once", "sync_push_unit_once",
])
def test_sender_succeeds_while_watcher_owns_writer(source, monkeypatch, sender):
    # The old sender tried source DDL/receipt updates and failed on this lock.
    writer = connect(source)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("UPDATE unit SET name='not committed'")
    monkeypatch.setattr(sync_agent, "_http_json", lambda *a, **kw: {"ok": True})
    try:
        result = getattr(sync_agent, sender)(upstream_base="http://test", sync_key="test")
        assert result["ok"] is True
        assert result["sent"] == 1
    finally:
        writer.rollback()
        writer.close()
    with read_source(source) as conn:
        assert conn.execute("SELECT sent_at FROM sync_outbox").fetchone()[0] is None
        assert conn.execute("SELECT COUNT(*) FROM sync_meta").fetchone()[0] == 0


@pytest.mark.parametrize("sender", [
    "sync_push_once", "sync_push_seanses_once", "sync_push_online_search_once", "sync_push_unit_once",
])
def test_source_is_closed_while_network_is_waiting(source, monkeypatch, sender):
    with closing(connect(source)) as conn:
        conn.execute("PRAGMA journal_mode=DELETE")
    entered = threading.Event()
    release = threading.Event()
    results = []

    def slow_http(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return {"ok": True}

    monkeypatch.setattr(sync_agent, "_http_json", slow_http)
    thread = threading.Thread(target=lambda: results.append(
        getattr(sync_agent, sender)(upstream_base="http://test", sync_key="test")))
    thread.start()
    try:
        assert entered.wait(3)
        writer = sqlite3.connect(str(source), timeout=0.1)
        try:
            writer.execute("BEGIN EXCLUSIVE")
            writer.execute("UPDATE unit SET name='still working'")
            writer.commit()
        finally:
            writer.close()
    finally:
        release.set()
        thread.join(3)
    assert results[0]["sent"] == 1


def test_failed_delivery_retries_and_success_is_remembered(source, monkeypatch):
    responses = iter([{"ok": False, "error": "offline"}, {"ok": True}])
    monkeypatch.setattr(sync_agent, "_http_json", lambda *a, **kw: next(responses))
    kwargs = {"upstream_base": "http://test", "sync_key": "test"}
    assert sync_agent.sync_push_once(**kwargs)["ok"] is False
    pending = pending_delivery(source)
    assert pending[0]["attempts"] == 1
    assert pending[0]["last_error"] == "offline"
    assert sync_agent.sync_push_once(**kwargs)["sent"] == 1
    assert sync_agent.sync_push_priority_once(**kwargs)["sent"] == 0
    assert pending_delivery(source) == []


def test_legacy_cursor_fallback_and_separate_atomic_update(source):
    with closing(connect(source)) as conn:
        conn.execute("INSERT INTO sync_meta VALUES ('unit_last_rowid', '17')")
        conn.commit()
    assert load_cursor(source, "unit_last_rowid") == "17"
    save_cursors(source, {"unit_last_rowid": "18", "online_search_last_id": "4"})
    assert load_cursor(source, "unit_last_rowid") == "18"
    with read_source(source) as conn:
        assert conn.execute("SELECT value FROM sync_meta WHERE key='unit_last_rowid'").fetchone()[0] == "17"


def test_bulk_failure_does_not_advance_cursor(source, monkeypatch):
    monkeypatch.setattr(sync_agent, "_http_json", lambda *a, **kw: {"ok": False, "error": "offline"})
    assert sync_agent.sync_push_seanses_once(upstream_base="http://test", sync_key="test")["ok"] is False
    assert load_cursor(source, "seanses_last_rowid") == ""


def test_unit_full_reconciliation_recovers_rows_after_incremental_cursor(source, monkeypatch):
    """Повторная сверка восстанавливает привязки на очищенном SERVER."""
    delivered = []
    monkeypatch.setattr(
        sync_agent,
        "_http_json",
        lambda _method, _url, *, body, **_kw: delivered.append(body) or {"ok": True},
    )
    # Имитируем HUB, который уже отправил инкрементальную строку раньше.
    save_cursors(source, {"unit_last_rowid": "1"})

    result = sync_agent.sync_push_unit_once(
        upstream_base="http://test", sync_key="test"
    )

    assert result["full"] is True
    assert result["sent"] == 1
    event = delivered[0]["events"][0]
    assert event["kind"] == "unit:batch"
    assert event["payload"]["rows"][0]["name"] == "unit1"


@pytest.mark.parametrize("sender, table", [
    ("sync_push_seanses_once", "seanses"),
    ("sync_push_unit_once", "unit"),
    ("sync_push_online_search_once", "online_search"),
])
def test_server_route_accepts_sender_payload(source, tmp_path, monkeypatch, sender, table):
    from flask import Flask
    from web_portal.webapp.context import AppContext
    from web_portal.webapp.routes import sync_api
    from web_portal.lib import sync_push_apply

    server = tmp_path / "server.sqlite"
    ensure_db(server)
    monkeypatch.setattr(sync_api, "db_path", lambda name: server)
    monkeypatch.setattr(sync_api, "connect_portal", lambda path: sqlite3.connect(":memory:"))
    monkeypatch.setattr(sync_api, "update_hub_activity", lambda *a, **kw: None)
    monkeypatch.setattr(seans_db, "connect_seans_storage", lambda: connect(server))
    monkeypatch.setattr(sync_push_apply, "search_online_db_path", lambda: server)
    app = Flask(__name__)
    sync_api.register_sync_routes(app, AppContext(base_dir=tmp_path, sync_key="test", sync_upstream=""))

    def deliver(method, url, *, headers, body, **kwargs):
        with app.test_client() as client:
            response = client.post("/api/sync/push", headers=headers, json=body)
            assert response.status_code == 200
            result = response.get_json()
            assert "errors" not in result, result
            return result

    monkeypatch.setattr(sync_agent, "_http_json", deliver)
    result = getattr(sync_agent, sender)(upstream_base="http://test", sync_key="test")
    assert result["sent"] == 1
    with read_source(server) as conn:
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1


def test_hub_diagnostics_use_delivery_receipts(source, monkeypatch):
    from web_portal.application.admin.sync_status import assemble_admin_sync_status_payload
    from web_portal.lib import sync_delivery

    monkeypatch.setattr(sync_agent, "_http_json", lambda *a, **kw: {"ok": True})
    monkeypatch.setattr(sync_delivery, "session_source", lambda: source)
    sync_agent.sync_push_once(upstream_base="http://test", sync_key="test")
    sync_agent.sync_push_unit_once(upstream_base="http://test", sync_key="test")
    with read_source(source) as conn:
        result = assemble_admin_sync_status_payload(
            conn, now_ts="2026-09-13 12:00:00", sync_upstream="http://test", sync_key="test")
    assert result["outbox_pending"] == 0
    assert result["meta"]["unit_last_rowid"] == "1"


@pytest.mark.parametrize("is_hub", [True, False])
def test_status_route_reads_hub_receipts_only_on_hub(source, tmp_path, monkeypatch, is_hub):
    from flask import Flask
    from web_portal.webapp.context import AppContext
    from web_portal.webapp.routes import sync_api
    from web_portal.lib import sync_delivery

    monkeypatch.setattr(sync_agent, "_http_json", lambda *a, **kw: {"ok": True})
    monkeypatch.setattr(sync_delivery, "session_source", lambda: source)
    monkeypatch.setattr(sync_api, "db_path", lambda name: source)
    sync_agent.sync_push_once(upstream_base="http://test", sync_key="test")
    sync_agent.sync_push_unit_once(upstream_base="http://test", sync_key="test")
    app = Flask(__name__)
    sync_api.register_sync_routes(app, AppContext(
        base_dir=tmp_path, sync_key="test", sync_upstream="http://test" if is_hub else ""))
    with app.test_client() as client:
        response = client.get("/api/sync/status", headers={"X-Sync-Key": "test"})
    assert response.status_code == 200
    result = response.get_json()
    assert result["outbox_pending"] == (0 if is_hub else 1)
    assert result["meta"]["unit_last_rowid"] == ("1" if is_hub else "")


def test_network_exception_leaves_outbox_pending(source, monkeypatch):
    def disconnected(*args, **kwargs):
        raise RuntimeError("connection lost")

    monkeypatch.setattr(sync_agent, "_http_json", disconnected)
    with pytest.raises(RuntimeError, match="connection lost"):
        sync_agent.sync_push_once(upstream_base="http://test", sync_key="test")
    assert len(pending_delivery(source)) == 1


@pytest.mark.parametrize("separate_has_rows, main_has_rows, expected", [
    (True, True, "separate"), (False, True, "main"), (False, False, "separate"),
])
def test_session_source_preserves_fallback(tmp_path, monkeypatch, separate_has_rows, main_has_rows, expected):
    from web_portal.lib.sync_delivery import session_source

    main = tmp_path / "main.sqlite"
    separate = tmp_path / "seans.sqlite"
    for path, has_rows in ((main, main_has_rows), (separate, separate_has_rows)):
        ensure_db(path)
        if has_rows:
            with closing(connect(path)) as conn:
                conn.execute("INSERT INTO seanses (date_time, frequency, group_, id) VALUES ('2026-09-13','151','G1','123')")
                conn.commit()
    monkeypatch.setattr(seans_db, "db_path", lambda name: main)
    monkeypatch.setattr(seans_db, "seans_db_path", lambda: separate)
    monkeypatch.setattr(seans_db, "use_separate_seans_db", lambda: True)
    assert session_source() == (main if expected == "main" else separate)
