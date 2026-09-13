"""Physically extract connection domain from lib/db/_impl.py."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "lib" / "db" / "_impl.py"
CONN = ROOT / "lib" / "db" / "connection.py"

FUNC_NAMES = [
    "optimize_connection",
    "connect",
    "_conn_schema_key",
    "_schema_ready_for_conn",
    "set_connection_defer_commit",
    "connection_defer_commit_active",
    "finish_connection_defer_commit",
    "unregister_connection",
    "_commit_if_needed",
    "_conn_has_table",
    "_conn_has_core_schema",
    "init_db",
    "ensure_db",
    "list_db_files",
]

STATE_NAMES = [
    "_sqlite_optimize_once_lock",
    "_sqlite_optimize_once_done",
    "_SCHEMA_READY_PATHS",
    "_CONN_INIT_IDS",
    "_CONN_SCHEMA_KEYS_BY_ID",
    "_CONN_DEFER_COMMIT_IDS",
    "_CONN_DEFER_COMMIT_LOCK",
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
    block = "".join(f"    {imp}\n" for imp in imports)
    lines[idx:idx] = [block]
    return "".join(lines)


def main() -> None:
    src = IMPL.read_text(encoding="utf-8")
    tree = ast.parse(src)

    nodes: dict[str, ast.AST] = {}
    assigns: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nodes[node.name] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in STATE_NAMES:
                    assigns[t.id] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in STATE_NAMES:
                assigns[node.target.id] = node

    missing = [n for n in FUNC_NAMES if n not in nodes]
    if missing:
        raise SystemExit(f"missing funcs: {missing}")
    missing_s = [n for n in STATE_NAMES if n not in assigns]
    if missing_s:
        raise SystemExit(f"missing state: {missing_s}")

    parts = [
        '"""Подключение SQLite, schema bootstrap, defer-commit."""',
        "from __future__ import annotations",
        "",
        "import logging",
        "import os",
        "import sqlite3",
        "import threading",
        "import time",
        "from pathlib import Path",
        "",
        '_log = logging.getLogger("web_portal.db")',
        "",
        "# Process-wide connection / schema caches",
    ]
    # state in stable order
    for name in STATE_NAMES:
        parts.append(src_of(src, assigns[name]).rstrip())
        parts.append("")

    for name in FUNC_NAMES:
        body = src_of(src, nodes[name])
        lazy: list[str] = []
        if name == "init_db":
            lazy = [
                "from web_portal.lib.db._impl import init_online_search",
                "from web_portal.lib.db._impl import init_intercepts",
                "from web_portal.lib.db._impl import _migrate_intercepts_sync_fields",
                "from web_portal.lib.db.sync import init_sync",
            ]
        if lazy:
            body = inject_lazy(body, lazy)
        parts.append(body.rstrip())
        parts.append("")
        parts.append("")

    parts.append("__all__ = [")
    for n in [
        "optimize_connection",
        "connect",
        "set_connection_defer_commit",
        "connection_defer_commit_active",
        "finish_connection_defer_commit",
        "unregister_connection",
        "_commit_if_needed",
        "init_db",
        "ensure_db",
        "list_db_files",
        "_SCHEMA_READY_PATHS",
    ]:
        parts.append(f'    "{n}",')
    parts.append("]")
    parts.append("")

    CONN.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    ast.parse(CONN.read_text(encoding="utf-8"))
    print("wrote connection.py")

    # Remove from _impl
    remove: set[int] = set()
    for name in FUNC_NAMES:
        node = nodes[name]
        remove.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    for name in STATE_NAMES:
        node = assigns[name]
        remove.update(
            range(node.lineno, (getattr(node, "end_lineno", None) or node.lineno) + 1)
        )
    # also remove optimize globals comment block lines 27-29 if present
    lines = src.splitlines(keepends=True)
    new_lines = [ln for i, ln in enumerate(lines, 1) if i not in remove]
    text = "".join(new_lines)
    # strip orphaned optimize comment if left alone
    text = re.sub(
        r"\n# PRAGMA optimize[^\n]*\n(?:_sqlite_optimize[^\n]*\n){0,2}",
        "\n",
        text,
        count=1,
    )
    while "\n\n\n\n" in text:
        text = text.replace("\n\n\n\n", "\n\n\n")

    reexport = """

# --- connection domain (physically extracted) ---
from web_portal.lib.db.connection import (  # noqa: E402,F401
    _CONN_DEFER_COMMIT_IDS,
    _CONN_DEFER_COMMIT_LOCK,
    _CONN_INIT_IDS,
    _CONN_SCHEMA_KEYS_BY_ID,
    _SCHEMA_READY_PATHS,
    _commit_if_needed,
    _conn_has_core_schema,
    _conn_has_table,
    _conn_schema_key,
    _schema_ready_for_conn,
    _sqlite_optimize_once_done,
    _sqlite_optimize_once_lock,
    connect,
    connection_defer_commit_active,
    ensure_db,
    finish_connection_defer_commit,
    init_db,
    list_db_files,
    optimize_connection,
    set_connection_defer_commit,
    unregister_connection,
)
"""
    # Insert connection re-export before sync re-export if present, else append
    if "# --- Domain modules (physically extracted) ---" in text:
        text = text.replace(
            "# --- Domain modules (physically extracted) ---",
            reexport.strip() + "\n\n# --- Domain modules (physically extracted) ---",
        )
    else:
        text = text.rstrip() + "\n" + reexport

    IMPL.write_text(text.rstrip() + "\n", encoding="utf-8")
    ast.parse(IMPL.read_text(encoding="utf-8"))
    print("updated _impl.py")

    # Fix sync/ai lazy imports to use connection for init_db / _commit_if_needed
    for mod_name in ("sync", "ai"):
        p = ROOT / "lib" / "db" / f"{mod_name}.py"
        t = p.read_text(encoding="utf-8")
        t2 = t.replace(
            "from web_portal.lib.db._impl import init_db",
            "from web_portal.lib.db.connection import init_db",
        )
        t2 = t2.replace(
            "from web_portal.lib.db._impl import _commit_if_needed",
            "from web_portal.lib.db.connection import _commit_if_needed",
        )
        if t2 != t:
            p.write_text(t2, encoding="utf-8")
            print(f"updated lazy imports in {mod_name}.py")
            ast.parse(t2)


if __name__ == "__main__":
    main()
