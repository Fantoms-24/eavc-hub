"""Extract remaining seans query helpers into lib/db/seans_query.py."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "lib" / "db" / "_impl.py"
OUT = ROOT / "lib" / "db" / "seans_query.py"
SEANS_FACADE = ROOT / "lib" / "db" / "seans.py"

NAMES = [
    "list_distinct_seans_frequency_groups",
    "list_seans_pairs",
    "count_seanses_by_code",
    "count_seanses_by_code_for_unit",
    "get_seanses_rows_export",
    "list_active_seans_freq_groups_for_unit_name",
    "seanses_datetime_extremes_for_unit_pair",
    "list_seanses_ids_for_unit_pair",
    "list_seanses_rows_after_rowid",
    "upsert_seanses_rows_from_sync",
    "list_seanses_since",
]

LAZY_IMPL: dict[str, list[str]] = {
    "list_seanses_since": [
        "from web_portal.lib.db._impl import _in_clause",
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
        '"""Запросы / sync-upsert по сеансам (физически из ``_impl``)."""',
        "from __future__ import annotations",
        "",
        "import sqlite3",
        "from typing import Any",
        "",
        "from web_portal.lib.db.connection import _commit_if_needed, init_db",
        "from web_portal.lib.db.seans_archive import resolve_seans_conn_for_queries",
        "from web_portal.lib.db.seans_schema import (",
        "    init_seans_tables,",
        "    seanses_union_source_sql,",
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

    parts.append("__all__ = [")
    for n in NAMES:
        parts.append(f'    "{n}",')
    parts.append("]")
    parts.append("")
    OUT.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    ast.parse(OUT.read_text(encoding="utf-8"))
    print("wrote seans_query.py", sum(1 for _ in OUT.open(encoding="utf-8")), "lines")

    remove: set[int] = set()
    for name in NAMES:
        n = nodes[name]
        remove.update(range(n.lineno, (n.end_lineno or n.lineno) + 1))
    lines = src.splitlines(keepends=True)
    text = "".join(ln for i, ln in enumerate(lines, 1) if i not in remove)
    while "\n\n\n\n" in text:
        text = text.replace("\n\n\n\n", "\n\n\n")

    reexport = """

# --- seans query slice (physically extracted) ---
from web_portal.lib.db.seans_query import (  # noqa: E402,F401
    count_seanses_by_code,
    count_seanses_by_code_for_unit,
    get_seanses_rows_export,
    list_active_seans_freq_groups_for_unit_name,
    list_distinct_seans_frequency_groups,
    list_seans_pairs,
    list_seanses_ids_for_unit_pair,
    list_seanses_rows_after_rowid,
    list_seanses_since,
    seanses_datetime_extremes_for_unit_pair,
    upsert_seanses_rows_from_sync,
)
"""
    if "# --- seans write/scan/import" in text:
        text = text.replace(
            "# --- seans write/scan/import",
            reexport.strip() + "\n\n# --- seans write/scan/import",
        )
    else:
        text = text.rstrip() + "\n" + reexport
    IMPL.write_text(text.rstrip() + "\n", encoding="utf-8")
    ast.parse(IMPL.read_text(encoding="utf-8"))
    print("updated _impl.py", sum(1 for _ in IMPL.open(encoding="utf-8")), "lines")

    new_facade = '''"""Сеансы: схема, архив, запись, запросы.

Физически: ``seans_schema``, ``seans_archive``, ``seans_write``, ``seans_query``.
"""
from __future__ import annotations

from web_portal.lib.db.seans_schema import (  # noqa: F401
    init_daily_aggregates,
    init_seans_tables,
    refresh_seanses_daily_aggregates,
    refresh_seanses_daily_aggregates_for_entries,
    seanses_union_source_sql,
)
from web_portal.lib.db.seans_archive import (  # noqa: F401
    clear_seanses_by_client_name,
    archive_seanses_outside_current_day,
    archive_all_seanses_to_archive,
    init_seanses_archive_file_schema,
    archive_seanses_before_date_to_file,
    cleanup_seanses,
    resolve_seans_conn_for_queries,
)
from web_portal.lib.db.seans_write import (  # noqa: F401
    _delete_conflicting_tt_seans_rows,
    _save_seans_batch,
    _save_seans_batch_with_client,
    save_seans_entries,
    seans_entries_fully_in_database,
    _parse_seans_date_time_value,
    max_seans_date_times_by_frequency,
    scan_seanses_once,
)
from web_portal.lib.db.seans_query import (  # noqa: F401
    list_distinct_seans_frequency_groups,
    list_seans_pairs,
    count_seanses_by_code,
    count_seanses_by_code_for_unit,
    get_seanses_rows_export,
    list_active_seans_freq_groups_for_unit_name,
    seanses_datetime_extremes_for_unit_pair,
    list_seanses_ids_for_unit_pair,
    list_seanses_rows_after_rowid,
    upsert_seanses_rows_from_sync,
    list_seanses_since,
)
from web_portal.lib.db.stats import (  # noqa: F401
    _seanses_period_has_rows,
    _seans_sessions_total_for_days,
    _seans_network_pairs_for_days,
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
    print("updated seans.py — fully off _impl")

    init_py = ROOT / "lib" / "db" / "__init__.py"
    text_init = init_py.read_text(encoding="utf-8")
    text_init = text_init.replace(
        "``seans_archive``, ``seans_write``, ``stats`` вынесены физически;\n"
        "остальные — фасады над ``_impl``.",
        "``seans_*``, ``stats`` вынесены физически; остальные — фасады над ``_impl``.",
    )
    init_py.write_text(text_init, encoding="utf-8")


if __name__ == "__main__":
    main()
