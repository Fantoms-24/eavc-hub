"""Physically extract units domain into lib/db/units.py."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "lib" / "db" / "_impl.py"
OUT = ROOT / "lib" / "db" / "units.py"
STATS = ROOT / "lib" / "db" / "stats.py"

NAMES = [
    "_normalize_frequency_key",
    "_extract_gid_tokens",
    "_normalize_group_text",
    "_sql_freq_zone_expr",
    "freq_zone_for_sessions_merge",
    "sessions_favorite_matches_row",
    "build_sessions_favorite_match_set",
    "sessions_row_is_favorite",
    "apply_search_note_to_unit",
    "update_unit_name",
    "_unit_map_legacy",
    "_unit_row_score",
    "_build_unit_name_map_for_pairs",
    "_get_unit_name_for_pair",
    "get_pairs_for_unit_name",
    "canonical_intensity_unit_key",
    "_is_unknown_intensity_unit_name",
    "list_units_tree",
    "_unit_map",
    "get_sessions_favorites",
    "add_sessions_favorite",
    "remove_sessions_favorite",
    "_norm_unit_note",
    "parse_note_unit_parent_child",
    "_try_loose_child_prefix",
    "_unit_parent_groups_file",
    "load_unit_parent_manual_groups",
    "get_unit_family_by_parent_key",
    "match_callsign_for_corr",
    "list_unit_rows_after_rowid",
    "list_unit_rows_since",
    "list_dict_frequencies",
    "list_dict_units",
    "list_dict_callsigns",
]

LAZY: dict[str, list[str]] = {
    "_unit_map_legacy": [
        "from web_portal.lib.db._impl import _pick_first, _table_columns",
    ],
    "get_unit_family_by_parent_key": [
        "from web_portal.lib.db._impl import list_online_search_unit_families",
    ],
    "list_dict_frequencies": [
        "from web_portal.lib.db._impl import _get_last_recorded_intercept_by_freq_group",
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
        '"""Подразделения, избранное, частоты (физически из ``_impl``)."""',
        "from __future__ import annotations",
        "",
        "import sqlite3",
        "from pathlib import Path",
        "from typing import Any",
        "",
        "from web_portal.lib.db.connection import init_db",
        "",
        "",
    ]
    for name in NAMES:
        body = src_of(src, nodes[name])
        if name in LAZY:
            body = inject_lazy(body, LAZY[name])
        parts.append(body)
        parts.append("")

    public = [
        "freq_zone_for_sessions_merge",
        "sessions_favorite_matches_row",
        "build_sessions_favorite_match_set",
        "sessions_row_is_favorite",
        "apply_search_note_to_unit",
        "update_unit_name",
        "get_pairs_for_unit_name",
        "canonical_intensity_unit_key",
        "list_units_tree",
        "get_sessions_favorites",
        "add_sessions_favorite",
        "remove_sessions_favorite",
        "parse_note_unit_parent_child",
        "load_unit_parent_manual_groups",
        "get_unit_family_by_parent_key",
        "match_callsign_for_corr",
        "list_unit_rows_after_rowid",
        "list_unit_rows_since",
        "list_dict_frequencies",
        "list_dict_units",
        "list_dict_callsigns",
    ]
    parts.append("__all__ = [")
    for n in public:
        parts.append(f'    "{n}",')
    parts.append("]")
    parts.append("")
    OUT.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    ast.parse(OUT.read_text(encoding="utf-8"))
    print("wrote units.py", sum(1 for _ in OUT.open(encoding="utf-8")), "lines")

    remove: set[int] = set()
    for name in NAMES:
        n = nodes[name]
        remove.update(range(n.lineno, (n.end_lineno or n.lineno) + 1))
    lines = src.splitlines(keepends=True)
    text = "".join(ln for i, ln in enumerate(lines, 1) if i not in remove)
    while "\n\n\n\n" in text:
        text = text.replace("\n\n\n\n", "\n\n\n")

    reexport = """

# --- units domain (physically extracted) ---
from web_portal.lib.db.units import (  # noqa: E402,F401
    _build_unit_name_map_for_pairs,
    _extract_gid_tokens,
    _get_unit_name_for_pair,
    _is_unknown_intensity_unit_name,
    _norm_unit_note,
    _normalize_frequency_key,
    _normalize_group_text,
    _sql_freq_zone_expr,
    _try_loose_child_prefix,
    _unit_map,
    _unit_map_legacy,
    _unit_parent_groups_file,
    _unit_row_score,
    add_sessions_favorite,
    apply_search_note_to_unit,
    build_sessions_favorite_match_set,
    canonical_intensity_unit_key,
    freq_zone_for_sessions_merge,
    get_pairs_for_unit_name,
    get_sessions_favorites,
    get_unit_family_by_parent_key,
    list_dict_callsigns,
    list_dict_frequencies,
    list_dict_units,
    list_unit_rows_after_rowid,
    list_unit_rows_since,
    list_units_tree,
    load_unit_parent_manual_groups,
    match_callsign_for_corr,
    parse_note_unit_parent_child,
    remove_sessions_favorite,
    sessions_favorite_matches_row,
    sessions_row_is_favorite,
    update_unit_name,
)
"""
    if "# --- seans query slice" in text:
        text = text.replace(
            "# --- seans query slice",
            reexport.strip() + "\n\n# --- seans query slice",
        )
    else:
        text = text.rstrip() + "\n" + reexport
    IMPL.write_text(text.rstrip() + "\n", encoding="utf-8")
    ast.parse(IMPL.read_text(encoding="utf-8"))
    print("updated _impl.py", sum(1 for _ in IMPL.open(encoding="utf-8")), "lines")

    # Point stats lazy imports at units for moved helpers
    stats = STATS.read_text(encoding="utf-8")
    stats = stats.replace(
        "from web_portal.lib.db._impl import _build_unit_name_map_for_pairs, _sql_freq_zone_expr",
        "from web_portal.lib.db.units import _build_unit_name_map_for_pairs, _sql_freq_zone_expr",
    )
    stats = stats.replace(
        "from web_portal.lib.db._impl import _build_unit_name_map_for_pairs",
        "from web_portal.lib.db.units import _build_unit_name_map_for_pairs",
    )
    stats = stats.replace(
        "from web_portal.lib.db._impl import _sql_freq_zone_expr",
        "from web_portal.lib.db.units import _sql_freq_zone_expr",
    )
    stats = stats.replace(
        "from web_portal.lib.db._impl import _date_only_window, _sql_freq_zone_expr",
        "from web_portal.lib.db._impl import _date_only_window\n"
        "    from web_portal.lib.db.units import _sql_freq_zone_expr",
    )
    stats = stats.replace(
        "from web_portal.lib.db._impl import _pick_first, _table_columns, _unit_map_legacy",
        "from web_portal.lib.db._impl import _pick_first, _table_columns\n"
        "    from web_portal.lib.db.units import _unit_map_legacy",
    )
    STATS.write_text(stats, encoding="utf-8")
    ast.parse(STATS.read_text(encoding="utf-8"))
    print("updated stats.py lazy imports")

    init_py = ROOT / "lib" / "db" / "__init__.py"
    text_init = init_py.read_text(encoding="utf-8")
    text_init = text_init.replace(
        "``seans_*``, ``stats`` вынесены физически; остальные — фасады над ``_impl``.",
        "``seans_*``, ``stats``, ``units`` вынесены физически; остальные — фасады над ``_impl``.",
    )
    init_py.write_text(text_init, encoding="utf-8")


if __name__ == "__main__":
    main()
