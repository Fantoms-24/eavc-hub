from __future__ import annotations

import sqlite3

from web_portal.lib.db import (
    count_seanses_by_code,
    count_seanses_by_code_for_unit,
    init_db,
    init_seans_tables,
)


def _main_conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    c.execute(
        """
        INSERT INTO intercept_catalog (position_name, unit_name, frequency, group_code, uuid)
        VALUES ('pos1', 'Unit A', '149.9750', '2047519', 'cat-1')
        """
    )
    c.commit()
    return c


def _seans_conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_seans_tables(c)
    c.executemany(
        """
        INSERT INTO seanses (date_time, frequency, group_, id, client_name)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("2026-06-01 10:00:00", "149.9750", "2047519", "1343", "pos1"),
            ("2026-06-01 10:05:00", "149.9750", "2047519", "1343", "pos1"),
            ("2026-06-01 11:00:00", "149.9750", "2047519", "2324", "pos1"),
        ],
    )
    c.commit()
    return c


def test_count_seanses_by_code_uses_seans_db() -> None:
    main = _main_conn()
    seans = _seans_conn()
    counts = count_seanses_by_code(
        main,
        seans_conn=seans,
        position_name="pos1",
        frequency="149.9750",
        group_code="2047519",
        start_dt="2026-06-01 00:00:00",
        end_dt="2026-06-02 00:00:00",
    )
    assert counts.get("1343") == 2
    assert counts.get("2324") == 1


def test_count_seanses_by_code_for_unit_uses_seans_db() -> None:
    main = _main_conn()
    seans = _seans_conn()
    counts = count_seanses_by_code_for_unit(
        main,
        seans_conn=seans,
        position_name="pos1",
        unit_name="Unit A",
        start_dt="2026-06-01 00:00:00",
        end_dt="2026-06-02 00:00:00",
    )
    assert counts.get("1343") == 2
    assert counts.get("2324") == 1
