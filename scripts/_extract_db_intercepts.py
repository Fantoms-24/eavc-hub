"""Extract sql_util + full intercepts domain from lib/db/_impl.py."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "lib" / "db" / "_impl.py"
SQL_UTIL = ROOT / "lib" / "db" / "sql_util.py"
OUT = ROOT / "lib" / "db" / "intercepts.py"
CONN = ROOT / "lib" / "db" / "connection.py"
UNITS = ROOT / "lib" / "db" / "units.py"
STATS = ROOT / "lib" / "db" / "stats.py"
SEANS_QUERY = ROOT / "lib" / "db" / "seans_query.py"

SQL_NAMES = [
    "_table_columns",
    "_pick_first",
    "_normalize_positions",
    "_in_clause",
]

EXTRA_INTERCEPT = [
    "_os_norm_freq",
    "_extract_last_time_block",
]


def src_of(src: str, node: ast.AST) -> str:
    seg = ast.get_source_segment(src, node)
    if seg is None:
        raise RuntimeError("no source")
    return seg.rstrip() + "\n"


def facade_import_names() -> list[str]:
    tree = ast.parse(OUT.read_text(encoding="utf-8") if OUT.exists() else "")
    # Prefer current facade content before overwrite — read from backup path pattern
    fac = (ROOT / "lib" / "db" / "intercepts.py").read_text(encoding="utf-8")
    tree = ast.parse(fac)
    names: list[str] = []
    for n in tree.body:
        if isinstance(n, ast.ImportFrom) and n.module and n.module.endswith("_impl"):
            names.extend(a.name for a in n.names if a.name != "annotations")
    return names


def main() -> None:
    src = IMPL.read_text(encoding="utf-8")
    tree = ast.parse(src)
    nodes = {
        n.name: n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    # --- sql_util ---
    for name in SQL_NAMES:
        if name not in nodes:
            raise SystemExit(f"missing sql helper {name}")
    sql_parts = [
        '"""Мелкие SQL-хелперы (общие для доменов)."""',
        "from __future__ import annotations",
        "",
        "import sqlite3",
        "",
        "",
    ]
    for name in SQL_NAMES:
        sql_parts.append(src_of(src, nodes[name]))
        sql_parts.append("")
    sql_parts.append("__all__ = [")
    for n in SQL_NAMES:
        sql_parts.append(f'    "{n}",')
    sql_parts.append("]")
    sql_parts.append("")
    SQL_UTIL.write_text("\n".join(sql_parts).rstrip() + "\n", encoding="utf-8")
    ast.parse(SQL_UTIL.read_text(encoding="utf-8"))
    print("wrote sql_util.py")

    # --- intercepts names from current facade ---
    fac_text = OUT.read_text(encoding="utf-8")
    fac_tree = ast.parse(fac_text)
    intercept_names: list[str] = []
    for n in fac_tree.body:
        if isinstance(n, ast.ImportFrom) and n.module and n.module.endswith("_impl"):
            intercept_names.extend(
                a.name for a in n.names if a.name != "annotations"
            )
    intercept_names = intercept_names + [
        x for x in EXTRA_INTERCEPT if x not in intercept_names
    ]
    # Stable order by lineno
    intercept_names = sorted(intercept_names, key=lambda n: nodes[n].lineno)
    missing = [n for n in intercept_names if n not in nodes]
    if missing:
        raise SystemExit(f"missing intercepts: {missing}")

    parts = [
        '"""Каталог/смены/пункты перехватов (физически из ``_impl``)."""',
        "from __future__ import annotations",
        "",
        "import logging",
        "import re",
        "import sqlite3",
        "from typing import Any",
        "",
        "from web_portal.lib.intercept_blocks import (",
        "    StoredBlock,",
        "    day_offset as _block_day_offset,",
        "    parse_blocks as _parse_intercept_blocks,",
        "    reconcile as _reconcile_intercept_blocks,",
        "    sort_key as _block_sort_key,",
        ")",
        "from web_portal.lib.uuid7 import new_uuid7",
        "",
        "from web_portal.lib.db.ai import init_ai_tables",
        "from web_portal.lib.db.connection import _commit_if_needed, init_db",
        "from web_portal.lib.db.seans_schema import _table_exists, init_daily_aggregates",
        "from web_portal.lib.db.sql_util import _in_clause, _table_columns",
        "from web_portal.lib.db.sync import _sync_blocks_quietly",
        "",
        '_log = logging.getLogger("web_portal.db")',
        "",
        "",
    ]
    for name in intercept_names:
        parts.append(src_of(src, nodes[name]))
        parts.append("")

    # Keep previous public __all__ from facade
    public: list[str] = []
    for n in fac_tree.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == "__all__":
                    public = [elt.value for elt in n.value.elts]  # type: ignore[attr-defined]
    if not public:
        public = [n for n in intercept_names if not n.startswith("_")]
    parts.append("__all__ = [")
    for n in public:
        parts.append(f'    "{n}",')
    parts.append("]")
    parts.append("")
    OUT.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    ast.parse(OUT.read_text(encoding="utf-8"))
    print("wrote intercepts.py", sum(1 for _ in OUT.open(encoding="utf-8")), "lines")

    # Remove extracted from _impl
    remove: set[int] = set()
    for name in SQL_NAMES + intercept_names:
        n = nodes[name]
        remove.update(range(n.lineno, (n.end_lineno or n.lineno) + 1))
    lines = src.splitlines(keepends=True)
    text = "".join(ln for i, ln in enumerate(lines, 1) if i not in remove)
    while "\n\n\n\n" in text:
        text = text.replace("\n\n\n\n", "\n\n\n")

    # Drop unused intercept_blocks / uuid7 imports from _impl if present
    # (may still be unused — keep uuid7 if needed elsewhere)
    if "new_uuid7" not in text.split("from web_portal.lib.uuid7")[0] and "new_uuid7(" not in text:
        # remove uuid7 import block
        text2 = []
        skip = False
        for ln in text.splitlines(keepends=True):
            if ln.startswith("from web_portal.lib.uuid7 import"):
                continue
            if ln.startswith("from web_portal.lib.intercept_blocks import"):
                skip = True
                continue
            if skip:
                if ln.startswith(")") or ln.strip() == ")":
                    skip = False
                continue
            text2.append(ln)
        text = "".join(text2)

    ix_lines = "\n".join(f"    {n}," for n in sorted(intercept_names))
    reexport = f"""

