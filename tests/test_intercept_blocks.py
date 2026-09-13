from __future__ import annotations

from web_portal.lib.intercept_blocks import (
    ParsedBlock,
    StoredBlock,
    compose_content,
    parse_blocks,
    parse_time_key,
    reconcile,
)


def store(blocks: list[ParsedBlock], uuids: list[str]) -> list[StoredBlock]:
    """Превращает разобранные блоки в «уже лежащие в базе»."""
    assert len(blocks) == len(uuids)
    return [
        StoredBlock(
            uuid=u,
            time_key=b.time_key,
            header=b.header,
            body=b.body,
            ord=b.ord,
        )
        for b, u in zip(blocks, uuids)
    ]


def uuids_of(result) -> list[str | None]:
    return [r.uuid for r in result.resolved]


# ─── разбор ─────────────────────────────────────────────────────────


def test_parse_time_key_accepts_both_separators() -> None:
    assert parse_time_key("13.45") == 13 * 60 + 45
    assert parse_time_key("13:45") == 13 * 60 + 45
    assert parse_time_key(" 9.05 ") == 9 * 60 + 5
    assert parse_time_key("13.45 -Привет") is None
    assert parse_time_key("25.00") is None
    assert parse_time_key("13.60") is None
    assert parse_time_key("") is None


def test_parse_splits_by_time_headers() -> None:
    blocks = parse_blocks("13.45\n-Привет. (1)\n\n14.10\n-Ответ. (2)")
    assert len(blocks) == 2
    assert blocks[0].header == "13.45"
    assert blocks[0].body == "-Привет. (1)"
    assert blocks[1].header == "14.10"
    assert blocks[1].body == "-Ответ. (2)"


def test_parse_normalizes_colon_header() -> None:
    blocks = parse_blocks("13:45\n-Привет. (1)")
    assert blocks[0].header == "13.45"
    assert blocks[0].time_key == 13 * 60 + 45


def test_parse_keeps_preamble_as_block_without_time() -> None:
    blocks = parse_blocks("Служебная пометка\n13.45\n-Привет. (1)")
    assert len(blocks) == 2
    assert blocks[0].time_key is None
    assert blocks[0].body == "Служебная пометка"
    assert blocks[1].time_key == 13 * 60 + 45


def test_parse_drops_empty_blocks() -> None:
    assert parse_blocks("") == []
    assert parse_blocks("\n\n   \n") == []


def test_parse_keeps_header_only_block() -> None:
    blocks = parse_blocks("13.45\n\n")
    assert len(blocks) == 1
    assert blocks[0].header == "13.45"
    assert blocks[0].body == ""


# ─── сборка текста ──────────────────────────────────────────────────


def test_compose_sorts_by_time() -> None:
    blocks = parse_blocks("15.00\n-Позже. (2)\n14.00\n-Раньше. (1)")
    assert compose_content(blocks, base_min=None) == (
        "14.00\n-Раньше. (1)\n15.00\n-Позже. (2)\n"
    )


def test_compose_puts_block_without_time_last() -> None:
    blocks = parse_blocks("Пометка\n14.00\n-Раз. (1)")
    assert compose_content(blocks, base_min=None) == "14.00\n-Раз. (1)\nПометка\n"


def test_compose_handles_midnight_rollover() -> None:
    # Смена началась в 20.00: блок за 02.00 относится к следующим суткам.
    blocks = parse_blocks("02.00\n-Ночь. (1)\n21.00\n-Вечер. (2)")
    assert compose_content(blocks, base_min=20 * 60) == (
        "21.00\n-Вечер. (2)\n02.00\n-Ночь. (1)\n"
    )


def test_compose_of_empty_is_empty() -> None:
    assert compose_content([], base_min=None) == ""


def test_compose_is_idempotent() -> None:
    text = "13.45\n-Привет. (1)\n\n14.10\n-Ответ. (2)"
    once = compose_content(parse_blocks(text), base_min=None)
    twice = compose_content(parse_blocks(once), base_min=None)
    assert once == twice


# ─── сверка ─────────────────────────────────────────────────────────


def test_unchanged_blank_keeps_all_uuids() -> None:
    text = "13.45\n-Привет. (1)\n14.10\n-Ответ. (2)"
    existing = store(parse_blocks(text), ["a", "b"])
    res = reconcile(existing, parse_blocks(text))
    assert uuids_of(res) == ["a", "b"]
    assert res.removed == ()
    assert res.changed_count == 0
    assert res.created_count == 0


def test_text_edit_keeps_uuid() -> None:
    before = "13.45\n-Привет. (1)\n14.10\n-Ответ. (2)"
    after = "13.45\n-Привет. (1)\n14.10\n-Ответ исправлен. (2)"
    existing = store(parse_blocks(before), ["a", "b"])
    res = reconcile(existing, parse_blocks(after))
    assert uuids_of(res) == ["a", "b"]
    assert res.removed == ()
    assert res.resolved[0].changed is False
    assert res.resolved[1].changed is True


def test_time_correction_keeps_uuid() -> None:
    existing = store(parse_blocks("13.45\n-Привет. (1)"), ["a"])
    res = reconcile(existing, parse_blocks("13.46\n-Привет. (1)"))
    assert uuids_of(res) == ["a"]
    assert res.removed == ()
    assert res.resolved[0].changed is True


def test_new_block_gets_no_uuid_and_others_untouched() -> None:
    existing = store(parse_blocks("13.45\n-Раз. (1)\n14.10\n-Два. (2)"), ["a", "b"])
    res = reconcile(
        existing, parse_blocks("13.45\n-Раз. (1)\n14.10\n-Два. (2)\n15.00\n-Три. (3)")
    )
    assert uuids_of(res) == ["a", "b", None]
    assert res.removed == ()
    assert res.created_count == 1


