"""Physically extract stats domain from lib/db/_impl.py into lib/db/stats.py."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "lib" / "db" / "_impl.py"
OUT = ROOT / "lib" / "db" / "stats.py"
SEANS_FACADE = ROOT / "lib" / "db" / "seans.py"

# Order matters for readability; mutual deps stay in this module.
NAMES = [
    "get_db_stats_legacy",
    "get_doc_stats_legacy",
    "get_db_stats",
    "format_ids",
    "get_doc_stats",
    "_seanses_period_has_rows",
    "_doc_stats_page_ids_from_daily_agg",
    "_doc_stats_page_ids_from_daily_agg_chunk",
    "_doc_stats_page_ids_map_chunk",
    "_doc_stats_page_ids_map",
    "_doc_stats_page_grouped_sql",
    "_doc_stats_page_build_result",
    "_seans_sessions_total_for_days",
    "_seans_network_pairs_for_days",
    "_daily_agg_network_pairs_for_days",
    "_daily_agg_sessions_total_for_days",
    "_try_get_doc_stats_page_from_daily_agg",
    "get_doc_stats_page",
    "dump_selected_rows_for_doc",
]

# Lazy imports from _impl (avoid cycle with bottom re-export).
LAZY_IMPL: dict[str, list[str]] = {
    "get_db_stats_legacy": [
        "from web_portal.lib.db._impl import _pick_first, _table_columns",
    ],
    "get_doc_stats_legacy": [
        "from web_portal.lib.db._impl import _pick_first, _table_columns, _unit_map_legacy",
    ],
    "get_doc_stats": [
        "from web_portal.lib.db._impl import _build_unit_name_map_for_pairs, _sql_freq_zone_expr",
    ],
    "_doc_stats_page_build_result": [
        "from web_portal.lib.db._impl import _build_unit_name_map_for_pairs",
    ],
    "_seans_network_pairs_for_days": [
        "from web_portal.lib.db._impl import _sql_freq_zone_expr",
    ],
    "_daily_agg_network_pairs_for_days": [
        "from web_portal.lib.db._impl import _sql_freq_zone_expr",
    ],
    "_try_get_doc_stats_page_from_daily_agg": [
        "from web_portal.lib.db._impl import _date_only_window, _sql_freq_zone_expr",
    ],
    "get_doc_stats_page": [
        "from web_portal.lib.db._impl import _sql_freq_zone_expr",
    ],
}


def src_of(src: str, node: ast.AST) -> str:
    seg = ast.get_source_segment(src, node)
    if seg is None:
        raise RuntimeError("no source")
    return seg.rstrip() + "\n"


def inject_lazy(body: str, imports: list[str]) -> str:
    tree = ast.parse(body)
    fn = tree.body[0]
    assert isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
    lines = body.splitlines(keepends=True)
    first = fn.body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(getattr(first, "value", None), ast.Constant)
        and isinstance(first.value.value, str)
        and len(fn.body) > 1
    ):
        insert_line = (first.end_lineno or first.lineno) + 1
    else:
        insert_line = first.lineno
    idx = insert_line - 1
    lines[idx:idx] = ["".join(f"    {imp}\n" for imp in imports)]
    return "".join(lines)


def main() -> None:
    src = IMPL.read_text(encoding="utf-8")
    tree = ast.parse(src)
    nodes = {
        n.name: n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = [n for n in NAMES if n not in nodes]
    if missing:
        raise SystemExit(f"missing: {missing}")

    parts = [
        '"""Статистика БД и документов (физически вынесено из ``_impl``)."""',
        "from __future__ import annotations",
        "",
        "from collections import Counter, defaultdict",
        "import sqlite3",
        "from typing import Any",
        "",
        "from web_portal.lib.db.seans_schema import (",
        "    _table_exists,",
        "    init_daily_aggregates,",
        "    init_seans_tables,",
        "    refresh_seanses_daily_aggregates,",
        ")",
        "",
        "",
    ]

    for name in NAMES:
        body = src_of(src, nodes[name])
        if name in LAZY_IMPL:
            body = inject_lazy(body, LAZY_IMPL[name])
        parts.append(body)
        parts.append("")

    public = [
        "get_db_stats_legacy",
        "get_doc_stats_legacy",
        "get_db_stats",
        "format_ids",
        "get_doc_stats",
        "get_doc_stats_page",
        "dump_selected_rows_for_doc",
    ]
    parts.append("__all__ = [")
    for n in public:
        parts.append(f'    "{n}",')
    parts.append("]")
    parts.append("")

    OUT.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    ast.parse(OUT.read_text(encoding="utf-8"))
    print("wrote stats.py", sum(1 for _ in OUT.open(encoding="utf-8")), "lines")

    remove: set[int] = set()
    for name in NAMES:
        n = nodes[name]
        remove.update(range(n.lineno, (n.end_lineno or n.lineno) + 1))
    lines = src.splitlines(keepends=True)
    text = "".join(ln for i, ln in enumerate(lines, 1) if i not in remove)
    while "\n\n\n\n" in text:
        text = text.replace("\n\n\n\n", "\n\n\n")

    reexport = """

