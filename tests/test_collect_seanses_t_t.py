"""Парсер result0: трубка-в-трубку (T-T) и пары abonent↔G."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from web_portal.lib.collect_seanses_from_dir import (
    SeansEntry,
    _session_group,
    parse_ambe_wav_filename,
    parse_result0_file,
)
from web_portal.lib.db import get_doc_stats, init_db, init_seans_tables, save_seans_entries
from web_portal.lib.audio_zip_import import collect_audio_zip_entries


def test_session_group_tt_and_g() -> None:
    assert _session_group("13131", "G13131") == "T-T"
    assert _session_group("13131", "g13131") == "T-T"
    assert _session_group("13131", "G13132") == "G13132"
    assert _session_group("13131", "13131") == "T-T"
    assert _session_group("1", "2") == "G2"
    assert _session_group("x", "1") is None


def test_parse_result0_tt_underscore() -> None:
    td = tempfile.mkdtemp()
    freq_dir = os.path.join(td, "151.0000_2000-01-01_00-00-00", "x")
    os.makedirs(freq_dir, exist_ok=True)
    p = Path(freq_dir) / "result0.txt"
    p.write_text(
        "AES256 key id: 1\ntime: 1000 ms\n13131_to_13131\n",
        encoding="utf-8",
    )
    rows = parse_result0_file(p)
    assert rows
    r0 = {x.id: x.group for x in rows}
    assert r0.get("13131") == "T-T"


def test_parse_result0_windows_copy_suffix_folder() -> None:
    td = tempfile.mkdtemp()
    freq_dir = os.path.join(
        td, "2026-06-03", "154.0130", "154.0130_2026-06-03_05-41-03 (0)", "DMR"
    )
    os.makedirs(freq_dir, exist_ok=True)
    p = Path(freq_dir) / "result0.txt"
    p.write_text("AES256 key id: 1\n12345 to G999\n", encoding="utf-8")
    rows = parse_result0_file(p)
    assert rows
    assert rows[0].frequency == "154.0130"


def test_parse_result0_group_pair() -> None:
    td = tempfile.mkdtemp()
    freq_dir = os.path.join(td, "151.0000_2000-01-01_00-00-00", "x")
    os.makedirs(freq_dir, exist_ok=True)
    p = Path(freq_dir) / "result0.txt"
    p.write_text(
        "AES256 key id: 1\n12345 to G999\n",
        encoding="utf-8",
    )
    rows = parse_result0_file(p)
    gmap = {(r.id, r.group) for r in rows}
    assert ("12345", "G999") in gmap


def test_parse_result0_private_call_is_tt() -> None:
    td = tempfile.mkdtemp()
    freq_dir = os.path.join(td, "160.8260_2026-06-14_11-45-14", "DMR")
    os.makedirs(freq_dir, exist_ok=True)
    p = Path(freq_dir) / "result0.txt"
    p.write_text(
        "6734818 to 7854033\n"
        "slot: 1 BS Voice Color code: 1 time: 7200ms\n"
        "6734818 - 7854033 Private call\n",
        encoding="utf-8",
    )

    rows = parse_result0_file(p)

    assert rows
    assert {(r.id, r.group) for r in rows} == {("6734818", "T-T")}


def test_parse_ambe_wav_filename_ras_id_group() -> None:
    row = parse_ambe_wav_filename(
        "151.3920_2026-05-03_03-36-48.bit.007-AES-k185-dc-RAS-15501020.207506.ambe.wav"
    )

    assert row is not None
    assert row.frequency == "151.3920"
    assert row.date_time == "2026-05-03 03:36:48"
    assert row.id == "15501020"
    assert row.group == "207506"
    assert row.aes_key == "185"
    assert row.color_voice == "dc"
    assert row.time_seconds is None


def test_parse_ambe_wav_filename_copy_suffix() -> None:
    row = parse_ambe_wav_filename(
        "164.8325_2026-05-05_17-44-28 (0).bit.000-AES-k140-e5-RAS-115454.100173.ambe.wav"
    )

    assert row is not None
    assert row.date_time == "2026-05-05 17:44:28"
    assert row.frequency == "164.8325"
    assert row.id == "115454"
    assert row.group == "100173"
    assert row.aes_key == "140"
    assert row.color_voice == "e5"


def test_parse_ambe_wav_filename_alt_underscore_date() -> None:
    row = parse_ambe_wav_filename(
        "145.2460__2026_05_09__03_18_21.bit.000-AES-k140-e5-RAS-1.100173.ambe.wav"
    )

    assert row is not None
    assert row.date_time == "2026-05-09 03:18:21"
    assert row.frequency == "145.2460"
    assert row.id == "1"
    assert row.group == "100173"


def test_parse_ambe_wav_filename_without_ras_is_skipped() -> None:
    assert (
        parse_ambe_wav_filename(
            "151.3920_2026-05-01_00-55-34.bit.000-AES-k255-bf-15501020.207506.ambe.wav"
        )
        is None
    )


def test_collect_audio_zip_entries_dry_run(tmp_path: Path) -> None:
    import zipfile

    archive = tmp_path / "audio.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "Аудио/03.05/151.3920_2026-05-03_03-36-48.bit.007-AES-k185-dc-RAS-15501020.207506.ambe.wav",
            b"",
        )
        zf.writestr(
            "Аудио/03.05/151.3920_2026-05-03_03-36-49.bit.008-AES-k185-dc-15501020.207506.ambe.wav",
            b"",
        )

    rows, stats = collect_audio_zip_entries(archive)

    assert len(rows) == 1
    assert rows[0].id == "15501020"
    assert rows[0].group == "207506"
    assert stats["members"] == 2
    assert stats["wav_members"] == 2
    assert stats["parsed"] == 1
    assert stats["skipped_unparsed"] == 1


def test_save_tt_reimport_removes_old_peer_group() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_seans_tables(conn)
    conn.execute(
        """
        INSERT INTO seanses (date_time, frequency, group_, id)
        VALUES (?, ?, ?, ?)
        """,
        ("2026-06-14 11:45:14", "160.8260", "G7854033", "6734818"),
    )
    conn.commit()

    save_seans_entries(
        conn,
        [
            SeansEntry(
                date_time="2026-06-14 11:45:14",
                frequency="160.8260",
                group="T-T",
                id="6734818",
                aes_key=None,
                color_voice="1",
                time_seconds=7.2,
            )
        ],
    )

    groups = [
        str(row["group_"])
        for row in conn.execute(
            """
            SELECT group_ FROM seanses
            WHERE date_time=? AND frequency=? AND id=?
            ORDER BY group_
            """,
            ("2026-06-14 11:45:14", "160.8260", "6734818"),
        ).fetchall()
    ]
    assert groups == ["T-T"]


def test_doc_stats_groups_private_calls_under_tt_with_ids() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    save_seans_entries(
        conn,
        [
            SeansEntry(
                date_time="2026-06-14 11:45:14",
                frequency="160.8260",
                group="T-T",
                id="6734818",
                aes_key=None,
            ),
            SeansEntry(
                date_time="2026-06-14 11:46:00",
                frequency="160.8260",
                group="T-T",
                id="7777777",
                aes_key=None,
            ),
        ],
    )

    rows = get_doc_stats(
        conn,
        "2026-06-14 00:00:00",
        "2026-06-14 23:59:59",
        unit_conn=conn,
    )

    tt_rows = [r for r in rows if r["frequency"] == "160.8260" and r["group"] == "T-T"]
    assert len(tt_rows) == 1
    assert tt_rows[0]["count"] == 2
    assert "6734818" in tt_rows[0]["ids_csv"]
    assert "7777777" in tt_rows[0]["ids_csv"]
