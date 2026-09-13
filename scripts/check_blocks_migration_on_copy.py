"""Проверка миграции блоков на копии настоящей базы.

Оригинал не трогается: файл копируется во временную папку, миграция прогоняется
на копии, результат сверяется с текстом бланков. Запуск:

    python scripts/check_blocks_migration_on_copy.py
"""

from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))

from web_portal.lib.db import init_db  # noqa: E402
from web_portal.lib.intercept_blocks import parse_blocks  # noqa: E402


def main() -> int:
    src = ROOT / "data" / "main.sqlite"
    if not src.exists():
        print(f"нет базы {src}")
        return 1

    tmp_dir = Path(tempfile.mkdtemp(prefix="blocks-migration-"))
    dst = tmp_dir / "main.sqlite"
    try:
        size_mb = src.stat().st_size / (1024 * 1024)
        print(f"копирую {src.name} ({size_mb:.0f} МБ) -> {dst}")
        t0 = time.time()
        shutil.copy2(src, dst)
        print(f"копия готова за {time.time() - t0:.1f} с")

        conn = sqlite3.connect(str(dst), timeout=60)
        conn.row_factory = sqlite3.Row

        t0 = time.time()
        init_db(conn)
        print(f"init_db (вместе с миграцией блоков) занял {time.time() - t0:.2f} с")

        items = conn.execute(
            """
            SELECT i.id AS id, i.uuid AS uuid, i.content AS content,
                   i.frequency AS frequency, i.group_code AS group_code,
                   s.started_at AS started_at
            FROM intercept_items i
            LEFT JOIN intercept_sessions s ON s.id = i.session_id
            WHERE TRIM(COALESCE(i.content, '')) <> ''
            ORDER BY i.id
            """
        ).fetchall()
        print(f"\nактивных бланков с текстом: {len(items)}")

        problems: list[str] = []
        total_blocks = 0
        for it in items:
            rows = conn.execute(
                """
                SELECT uuid, header, body, time_key, ord
                FROM intercept_blocks
                WHERE item_id=? AND deleted_at IS NULL
                ORDER BY day_offset, (time_key IS NULL), time_key, ord
                """,
                (int(it["id"]),),
            ).fetchall()
            expected = parse_blocks(str(it["content"] or ""))
            total_blocks += len(rows)

            label = f"{it['frequency']}/{it['group_code']}"
            if len(rows) != len(expected):
                problems.append(
                    f"{label}: блоков в базе {len(rows)}, в тексте {len(expected)}"
                )
                continue
            for got, want in zip(rows, expected):
                if str(got["header"]) != want.header or str(got["body"]) != want.body:
                    problems.append(f"{label}: блок {got['header']!r} не совпал с текстом")
                    break
            versions = {
                __import__("uuid").UUID(str(r["uuid"])).version for r in rows
            }
            if versions - {7}:
                problems.append(f"{label}: не все блоки на UUIDv7: {versions}")
            print(f"  {label}: {len(rows)} блоков")

        print(f"\nвсего блоков создано: {total_blocks}")

        # Текст бланков не должен измениться от миграции.
        changed = []
        ref = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True, timeout=30)
        ref.row_factory = sqlite3.Row
        try:
            for it in items:
                orig = ref.execute(
                    "SELECT content FROM intercept_items WHERE id=?", (int(it["id"]),)
                ).fetchone()
                if orig is None:
                    continue
                if str(orig["content"] or "") != str(it["content"] or ""):
                    changed.append(f"{it['frequency']}/{it['group_code']}")
        finally:
            ref.close()

        if changed:
            problems.append("миграция изменила текст бланков: " + ", ".join(changed))
        else:
            print("текст бланков не изменился ни в одной записи")

        # Повторный init_db не должен создавать дублей.
        before = int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM intercept_blocks WHERE deleted_at IS NULL"
            ).fetchone()["n"]
        )
        from web_portal.lib.db import _migrate_intercept_blocks_backfill

        _migrate_intercept_blocks_backfill(conn)
        after = int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM intercept_blocks WHERE deleted_at IS NULL"
            ).fetchone()["n"]
        )
        if before != after:
            problems.append(f"повторная миграция создала дубли: {before} -> {after}")
        else:
            print(f"повторный прогон миграции не создал дублей ({after} блоков)")

        conn.close()

        print()
        if problems:
            print("ПРОБЛЕМЫ:")
            for p in problems:
                print(f"  - {p}")
            return 1
        print("Всё сошлось.")
        return 0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
