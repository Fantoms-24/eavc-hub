"""Extract seans schema/aggregates slice into lib/db/seans_schema.py."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "lib" / "db" / "_impl.py"
OUT = ROOT / "lib" / "db" / "seans_schema.py"
SEANS_FACADE = ROOT / "lib" / "db" / "seans.py"

NAMES = [
    "_table_exists",
    "seanses_union_source_sql",
    "init_daily_aggregates",
    "refresh_seanses_daily_aggregates",
    "refresh_seanses_daily_aggregates_for_entries",
    "init_seans_tables",
]


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
    for name in NAMES:
        if name not in nodes:
            raise SystemExit(f"missing {name}")

    parts = [
        '"""Seans schema / daily aggregates (physically extracted)."""',
        "from __future__ import annotations",
        "",
        "from typing import Any",
        "import sqlite3",
        "",
        "",
    ]
    for name in NAMES:
        body = src_of(src, nodes[name])
        if name == "init_seans_tables" and "init_db(" in body:
            # already has nested import for seans_db; add connection.init_db lazy
            body = inject_lazy(
                body, ["from web_portal.lib.db.connection import init_db"]
            )
        parts.append(body)
        parts.append("")

    parts.append("__all__ = [")
    for n in NAMES:
        if not n.startswith("_") or n == "_table_exists":
            parts.append(f'    "{n}",')
    parts.append("]")
    parts.append("")
    OUT.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    ast.parse(OUT.read_text(encoding="utf-8"))
    print("wrote seans_schema.py")

    # Remove from _impl
    remove: set[int] = set()
    for name in NAMES:
        n = nodes[name]
        remove.update(range(n.lineno, (n.end_lineno or n.lineno) + 1))
    lines = src.splitlines(keepends=True)
    text = "".join(ln for i, ln in enumerate(lines, 1) if i not in remove)
    while "\n\n\n\n" in text:
        text = text.replace("\n\n\n\n", "\n\n\n")

    reexport = """

# --- seans schema slice (physically extracted) ---
from web_portal.lib.db.seans_schema import (  # noqa: E402,F401
    _table_exists,
    init_daily_aggregates,
    init_seans_tables,
    refresh_seanses_daily_aggregates,
    refresh_seanses_daily_aggregates_for_entries,
    seanses_union_source_sql,
)
"""
    if "# --- connection domain" in text:
        text = text.replace(
            "# --- connection domain",
            reexport.strip() + "\n\n# --- connection domain",
        )
    else:
        text = text.rstrip() + "\n" + reexport
    IMPL.write_text(text.rstrip() + "\n", encoding="utf-8")
    ast.parse(IMPL.read_text(encoding="utf-8"))
    print("updated _impl.py")

    # Update seans facade: pull extracted from seans_schema, rest from _impl
    facade = SEANS_FACADE.read_text(encoding="utf-8")
    # Replace import block
    new_facade = '''"""Сеансы, архив, daily aggregates.

Часть схемы/агрегатов — в ``seans_schema``; остальное пока из ``_impl``.
"""
from __future__ import annotations

from web_portal.lib.db.seans_schema import (  # noqa: F401
    init_daily_aggregates,
    init_seans_tables,
    refresh_seanses_daily_aggregates,
    refresh_seanses_daily_aggregates_for_entries,
    seanses_union_source_sql,
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
    _seanses_period_has_rows,
    _seans_sessions_total_for_days,
    _seans_network_pairs_for_days,
    get_seanses_rows_export,
    list_active_seans_freq_groups_for_unit_name,
    seanses_datetime_extremes_for_unit_pair,
    list_seanses_ids_for_unit_pair,
    list_seanses_rows_after_rowid,
    upsert_seanses_rows_from_sync,
    list_seanses_since,
)

__all__ = [
    "init_daily_aggregates",
    "refresh_seanses_daily_aggregates",
    "refresh_seanses_daily_aggregates_for_entries",
    "seanses_union_source_sql",
    "clear_seanses_by_client_name",
    "archive_seanses_outside_current_day",
    "archive_all_seanses_to_archive",
    "init_seanses_archive_file_schema",
    "archive_seanses_before_date_to_file",
    "cleanup_seanses",
    "init_seans_tables",
    "resolve_seans_conn_for_queries",
    "list_distinct_seans_frequency_groups",
    "list_seans_pairs",
    "count_seanses_by_code",
    "count_seanses_by_code_for_unit",
    "save_seans_entries",
    "seans_entries_fully_in_database",
    "max_seans_date_times_by_frequency",
    "scan_seanses_once",
    "get_seanses_rows_export",
    "list_active_seans_freq_groups_for_unit_name",
    "seanses_datetime_extremes_for_unit_pair",
    "list_seanses_ids_for_unit_pair",
    "list_seanses_rows_after_rowid",
    "upsert_seanses_rows_from_sync",
    "list_seanses_since",
]
'''
    SEANS_FACADE.write_text(new_facade, encoding="utf-8")
    # Cycle check: seans facade imports _impl which must not import seans facade
    print("updated seans.py facade")


if __name__ == "__main__":
    main()
