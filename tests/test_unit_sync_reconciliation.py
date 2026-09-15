"""Регрессии двусторонней синхронизации привязок подразделений."""

import sqlite3

from web_portal.lib.db import init_db, upsert_unit_rows_from_sync


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_unit_sync_is_idempotent_and_preserves_newer_local_name() -> None:
    conn = _conn()
    first = {
        "frequency": "149.200",
        "group_": "101",
        "name": "155 ОМБр 1 мсб",
        "manual": 1,
        "updated_at": "2026-09-15 10:00:00",
    }
    assert upsert_unit_rows_from_sync(conn, rows=[first])["applied"] == 1
    # Полная сверка повторяет пакет, но не создаёт новую запись и не зацикливает обмен.
    assert upsert_unit_rows_from_sync(conn, rows=[first]) == {
        "applied": 0,
        "unchanged": 1,
        "skipped_newer": 0,
    }

    conn.execute(
        """
        UPDATE unit
        SET name='155 ОМБр 1 механизированный батальон', updated_at='2026-09-15 11:00:00'
        WHERE frequency='149.200' AND group_='101'
        """
    )
    conn.commit()
    result = upsert_unit_rows_from_sync(conn, rows=[first])
    assert result["skipped_newer"] == 1
    assert conn.execute(
        "SELECT name FROM unit WHERE frequency='149.200' AND group_='101'"
    ).fetchone()[0] == "155 ОМБр 1 механизированный батальон"