# --- stats domain (physically extracted) ---
from web_portal.lib.db.stats import (  # noqa: E402,F401
    _daily_agg_network_pairs_for_days,
    _daily_agg_sessions_total_for_days,
    _doc_stats_page_build_result,
    _doc_stats_page_grouped_sql,
    _doc_stats_page_ids_from_daily_agg,
    _doc_stats_page_ids_from_daily_agg_chunk,
    _doc_stats_page_ids_map,
    _doc_stats_page_ids_map_chunk,
    _seans_network_pairs_for_days,
    _seans_sessions_total_for_days,
    _seanses_period_has_rows,
    _try_get_doc_stats_page_from_daily_agg,
    dump_selected_rows_for_doc,
    format_ids,
    get_db_stats,
    get_db_stats_legacy,
    get_doc_stats,
    get_doc_stats_legacy,
    get_doc_stats_page,
)
"""
    if "# --- seans schema slice" in text:
        text = text.replace(
            "# --- seans schema slice",
            reexport.strip() + "\n\n# --- seans schema slice",
        )
    else:
        text = text.rstrip() + "\n" + reexport
    IMPL.write_text(text.rstrip() + "\n", encoding="utf-8")
    ast.parse(IMPL.read_text(encoding="utf-8"))
    print("updated _impl.py", sum(1 for _ in IMPL.open(encoding="utf-8")), "lines")

    facade = SEANS_FACADE.read_text(encoding="utf-8")
    # Point seans helpers that moved into stats at the new module.
    old_impl_block = """from web_portal.lib.db._impl import (  # noqa: F401
    clear_seanses_by_client_name,
    archive_seanses_outside_current_day,
    archive_all_seanses_to_archive,
    init_seanses_archive_file_schema,
    archive_seanses_before_date_to_file,
    cleanup_seanses,
    resolve_seans_conn_for_queries,
    list_distinct_seans_frequency_groups,
    list_seans_pairs,
    count_seanses_by_code,
    count_seanses_by_code_for_unit,
    _delete_conflicting_tt_seans_rows,
    _save_seans_batch,
    _save_seans_batch_with_client,
    save_seans_entries,
    seans_entries_fully_in_database,
    _parse_seans_date_time_value,
    max_seans_date_times_by_frequency,
    scan_seanses_once,
    _seanses_period_has_rows,
    _seans_sessions_total_for_days,
    _seans_network_pairs_for_days,
    get_seanses_rows_export,
"""
    new_impl_block = """from web_portal.lib.db.stats import (  # noqa: F401
    _seanses_period_has_rows,
    _seans_sessions_total_for_days,
    _seans_network_pairs_for_days,
)
from web_portal.lib.db._impl import (  # noqa: F401
    clear_seanses_by_client_name,
    archive_seanses_outside_current_day,
    archive_all_seanses_to_archive,
    init_seanses_archive_file_schema,
    archive_seanses_before_date_to_file,
    cleanup_seanses,
    resolve_seans_conn_for_queries,
    list_distinct_seans_frequency_groups,
    list_seans_pairs,
    count_seanses_by_code,
    count_seanses_by_code_for_unit,
    _delete_conflicting_tt_seans_rows,
    _save_seans_batch,
    _save_seans_batch_with_client,
    save_seans_entries,
    seans_entries_fully_in_database,
    _parse_seans_date_time_value,
    max_seans_date_times_by_frequency,
    scan_seanses_once,
    get_seanses_rows_export,
"""
    if old_impl_block not in facade:
        raise SystemExit("seans facade block not found; update script")
    SEANS_FACADE.write_text(facade.replace(old_impl_block, new_impl_block), encoding="utf-8")
    print("updated seans.py facade")

    # Soft-update package docstring
    init_py = ROOT / "lib" / "db" / "__init__.py"
    text_init = init_py.read_text(encoding="utf-8")
    text_init = text_init.replace(
        "Реализация: ``sync`` и ``ai`` вынесены физически; остальные домены —\n"
        "фасады над ``_impl`` (постепенный распил).",
        "Реализация: ``sync``, ``ai``, ``connection``, ``seans_schema``, ``stats``\n"
        "вынесены физически; остальные домены — фасады над ``_impl``.",
    )
    init_py.write_text(text_init, encoding="utf-8")
    print("updated __init__.py note")


if __name__ == "__main__":
    main()