# --- sql_util (physically extracted) ---
from web_portal.lib.db.sql_util import (  # noqa: E402,F401
    _in_clause,
    _normalize_positions,
    _pick_first,
    _table_columns,
)

# --- intercepts domain (physically extracted) ---
from web_portal.lib.db.intercepts import (  # noqa: E402,F401
{ix_lines}
)
"""
    if "# --- online_search domain" in text:
        text = text.replace(
            "# --- online_search domain",
            reexport.strip() + "\n\n# --- online_search domain",
        )
    else:
        text = text.rstrip() + "\n" + reexport
    IMPL.write_text(text.rstrip() + "\n", encoding="utf-8")
    # Validate remaining file parses; fix reexport if symbol missing
    try:
        ast.parse(IMPL.read_text(encoding="utf-8"))
    except SyntaxError as e:
        raise SystemExit(f"_impl syntax error: {e}")
    print("updated _impl.py", sum(1 for _ in IMPL.open(encoding="utf-8")), "lines")

    # connection
    conn = CONN.read_text(encoding="utf-8")
    conn = conn.replace(
        "from web_portal.lib.db._impl import init_intercepts\n"
        "    from web_portal.lib.db._impl import _migrate_intercepts_sync_fields",
        "from web_portal.lib.db.intercepts import init_intercepts, _migrate_intercepts_sync_fields",
    )
    CONN.write_text(conn, encoding="utf-8")
    print("updated connection.py")

    # units
    units = UNITS.read_text(encoding="utf-8")
    units = units.replace(
        "from web_portal.lib.db._impl import _pick_first, _table_columns",
        "from web_portal.lib.db.sql_util import _pick_first, _table_columns",
    )
    units = units.replace(
        "from web_portal.lib.db._impl import _get_last_recorded_intercept_by_freq_group",
        "from web_portal.lib.db.intercepts import _get_last_recorded_intercept_by_freq_group",
    )
    UNITS.write_text(units, encoding="utf-8")
    print("updated units.py")

    # stats
    stats = STATS.read_text(encoding="utf-8")
    stats = stats.replace(
        "from web_portal.lib.db._impl import _pick_first, _table_columns",
        "from web_portal.lib.db.sql_util import _pick_first, _table_columns",
    )
    STATS.write_text(stats, encoding="utf-8")
    print("updated stats.py")

    # seans_query
    sq = SEANS_QUERY.read_text(encoding="utf-8")
    sq = sq.replace(
        "from web_portal.lib.db._impl import _in_clause",
        "from web_portal.lib.db.sql_util import _in_clause",
    )
    SEANS_QUERY.write_text(sq, encoding="utf-8")
    print("updated seans_query.py")

    # seans_archive clear/archive may lazy _table_columns
    arch = (ROOT / "lib" / "db" / "seans_archive.py").read_text(encoding="utf-8")
    if "from web_portal.lib.db._impl import _table_columns" in arch:
        (ROOT / "lib" / "db" / "seans_archive.py").write_text(
            arch.replace(
                "from web_portal.lib.db._impl import _table_columns",
                "from web_portal.lib.db.sql_util import _table_columns",
            ),
            encoding="utf-8",
        )
        print("updated seans_archive.py")

    init_py = ROOT / "lib" / "db" / "__init__.py"
    text_init = init_py.read_text(encoding="utf-8")
    text_init = text_init.replace(
        "``seans_*``, ``stats``, ``units``, ``online_search`` вынесены физически;\n"
        "остальные — фасады над ``_impl``.",
        "``seans_*``, ``stats``, ``units``, ``online_search``, ``intercepts``,\n"
        "``sql_util`` вынесены физически; в ``_impl`` — analysis/ASR/map и т.п.",
    )
    init_py.write_text(text_init, encoding="utf-8")


if __name__ == "__main__":
    main()