def test_insert_in_middle_keeps_neighbours() -> None:
    existing = store(parse_blocks("13.00\n-Раз. (1)\n15.00\n-Три. (3)"), ["a", "c"])
    res = reconcile(
        existing, parse_blocks("13.00\n-Раз. (1)\n14.00\n-Два. (2)\n15.00\n-Три. (3)")
    )
    assert uuids_of(res) == ["a", None, "c"]
    assert res.removed == ()


def test_deleted_block_is_tombstoned() -> None:
    existing = store(
        parse_blocks("13.00\n-Раз. (1)\n14.00\n-Два. (2)\n15.00\n-Три. (3)"),
        ["a", "b", "c"],
    )
    res = reconcile(existing, parse_blocks("13.00\n-Раз. (1)\n15.00\n-Три. (3)"))
    assert uuids_of(res) == ["a", "c"]
    assert res.removed == ("b",)


def test_full_clear_removes_everything() -> None:
    existing = store(parse_blocks("13.00\n-Раз. (1)\n14.00\n-Два. (2)"), ["a", "b"])
    res = reconcile(existing, parse_blocks(""))
    assert res.resolved == ()
    assert set(res.removed) == {"a", "b"}


def test_deleted_block_does_not_come_back() -> None:
    # Именно этот случай раньше возвращал удалённые строки в бланк.
    existing = store(parse_blocks("13.00\n-Раз. (1)\n14.00\n-Два. (2)"), ["a", "b"])
    incoming = parse_blocks("13.00\n-Раз. (1)")
    res = reconcile(existing, incoming)
    text = compose_content([r.block for r in res.resolved], base_min=None)
    assert "-Два. (2)" not in text
    assert res.removed == ("b",)


# ─── одинаковое время у двух блоков ─────────────────────────────────


def test_duplicate_time_both_kept_separately() -> None:
    text = "12.00\n-Первый. (1)\n12.00\n-Второй. (2)"
    blocks = parse_blocks(text)
    assert len(blocks) == 2
    existing = store(blocks, ["a", "b"])
    res = reconcile(existing, parse_blocks(text))
    assert uuids_of(res) == ["a", "b"]


def test_duplicate_time_edit_hits_the_right_block() -> None:
    existing = store(parse_blocks("12.00\n-Первый. (1)\n12.00\n-Второй. (2)"), ["a", "b"])
    res = reconcile(
        existing, parse_blocks("12.00\n-Первый. (1)\n12.00\n-Второй правленый. (2)")
    )
    assert uuids_of(res) == ["a", "b"]
    assert res.resolved[0].changed is False
    assert res.resolved[1].changed is True


def test_duplicate_time_reorder_does_not_swap_identities() -> None:
    # Оператор переставил блоки с одинаковым временем местами.
    existing = store(parse_blocks("12.00\n-Первый. (1)\n12.00\n-Второй. (2)"), ["a", "b"])
    res = reconcile(
        existing, parse_blocks("12.00\n-Второй. (2)\n12.00\n-Первый. (1)")
    )
    assert uuids_of(res) == ["b", "a"], "личности блоков перепутаны при перестановке"
    assert res.removed == ()


def test_duplicate_time_insert_above_does_not_steal_identity() -> None:
    """Вставка блока с тем же временем выше существующего.

    Именно здесь текстовые ключи вида `12.00#2` раньше сдвигались, и сообщение
    в Telegram получало чужой текст.
    """
    existing = store(parse_blocks("12.00\n-Старый. (1)"), ["a"])
    res = reconcile(existing, parse_blocks("12.00\n-Новый. (2)\n12.00\n-Старый. (1)"))
    assert uuids_of(res) == [None, "a"], "новый блок забрал личность существующего"
    assert res.removed == ()


def test_duplicate_time_insert_above_with_edit_prefers_similar_text() -> None:
    # Одновременно вставлен новый блок и правлен старый: узнаём по сходству текста.
    existing = store(parse_blocks("12.00\n-Старый текст про колонну. (1)"), ["a"])
    res = reconcile(
        existing,
        parse_blocks(
            "12.00\n-Совсем другое сообщение. (9)\n"
            "12.00\n-Старый текст про колонну, уточнено. (1)"
        ),
    )
    assert uuids_of(res) == [None, "a"]
    assert res.removed == ()


# ─── что сверка делать не должна ────────────────────────────────────


def test_unrelated_replacement_is_not_matched_across_times() -> None:
    """Полностью другой блок в другое время — это новый блок, а не правка.

    Ложное узнавание привело бы к затиранию сообщения в Telegram, поэтому такой
    случай сознательно решается как «удалить старый, создать новый».
    """
    existing = store(parse_blocks("09.00\n-Работа техники в квадрате. (1)"), ["a"])
    res = reconcile(existing, parse_blocks("21.00\n-Смена частоты связи. (7)"))
    assert uuids_of(res) == [None]
    assert res.removed == ("a",)


def test_reconcile_from_scratch_creates_all() -> None:
    res = reconcile([], parse_blocks("13.00\n-Раз. (1)\n14.00\n-Два. (2)"))
    assert uuids_of(res) == [None, None]
    assert res.removed == ()


def test_no_uuid_is_used_twice() -> None:
    existing = store(
        parse_blocks("12.00\n-Раз. (1)\n12.00\n-Два. (2)\n12.00\n-Три. (3)"),
        ["a", "b", "c"],
    )
    res = reconcile(existing, parse_blocks("12.00\n-Раз правлен. (1)"))
    assigned = [u for u in uuids_of(res) if u]
    assert len(assigned) == len(set(assigned))
    assert len(assigned) + len(res.removed) == 3
