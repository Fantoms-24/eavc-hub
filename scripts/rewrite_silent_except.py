"""Одноразовый скрипт: замена молчаливых `except Exception:/except:` + `pass`
на `_log.debug(..., exc_info=True)`.

Только пары "except-строка" -> следующая строка ровно `pass`.
Целевые классы: bare except, Exception, BaseException (с `as e` или без).
Типизированные подавления (sqlite3.OperationalError и т.п.) не трогаем —
это осознанные миграционные паттерны.

Запуск: python scripts/rewrite_silent_except.py app.py lib/db.py ...
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

EXCEPT_RE = re.compile(
    r"^(\s*)except(\s*|\s+(Exception|BaseException)(\s+as\s+\w+)?\s*)?:\s*(#.*)?$"
)
PASS_RE = re.compile(r"^(\s*)pass\s*$")
DEF_RE = re.compile(r"^(\s*)(?:async\s+)?def\s+(\w+)")


def enclosing_func(lines: list[str], idx: int, indent: int) -> str:
    for j in range(idx - 1, -1, -1):
        m = DEF_RE.match(lines[j])
        if m and len(m.group(1)) < indent:
            return m.group(2)
    return "module"


def logger_name_for(path: Path) -> str:
    parts = list(path.with_suffix("").parts)
    return "web_portal." + ".".join(p for p in parts if p not in (".", ""))


def ensure_logger(lines: list[str], path: Path) -> bool:
    """Добавляет `import logging` и `_log = logging.getLogger(...)` при отсутствии.

    Точка вставки определяется по AST (end_lineno последнего top-level
    импорта), чтобы не попасть внутрь многострочного `from x import (...)`.
    """
    src = "".join(lines)
    if re.search(r"^_log\s*=", src, re.M):
        return False
    tree = ast.parse(src)
    has_import = any(
        isinstance(n, ast.Import) and any(a.name == "logging" for a in n.names)
        for n in tree.body
    )
    last_import_end = 0
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            last_import_end = max(last_import_end, n.end_lineno or n.lineno)
    insert_at = last_import_end  # индекс строки ПОСЛЕ последнего импорта (0-based)
    block = []
    if not has_import:
        block.append("import logging\n")
    block.append("\n")
    block.append(f'_log = logging.getLogger("{logger_name_for(path)}")\n')
    lines[insert_at:insert_at] = block
    return True


def process(path: Path) -> int:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = 0
    for i in range(len(lines) - 1):
        m_exc = EXCEPT_RE.match(lines[i].rstrip("\n"))
        if not m_exc:
            continue
        m_pass = PASS_RE.match(lines[i + 1].rstrip("\n"))
        if not m_pass:
            continue
        exc_indent = len(m_exc.group(1))
        pass_indent = m_pass.group(1)
        if len(pass_indent) <= exc_indent:
            continue
        func = enclosing_func(lines, i, exc_indent)
        lines[i + 1] = (
            f'{pass_indent}_log.debug("{func}: suppressed error", exc_info=True)\n'
        )
        changed += 1
    if changed:
        ensure_logger(lines, path)
        path.write_text("".join(lines), encoding="utf-8")
    return changed


if __name__ == "__main__":
    total = 0
    for arg in sys.argv[1:]:
        p = Path(arg)
        n = process(p)
        print(f"{p}: {n} replacements")
        total += n
    print(f"TOTAL: {total}")
