"""Схема и базовые операции модуля «Авиация»."""

from __future__ import annotations

import sqlite3

from web_portal.lib.aviation_db import (
    create_aviation_frequency,
    create_or_update_aviation_intercept,
    get_aviation_intercept_for_api,
    get_aviation_stats,
    init_aviation,
    normalize_aviation_work_date,
    parse_aviation_content_for_callsigns,
    upsert_aviation_daily_intercept,
)


def test_aviation_init_all_types_and_stats() -> None:
    conn = sqlite3.connect(":memory:")
    init_aviation(conn)
    types = [
        "Армейская авиация",
        "Тактическая авиация",
        "н/у",
        "ЯК",
        "F-16",
    ]
    for i, t in enumerate(types):
        rid = create_aviation_frequency(conn, frequency=f"120.{i}", aviation_type=t)
        assert rid > 0
        create_or_update_aviation_intercept(conn, frequency_id=rid, content="12.34\n-Тест")

    stats = get_aviation_stats(conn)
    assert len(stats) == 5

    cur = conn.cursor()
    cur.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='aviation_frequencies'"
    )
    row = cur.fetchone()
    sql = row[0] if row else ""
    assert "F-16" in sql or "ЯК" in sql or "н/у" in sql


def test_parse_aviation_content_for_callsigns() -> None:
    content = "12.30\n-Сова на связи\n14.05\n-other"
    hits = parse_aviation_content_for_callsigns(
        content, known_callsigns=[{"label": "Сова"}]
    )
    assert len(hits) == 1
    assert hits[0].get("time") == "12.30"
    assert "Сова" in (hits[0].get("snippet") or "")


def test_aviation_daily_work_date_isolated() -> None:
    conn = sqlite3.connect(":memory:")
    init_aviation(conn)
    rid = create_aviation_frequency(conn, frequency="100.0", aviation_type="н/у")
    upsert_aviation_daily_intercept(
        conn, frequency_id=rid, work_date="2030-01-01", content="день 1"
    )
    upsert_aviation_daily_intercept(
        conn, frequency_id=rid, work_date="2030-01-07", content="семь"
    )

    d1 = get_aviation_intercept_for_api(conn, frequency_id=rid, work_date="2030-01-01")
    d7 = get_aviation_intercept_for_api(conn, frequency_id=rid, work_date="2030-01-07")
    assert (d1 or {}).get("content") == "день 1"
    assert (d7 or {}).get("content") == "семь"

    stats = get_aviation_stats(conn, date="2030-01-07")
    row = next((x for x in stats if x["frequency"] == "100.0"), None)
    assert row and row["has_content"] is True


def test_normalize_aviation_work_date() -> None:
    assert normalize_aviation_work_date("2030-12-07") == "2030-12-07"
    assert normalize_aviation_work_date("2030-12-07T11:22:33") == "2030-12-07"
    assert normalize_aviation_work_date("bad") is None
