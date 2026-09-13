"""Unit tests for application/analysis use cases."""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from web_portal.application.analysis.errors import AnalysisUseCaseHTTP
from web_portal.application.analysis.keys_check import (
    assemble_analysis_keys_check_payload,
    build_analysis_keys_sql_filter,
    parse_analysis_keys_check_range,
)
from web_portal.application.analysis.keys_helpers import (
    find_analysis_keys_column_indices,
    normalize_analysis_key_header,
    parse_analysis_keys_import_row,
)
from web_portal.application.analysis.keys_import import execute_analysis_keys_import
from web_portal.application.analysis.network_order import normalize_network_column_order
from web_portal.application.analysis.network_summary import (
    assemble_network_summary_payload,
    merge_network_summary_unit_names,
    parse_analysis_custom_units,
    parse_analysis_order_list,
    parse_network_summary_range,
)
from web_portal.application.analysis.ml_helpers import (
    ml_heuristic_label,
    ml_match_event_label,
    ml_parse_scope_pairs,
    ml_setting_key,
)
from web_portal.application.analysis.period_bounds import (
    build_analysis_period_bounds,
    fmt_analysis_dt,
    parse_analysis_datetime,
)
from web_portal.application.analysis.seans_rows import collect_seans_rows
from web_portal.application.analysis.graph_compare import (
    assemble_analysis_graph_compare_payload,
)
from web_portal.application.analysis.graph_dynamic import (
    assemble_analysis_graph_dynamic_live_payload,
    resolve_dynamic_scope_pairs,
)
from web_portal.application.analysis.graph_payload import (
    assemble_analysis_graph_payload,
    build_simple_analysis_graph,
    normalize_analysis_freq_str,
    normalize_analysis_group_key,
)
from web_portal.application.analysis.graph_timeline import (
    assemble_analysis_graph_timeline_payload,
    default_graph_timeline_bucket_minutes,
    resolve_graph_timeline_window,
)
from web_portal.application.analysis.assignments import execute_analysis_assign
from web_portal.lib.db import get_analysis_assignments, init_db, init_seans_tables


def test_parse_network_summary_range() -> None:
    start, end = parse_network_summary_range(
        "2030-06-01T00:00:00", "2030-06-02T00:00:00"
    )
    assert start.year == 2030
    assert end.day == 2
    with pytest.raises(AnalysisUseCaseHTTP):
        parse_network_summary_range("", "2030-06-02T00:00:00")


def test_ml_heuristic_label_and_match() -> None:
    assert ml_heuristic_label({"new_ratio": 0.4}) == "alert_high"
    assert ml_heuristic_label({"sessions": 1}) == "stable"
    assert ml_setting_key("pos1", "window_minutes") == "ml:pos1:window_minutes"
    tag_rows = [
        {"start_ts": "2030-06-01 10:00:00", "end_ts": "2030-06-01 11:00:00", "label": "alert_high"},
    ]
    assert (
        ml_match_event_label("2030-06-01 10:30:00", "2030-06-01 10:45:00", tag_rows)
        == "alert_high"
    )
    assert ml_match_event_label("2030-06-01 12:00:00", "2030-06-01 13:00:00", tag_rows) == ""


def test_ml_parse_scope_pairs() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.execute(
        "INSERT INTO unit (frequency, group_, name) VALUES (?, ?, ?)",
        ("149.9750", "2047519", "Unit A"),
    )
    conn.commit()
    assert ml_parse_scope_pairs(
        conn, unit_name="", frequency="149.9750", group_code="2047519"
    ) == [("149.9750", "2047519")]
    pairs = ml_parse_scope_pairs(conn, unit_name="Unit A", frequency="", group_code="")
    assert pairs == [("149.9750", "2047519")]


def test_fmt_analysis_dt() -> None:
    dt = datetime(2030, 6, 1, 12, 30, 45)
    assert fmt_analysis_dt(dt) == "2030-06-01 12:30:45"


def test_parse_analysis_datetime() -> None:
    assert parse_analysis_datetime("2030-06-01 12:30:45") == datetime(
        2030, 6, 1, 12, 30, 45
    )
    assert parse_analysis_datetime("2030-06-01T12:30:45") == datetime(
        2030, 6, 1, 12, 30, 45
    )
    assert parse_analysis_datetime("") is None
    assert parse_analysis_datetime("bad") is None


def test_normalize_analysis_freq_and_group_keys() -> None:
    assert normalize_analysis_freq_str("149,9750") == "149.975"
    assert normalize_analysis_group_key("G2047519") == "2047519"


