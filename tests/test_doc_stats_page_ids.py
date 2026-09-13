"""Быстрые ids для table-data: daily agg вместо полного скана seanses."""

from __future__ import annotations

import sqlite3

from web_portal.lib.db import (
    _build_unit_name_map_for_pairs,
    _date_only_window,
    _doc_stats_page_ids_from_daily_agg,
    _network_prev_daily_window,
    _sql_freq_zone_expr,
    get_doc_stats_page,
    init_db,
    init_daily_aggregates,
    init_seans_tables,
    refresh_seanses_daily_aggregates,
)


def _seans_with_sample() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_seans_tables(c)
    c.executemany(
        """
        INSERT INTO seanses (date_time, frequency, group_, id, client_name)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("2026-06-01 10:00:00", "151.0000", "G001", "A1", "pos1"),
            ("2026-06-01 10:05:00", "151.0000", "G001", "A1", "pos1"),
            ("2026-06-01 11:00:00", "151.0000", "G001", "A2", "pos1"),
            ("2026-06-02 09:00:00", "152.1000", "G002", "B1", "pos1"),
        ],
    )
    c.commit()
    init_daily_aggregates(c)
    refresh_seanses_daily_aggregates(c, start_day="2026-06-01", end_day="2026-06-02")
    return c


def test_doc_stats_page_ids_from_daily_agg():
    c = _seans_with_sample()
    fz = _sql_freq_zone_expr("frequency")
    ids_map = _doc_stats_page_ids_from_daily_agg(
        c.cursor(),
        page_keys=[("151", "G001"), ("152", "G002")],
        day_from="2026-06-01",
        day_to="2026-06-02",
        client_name=None,
        fz=fz,
    )
    assert "A1" in ids_map.get(("151", "G001"), "")
    assert "B1" in ids_map.get(("152", "G002"), "")


def test_get_doc_stats_page_uses_daily_agg_for_calendar_window():
    main = sqlite3.connect(":memory:")
    main.row_factory = sqlite3.Row
    init_db(main)
    seans = _seans_with_sample()
    page = get_doc_stats_page(
        seans,
        "2026-06-01 00:00:00",
        "2026-06-02 23:59:59",
        client_name=None,
        limit=50,
        offset=0,
        unit_conn=main,
        exact_period=True,
    )
    assert page["total"] >= 2
    freqs = {row["frequency"] for row in page["data"]}
    assert "151.0000" in freqs or any(f.startswith("151") for f in freqs)


def test_date_only_window_requires_full_calendar_days():
    assert _date_only_window("2026-06-01 00:00:00", "2026-06-02 23:59:59") == (
        "2026-06-01",
        "2026-06-02",
    )
    assert _date_only_window("2026-06-01 10:00:00", "2026-06-01 12:00:00") is None


def test_network_prev_daily_window_excludes_current_start_day():
    assert _network_prev_daily_window(
        "2026-06-05 00:00:00",
        "2026-05-29 00:00:00",
    ) == ("2026-05-29", "2026-06-04")


def test_get_doc_stats_page_subday_uses_exact_scan():
    main = sqlite3.connect(":memory:")
    main.row_factory = sqlite3.Row
    init_db(main)
    seans = _seans_with_sample()
    page = get_doc_stats_page(
        seans,
        "2026-06-01 10:00:00",
        "2026-06-01 10:30:00",
        client_name=None,
        limit=50,
        offset=0,
        unit_conn=main,
    )
    assert page["total"] == 1
    assert page["data"][0]["count"] == 2


def test_build_unit_name_map_chunks_large_group_list():
    main = sqlite3.connect(":memory:")
    main.row_factory = sqlite3.Row
    init_db(main)
    pairs = [(f"151.{i:04d}", f"G{i:04d}") for i in range(1100)]
    main.executemany(
        """
        INSERT INTO unit (frequency, group_, name, manual, updated_at)
        VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
        """,
        [(freq, group, f"Unit {i}") for i, (freq, group) in enumerate(pairs)],
    )
    main.commit()

    names = _build_unit_name_map_for_pairs(main, pairs)

    assert names[pairs[0]] == "Unit 0"
    assert names[pairs[-1]] == "Unit 1099"
