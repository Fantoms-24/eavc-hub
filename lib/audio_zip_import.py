from __future__ import annotations

import sqlite3
import struct
import zipfile
from pathlib import Path
from typing import Callable, Iterator

from web_portal.lib.collect_seanses_from_dir import SeansEntry, parse_ambe_wav_filename
from web_portal.lib.db import connect, init_seans_tables, refresh_seanses_daily_aggregates, save_seans_entries
from web_portal.lib.seans_db import resolve_seans_storage_path
import logging

_log = logging.getLogger("web_portal.lib.audio_zip_import")

ProgressCallback = Callable[[dict[str, object]], None]


def _decode_zip_name(raw: bytes, flag_bits: int) -> str:
    if flag_bits & (1 << 11):
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
    for enc in ("utf-8", "cp866", "cp437"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _split_zip_member_names(zip_path: Path) -> Iterator[str]:
    """
    Читает central directory из финальной части split ZIP.

    Для многотомного архива Python zipfile падает до чтения списка файлов, но
    центральный каталог обычно лежит в последнем `.zip`, и его достаточно для
    импорта метаданных.
    """
    data = zip_path.read_bytes()
    eocd64_pos = data.rfind(b"PK\x06\x06")
    if eocd64_pos >= 0:
        if eocd64_pos + 56 > len(data):
            raise zipfile.BadZipFile("truncated ZIP64 EOCD")
        rec = struct.unpack("<4sQHHIIQQQQ", data[eocd64_pos : eocd64_pos + 56])
        cd_size = int(rec[8])
        cd_offset = int(rec[9])
        cd_start = cd_offset if cd_offset + cd_size <= len(data) else eocd64_pos - cd_size
    else:
        eocd_pos = data.rfind(b"PK\x05\x06")
        if eocd_pos < 0 or eocd_pos + 22 > len(data):
            raise zipfile.BadZipFile("central directory not found")
        rec = struct.unpack("<4sHHHHIIH", data[eocd_pos : eocd_pos + 22])
        cd_size = int(rec[5])
        cd_offset = int(rec[6])
        cd_start = cd_offset if cd_offset + cd_size <= len(data) else eocd_pos - cd_size

    if cd_start < 0 or cd_start + cd_size > len(data):
        raise zipfile.BadZipFile("central directory points outside final ZIP part")

    cd = data[cd_start : cd_start + cd_size]
    i = 0
    while i + 46 <= len(cd):
        if cd[i : i + 4] != b"PK\x01\x02":
            break
        header = struct.unpack("<4sHHHHHHIIIHHHHHII", cd[i : i + 46])
        flag_bits = int(header[3])
        name_len = int(header[10])
        extra_len = int(header[11])
        comment_len = int(header[12])
        name_raw = cd[i + 46 : i + 46 + name_len]
        yield _decode_zip_name(name_raw, flag_bits)
        i += 46 + name_len + extra_len + comment_len


def iter_zip_member_names(zip_path: Path | str) -> Iterator[str]:
    zip_path = Path(zip_path)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                yield info.filename
            return
    except zipfile.BadZipFile as exc:
        if "span multiple disks" not in str(exc).lower():
            raise
    yield from _split_zip_member_names(zip_path)


def collect_audio_zip_entries(
    zip_path: Path | str,
    *,
    limit: int | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[list[SeansEntry], dict[str, object]]:
    entries: list[SeansEntry] = []
    stats: dict[str, object] = {
        "members": 0,
        "wav_members": 0,
        "parsed": 0,
        "skipped_dirs": 0,
        "skipped_not_wav": 0,
        "skipped_unparsed": 0,
        "examples_unparsed": [],
    }
    examples_unparsed: list[str] = []

    for name in iter_zip_member_names(zip_path):
        stats["members"] = int(stats["members"]) + 1
        members = int(stats["members"])
        if progress and members % 5000 == 0:
            progress(
                {
                    "phase": "scan",
                    "message": f"Чтение каталога архива… ({members} файлов)",
                    "members": members,
                    "parsed": int(stats["parsed"]),
                }
            )
        if str(name).endswith("/"):
            stats["skipped_dirs"] = int(stats["skipped_dirs"]) + 1
            continue
        if not str(name).lower().endswith(".wav"):
            stats["skipped_not_wav"] = int(stats["skipped_not_wav"]) + 1
            continue
        stats["wav_members"] = int(stats["wav_members"]) + 1
        parsed = parse_ambe_wav_filename(name)
        if parsed is None:
            stats["skipped_unparsed"] = int(stats["skipped_unparsed"]) + 1
            if len(examples_unparsed) < 10:
                examples_unparsed.append(str(name))
            continue
        entries.append(parsed)
        stats["parsed"] = int(stats["parsed"]) + 1
        if limit is not None and len(entries) >= int(limit):
            break

    stats["examples_unparsed"] = examples_unparsed
    return entries, stats


def import_audio_zip_sessions(
    zip_path: Path | str,
    *,
    db_file: Path | str | None = None,
    client_name: str | None = None,
    commit: bool = False,
    batch_size: int = 1000,
    limit: int | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, object]:
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise FileNotFoundError(f"Архив не найден: {zip_path}")

    if progress:
        progress({"phase": "scan", "message": "Чтение каталога архива…"})

    entries, stats = collect_audio_zip_entries(zip_path, limit=limit, progress=progress)
    stats["dry_run"] = not commit
    stats["db_path"] = str(Path(db_file).resolve() if db_file else resolve_seans_storage_path())
    stats["zip_path"] = str(zip_path.resolve())
    stats["saved"] = 0

    if not commit or not entries:
        if progress:
            progress(
                {
                    "phase": "done" if not commit else "done",
                    "message": "Предпросмотр завершён" if not commit else "Нечего записывать",
                    "done": True,
                    **{k: stats[k] for k in ("members", "wav_members", "parsed", "saved") if k in stats},
                }
            )
        return stats

    conn = connect(Path(stats["db_path"]))
    try:
        init_seans_tables(conn)
        saved = 0
        batch_size = max(1, int(batch_size or 1000))
        total = len(entries)
        for i in range(0, total, batch_size):
            batch = entries[i : i + batch_size]
            saved += save_seans_entries(conn, batch, client_name=client_name or None)
            if progress:
                progress(
                    {
                        "phase": "save",
                        "message": f"Запись в БД… {min(i + batch_size, total)} / {total}",
                        "saved": saved,
                        "parsed": total,
                    }
                )
        try:
            refresh_seanses_daily_aggregates(conn)
        except Exception:
            _log.debug("import_audio_zip_sessions: suppressed error", exc_info=True)
        stats["saved"] = saved
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass

    if progress:
        progress(
            {
                "phase": "done",
                "message": "Импорт завершён",
                "done": True,
                "saved": stats["saved"],
                "parsed": stats["parsed"],
            }
        )
    return stats
