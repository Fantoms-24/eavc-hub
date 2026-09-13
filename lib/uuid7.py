"""Генерация UUIDv7 (RFC 9562, §5.7).

В стандартную библиотеку `uuid.uuid7()` вошёл только в Python 3.14, проект
работает на 3.12. Здесь повторён алгоритм CPython, чтобы после обновления
интерпретатора модуль сводился к вызову стандартной функции без изменения
формата уже выданных идентификаторов.

Раскладка 128 бит:

    --- 48 ---   -- 4 --   --- 12 ---   -- 2 --   --- 30 ---   - 32 -
    unix_ts_ms | version | counter_hi | variant | counter_lo | random

`counter` — 42-битный счётчик (метод 1 из RFC 9562, §6.2) со сброшенным
старшим битом, он обеспечивает монотонность внутри одной миллисекунды.
"""

from __future__ import annotations

import os
import threading
import time
import uuid as _uuid

_VERSION_7_FLAGS = (7 << 76) | (0x8000 << 48)

_COUNTER_MAX = 0x3FF_FFFF_FFFF  # 2**42 - 1
_COUNTER_SEED_MASK = 0x1FF_FFFF_FFFF  # 41 бит: старший бит счётчика остаётся 0

# В CPython защиты от гонки нет (см. gh-89083), но у нас идентификаторы выдаются
# из потоков Flask и фонового синхронизатора, поэтому блокировка обязательна:
# иначе два потока в одной миллисекунде получили бы один и тот же счётчик.
_lock = threading.Lock()
_last_timestamp_ms: int | None = None
_last_counter: int = 0


def _seed_counter_and_tail() -> tuple[int, int]:
    rand = int.from_bytes(os.urandom(10), "big")
    return (rand >> 32) & _COUNTER_SEED_MASK, rand & 0xFFFF_FFFF


def uuid7() -> _uuid.UUID:
    """Новый UUID версии 7, монотонный в пределах процесса."""
    global _last_timestamp_ms, _last_counter

    with _lock:
        timestamp_ms = time.time_ns() // 1_000_000
        if _last_timestamp_ms is None or timestamp_ms > _last_timestamp_ms:
            counter, tail = _seed_counter_and_tail()
        else:
            # Часы могли уйти назад (перевод времени, NTP) — не даём порядку сломаться.
            if timestamp_ms < _last_timestamp_ms:
                timestamp_ms = _last_timestamp_ms + 1
            counter = _last_counter + 1
            if counter > _COUNTER_MAX:
                timestamp_ms += 1
                counter, tail = _seed_counter_and_tail()
            else:
                tail = int.from_bytes(os.urandom(4), "big")

        _last_timestamp_ms = timestamp_ms
        _last_counter = counter

    value = (timestamp_ms & 0xFFFF_FFFF_FFFF) << 80
    value |= (counter >> 30) << 64
    value |= (counter & 0x3FFF_FFFF) << 32
    value |= tail
    value |= _VERSION_7_FLAGS
    return _uuid.UUID(int=value)


def new_uuid7() -> str:
    """UUIDv7 строкой — основной способ обращения из кода проекта."""
    return str(uuid7())


def uuid7_timestamp_ms(value: str | _uuid.UUID) -> int:
    """Момент создания идентификатора в миллисекундах Unix.

    Нужен при разборе инцидентов: позволяет отличить блок, созданный только
    что, от блока, живущего с начала смены, даже если `created_at` перезаписан.
    """
    u = value if isinstance(value, _uuid.UUID) else _uuid.UUID(str(value))
    if u.version != 7:
        raise ValueError(f"ожидался UUID версии 7, получен {u.version}")
    return u.int >> 80
