from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sqlite3

from web_portal.application.online_search import unit_dashboard


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def test_dashboard_period_and_correspondent_semantics(monkeypatch) -> None:
    search_conn = _conn()
    main_conn = _conn()
    main_conn.executescript(
        """
        CREATE TABLE unit (frequency TEXT, group_ TEXT, name TEXT);
        CREATE TABLE seanses (date_time TEXT, frequency TEXT, group_ TEXT, id TEXT, client_name TEXT);
        CREATE TABLE intercept_callsigns (code TEXT, label TEXT, unit_name TEXT);
        CREATE TABLE intercept_items (
            id INTEGER PRIMARY KEY,
            content TEXT,
            updated_at TEXT,
            frequency TEXT,
            group_code TEXT,
            unit_name TEXT
        );
        INSERT INTO unit VALUES ('149.200', 'Основная', '155 ОМБр');
        INSERT INTO intercept_callsigns VALUES ('12345', 'Барс-12', '155 ОМБр');
        INSERT INTO intercept_callsigns VALUES ('67890', 'Гром-3', '155 ОМБр');
        INSERT INTO intercept_items VALUES (1, 'Барс-12 на связи', '2026-09-13 12:00:00', '149.200', 'Основная', '155 ОМБр');
        """
    )
    now = datetime.now().replace(microsecond=0)
    rows = [
        (now, "12345"),
        (now, "67890"),
        (now - timedelta(days=1), "12345"),
    ]
    main_conn.executemany(
        "INSERT INTO seanses VALUES (?, '149.200', 'Основная', ?, '')",
        [(stamp.strftime("%Y-%m-%d %H:%M:%S"), code) for stamp, code in rows],
    )
    family = {"parent_key": "155 ОМБр", "parent_label": "155 ОМБр", "children": [], "row_count": 1}
    monkeypatch.setattr(unit_dashboard, "get_unit_family_by_parent_key", lambda _conn, _key: family)
    monkeypatch.setattr(unit_dashboard, "resolve_seans_conn_for_queries", lambda conn, _other: conn)
    monkeypatch.setattr(unit_dashboard, "seanses_union_source_sql", lambda _conn: "SELECT date_time, frequency, group_, id, client_name FROM seanses")

    payload = unit_dashboard.assemble_online_search_unit_dashboard_payload(
        search_conn,
        main_conn,
        "155 ОМБр",
        period_days=14,
    )

    assert payload["period"]["days"] == 14
    assert len(payload["days"]) == 14
    assert payload["summary"]["sessions"] == 2
    assert payload["summary"]["correspondents"] == 2
    assert payload["days"][-1]["sessions"] == 1
    assert payload["days"][-1]["correspondents"] == 2
    assert payload["callsigns"][0]["correspondent_id"] in {"12345", "67890"}
    bars = next(item for item in payload["callsigns"] if item["correspondent_id"] == "12345")
    assert bars["label"] == "Барс-12"
    assert bars["last_intercept"]["content"] == "Барс-12 на связи"


def test_dashboard_invalid_period_falls_back_to_seven(monkeypatch) -> None:
    search_conn = _conn()
    main_conn = _conn()
    main_conn.execute("CREATE TABLE unit (frequency TEXT, group_ TEXT, name TEXT)")
    family = {"parent_key": "155 ОМБр", "parent_label": "155 ОМБр", "children": [], "row_count": 0}
    monkeypatch.setattr(unit_dashboard, "get_unit_family_by_parent_key", lambda _conn, _key: family)

    payload = unit_dashboard.assemble_online_search_unit_dashboard_payload(
        search_conn,
        main_conn,
        "155 ОМБр",
        period_days=99,
    )

    assert payload["period"]["days"] == 7
    assert len(payload["days"]) == 7


def test_dashboard_uses_route_class_instead_of_root_has_selector() -> None:
    base = (PROJECT_ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    dashboard_css = (PROJECT_ROOT / "static" / "css" / "unit-dashboard.css").read_text(encoding="utf-8")
    shell_js = (PROJECT_ROOT / "static" / "js" / "eavc-app-shell.js").read_text(encoding="utf-8")
    dashboard_js = (PROJECT_ROOT / "static" / "js" / "unit_dashboard.js").read_text(encoding="utf-8")

    assert "search_online_unit_parent_page" in base
    assert "eavc-page-unit-dashboard" in base
    assert "body:has(.up2-page)" not in dashboard_css
    assert "body.eavc-page-unit-dashboard" in dashboard_css
    assert "overflow-y: hidden" in dashboard_css
    assert 'classList.contains("eavc-page-unit-dashboard")' in shell_js
    assert 'id="ud-chart-tip" hidden' in dashboard_js
    assert "root.onpointerleave" in dashboard_js


def test_search_online_scroll_path_avoids_glass_repaint() -> None:
    search_css = (PROJECT_ROOT / "static" / "css" / "search-online-workbench.css").read_text(encoding="utf-8")

    assert "body.eavc-page-search-online .eavc-rail" in search_css
    assert "backdrop-filter: none !important" in search_css
    assert "body.eavc-page-search-online::before" in search_css
    assert "contain: paint" in search_css
    assert "content-visibility: visible" in search_css
