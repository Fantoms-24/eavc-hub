"""Physically extract online_search domain into lib/db/online_search.py."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "lib" / "db" / "_impl.py"
OUT = ROOT / "lib" / "db" / "online_search.py"
CONN = ROOT / "lib" / "db" / "connection.py"
UNITS = ROOT / "lib" / "db" / "units.py"
MISC = ROOT / "lib" / "db" / "misc.py"

NAMES = [
    "_ensure_online_search_unit_profile",
    "init_online_search",
    "set_online_search_headers",
    "get_online_search_headers",
    "get_online_search_meta",
    "get_online_search_meta_payload",
    "upsert_online_search_meta_from_sync",
    "sync_units_from_online_search",
    "list_online_search",
    "_row_to_online_search_dict",
    "get_online_search_unit_profile",
    "upsert_online_search_unit_profile",
    "set_online_search_unit_profile",
    "set_online_search_unit_avatar",
    "list_online_search_rows_by_unit_key",
    "count_online_search_by_unit_key",
    "_parent_merge_key",
    "_child_label_sort",
    "merge_families_by_manual_groups",
    "list_online_search_unit_families",
    "list_online_search_unit_avatar_files",
    "list_archive_freq_by_note",
    "list_online_search_ids_for_note_pair",
    "list_distinct_online_search_units",
    "upsert_online_search_row",
    "update_online_search_note",
    "delete_online_search_row",
    "list_online_search_rows_after",
    "upsert_online_search_rows_from_sync",
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
        '"""Поиск онлайн и unit profiles (физически из ``_impl``)."""',
        "from __future__ import annotations",
        "",
        "import re",
        "import sqlite3",
        "from typing import Any",
        "",
        "from web_portal.lib.db.connection import (",
        "    _commit_if_needed,",
        "    _conn_has_table,",
        "    _schema_ready_for_conn,",
        "    init_db,",
        ")",
        "from web_portal.lib.db.seans_query import list_distinct_seans_frequency_groups",
        "from web_portal.lib.db.units import (",
        "    _extract_gid_tokens,",
        "    _norm_unit_note,",
        "    _normalize_frequency_key,",
        "    _normalize_group_text,",
        "    load_unit_parent_manual_groups,",
        "    parse_note_unit_parent_child,",
        ")",
        "",
        "",
    ]
    for name in NAMES:
        parts.append(src_of(src, nodes[name]))
        parts.append("")

    public = [
        "init_online_search",
        "set_online_search_headers",
        "get_online_search_headers",
        "get_online_search_meta",
        "get_online_search_meta_payload",
        "upsert_online_search_meta_from_sync",
        "sync_units_from_online_search",
        "list_online_search",
        "get_online_search_unit_profile",
        "upsert_online_search_unit_profile",
        "set_online_search_unit_profile",
        "set_online_search_unit_avatar",
        "list_online_search_rows_by_unit_key",
        "count_online_search_by_unit_key",
        "list_online_search_unit_families",
        "list_online_search_unit_avatar_files",
        "list_online_search_ids_for_note_pair",
        "list_distinct_online_search_units",
        "upsert_online_search_row",
        "update_online_search_note",
        "delete_online_search_row",
        "list_online_search_rows_after",
        "upsert_online_search_rows_from_sync",
        "merge_families_by_manual_groups",
        "list_archive_freq_by_note",
    ]
    parts.append("__all__ = [")
    for n in public:
        parts.append(f'    "{n}",')
    parts.append("]")
    parts.append("")
    OUT.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    ast.parse(OUT.read_text(encoding="utf-8"))
    print("wrote online_search.py", sum(1 for _ in OUT.open(encoding="utf-8")), "lines")

    remove: set[int] = set()
    for name in NAMES:
        n = nodes[name]
        remove.update(range(n.lineno, (n.end_lineno or n.lineno) + 1))
    lines = src.splitlines(keepends=True)
    text = "".join(ln for i, ln in enumerate(lines, 1) if i not in remove)
    while "\n\n\n\n" in text:
        text = text.replace("\n\n\n\n", "\n\n\n")

    reexport = """