def _seans_conn_with_rows() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_seans_tables(conn)
    conn.executemany(
        """
        INSERT INTO seanses (date_time, frequency, group_, id, client_name)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("2030-06-01 10:00:00", "149.9750", "2047519", "1343", "pos1"),
            ("2030-06-01 10:05:00", "149.9750", "2047519", "2324", "pos1"),
            ("2030-06-01 11:00:00", "150.0000", "2047520", "1343", "pos2"),
        ],
    )
    conn.commit()
    return conn


def test_collect_seans_rows_filters_by_position_and_scope() -> None:
    seans = _seans_conn_with_rows()
    rows = collect_seans_rows(
        seans,
        start_s="2030-06-01 00:00:00",
        end_s="2030-06-02 00:00:00",
        position_name="pos1",
        scope_pairs=[("149.9750", "2047519")],
    )
    assert len(rows) == 2
    ids = {r[3] for r in rows}
    assert ids == {"1343", "2324"}


def test_build_simple_analysis_graph_from_rows() -> None:
    rows = [
        ("2030-06-01 10:00:00", "149.9750", "2047519", "1343"),
        ("2030-06-01 10:00:00", "149.9750", "2047519", "2324"),
    ]
    pair_to_unit = {("149.9750", "2047519"): "Unit A"}
    nodes, edges, metrics = build_simple_analysis_graph(
        rows,
        pair_to_unit=pair_to_unit,
        cluster_by="unit",
        min_weight=1,
        max_nodes=50,
        max_edges=50,
        end_dt=datetime(2030, 6, 1, 12, 0, 0),
    )
    assert len(nodes) == 2
    assert len(edges) == 1
    assert metrics["density"] > 0


def test_assemble_analysis_graph_payload_empty_scope() -> None:
    main = sqlite3.connect(":memory:")
    main.row_factory = sqlite3.Row
    init_db(main)
    seans = _seans_conn_with_rows()
    payload = assemble_analysis_graph_payload(
        main,
        seans,
        pos="pos1",
        all_positions=False,
        unit_name="",
        frequency="149.9750",
        group_code="2047519",
        unit_query="",
        group_query="",
        include_other=False,
        minutes=60,
        start=datetime(2030, 6, 1, 0, 0),
        end=datetime(2030, 6, 2, 0, 0),
        start_s="2030-06-01 00:00:00",
        end_s="2030-06-02 00:00:00",
        max_nodes=50,
        max_edges=50,
        min_weight=1,
        cluster_by="unit",
        layout_hint="cose",
        focus_id="",
        max_nodes_mode="balanced",
    )
    assert payload["ok"] is True
    assert payload["frequency"] == "149.9750"
    assert isinstance(payload["nodes"], list)
    assert "metrics" in payload


def test_build_analysis_period_bounds_rolling() -> None:
    bounds = build_analysis_period_bounds(days="3")
    assert bounds is not None
    assert bounds.meta["period_mode"] == "rolling"
    assert bounds.meta["preset_days"] == 3
    assert bounds.end_naive >= bounds.start_naive


def test_build_analysis_period_bounds_calendar() -> None:
    bounds = build_analysis_period_bounds(
        period_start="2030-01-01", period_end="2030-01-07"
    )
    assert bounds is not None
    assert bounds.meta["period_mode"] == "calendar"
    assert bounds.meta["period_start_day"] == "2030-01-01"
    assert bounds.meta["period_end_day"] == "2030-01-07"
    assert bounds.start_naive.hour == 0
    assert bounds.end_naive.hour == 23


def test_build_analysis_period_bounds_invalid_calendar() -> None:
    assert build_analysis_period_bounds(period_start="bad-date") is None


def test_normalize_network_column_order() -> None:
    assert normalize_network_column_order(["B", "A", "B", "", "C"]) == ["B", "A", "C"]
    with pytest.raises(AnalysisUseCaseHTTP) as exc:
        normalize_network_column_order("not-a-list")
    assert exc.value.status_code == 400


def test_parse_analysis_order_list_and_custom_units() -> None:
    assert parse_analysis_order_list('["Alpha", "Beta", "Alpha"]') == [
        "Alpha",
        "Beta",
    ]
    assert parse_analysis_custom_units("Unit A, Unit B") == ["Unit A", "Unit B"]
    assert parse_analysis_custom_units('["X"]') == ["X"]


def test_merge_network_summary_unit_names() -> None:
    cur = [{"unit_name": "Bravo", "sessions": 10, "correspondents": 2}]
    prev = [{"unit_name": "Alpha", "sessions": 5, "correspondents": 1}]
    names = merge_network_summary_unit_names(
        cur,
        prev,
        custom_units=["Charlie"],
    )
    assert names == ["Alpha", "Bravo", "Charlie"]


def test_assemble_network_summary_payload() -> None:
    start = datetime(2030, 6, 1, 0, 0)
    end = datetime(2030, 6, 2, 23, 59)
    prev = datetime(2030, 5, 30, 0, 0)
    cur = [{"unit_name": "Alpha", "sessions": 3, "correspondents": 2}]
    payload = assemble_network_summary_payload(
        names=["Alpha"],
        cur_clusters=cur,
        prev_clusters=[],
        position_filter="pos1",
        all_positions=False,
        shared_order=[],
        column_order=[],
        start_clean=start,
        end_clean=end,
        prev_start=prev,
    )
    assert payload["ok"] is True
    assert payload["clusters"] == ["Alpha"]
    assert payload["current"]["Alpha"]["sessions"] == 3
    assert payload["previous"]["Alpha"]["sessions"] == 0


def test_parse_analysis_keys_check_range() -> None:
    assert parse_analysis_keys_check_range("", "") is None
    start, end = parse_analysis_keys_check_range(
        "2030-01-01T00:00:00", "2030-01-02T00:00:00"
    )
    assert start.year == 2030
    assert end.day == 2
    with pytest.raises(AnalysisUseCaseHTTP):
        parse_analysis_keys_check_range("2030-01-01T00:00:00", "")


def test_build_analysis_keys_sql_filter() -> None:
    where, params = build_analysis_keys_sql_filter(
        new_since="2030-01-01 10:00:00",
        start=datetime(2030, 1, 1),
        end=datetime(2030, 1, 31),
    )
    assert "created_at >= ?" in where
    assert "added_date" in where
    assert len(params) == 3


def test_keys_import_helpers_and_execute() -> None:
    assert normalize_analysis_key_header("Частота") == "частота"
    header = ("Frequency", "Group", "AES ID", "Key")
    indices = find_analysis_keys_column_indices(header)
    row = ("149.9750", "2047519", "1343", "ABCD")
    parsed = parse_analysis_keys_import_row(row, indices)
    assert parsed is not None
    assert parsed.frequency == "149.9750"

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    result = execute_analysis_keys_import(
        conn,
        [header, row],
        now_ts="2030-01-01 00:00:00",
    )
    assert result["inserted"] == 1
    assert result["skipped"] == 0


def _main_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_execute_analysis_assign() -> None:
    conn = _main_conn()
    payload = execute_analysis_assign(
        conn,
        position_name="pos1",
        frequency="149.9750",
        group_code="2047519",
        role_type="battalion",
        code="2324",
        mode="set",
        sync_hub=False,
        now_ts="2030-01-01 00:00:00",
    )
    assert payload["ok"] is True
    assignments = get_analysis_assignments(
        conn,
        position_name="pos1",
        frequency="149.9750",
        group_code="2047519",
    )
    assert assignments.get("battalion") == "2324"


def test_default_graph_timeline_bucket_minutes() -> None:
    assert default_graph_timeline_bucket_minutes(1) == 60
    assert default_graph_timeline_bucket_minutes(3) == 120
    assert default_graph_timeline_bucket_minutes(7) == 360
    assert default_graph_timeline_bucket_minutes(30) == 360


def test_resolve_graph_timeline_window_custom_range() -> None:
    start = datetime(2030, 6, 1, 0, 0)
    end = datetime(2030, 6, 2, 0, 0)
    s, e, bucket = resolve_graph_timeline_window(
        days=1,
        start_override=start,
        end_override=end,
        now=datetime(2030, 6, 3, 0, 0),
    )
    assert s == start
    assert e == end
    assert 5 <= bucket <= 360


def test_assemble_analysis_graph_timeline_payload() -> None:
    main = sqlite3.connect(":memory:")
    main.row_factory = sqlite3.Row
    init_db(main)
    main.execute(
        "INSERT INTO unit (frequency, group_, name) VALUES (?, ?, ?)",
        ("149.9750", "2047519", "Unit A"),
    )
    main.commit()
    seans = _seans_conn_with_rows()
    payload = assemble_analysis_graph_timeline_payload(
        main,
        seans,
        pos="pos1",
        all_positions=False,
        unit_name="",
        frequency="149.9750",
        group_code="2047519",
        group_query="",
        unit_query="",
        include_other=False,
        days=1,
        start=datetime(2030, 6, 1, 0, 0),
        end=datetime(2030, 6, 2, 0, 0),
        bucket_minutes=60,
        start_s="2030-06-01 00:00:00",
        end_s="2030-06-02 00:00:00",
    )
    assert payload["ok"] is True
    assert isinstance(payload["buckets"], list)
    assert "heatmap" in payload


def test_assemble_analysis_graph_compare_payload() -> None:
    main = sqlite3.connect(":memory:")
    main.row_factory = sqlite3.Row
    init_db(main)
    main.execute(
        "INSERT INTO unit (frequency, group_, name) VALUES (?, ?, ?)",
        ("149.9750", "2047519", "Unit A"),
    )
    main.commit()
    seans = _seans_conn_with_rows()
    start = datetime(2030, 6, 1, 0, 0)
    end = datetime(2030, 6, 2, 0, 0)
    prev_start = datetime(2030, 5, 31, 0, 0)
    prev_end = datetime(2030, 6, 1, 0, 0)
    payload = assemble_analysis_graph_compare_payload(
        main,
        seans,
        pos="pos1",
        all_positions=False,
        unit_name="",
        frequency="149.9750",
        group_code="2047519",
        group_query="",
        unit_query="",
        include_other=False,
        days=1,
        start=start,
        end=end,
        bucket_minutes=60,
        start_s="2030-06-01 00:00:00",
        end_s="2030-06-02 00:00:00",
        prev_start=prev_start,
        prev_end=prev_end,
        prev_start_s="2030-05-31 00:00:00",
        prev_end_s="2030-06-01 00:00:00",
    )
    assert payload["ok"] is True
    assert isinstance(payload["current"], list)
    assert isinstance(payload["previous"], list)


def test_assemble_analysis_keys_check_payload() -> None:
    main = sqlite3.connect(":memory:")
    main.row_factory = sqlite3.Row
    init_db(main)
    main.execute(
        """
        INSERT INTO analysis_keys (
            frequency, frequency_norm, group_, aes_id, aes_key, unit_name, added_date, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "149.9750",
            "149.975",
            "2047519",
            "1343",
            "ABCD",
            "Unit A",
            "2030-01-01",
            "2030-01-01 00:00:00",
        ),
    )
    main.commit()
    seans = _seans_conn_with_rows()
    payload = assemble_analysis_keys_check_payload(
        main,
        seans,
        position_filter="pos1",
        match_id=True,
        debug=False,
        all_keys=True,
        start=None,
        end=None,
        new_since="",
    )
    assert payload["ok"] is True
    assert payload["crypto_available"] is False
    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["session_matched"] is True


