from __future__ import annotations

import uuid

import pytest

from web_portal.lib.uuid7 import new_uuid7, uuid7, uuid7_timestamp_ms


def test_version_and_variant() -> None:
    for _ in range(200):
        u = uuid7()
        assert u.version == 7
        # вариант RFC 4122/9562: старшие биты 8-го байта равны 0b10
        assert (u.int >> 62) & 0b11 == 0b10


def test_string_form_is_parseable() -> None:
    s = new_uuid7()
    assert uuid.UUID(s).version == 7
    assert len(s) == 36


def test_monotonic_within_same_millisecond() -> None:
    # Генерируем заведомо быстрее, чем тикает миллисекунда.
    values = [uuid7().int for _ in range(5000)]
    assert values == sorted(values), "порядок выдачи нарушен"
    assert len(set(values)) == len(values), "выданы повторяющиеся идентификаторы"


def test_lexicographic_order_matches_numeric_order() -> None:
    strings = [str(uuid7()) for _ in range(1000)]
    assert strings == sorted(strings)


def test_timestamp_is_recoverable() -> None:
    import time

    before = time.time_ns() // 1_000_000
    u = uuid7()
    after = time.time_ns() // 1_000_000
    ts = uuid7_timestamp_ms(u)
    assert before <= ts <= after + 1


def test_timestamp_rejects_other_versions() -> None:
    with pytest.raises(ValueError):
        uuid7_timestamp_ms(str(uuid.uuid4()))
