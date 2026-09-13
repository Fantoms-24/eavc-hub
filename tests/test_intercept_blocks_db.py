"""Блоки бланка в базе: сохранение, правка, удаление, жизненный цикл."""

from __future__ import annotations

import sqlite3

import pytest

from web_portal.lib.db import (
    get_or_create_intercept_item,
    init_db,
    list_intercept_item_blocks,
    replace_intercept_item_content,
    update_intercept_item_content,
    upsert_intercept_catalog,
)


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    return c


POS = "test-pos"


def make_item(
    conn: sqlite3.Connection,
    *,
    freq: str = "162.0000",
    group: str = "53525",
    unit: str = "1 мб 155 омбр",
    started_at: str = "2026-07-30 08:00:00",
) -> int:
    cur = conn.execute(
        """
        INSERT INTO intercept_sessions (position_name, uuid, started_at)
        VALUES (?, ?, ?)
        """,
        (POS, f"sess-{freq}-{group}", started_at),
    )
    session_id = int(cur.lastrowid)
    catalog_id = upsert_intercept_catalog(
        conn,
        position_name=POS,
        unit_name=unit,
        frequency=freq,
        group_code=group,
    )
    if isinstance(catalog_id, dict):
        catalog_id = int(catalog_id.get("id") or 0)
    item = get_or_create_intercept_item(
        conn, session_id=session_id, catalog_id=int(catalog_id)
    )
    return int(item["id"])


def bodies(conn: sqlite3.Connection, item_id: int) -> list[str]:
    return [b["body"] for b in list_intercept_item_blocks(conn, item_id=item_id)]


def uuid_by_body(conn: sqlite3.Connection, item_id: int, needle: str) -> str:
    for b in list_intercept_item_blocks(conn, item_id=item_id):
        if needle in b["body"]:
            return b["uuid"]
    raise AssertionError(f"блок с текстом {needle!r} не найден")


def test_save_creates_blocks_with_uuid7(conn: sqlite3.Connection) -> None:
    item_id = make_item(conn)
    replace_intercept_item_content(
        conn, item_id, "13.45\n-Привет. (1)\n14.10\n-Ответ. (2)", "operator"
    )
    blocks = list_intercept_item_blocks(conn, item_id=item_id)
    assert len(blocks) == 2
    assert [b["header"] for b in blocks] == ["13.45", "14.10"]
    for b in blocks:
        import uuid as _uuid

        assert _uuid.UUID(b["uuid"]).version == 7
    assert blocks[0]["item_uuid"], "блок не привязан к записи бланка"


def test_edit_keeps_block_uuid(conn: sqlite3.Connection) -> None:
    item_id = make_item(conn)
    replace_intercept_item_content(
        conn, item_id, "13.45\n-Привет. (1)\n14.10\n-Ответ. (2)", "operator"
    )
    before = uuid_by_body(conn, item_id, "-Ответ. (2)")

    replace_intercept_item_content(
        conn, item_id, "13.45\n-Привет. (1)\n14.10\n-Ответ исправлен. (2)", "operator"
    )
    after = uuid_by_body(conn, item_id, "-Ответ исправлен. (2)")
    assert after == before, "правка текста сменила личность блока"
    assert len(list_intercept_item_blocks(conn, item_id=item_id)) == 2


def test_time_correction_keeps_block_uuid(conn: sqlite3.Connection) -> None:
    item_id = make_item(conn)
    replace_intercept_item_content(conn, item_id, "13.45\n-Привет. (1)", "operator")
    before = uuid_by_body(conn, item_id, "-Привет. (1)")

    replace_intercept_item_content(conn, item_id, "13.46\n-Привет. (1)", "operator")
    blocks = list_intercept_item_blocks(conn, item_id=item_id)
    assert len(blocks) == 1
    assert blocks[0]["uuid"] == before, "исправление времени сменило личность блока"
    assert blocks[0]["header"] == "13.46"


def test_delete_block_tombstones_it(conn: sqlite3.Connection) -> None:
    item_id = make_item(conn)
    replace_intercept_item_content(
        conn, item_id, "13.00\n-Раз. (1)\n14.00\n-Два. (2)\n15.00\n-Три. (3)", "operator"
    )
    dead = uuid_by_body(conn, item_id, "-Два. (2)")

    replace_intercept_item_content(
        conn, item_id, "13.00\n-Раз. (1)\n15.00\n-Три. (3)", "operator"
    )
    assert bodies(conn, item_id) == ["-Раз. (1)", "-Три. (3)"]
    row = conn.execute(
        "SELECT deleted_at FROM intercept_blocks WHERE uuid=?", (dead,)
    ).fetchone()
    assert row is not None and row["deleted_at"], "удалённый блок не получил надгробие"


def test_deleted_block_does_not_return(conn: sqlite3.Connection) -> None:
    item_id = make_item(conn)
    replace_intercept_item_content(
        conn, item_id, "13.00\n-Раз. (1)\n14.00\n-Два. (2)", "operator"
    )
    replace_intercept_item_content(conn, item_id, "13.00\n-Раз. (1)", "operator")
    replace_intercept_item_content(conn, item_id, "13.00\n-Раз. (1)", "operator")
    assert bodies(conn, item_id) == ["-Раз. (1)"]
    r = conn.execute(
        "SELECT content FROM intercept_items WHERE id=?", (item_id,)
    ).fetchone()
    assert "-Два. (2)" not in str(r["content"])


def test_full_clear_removes_all_blocks(conn: sqlite3.Connection) -> None:
    item_id = make_item(conn)
    replace_intercept_item_content(
        conn, item_id, "13.00\n-Раз. (1)\n14.00\n-Два. (2)", "operator"
    )
    replace_intercept_item_content(conn, item_id, "", "operator")
    assert list_intercept_item_blocks(conn, item_id=item_id) == []


