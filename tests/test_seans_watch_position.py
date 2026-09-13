"""The global watcher has one explicit position per launch."""

import threading
import sqlite3
from unittest.mock import Mock

import pytest
from flask import Flask

from web_portal.webapp import seans_watch
from web_portal.lib.seans_watch_core import run_seans_watch_loop
from web_portal.lib.collect_seanses_from_dir import SeansEntry
from web_portal.lib.db.seans_write import save_seans_entries


def test_launch_passes_only_selected_position_to_child(tmp_path, monkeypatch):
    app = Flask(__name__)
    monkeypatch.setenv("WEB_PORTAL_SEANS_WATCH_SUBPROCESS", "1")
    monkeypatch.setattr(seans_watch, "seans_watch_stop_path", lambda: tmp_path / "stop")
    monkeypatch.setattr(seans_watch, "seans_watch_status_path", lambda: tmp_path / "status")
    saved = Mock()
    monkeypatch.setattr(seans_watch, "_write_seans_watch_autostart", saved)
    proc = Mock(pid=123)
    proc.poll.return_value = None
    spawn = Mock(return_value=proc)
    monkeypatch.setattr(seans_watch.subprocess, "Popen", spawn)

    assert seans_watch._launch_global_seans_watch_worker(
        app, "  Позиция Север  ", str(tmp_path), 5
    )["ok"]
    command = spawn.call_args.args[0]
    assert command[command.index("--position") + 1] == "Позиция Север"
    assert command.count("--position") == 1
    assert app.session_watchers["hub_global"]["position_name"] == "Позиция Север"
    assert saved.call_args.kwargs["position_name"] == "Позиция Север"
    assert seans_watch._launch_global_seans_watch_worker(
        app, "Позиция Север", str(tmp_path), 5
    )["noop"]
    spawn.assert_called_once()


def test_cannot_start_other_position_until_old_thread_stops(tmp_path, monkeypatch):
    app = Flask(__name__)
    old_thread = Mock()
    old_thread.is_alive.return_value = True
    stop = threading.Event()
    app.session_watchers = {"hub_global": {
        "mode": "thread", "position_name": "Север", "thread": old_thread,
        "stop": stop, "folder_path": str(tmp_path), "interval_sec": 5,
    }}
    spawn = Mock()
    monkeypatch.setattr(seans_watch.subprocess, "Popen", spawn)
    with pytest.raises(RuntimeError, match="ещё останавливается"):
        seans_watch._launch_global_seans_watch_worker(app, "Юг", str(tmp_path), 5)
    assert stop.is_set()
    spawn.assert_not_called()
    assert app.session_watchers["hub_global"]["position_name"] == "Север"


@pytest.mark.parametrize("position", ["", "   ", None])
def test_empty_position_cannot_launch_or_scan(position, tmp_path):
    with pytest.raises(ValueError, match="одну позицию"):
        seans_watch._launch_global_seans_watch_worker(Flask(__name__), position, str(tmp_path), 5)
    with pytest.raises(ValueError, match="одну позицию"):
        run_seans_watch_loop(
            position_name=position, folder_path=str(tmp_path), interval_sec=5,
            should_stop=lambda: True, wait_secs=lambda _: None,
            status={}, status_lock=threading.Lock(),
        )


def test_all_batches_are_written_with_one_selected_client(monkeypatch):
    monkeypatch.setattr(
        "web_portal.lib.sessions_id_watch.process_new_seans_for_watch", Mock()
    )
    conn = sqlite3.connect(":memory:")
    try:
        rows = [SeansEntry("2030-06-01 10:00:00", "151.3920", "100", str(i), None)
                for i in range(501)]
        assert save_seans_entries(conn, rows, client_name="  Север  ") == 501
        assert conn.execute("SELECT DISTINCT client_name FROM seanses").fetchall() == [("Север",)]
        assert conn.execute("SELECT COUNT(*) FROM seanses").fetchone()[0] == 501
    finally:
        conn.close()
