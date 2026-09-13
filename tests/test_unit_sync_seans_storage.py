"""Синхронизация unit должна читать пары из seans.sqlite, не из пустого main.seanses."""

import sqlite3

from web_portal.lib.db import (
    init_db,
    init_online_search,
    init_seans_tables,
    list_distinct_seans_frequency_groups,
    sync_units_from_online_search,
)


def _main_conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    return c


def _seans_conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_seans_tables(c)
    return c


def test_list_distinct_seans_frequency_groups_uses_seans_conn():
    main = _main_conn()
    seans = _seans_conn()
    seans.execute(
        """
        INSERT INTO seanses (date_time, frequency, group_, id, client_name)
        VALUES ('2024-06-10 12:00:00', '151.0000', 'G001', 'id1', 'pos1')
        """
    )
    seans.commit()

    assert list_distinct_seans_frequency_groups(main, seans_conn=seans) == [
        ("151.0000", "G001")
    ]
    assert main.execute("SELECT COUNT(*) FROM seanses").fetchone()[0] == 0


def test_sync_units_from_online_search_with_seans_storage():
    main = _main_conn()
    seans = _seans_conn()
    seans.execute(
        """
        INSERT INTO seanses (date_time, frequency, group_, id, client_name)
        VALUES ('2024-06-10 12:00:00', '151.0000', 'G001', 'id1', 'pos1')
        """
    )
    seans.commit()

    search = sqlite3.connect(":memory:")
    search.row_factory = sqlite3.Row
    init_online_search(search)
    search.execute(
        """
        INSERT INTO online_search (frequency, group_id, note, col1, col2, col9)
        VALUES ('151.0000', 'G001', '425 oshp Test', '151.0000', 'G001', '425 oshp Test')
        """
    )
    search.commit()

    pairs = list_distinct_seans_frequency_groups(main, seans_conn=seans)
    stats = sync_units_from_online_search(main, search, pairs)
    assert stats["total_applied"] >= 1
    name = main.execute(
        "SELECT name FROM unit WHERE frequency=? AND group_=?",
        ("151.0000", "G001"),
    ).fetchone()[0]
    assert "425 oshp Test" in str(name)
