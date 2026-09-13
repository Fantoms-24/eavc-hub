"""Запись / сканирование / импорт сеансов (физически из ``_impl``)."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from web_portal.lib.collect_seanses_from_dir import SeansEntry, collect_seanses_from
from web_portal.lib.db.connection import init_db
from web_portal.lib.db.seans_schema import (
    init_seans_tables,
    refresh_seanses_daily_aggregates_for_entries,
)

_log = logging.getLogger("web_portal.db")


def _delete_conflicting_tt_seans_rows(
    cur: sqlite3.Cursor,
    rows: list[SeansEntry],
    *,
    client_name: str | None = None,
) -> None:
    """
    Переимпорт после исправления парсера должен убрать старую ошибочную строку,
    где DMR Private call был сохранён как группа второго абонента.
    """
    tt_keys = {
        (str(e.date_time), str(e.frequency), str(e.id))
        for e in rows
        if str(e.group or "").strip().upper() == "T-T"
    }
    if not tt_keys:
        return
    if client_name:
        cur.executemany(
            """
            DELETE FROM seanses
            WHERE date_time=? AND frequency=? AND id=? AND group_!='T-T' AND client_name=?
            """,
            [(dt, freq, id_, str(client_name)) for dt, freq, id_ in tt_keys],
        )
    else:
        cur.executemany(
            """
            DELETE FROM seanses
            WHERE date_time=? AND frequency=? AND id=? AND group_!='T-T' AND client_name=''
            """,
            list(tt_keys),
        )


def _save_seans_batch(rows: list[SeansEntry], cur: sqlite3.Cursor) -> int:
    """
    Внутренняя функция для сохранения одного батча записей.
    Аналогично _save_seans_batch из основного проекта src/database.py.
    """
    if not rows:
        return 0

    _delete_conflicting_tt_seans_rows(cur, rows)
    values = [
        (
            entry.date_time,
            entry.frequency,
            entry.group,
            entry.id,
            entry.aes_key if entry.aes_key != "" else None,
            getattr(entry, "color_voice", None),
            getattr(entry, "time_seconds", None),
            "",
        )
        for entry in rows
    ]
    try:
        # избегаем перезаписи существующего aes_key значением None/NULL
        # ВАЖНО: НЕ обновляем created_at при конфликте, чтобы старые записи не становились "новыми"
        cur.executemany(
            """INSERT INTO seanses (date_time, frequency, group_, id, aes_key, color_voice, time_seconds, client_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (date_time, frequency, group_, id, client_name)
            DO UPDATE SET
            aes_key=COALESCE(excluded.aes_key, aes_key),
            color_voice=COALESCE(excluded.color_voice, color_voice),
            time_seconds=COALESCE(excluded.time_seconds, time_seconds);""",
            values,
        )
    except sqlite3.IntegrityError as e:
        import logging

        logger = logging.getLogger("web_portal.db")
        logger.warning(
            f"ERROR while _save_seans_batch {e} in batch of {len(rows)} records"
        )
        # При ошибке пробуем сохранить по одной записи для диагностики
        if len(rows) > 1:
            logger.debug("Attempting to save records individually for error diagnosis")
            for entry in rows:
                try:
                    _save_seans_batch([entry], cur)
                except Exception as single_error:
                    logger.error(
                        f"Failed to save single record {entry}: {single_error}"
                    )
    # SQLite не даёт точное число вставок при ON CONFLICT; считаем как размер батча
    return len(rows)


def _save_seans_batch_with_client(
    rows: list[SeansEntry], cur: sqlite3.Cursor, client_name: str
) -> int:
    if not rows:
        return 0
    _delete_conflicting_tt_seans_rows(cur, rows, client_name=client_name)
    values = [
        (
            entry.date_time,
            entry.frequency,
            entry.group,
            entry.id,
            entry.aes_key if entry.aes_key != "" else None,
            getattr(entry, "color_voice", None),
            getattr(entry, "time_seconds", None),
            client_name,
        )
        for entry in rows
    ]
    cur.executemany(
        """
        INSERT INTO seanses (date_time, frequency, group_, id, aes_key, color_voice, time_seconds, client_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (date_time, frequency, group_, id, client_name)
        DO UPDATE SET
          aes_key=COALESCE(excluded.aes_key, aes_key),
          color_voice=COALESCE(excluded.color_voice, color_voice),
          time_seconds=COALESCE(excluded.time_seconds, time_seconds);
        """,
        values,
    )
    return len(rows)


def save_seans_entries(
    conn: sqlite3.Connection,
    entries: list[SeansEntry],
    client_name: str | None = None,
    *,
    commit: bool = True,
) -> int:
    """
    Пишет список SeansEntry в seanses (UPSERT, без перезаписи aes_key значением NULL).
    Возвращает количество обработанных записей (не точное кол-во вставок).
    """
    if not entries:
        return 0
    normalized_client_name = str(client_name or "").strip()
    new_for_watch: list[SeansEntry] = []
    try:
        from web_portal.lib.sessions_id_watch import seans_entries_not_in_database

        new_for_watch = seans_entries_not_in_database(
            conn, entries, client_name=normalized_client_name
        )
    except Exception:
        new_for_watch = []
    init_seans_tables(conn)
    cur = conn.cursor()
    BATCH_SIZE = 500
    processed = 0
    if len(entries) > BATCH_SIZE:
        for i in range(0, len(entries), BATCH_SIZE):
            batch = entries[i : i + BATCH_SIZE]
            if normalized_client_name:
                processed += _save_seans_batch_with_client(batch, cur, normalized_client_name)
            else:
                processed += _save_seans_batch(batch, cur)
    else:
        if normalized_client_name:
            processed += _save_seans_batch_with_client(entries, cur, normalized_client_name)
        else:
            processed += _save_seans_batch(entries, cur)
    if new_for_watch:
        try:
            from web_portal.lib.seans_db import connection_path_is_seans_storage
            from web_portal.lib.sessions_id_watch import process_new_seans_for_watch

            watch_conn = None if connection_path_is_seans_storage(conn) else conn
            process_new_seans_for_watch(new_for_watch, main_conn=watch_conn)
        except Exception:
            import logging

            logging.getLogger("web_portal.db").exception(
                "sessions id watch notify failed"
            )
    if commit:
        conn.commit()
        refresh_seanses_daily_aggregates_for_entries(
            conn, entries, client_name=normalized_client_name
        )
    return processed


def _processed_files_key(path: str, position_name: str | None = None) -> str:
    """
    Ключ для processed_files.
    Важно: в "сеансах" обработка должна быть независима по позициям, поэтому
    включаем position_name в ключ (без изменения схемы таблицы).
    """
    p = str(path or "")
    pos = str(position_name or "").strip()
    return f"{pos}::{p}" if pos else p


def was_processed(
    conn: sqlite3.Connection,
    path: str,
    mtime: float,
    size: int,
    position_name: str | None = None,
) -> bool:
    """
    Проверяет, был ли файл уже обработан (аналогично основному проекту).
    Возвращает True, если файл уже обработан с теми же mtime и size.
    """
    init_seans_tables(conn)
    cur = conn.cursor()
    key = _processed_files_key(path, position_name)
    row = cur.execute(
        "SELECT mtime, size FROM processed_files WHERE path=?", (key,)
    ).fetchone()
    if not row:
        return False
    return (row[0] == mtime) and (row[1] == size)


def mark_processed(
    conn: sqlite3.Connection,
    path: str,
    mtime: float,
    size: int,
    position_name: str | None = None,
    *,
    commit: bool = True,
) -> None:
    """
    Помечает файл как обработанный (аналогично основному проекту).
    """
    init_seans_tables(conn)
    cur = conn.cursor()
    key = _processed_files_key(path, position_name)
    cur.execute(
        """
        INSERT INTO processed_files (path, mtime, size)
        VALUES (?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            mtime=excluded.mtime,
            size=excluded.size,
            processed_at=CURRENT_TIMESTAMP;
        """,
        (key, float(mtime), int(size)),
    )
    if commit:
        conn.commit()


def seans_entries_fully_in_database(
    conn: sqlite3.Connection, entries: list[SeansEntry], *, client_name: str | None = None
) -> bool:
    """
    True, если для каждой уникальной строки из result0 уже есть строка в seanses
    с тем же PK (date_time, frequency, group_, id, client_name).

    Нужна автопоиску: после «Обработать папку» в processed_files может не быть записи,
    но дублировать UPSERT не нужно — пропускаем файл и помечаем processed_files.
    """
    if not entries:
        return True
    init_seans_tables(conn)
    position = str(client_name or "").strip()
    unique_keys: set[tuple[str, str, str, str, str]] = set()
    for e in entries:
        unique_keys.add(
            (str(e.date_time), str(e.frequency), str(e.group), str(e.id), position)
        )
    keys = list(unique_keys)
    cur = conn.cursor()
    need = len(keys)
    total = 0
    chunk_size = 100  # 5 * 100 = 500 переменных < лимита SQLite
    for i in range(0, len(keys), chunk_size):
        chunk = keys[i : i + chunk_size]
        placeholders = ",".join(["(?,?,?,?,?)"] * len(chunk))
        flat: list[str] = []
        for t in chunk:
            flat.extend(t)
        row = cur.execute(
            f"""
            SELECT COUNT(*) FROM seanses
            WHERE (date_time, frequency, group_, id, client_name) IN ({placeholders})
            """,
            flat,
        ).fetchone()
        total += int(row[0] or 0) if row else 0
    return total >= need


def _parse_seans_date_time_value(v: object) -> datetime | None:
    """Разбор date_time из seanses (TEXT), как в parse_result0_file."""
    from datetime import datetime as _dt

    s = str(v or "").strip()
    if not s:
        return None
    head = s[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H-%M-%S"):
        try:
            return _dt.strptime(head, fmt)
        except ValueError:
            continue
    return None


def max_seans_date_times_by_frequency(
    conn: sqlite3.Connection, *, client_name: str
) -> dict[str, datetime]:
    """
    Для каждой частоты — MAX(date_time) по сеансам данной позиции (один запрос).
    Нужен автопоиску как водяной знак, если нет строки в frequency_last_processed.
    """
    init_seans_tables(conn)
    rows = conn.execute(
        """
        SELECT frequency, MAX(date_time)
        FROM seanses
        WHERE client_name=?
        GROUP BY frequency
        """,
        (client_name,),
    ).fetchall()
    out: dict[str, datetime] = {}
    for fr, dtv in rows or []:
        parsed = _parse_seans_date_time_value(dtv)
        if parsed is not None:
            out[str(fr or "")] = parsed
    return out


def scan_seanses_once(
    conn: sqlite3.Connection, scan_paths: list[Path], *, client_name: str | None = None
) -> dict[str, int]:
    """
    Сканирует указанные папки и собирает данные из result0.txt в таблицу seanses.
    Аналогично scan_once() из основного проекта agent/agent.py.

    Args:
        conn: Соединение с БД
        scan_paths: Список папок для сканирования
        client_name: Имя клиента/позиции (опционально)

    Returns:
        Словарь со статистикой: files_seen, files_processed, rows_parsed
    """
    init_db(conn)
    cur = conn.cursor()
    files_seen = 0
    files_processed = 0
    rows_parsed = 0

    from web_portal.lib.collect_seanses_from_dir import parse_result0_file
    import os

    for base in scan_paths:
        if not base.exists() or not base.is_dir():
            continue
        # Оптимизированный поиск result0.txt
        result0_files = []
        try:
            for root, dirs, files in os.walk(str(base), followlinks=False):
                # Ограничиваем глубину сканирования (максимум 10 уровней)
                depth = root[len(str(base)) :].count(os.sep)
                if depth > 10:
                    dirs[:] = []  # Не идем глубже
                    continue
                if "result0.txt" in files:
                    result0_files.append(Path(root) / "result0.txt")
        except Exception:
            # Fallback к glob если os.walk не работает
            result0_files = list(base.glob("**/result0.txt"))

        for file in result0_files:
            try:
                st = file.stat()
            except Exception:
                continue
            files_seen += 1
            key = str(file.resolve())
            if was_processed(
                conn, key, st.st_mtime, st.st_size, position_name=client_name
            ):
                continue

            parsed = parse_result0_file(file)
            if parsed:
                if client_name:
                    rows_parsed += save_seans_entries(
                        conn, parsed, client_name=client_name
                    )
                else:
                    rows_parsed += save_seans_entries(conn, parsed)
            mark_processed(
                conn, key, st.st_mtime, st.st_size, position_name=client_name
            )
            files_processed += 1

    conn.commit()
    return {
        "files_seen": files_seen,
        "files_processed": files_processed,
        "rows_parsed": rows_parsed,
    }


def save_all_from_dir(conn: sqlite3.Connection, folder: Path) -> int:
    """
    Импортирует все result0.txt из folder в seanses (аналогично save_all_from_dir из основного проекта).
    НЕ отслеживает обработанные файлы - просто собирает все данные.
    Возвращает количество обработанных файлов.
    """
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"Папка не найдена: {folder}")

    init_db(conn)
    cur = conn.cursor()
    counter = 0

    for seans in collect_seanses_from(folder):
        save_seans_entries(conn, seans)
        counter += 1

    conn.commit()
    return counter


def import_folder(conn: sqlite3.Connection, folder: Path) -> dict[str, Any]:
    """
    Импортирует все result0.txt из folder в seanses.
    Возвращает статистику по обработке.
    Использует save_all_from_dir() для совместимости с основным проектом.
    """
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"Папка не найдена: {folder}")

    init_db(conn)
    cur = conn.cursor()

    # Подсчитываем количество записей до импорта
    before = cur.execute("SELECT COUNT(*) FROM seanses").fetchone()[0]

    files_count = save_all_from_dir(conn, folder)

    # Подсчитываем количество записей после импорта
    after = cur.execute("SELECT COUNT(*) FROM seanses").fetchone()[0]
    rows_added = int(after) - int(before)

    return {"files_processed": files_count, "rows_processed": rows_added}


def import_folder_with_client(
    conn: sqlite3.Connection, folder: Path, *, client_name: str | None
) -> dict[str, Any]:
    """
    Импортирует все result0.txt из folder в seanses, проставляя client_name (позиция).
    Аналогично save_all_from_dir, но с указанием client_name.
    Дубликаты автоматически пропускаются через ON CONFLICT в save_seans_entries.
    """
    import logging

    logger = logging.getLogger(__name__)

    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"Папка не найдена: {folder}")

    init_db(conn)
    cur = conn.cursor()

    # Подсчитываем количество записей до импорта
    before = cur.execute("SELECT COUNT(*) FROM seanses").fetchone()[0]
    logger.info(
        f"Начало импорта папки {folder} для позиции {client_name}, записей в БД до импорта: {before}"
    )

    files_count = 0
    rows_in_files = 0
    for seans in collect_seanses_from(folder):
        rows_in_files += len(seans)
        save_seans_entries(conn, seans, client_name=client_name)
        files_count += 1

    conn.commit()

    # Подсчитываем количество записей после импорта
    after = cur.execute("SELECT COUNT(*) FROM seanses").fetchone()[0]
    rows_added = int(after) - int(before)

    logger.info(
        f"Импорт завершен: обработано файлов={files_count}, записей в файлах={rows_in_files}, добавлено новых записей в БД={rows_added}"
    )

    return {"files_processed": files_count, "rows_processed": rows_added}


def import_folder_incremental(
    conn: sqlite3.Connection,
    folder: Path,
    *,
    position_name: str,
    client_name: str | None,
) -> dict[str, Any]:
    """
    Инкрементальный импорт result0.txt:
    - сканируем **/result0.txt
    - читаем/парсим только новые/изменившиеся файлы (по mtime_ns + size)
    """
    from web_portal.lib.collect_seanses_from_dir import parse_result0_file
    import zlib
    from datetime import datetime

    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"Папка не найдена: {folder}")

    init_db(conn)
    pos = str(position_name or "").strip()
    if not pos:
        raise ValueError("position_name не может быть пустым")

    scanned = 0
    changed = 0
    rows_total = 0
    last_found_dt: datetime | None = None
    last_found_label = ""
    import logging

    logger = logging.getLogger(__name__)

    # Оптимизированный поиск result0.txt: используем os.walk для лучшей производительности
    import os

    result0_files = []
    try:
        for root, dirs, files in os.walk(str(folder), followlinks=False):
            # Ограничиваем глубину сканирования (максимум 10 уровней)
            depth = root[len(str(folder)) :].count(os.sep)
            if depth > 10:
                dirs[:] = []  # Не идем глубже
                continue
            if "result0.txt" in files:
                result0_files.append(Path(root) / "result0.txt")
    except Exception as e:
        logger.warning(f"Ошибка при os.walk для {folder}, используем glob: {e}")
        # Fallback к glob если os.walk не работает
        result0_files = list(folder.glob("**/result0.txt"))

    logger.info(f"Найдено файлов result0.txt для позиции {pos}: {len(result0_files)}")

    for file in result0_files:
        scanned += 1
        try:
            st = file.stat()
            mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))
            size = int(st.st_size or 0)
        except Exception:
            continue

        # Время "из структуры папки": .../<freq>_<YYYY-MM-DD>_<HH-MM-SS>/result0.txt
        # Храним для статуса watcher (даже если rows=0 из-за дублей).
        try:
            freq_s, date_s, time_s = file.parts[-3].split("_")
            dt = datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H-%M-%S")
            if last_found_dt is None or dt > last_found_dt:
                last_found_dt = dt
                last_found_label = dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            _log.debug("import_folder_incremental: suppressed error", exc_info=True)

        # Быстрая сигнатура содержимого (1KB) — на случай когда mtime/size не меняются в сетевых шарах
        sig = 0
        try:
            with open(file, "rb") as fh:
                head = fh.read(512) or b""
                if size > 512:
                    try:
                        fh.seek(max(0, size - 512))
                        tail = fh.read(512) or b""
                    except Exception:
                        tail = b""
                else:
                    tail = b""
            sig = int(zlib.crc32(head + tail) & 0xFFFFFFFF)
        except Exception:
            sig = 0

        fp = str(file.resolve())
        r0 = conn.execute(
            """
            SELECT mtime_ns, size, sig
            FROM seans_import_files
            WHERE position_name=? AND file_path=?
            """,
            (pos, fp),
        ).fetchone()
        if (
            r0
            and int(r0["mtime_ns"] or 0) == mtime_ns
            and int(r0["size"] or 0) == size
            and int(r0["sig"] or 0) == sig
        ):
            # Файл уже обработан ранее с теми же параметрами - пропускаем
            logger.debug(
                f"Файл {file} уже обработан (mtime={mtime_ns}, size={size}, sig={sig})"
            )
            continue

        # новый/изменился
        changed += 1
        parse_error = None
        try:
            entries = parse_result0_file(file)
        except Exception as e:
            parse_error = str(e)
            logger.warning(f"Ошибка при парсинге {file}: {e}")
            entries = None

        if entries:
            rows_added = save_seans_entries(conn, entries, client_name=client_name)
            rows_total += rows_added
            logger.debug(f"Файл {file}: добавлено {rows_added} строк")
        elif parse_error:
            logger.warning(f"Файл {file} пропущен из-за ошибки парсинга: {parse_error}")
        else:
            logger.debug(
                f"Файл {file}: нет записей для импорта (возможно, уже были импортированы)"
            )

        # фиксируем, что видели именно эту версию файла
        # Помечаем файл как обработанный даже если парсинг не удался, чтобы не пытаться обрабатывать его снова
        try:
            conn.execute(
                """
                INSERT INTO seans_import_files (position_name, file_path, mtime_ns, size, sig, last_import_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(position_name, file_path) DO UPDATE SET
                  mtime_ns=excluded.mtime_ns,
                  size=excluded.size,
                  sig=excluded.sig,
                  last_import_at=CURRENT_TIMESTAMP
                """,
                (pos, fp, mtime_ns, size, sig),
            )
        except Exception as e:
            logger.error(f"Ошибка при записи в seans_import_files для {file}: {e}")

        # Коммитим батчами (каждые 50 файлов) для лучшей производительности
        if changed % 50 == 0:
            try:
                conn.commit()
                logger.debug(
                    f"Промежуточный коммит после обработки {changed} измененных файлов"
                )
            except Exception as e:
                logger.error(f"Ошибка при промежуточном коммите: {e}")

    # Финальный коммит всех изменений
    try:
        conn.commit()
        logger.info(
            f"Импорт завершен для позиции {pos}: просканировано={scanned}, изменено={changed}, строк={rows_total}"
        )
    except Exception as e:
        logger.error(f"Ошибка при финальном коммите для позиции {pos}: {e}")
        raise
    return {
        "scanned_files": scanned,
        "changed_files": changed,
        "rows_processed": rows_total,
        "last_found": last_found_label,
    }


__all__ = [
    "save_seans_entries",
    "seans_entries_fully_in_database",
    "max_seans_date_times_by_frequency",
    "scan_seanses_once",
    "was_processed",
    "mark_processed",
    "save_all_from_dir",
    "import_folder",
    "import_folder_with_client",
    "import_folder_incremental",
]