# --- online_search domain (physically extracted) ---
from web_portal.lib.db.online_search import (  # noqa: E402,F401
    _child_label_sort,
    _ensure_online_search_unit_profile,
    _parent_merge_key,
    _row_to_online_search_dict,
    count_online_search_by_unit_key,
    delete_online_search_row,
    get_online_search_headers,
    get_online_search_meta,
    get_online_search_meta_payload,
    get_online_search_unit_profile,
    init_online_search,
    list_archive_freq_by_note,
    list_distinct_online_search_units,
    list_online_search,
    list_online_search_ids_for_note_pair,
    list_online_search_rows_after,
    list_online_search_rows_by_unit_key,
    list_online_search_unit_avatar_files,
    list_online_search_unit_families,
    merge_families_by_manual_groups,
    set_online_search_headers,
    set_online_search_unit_avatar,
    set_online_search_unit_profile,
    sync_units_from_online_search,
    update_online_search_note,
    upsert_online_search_meta_from_sync,
    upsert_online_search_row,
    upsert_online_search_rows_from_sync,
    upsert_online_search_unit_profile,
)
"""
    if "# --- units domain" in text:
        text = text.replace(
            "# --- units domain",
            reexport.strip() + "\n\n# --- units domain",
        )
    else:
        text = text.rstrip() + "\n" + reexport
    IMPL.write_text(text.rstrip() + "\n", encoding="utf-8")
    ast.parse(IMPL.read_text(encoding="utf-8"))
    print("updated _impl.py", sum(1 for _ in IMPL.open(encoding="utf-8")), "lines")

    # connection: import init_online_search from real module
    conn = CONN.read_text(encoding="utf-8")
    conn2 = conn.replace(
        "from web_portal.lib.db._impl import init_online_search",
        "from web_portal.lib.db.online_search import init_online_search",
    )
    if conn2 == conn:
        raise SystemExit("connection.py init_online_search import not found")
    CONN.write_text(conn2, encoding="utf-8")
    print("updated connection.py")

    units = UNITS.read_text(encoding="utf-8")
    units2 = units.replace(
        "from web_portal.lib.db._impl import list_online_search_unit_families",
        "from web_portal.lib.db.online_search import list_online_search_unit_families",
    )
    if units2 == units:
        raise SystemExit("units.py list_online_search_unit_families import not found")
    UNITS.write_text(units2, encoding="utf-8")
    print("updated units.py")

    misc = MISC.read_text(encoding="utf-8")
    old = """from web_portal.lib.db._impl import (  # noqa: F401
    add_ai_feedback,
    get_network_intensity_clusters,
    get_network_intensity_clusters_dual,
    get_network_intensity_clusters_dual_daily,
    get_analysis_assignments,
    set_analysis_assignment,
    list_analysis_assignments_since,
"""
    # Pull merge/archive from online_search; keep rest from _impl
    if "merge_families_by_manual_groups" in misc and "from web_portal.lib.db.online_search" not in misc:
        misc = misc.replace(
            "from web_portal.lib.db.seans_write import (  # noqa: F401\n",
            "from web_portal.lib.db.online_search import (  # noqa: F401\n"
            "    merge_families_by_manual_groups,\n"
            "    list_archive_freq_by_note,\n"
            ")\n"
            "from web_portal.lib.db.seans_write import (  # noqa: F401\n",
        )
        for line in (
            "    merge_families_by_manual_groups,\n",
            "    list_archive_freq_by_note,\n",
        ):
            # remove from _impl import block only (last occurrences in import)
            pass
        # remove from _impl import if present
        misc = misc.replace("    merge_families_by_manual_groups,\n", "")
        misc = misc.replace("    list_archive_freq_by_note,\n", "")
        # restore the online_search import lines we just wiped
        if "from web_portal.lib.db.online_search import" not in misc:
            raise SystemExit("misc online_search import lost")
        # The wipe also removed from online_search block — rebuild carefully
    MISC.write_text(
        '''"""Прочие операции данных.

Часть импорта/семейств — ``online_search`` / ``seans_write``; остальное — ``_impl``.
"""
from __future__ import annotations

from web_portal.lib.db.online_search import (  # noqa: F401
    merge_families_by_manual_groups,
    list_archive_freq_by_note,
)
from web_portal.lib.db.seans_write import (  # noqa: F401
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
    add_asr_train_sample,
    list_asr_train_samples,
    create_asr_training_run,
    finish_asr_training_run,
    upsert_asr_model,
    list_asr_models,
    activate_asr_model,
    get_active_asr_model,
    get_asr_settings,
    set_asr_settings,
    add_asr_feedback,
    count_asr_feedback,
    get_map_shared_objects,
    get_map_shared_objects_all,
    save_map_shared_objects,
)

__all__ = [
    "add_ai_feedback",
    "get_network_intensity_clusters",
    "get_network_intensity_clusters_dual",
    "get_network_intensity_clusters_dual_daily",
    "get_analysis_assignments",
    "set_analysis_assignment",
    "list_analysis_assignments_since",
    "was_processed",
    "mark_processed",
    "save_all_from_dir",
    "import_folder",
    "import_folder_with_client",
    "import_folder_incremental",
    "format_ids",
    "add_asr_train_sample",
    "list_asr_train_samples",
    "create_asr_training_run",
    "finish_asr_training_run",
    "upsert_asr_model",
    "list_asr_models",
    "activate_asr_model",
    "get_active_asr_model",
    "get_asr_settings",
    "set_asr_settings",
    "add_asr_feedback",
    "count_asr_feedback",
    "get_map_shared_objects",
    "get_map_shared_objects_all",
    "save_map_shared_objects",
    "merge_families_by_manual_groups",
    "list_archive_freq_by_note",
]
''',
        encoding="utf-8",
    )
    print("updated misc.py")

    init_py = ROOT / "lib" / "db" / "__init__.py"
    text_init = init_py.read_text(encoding="utf-8")
    text_init = text_init.replace(
        "``seans_*``, ``stats``, ``units`` вынесены физически; остальные — фасады над ``_impl``.",
        "``seans_*``, ``stats``, ``units``, ``online_search`` вынесены физически;\n"
        "остальные — фасады над ``_impl``.",
    )
    init_py.write_text(text_init, encoding="utf-8")


if __name__ == "__main__":
    main()
