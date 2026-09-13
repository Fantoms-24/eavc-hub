"""Extract seans write/scan/import slice into lib/db/seans_write.py."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "lib" / "db" / "_impl.py"
OUT = ROOT / "lib" / "db" / "seans_write.py"
SEANS_FACADE = ROOT / "lib" / "db" / "seans.py"
MISC_FACADE = ROOT / "lib" / "db" / "misc.py"

NAMES = [
    "_delete_conflicting_tt_seans_rows",
    "_save_seans_batch",
    "_save_seans_batch_with_client",
    "save_seans_entries",
    "_processed_files_key",
    "was_processed",
    "mark_processed",
    "seans_entries_fully_in_database",
    "_parse_seans_date_time_value",
    "max_seans_date_times_by_frequency",
    "scan_seanses_once",
    "save_all_from_dir",
    "import_folder",
    "import_folder_with_client",
    "import_folder_incremental",
]


def src_of(src: str, node: ast.AST) -> str:
    seg = ast.get_source_segment(src, node)
    if seg is None:
        raise RuntimeError("no source")
    return seg.rstrip() + "\n"


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
        '"""Запись / сканирование / импорт сеансов (физически из ``_impl``)."""',
        "from __future__ import annotations",
        "",
        "import logging",
        "import sqlite3",
        "from datetime import datetime",
        "from pathlib import Path",
        "from typing import Any",
        "",
        "from web_portal.lib.collect_seanses_from_dir import SeansEntry, collect_seanses_from",
        "from web_portal.lib.db.connection import init_db",
        "from web_portal.lib.db.seans_schema import (",
        "    init_seans_tables,",
        "    refresh_seanses_daily_aggregates_for_entries,",
        ")",
        "",
        '_log = logging.getLogger("web_portal.db")',
        "",
        "",
    ]
    for name in NAMES:
        parts.append(src_of(src, nodes[name]))
        parts.append("")

    public = [
        "save_seans_entries",
        "seans_entries_fully_in_database",
        "max_seans_date_times_by_frequency",
        "scan_seanses_once",
        "was_processed",
        "mark_processed",
        "save_all_from_dir",
        "import_folder",
        "import_folder_with_client",
        "import_folder_incremental",
    ]
    parts.append("__all__ = [")
    for n in public:
        parts.append(f'    "{n}",')
    parts.append("]")
    parts.append("")
    OUT.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    ast.parse(OUT.read_text(encoding="utf-8"))
    print("wrote seans_write.py", sum(1 for _ in OUT.open(encoding="utf-8")), "lines")

    remove: set[int] = set()
    for name in NAMES:
        n = nodes[name]
        remove.update(range(n.lineno, (n.end_lineno or n.lineno) + 1))
    lines = src.splitlines(keepends=True)
    text = "".join(ln for i, ln in enumerate(lines, 1) if i not in remove)
    while "\n\n\n\n" in text:
        text = text.replace("\n\n\n\n", "\n\n\n")

    reexport = """

# --- seans write/scan/import (physically extracted) ---
from web_portal.lib.db.seans_write import (  # noqa: E402,F401
    _delete_conflicting_tt_seans_rows,
    _parse_seans_date_time_value,
    _processed_files_key,
    _save_seans_batch,
    _save_seans_batch_with_client,
    import_folder,
    import_folder_incremental,
    import_folder_with_client,
    mark_processed,
    max_seans_date_times_by_frequency,
    save_all_from_dir,
    save_seans_entries,
    scan_seanses_once,
    seans_entries_fully_in_database,
    was_processed,
)
"""
    if "# --- seans archive slice" in text:
        text = text.replace(
            "# --- seans archive slice",
            reexport.strip() + "\n\n# --- seans archive slice",
        )
    else:
        text = text.rstrip() + "\n" + reexport
    IMPL.write_text(text.rstrip() + "\n", encoding="utf-8")
    ast.parse(IMPL.read_text(encoding="utf-8"))
    print("updated _impl.py", sum(1 for _ in IMPL.open(encoding="utf-8")), "lines")

    new_facade = '''"""Сеансы: схема, архив, запись/скан, запросы.

Физически: ``seans_schema``, ``seans_archive``, ``seans_write``; запросы — ``_impl``.
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
from web_portal.lib.db.stats import (  # noqa: F401
    _seanses_period_has_rows,
    _seans_sessions_total_for_days,
    _seans_network_pairs_for_days,
)
from web_portal.lib.db._impl import (  # noqa: F401
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
    print("updated seans.py")

    misc = MISC_FACADE.read_text(encoding="utf-8")
    old = """from web_portal.lib.db._impl import (  # noqa: F401
    add_ai_feedback,
    get_network_intensity_clusters,
    get_network_intensity_clusters_dual,
    get_network_intensity_clusters_dual_daily,
    get_analysis_assignments,
    set_analysis_assignment,
    list_analysis_assignments_since,
    was_processed,
    mark_processed,
    save_all_from_dir,
    import_folder,
    import_folder_with_client,
    import_folder_incremental,
    format_ids,
"""
    new = """from web_portal.lib.db.seans_write import (  # noqa: F401
    was_processed,
    mark_processed,
    save_all_from_dir,
    import_folder,
    import_folder_with_client,
    import_folder_incremental,
)
from web_portal.lib.db.stats import format_ids  # noqa: F401
from web_portal.lib.db._impl import (  # noqa: F401
    add_ai_feedback,
    get_network_intensity_clusters,
    get_network_intensity_clusters_dual,
    get_network_intensity_clusters_dual_daily,
    get_analysis_assignments,
    set_analysis_assignment,
    list_analysis_assignments_since,
"""
    if old not in misc:
        raise SystemExit("misc.py block not found")
    # remove format_ids from remaining _impl import if still there
    misc2 = misc.replace(old, new)
    misc2 = misc2.replace("    format_ids,\n", "")
    MISC_FACADE.write_text(misc2, encoding="utf-8")
    print("updated misc.py")

    init_py = ROOT / "lib" / "db" / "__init__.py"
    text_init = init_py.read_text(encoding="utf-8")
    text_init = text_init.replace(
        "``seans_archive``, ``stats`` вынесены физически; остальные — фасады над ``_impl``.",
        "``seans_archive``, ``seans_write``, ``stats`` вынесены физически;\n"
        "остальные — фасады над ``_impl``.",
    )
    init_py.write_text(text_init, encoding="utf-8")


if __name__ == "__main__":
    main()