def test_resolve_dynamic_scope_pairs_by_unit_name() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE unit (frequency TEXT, group_ TEXT, name TEXT)"
    )
    conn.execute(
        "INSERT INTO unit (frequency, group_, name) VALUES (?, ?, ?)",
        ("151.0000", "1", "Alpha"),
    )
    conn.commit()
    pairs = resolve_dynamic_scope_pairs(
        conn,
        unit_name="Alpha",
        frequency="",
        group_code="",
        unit_query="",
    )
    assert pairs == [("151.0000", "1")]
    exact = resolve_dynamic_scope_pairs(
        conn,
        unit_name="",
        frequency="151.0000",
        group_code="1",
        unit_query="",
    )
    assert exact == [("151.0000", "1")]


def test_assemble_analysis_graph_dynamic_live_empty() -> None:
    main = sqlite3.connect(":memory:")
    main.row_factory = sqlite3.Row
    main.execute("CREATE TABLE unit (frequency TEXT, group_ TEXT, name TEXT)")
    seans = sqlite3.connect(":memory:")
    seans.row_factory = sqlite3.Row
    init_seans_tables(seans)
    start = datetime(2030, 1, 1, 12, 0, 0)
    end = datetime(2030, 1, 1, 12, 30, 0)
    payload = assemble_analysis_graph_dynamic_live_payload(
        main,
        seans,
        pos="pos1",
        unit_name="",
        frequency="",
        group_code="",
        unit_query="",
        group_query="",
        include_other=False,
        bucket_minutes=5,
        start_dt=start,
        end_dt=end,
    )
    assert payload["ok"] is True
    assert payload["new_buckets"] == []
    assert "server_ts" in payload
