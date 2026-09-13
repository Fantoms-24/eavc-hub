from __future__ import annotations

import sqlite3

import pytest

from web_portal.application.intercepts.callsigns_commands import execute_intercepts_callsign_upsert
from web_portal.lib.db import init_db, list_intercept_callsigns


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    return c


def test_same_label_different_codes_allowed(conn: sqlite3.Connection) -> None:
    pos = "test-pos"
    freq = "149.9750"
    grp = "2047519"

    execute_intercepts_callsign_upsert(
        conn,
        position_name=pos,
        label="Сова",
        code="1343",
        unit_name="Unit A",
        frequency=freq,
        group_code=grp,
        hub_sync_enabled=False,
        invalidate_caches=lambda: None,
    )
    execute_intercepts_callsign_upsert(
        conn,
        position_name=pos,
        label="Сова",
        code="2324",
        unit_name="Unit A",
        frequency=freq,
        group_code=grp,
        hub_sync_enabled=False,
        invalidate_caches=lambda: None,
    )

    rows = list_intercept_callsigns(conn, pos)
    by_code = {r["code"]: r["label"] for r in rows}
    assert by_code.get("1343") == "Сова"
    assert by_code.get("2324") == "Сова"


def test_same_code_updates_label(conn: sqlite3.Connection) -> None:
    pos = "test-pos"
    freq = "149.9750"
    grp = "2047519"

    execute_intercepts_callsign_upsert(
        conn,
        position_name=pos,
        label="Сова",
        code="1343",
        unit_name="Unit A",
        frequency=freq,
        group_code=grp,
        hub_sync_enabled=False,
        invalidate_caches=lambda: None,
    )
    execute_intercepts_callsign_upsert(
        conn,
        position_name=pos,
        label="Сова-2",
        code="1343",
        unit_name="Unit A",
        frequency=freq,
        group_code=grp,
        hub_sync_enabled=False,
        invalidate_caches=lambda: None,
    )

    rows = list_intercept_callsigns(conn, pos)
    assert len(rows) == 1
    assert rows[0]["code"] == "1343"
    assert rows[0]["label"] == "Сова-2"
