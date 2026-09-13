"""Регрессия на реальных данных: сборка текста из блоков не меняет ни один бланк.

Пока `intercept_items.content` остаётся источником для всех выгрузок (Word, поиск,
отчёты, сводный бланк за день), сборка текста из блоков обязана совпадать с тем,
что даёт текущий путь сохранения, байт в байт. Иначе переход на блоки был бы тихой
порчей данных, которую заметил бы только оператор в готовом документе.

Тест берёт настоящие бланки из `data/main.sqlite` — активные и архивные — и для
каждого сравнивает два результата:

* что записывает в базу production-функция `replace_intercept_item_content`;
* что даёт сборка из разобранных блоков `compose_content(parse_blocks(...))`.

Если файла базы нет (другая машина, CI), тест пропускается.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from web_portal.lib.db import (
    get_or_create_intercept_item,
    init_db,
    replace_intercept_item_content,
    upsert_intercept_catalog,
)
from web_portal.lib.intercept_blocks import compose_content, parse_blocks

REAL_DB = Path(__file__).resolve().parent.parent / "data" / "main.sqlite"

pytestmark = pytest.mark.skipif(
    not REAL_DB.exists(), reason=f"нет реальной базы {REAL_DB}"
)


def _load_real_rows() -> list[tuple[str, str, str]]:
    """(источник, текст бланка, время старта смены) по всем непустым бланкам."""
    uri = f"file:{REAL_DB.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        rows: list[tuple[str, str, str]] = []
        for table, sessions in (
            ("intercept_items", "intercept_sessions"),
            ("intercept_items_archive", "intercept_sessions_archive"),
        ):
            try:
                found = conn.execute(
                    f"""
                    SELECT i.content AS content, s.started_at AS started_at
                    FROM {table} i
                    LEFT JOIN {sessions} s ON s.id = i.session_id
                    WHERE TRIM(COALESCE(i.content, '')) <> ''
                    """
                ).fetchall()
            except sqlite3.Error:
                continue
            for r in found:
                rows.append(
                    (table, str(r["content"] or ""), str(r["started_at"] or ""))
                )
        return rows
    finally:
        conn.close()


def _base_min(started_at: str) -> int | None:
    from datetime import datetime

    s = str(started_at or "").strip()
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return dt.hour * 60 + dt.minute


@pytest.fixture(scope="module")
def real_rows() -> list[tuple[str, str, str]]:
    rows = _load_real_rows()
    if not rows:
        pytest.skip("в реальной базе нет непустых бланков")
    return rows


@pytest.fixture(scope="module")
def scratch() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    return c


def _store_via_production_path(
    conn: sqlite3.Connection, *, index: int, content: str, started_at: str
) -> str:
    """Прогоняет текст через настоящий путь сохранения и возвращает записанное."""
    position = "regression-pos"
    freq = f"{index}.0000"
    group = f"g{index}"
    cur = conn.execute(
        """
        INSERT INTO intercept_sessions (position_name, uuid, started_at)
        VALUES (?, ?, ?)
        """,
        (position, f"regress-sess-{index}", started_at or "2026-01-01 08:00:00"),
    )
    session_id = int(cur.lastrowid)
    catalog_id = upsert_intercept_catalog(
        conn,
        position_name=position,
        unit_name=f"unit-{index}",
        frequency=freq,
        group_code=group,
    )
    if isinstance(catalog_id, dict):
        catalog_id = int(catalog_id.get("id") or 0)
    item = get_or_create_intercept_item(
        conn, session_id=session_id, catalog_id=int(catalog_id)
    )
    item_id = int(item["id"])
    replace_intercept_item_content(conn, item_id, content, "regression")
    row = conn.execute(
        "SELECT content FROM intercept_items WHERE id=?", (item_id,)
    ).fetchone()
    return str(row["content"] or "")


def test_compose_matches_production_save_on_every_real_blank(
    real_rows: list[tuple[str, str, str]], scratch: sqlite3.Connection
) -> None:
    mismatches: list[str] = []
    total_blocks = 0

    for index, (table, content, started_at) in enumerate(real_rows):
        stored = _store_via_production_path(
            scratch, index=index, content=content, started_at=started_at
        )
        blocks = parse_blocks(content)
        total_blocks += len(blocks)
        rebuilt = compose_content(blocks, base_min=_base_min(started_at))
        if rebuilt != stored:
            mismatches.append(
                f"{table}[{index}]: сборка из блоков расходится с сохранением\n"
                f"  сохранено: {stored[:200]!r}\n"
                f"  собрано:   {rebuilt[:200]!r}"
            )

    assert total_blocks > 0, "ни одного блока не разобрано — проверка бессмысленна"
    print(
        f"\nпроверено бланков: {len(real_rows)}, блоков: {total_blocks}, "
        f"расхождений: {len(mismatches)}"
    )
    assert not mismatches, "\n".join(mismatches[:5])


def test_parse_is_stable_on_real_data(real_rows: list[tuple[str, str, str]]) -> None:
    """Повторный разбор уже собранного текста даёт то же самое."""
    unstable: list[str] = []
    for index, (table, content, started_at) in enumerate(real_rows):
        base = _base_min(started_at)
        once = compose_content(parse_blocks(content), base_min=base)
        twice = compose_content(parse_blocks(once), base_min=base)
        if once != twice:
            unstable.append(f"{table}[{index}]: разбор не устойчив при повторе")
    assert not unstable, "\n".join(unstable[:5])


def test_every_real_block_keeps_its_text(
    real_rows: list[tuple[str, str, str]]
) -> None:
    """Ни один блок не теряет содержимое при разборе."""
    losses: list[str] = []
    for index, (table, content, _started) in enumerate(real_rows):
        blocks = parse_blocks(content)
        for b in blocks:
            if not b.text.strip():
                losses.append(f"{table}[{index}]: пустой блок после разбора")
            if b.time_key is not None and not b.header:
                losses.append(f"{table}[{index}]: блок со временем потерял заголовок")
    assert not losses, "\n".join(losses[:5])