def test_blocks_ordered_by_time_not_by_creation(conn: sqlite3.Connection) -> None:
    """UUIDv7 растёт по моменту создания, а порядок в бланке — по времени перехвата."""
    item_id = make_item(conn)
    replace_intercept_item_content(conn, item_id, "14.00\n-Позже. (2)", "operator")
    replace_intercept_item_content(
        conn, item_id, "14.00\n-Позже. (2)\n13.00\n-Раньше. (1)", "operator"
    )
    blocks = list_intercept_item_blocks(conn, item_id=item_id)
    assert [b["header"] for b in blocks] == ["13.00", "14.00"]
    assert [b["ord"] for b in blocks] == [0, 1]
    # Блок за 13.00 создан позже, значит его UUID «больше» — порядок берётся не оттуда.
    assert blocks[0]["uuid"] > blocks[1]["uuid"]


def test_duplicate_time_blocks_are_separate_rows(conn: sqlite3.Connection) -> None:
    item_id = make_item(conn)
    replace_intercept_item_content(
        conn, item_id, "12.00\n-Первый. (1)\n12.00\n-Второй. (2)", "operator"
    )
    blocks = list_intercept_item_blocks(conn, item_id=item_id)
    assert len(blocks) == 2
    assert len({b["uuid"] for b in blocks}) == 2


def test_insert_above_duplicate_time_keeps_old_identity(
    conn: sqlite3.Connection,
) -> None:
    item_id = make_item(conn)
    replace_intercept_item_content(conn, item_id, "12.00\n-Старый. (1)", "operator")
    old = uuid_by_body(conn, item_id, "-Старый. (1)")

    replace_intercept_item_content(
        conn, item_id, "12.00\n-Новый. (2)\n12.00\n-Старый. (1)", "operator"
    )
    assert uuid_by_body(conn, item_id, "-Старый. (1)") == old
    assert len(list_intercept_item_blocks(conn, item_id=item_id)) == 2


def test_merge_path_also_maintains_blocks(conn: sqlite3.Connection) -> None:
    item_id = make_item(conn)
    replace_intercept_item_content(conn, item_id, "13.00\n-Раз. (1)", "operator")
    kept = uuid_by_body(conn, item_id, "-Раз. (1)")

    update_intercept_item_content(
        conn, item_id, "13.00\n-Раз. (1)\n14.00\n-Два. (2)", "operator2"
    )
    blocks = list_intercept_item_blocks(conn, item_id=item_id)
    assert len(blocks) == 2
    assert uuid_by_body(conn, item_id, "-Раз. (1)") == kept


def test_blocks_match_stored_content(conn: sqlite3.Connection) -> None:
    """Текст бланка и блоки не должны расходиться."""
    from web_portal.lib.intercept_blocks import compose_content, parse_blocks

    item_id = make_item(conn, started_at="2026-07-30 08:00:00")
    replace_intercept_item_content(
        conn,
        item_id,
        "Пометка\n15.00\n-Три. (3)\n13.00\n-Раз. (1)\n14.00\n-Два. (2)",
        "operator",
    )
    stored = str(
        conn.execute(
            "SELECT content FROM intercept_items WHERE id=?", (item_id,)
        ).fetchone()["content"]
    )
    blocks = list_intercept_item_blocks(conn, item_id=item_id)
    rebuilt = compose_content(parse_blocks(stored), base_min=8 * 60)
    assert rebuilt == stored
    assert len(blocks) == len(parse_blocks(stored))


def test_bulk_unit_delete_removes_blocks(conn: sqlite3.Connection) -> None:
    from web_portal.application.intercepts.catalog_mutations import (
        execute_intercepts_catalog_delete_unit,
    )

    item_id = make_item(conn, unit="Подразделение под удаление")
    replace_intercept_item_content(conn, item_id, "13.00\n-Раз. (1)", "operator")
    assert list_intercept_item_blocks(conn, item_id=item_id)

    execute_intercepts_catalog_delete_unit(
        conn,
        position_name=POS,
        unit_name="Подразделение под удаление",
        hub_sync_enabled=False,
        schedule_hub_push_in_background=None,
    )
    left = conn.execute(
        "SELECT COUNT(*) AS n FROM intercept_blocks WHERE item_id=?", (item_id,)
    ).fetchone()
    assert int(left["n"]) == 0, "блоки остались сиротами после удаления подразделения"


def test_backfill_creates_blocks_for_existing_content() -> None:
    """Существующая база с текстом бланков: блоки заводятся миграцией."""
    from web_portal.lib.db import _migrate_intercept_blocks_backfill

    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    item_id = make_item(c)
    # Пишем текст напрямую, минуя пути сохранения — как в уже существующей базе.
    # Дальше обращаемся к таблице голым SQL: list_intercept_item_blocks вызывает
    # init_db, а тот сам прогнал бы миграцию и скрыл проверяемое поведение.
    c.execute(
        "UPDATE intercept_items SET content=? WHERE id=?",
        ("13.00\n-Раз. (1)\n14.00\n-Два. (2)\n", item_id),
    )
    c.execute("DELETE FROM intercept_blocks WHERE item_id=?", (item_id,))
    c.commit()

    def live() -> list[str]:
        rows = c.execute(
            """
            SELECT header FROM intercept_blocks
            WHERE item_id=? AND deleted_at IS NULL
            ORDER BY ord
            """,
            (item_id,),
        ).fetchall()
        return [str(r["header"]) for r in rows]

    assert live() == []

    _migrate_intercept_blocks_backfill(c)
    assert live() == ["13.00", "14.00"]

    # Повторный прогон не должен создавать дублей.
    _migrate_intercept_blocks_backfill(c)
    assert live() == ["13.00", "14.00"]
