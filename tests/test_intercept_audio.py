"""Парсинг имён wav OPK/STA и эвристика has_message."""

from __future__ import annotations

import struct
import os
import tempfile
import time
import wave
from pathlib import Path

from web_portal.lib.intercept_audio import (
    FILE_RE,
    _find_time_folder,
    _has_common_files,
    _parse_slot_wav_name,
    _wav_has_speech_like_content,
    parse_intercept_audio_file,
    scan_intercept_audio_files,
)


def test_file_re_group_call() -> None:
    name = "slot0_8888_to_G81676_AES256_k51_4[+].wav"
    assert FILE_RE.match(name)
    meta = _parse_slot_wav_name(name)
    assert meta
    assert meta["correspondent_id"] == "8888"
    assert meta["group_code"] == "81676"
    assert meta["call_mode"] == "group"
    assert meta["decoded"] is True


def test_file_re_direct_id_to_id() -> None:
    name = "slot0_202_to_203_AES256_k51_4[+].wav"
    assert FILE_RE.match(name)
    meta = _parse_slot_wav_name(name)
    assert meta
    assert meta["correspondent_id"] == "202"
    assert meta["group_code"] == "T-T"
    assert meta["call_mode"] == "tt"
    assert meta["peer_correspondent_id"] == "203"


def test_file_re_private_peer_call_is_tt() -> None:
    name = "slot1_6734818_to_7854033_0.wav"
    assert FILE_RE.match(name)
    meta = _parse_slot_wav_name(name)
    assert meta
    assert meta["correspondent_id"] == "6734818"
    assert meta["group_code"] == "T-T"
    assert meta["call_mode"] == "tt"
    assert meta["peer_correspondent_id"] == "7854033"


def test_file_re_tt_same_id() -> None:
    name = "slot1_13131_to_13131_AES256_k1_2.wav"
    meta = _parse_slot_wav_name(name)
    assert meta
    assert meta["group_code"] == "T-T"
    assert meta["call_mode"] == "tt"


def _write_wav(path: Path, samples: list[int], rate: int = 8000) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        raw = struct.pack(f"{len(samples)}h", *samples)
        wf.writeframes(raw)


def test_wav_has_speech_modulated() -> None:
    td = Path(tempfile.mkdtemp())
    p = td / "speech.wav"
    samples: list[int] = []
    for i in range(8000):
        amp = 12000 if (i // 400) % 2 == 0 else 2000
        samples.append(amp if i % 80 < 40 else -amp)
    _write_wav(p, samples)
    assert _wav_has_speech_like_content(p)


def test_wav_rejects_silence() -> None:
    td = Path(tempfile.mkdtemp())
    p = td / "silent.wav"
    _write_wav(p, [0] * 8000)
    assert not _wav_has_speech_like_content(p)


def test_wav_rejects_broadband_noise() -> None:
    import random

    td = Path(tempfile.mkdtemp())
    p = td / "noise.wav"
    rnd = random.Random(7)
    samples = [int(rnd.uniform(-24000, 24000)) for _ in range(12000)]
    _write_wav(p, samples)
    assert not _wav_has_speech_like_content(p)


def test_enrich_message_flags_checks_whole_session() -> None:
    from web_portal.lib.intercept_audio import (
        InterceptAudioEntry,
        _enrich_message_flags,
    )

    td = Path(tempfile.mkdtemp())
    base = InterceptAudioEntry(
        file_path=td / "x.wav",
        file_rel="x.wav",
        file_key="k",
        frequency="154.0130",
        group_code="12563612",
        correspondent_id="1",
        order_index=1,
        recorded_at="2025-06-05 10:26:23",
        recorded_ts=0.0,
        duration_sec=1.0,
        has_key=True,
        has_message=False,
        aes_key="19",
        slot="0",
    )

    def _entry(cid: str, order: int, speech: bool) -> InterceptAudioEntry:
        p = td / f"slot0_{cid}_to_G12563612_AES256_k19_{order}[+].wav"
        samples: list[int] = []
        if speech:
            for i in range(4000):
                amp = 9000 if (i // 200) % 2 == 0 else 1500
                samples.append(amp if i % 50 < 25 else -amp)
        else:
            import random

            rnd = random.Random(int(cid) + order)
            samples = [int(rnd.uniform(-24000, 24000)) for _ in range(4000)]
        _write_wav(p, samples)
        return InterceptAudioEntry(
            file_path=p,
            file_rel=p.name,
            file_key=f"{p.name}|1|1",
            frequency="154.0130",
            group_code="12563612",
            correspondent_id=cid,
            order_index=order,
            recorded_at="2025-06-05 10:26:23",
            recorded_ts=0.0,
            duration_sec=0.5,
            has_key=True,
            has_message=False,
            aes_key="19",
            slot="0",
        )

    # 8 корреспондентов в одном сеансе — все должны попасть в проверку при max_checks=50.
    entries = [_entry(str(i), i, speech=(i == 1)) for i in range(1, 9)]
    # Добавим «шум» в конец списка, чтобы старая логика last-50 не добралась до сеанса.
    for j in range(60):
        entries.append(
            InterceptAudioEntry(
                file_path=td / f"extra_{j}.wav",
                file_rel=f"extra_{j}.wav",
                file_key=f"e{j}",
                frequency="999.0000",
                group_code="1",
                correspondent_id="9",
                order_index=j,
                recorded_at="2099-01-01 00:00:00",
                recorded_ts=9999999999.0,
                duration_sec=1.0,
                has_key=True,
                has_message=False,
                aes_key="1",
                slot="0",
            )
        )
    out = _enrich_message_flags(entries, max_checks=50)
    by_id = {e.correspondent_id: e.has_message for e in out if e.frequency == "154.0130"}
    assert by_id.get("1") is True
    assert sum(1 for v in by_id.values() if v) == 1


def test_enrich_message_flags_keeps_unchecked_decodes_as_message() -> None:
    from web_portal.lib.intercept_audio import InterceptAudioEntry, _enrich_message_flags

    td = Path(tempfile.mkdtemp())
    unchecked = InterceptAudioEntry(
        file_path=td / "not_checked.wav",
        file_rel="not_checked.wav",
        file_key="unchecked",
        frequency="160.8700",
        group_code="12563612",
        correspondent_id="90043",
        order_index=4,
        recorded_at="2026-06-05 10:50:00",
        recorded_ts=0.0,
        duration_sec=1.0,
        has_key=True,
        has_message=False,
        aes_key="30",
        slot="0",
    )

    [out] = _enrich_message_flags([unchecked], max_checks=0)
    assert out.has_message is True


def test_wav_user_samples_if_present() -> None:
    """Регрессия по реальным примерам: шум vs речь (файлы из Downloads, если есть)."""
    noise = Path(r"c:\Users\user\Downloads\шум.wav")
    ref_noise = Path(
        r"c:\Users\user\Downloads\slot0_1_to_G12563612_AES256_k19_uid1953_2[+].wav"
    )
    ref_speech = Path(
        r"c:\Users\user\Downloads\slot0_1341839_to_G11234512_AES256_k9_uid2079_0[+].wav"
    )
    speech = Path(r"c:\Users\user\Downloads\нет шума.wav")
    if noise.is_file():
        assert not _wav_has_speech_like_content(noise)
    if ref_noise.is_file():
        assert not _wav_has_speech_like_content(ref_noise)
    corrected_noise = Path(
        r"c:\Users\user\Downloads\slot0_1341869_to_G11234512_AES256_k7_uid2077_5[+].wav"
    )
    if corrected_noise.is_file():
        assert not _wav_has_speech_like_content(corrected_noise)
    if ref_speech.is_file():
        assert _wav_has_speech_like_content(ref_speech)
    if speech.is_file():
        assert _wav_has_speech_like_content(speech)
    track_files = [
        r"c:\Users\user\Downloads\slot0_15500327_to_G172010_AES256_k103_uid1798_15[+].wav",
        r"c:\Users\user\Downloads\slot0_15500327_to_G172010_AES256_k194_uid1796_11[+].wav",
        r"c:\Users\user\Downloads\slot0_15500235_to_G172010_AES256_k11_uid1788_9[+].wav",
        r"c:\Users\user\Downloads\slot0_15500327_to_G172010_AES256_k108_uid1795_8[+].wav",
        r"c:\Users\user\Downloads\slot0_15500235_to_G172010_AES256_k167_uid1794_7[+].wav",
        r"c:\Users\user\Downloads\slot0_15500327_to_G172010_AES256_k198_uid1791_6[+].wav",
        r"c:\Users\user\Downloads\slot0_15500235_to_G172010_AES256_k108_uid1795_5[+].wav",
        r"c:\Users\user\Downloads\slot0_15500327_to_G172010_AES256_k18_uid1793_13[+].wav",
    ]
    for tf in track_files:
        p = Path(tf)
        if p.is_file():
            assert _wav_has_speech_like_content(p), p.name
    slot1_files = [
        r"c:\Users\user\Downloads\slot1_1073_to_G5554565_AES256_k250_uid1834_0[+].wav",
        r"c:\Users\user\Downloads\slot1_1073_to_G5554565_AES256_k250_uid1834_4[+].wav",
        r"c:\Users\user\Downloads\slot1_7004_to_G5554565_AES256_k250_uid1834_3[+].wav",
        r"c:\Users\user\Downloads\slot1_1073_to_G5554565_AES256_k250_uid1834_2[+].wav",
    ]
    for sf in slot1_files:
        p = Path(sf)
        if p.is_file():
            assert _wav_has_speech_like_content(p), p.name
    weak_speech_files = [
        r"c:\Users\user\Downloads\slot0_1_to_G12563612_AES256_k26_uid1960_3[+].wav",
        r"c:\Users\user\Downloads\slot0_90043_to_G12563612_AES256_k30_uid1964_4[+].wav",
    ]
    for wf in weak_speech_files:
        p = Path(wf)
        if p.is_file():
            assert _wav_has_speech_like_content(p), p.name


def test_find_time_folder_windows_copy_suffix() -> None:
    td = Path(tempfile.mkdtemp())
    time_dir = td / "151.000_2026-06-04_12-00-00 (0)" / "DMR"
    time_dir.mkdir(parents=True)
    info = _find_time_folder(time_dir)
    assert info is not None
    assert info[0] == "151.000"
    assert info[1] == "2026-06-04 12:00:00"


def test_has_common_files_opk_suffix_name() -> None:
    td = Path(tempfile.mkdtemp())
    dmr = td / "151.000_2026-06-04_12-00-00" / "DMR"
    dmr.mkdir(parents=True)
    (dmr / "slot0_common_file ГУПИК.wav").write_bytes(b"")
    assert _has_common_files(dmr)


def test_scan_finds_slot_with_opk_common_name() -> None:
    td = Path(tempfile.mkdtemp())
    time_dir = td / "151.000_2026-06-04_12-00-00 (0)" / "DMR"
    time_dir.mkdir(parents=True)
    (time_dir / "slot0_common_file ГУПИК.wav").write_bytes(b"")
    wav = time_dir / "slot0_8888_to_G81676_AES256_k51_4.wav"
    samples = [5000 if i % 80 < 40 else -5000 for i in range(4000)]
    _write_wav(wav, samples)
    entries = scan_intercept_audio_files(
        td, limit=50, use_cache=False, max_time_folders=10
    )
    assert len(entries) == 1
    assert entries[0].correspondent_id == "8888"
    assert entries[0].group_code == "81676"


def test_find_time_folder_new_format_fd_file() -> None:
    """Новый формат: папка {date}_{time} без частоты, частота — в имени .fd."""
    td = Path(tempfile.mkdtemp())
    session = td / "2026-06-10_13-21-30"
    dmr = session / "DMR"
    dmr.mkdir(parents=True)
    (session / "151.1750_2026-06-10_13-18-18.fd").write_bytes(b"")
    info = _find_time_folder(dmr)
    assert info is not None
    assert info[0] == "151.1750"
    assert info[1] == "2026-06-10 13:18:18"


def test_scan_new_format_with_nested_dmr_and_decoded_priority() -> None:
    """Структура выгрузки 2026-06-10: raw в DMR, декодированные [+] в DMR/DMR."""
    td = Path(tempfile.mkdtemp())
    session = td / "2026-06-10_13-21-30"
    dmr = session / "DMR"
    nested = dmr / "DMR"
    nested.mkdir(parents=True)
    (session / "151.1750_2026-06-10_13-18-18.fd").write_bytes(b"")
    (dmr / "slot0_common_file.wav").write_bytes(b"")
    (nested / "slot0_common_file_0.wav").write_bytes(b"")

    samples = [5000 if i % 80 < 40 else -5000 for i in range(4000)]
    # raw (без ключа) во внешней DMR
    _write_wav(dmr / "slot0_5217307_to_G775225_0.wav", samples)
    _write_wav(dmr / "slot0_5211918_to_G775225_3.wav", samples)
    _write_wav(dmr / "slot1_1_to_G229901_0.wav", samples)
    # расшифрованный дубль (order 0) во вложенной DMR/DMR
    _write_wav(
        nested / "slot0_5217307_to_G775225_AES256_k222_uid1478_0[+].wav", samples
    )

    entries = scan_intercept_audio_files(
        td, limit=50, use_cache=False, max_time_folders=10
    )
    assert entries, "новый формат должен парситься"
    assert all(e.frequency == "151.1750" for e in entries)
    by_key = {(e.correspondent_id, e.order_index, e.slot): e for e in entries}
    # дубль order=0: приоритет у расшифрованного [+]
    dup = by_key.get(("5217307", 0, "0"))
    assert dup is not None
    assert dup.has_key is True
    assert "[+]" in dup.file_rel
    # raw без дубля сохраняется
    assert ("5211918", 3, "0") in by_key
    assert ("1", 0, "1") in by_key


def test_scan_includes_recently_modified_old_time_folder_beyond_limit() -> None:
    td = Path(tempfile.mkdtemp())
    samples = [5000 if i % 80 < 40 else -5000 for i in range(4000)]
    target_dmr = None
    for minute in range(40, 60):
        dmr = td / f"160.8260_2026-06-14_12-{minute:02d}-00" / "DMR"
        dmr.mkdir(parents=True)
        (dmr / "slot0_common_file.wav").write_bytes(b"")
        _write_wav(dmr / f"slot0_100{minute}_to_G1687326_0.wav", samples)
        if minute == 49:
            target_dmr = dmr

    assert target_dmr is not None
    now_ts = time.time()
    os.utime(target_dmr, (now_ts, now_ts))
    os.utime(target_dmr.parent, (now_ts, now_ts))

    entries = scan_intercept_audio_files(
        td,
        limit=50,
        use_cache=False,
        max_time_folders=2,
        recent_mtime_since=now_ts - 5,
    )

    assert any(e.recorded_at == "2026-06-14 12:49:00" for e in entries)


def test_recently_modified_old_time_folder_bypasses_since_filter() -> None:
    td = Path(tempfile.mkdtemp())
    samples = [9000 if i % 80 < 40 else -9000 for i in range(1600)]
    older = td / "160.8260_2026-06-14_12-49-00" / "DMR"
    newer = td / "160.8260_2026-06-14_12-50-00" / "DMR"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    (older / "slot0_common_file.wav").write_bytes(b"")
    (newer / "slot0_common_file.wav").write_bytes(b"")
    _write_wav(older / "slot0_1249_to_G1687326_0.wav", samples)
    _write_wav(newer / "slot0_1250_to_G1687326_0.wav", samples)
    now_ts = time.time()
    for p in (older, older.parent, older / "slot0_common_file.wav"):
        os.utime(p, (now_ts, now_ts))

    entries = scan_intercept_audio_files(
        td,
        limit=50,
        use_cache=False,
        since_ts=older.stat().st_mtime,  # выше recorded_ts 12:49, как при автоопросе после 12:50
        max_time_folders=1,
        recent_mtime_since=now_ts - 5,
    )

    assert any(e.recorded_at == "2026-06-14 12:49:00" for e in entries)


def test_recent_session_scan_bounded_on_many_folders() -> None:
    td = Path(tempfile.mkdtemp())
    samples = [5000 if i % 80 < 40 else -5000 for i in range(4000)]
    for i in range(300):
        hour, minute = divmod(i, 60)
        dmr = td / f"160.8260_2026-06-14_{hour + 8:02d}-{minute:02d}-00" / "DMR"
        dmr.mkdir(parents=True)
        (dmr / "slot0_common_file.wav").write_bytes(b"")
        _write_wav(dmr / f"slot0_{i}_to_G1687326_0.wav", samples)

    t0 = time.perf_counter()
    entries = scan_intercept_audio_files(
        td,
        limit=10,
        use_cache=False,
        max_time_folders=2,
        recent_mtime_since=time.time() - 5,
    )
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0, f"scan must stay bounded, took {elapsed:.1f}s"
    assert entries


def test_parse_intercept_audio_file_direct_call() -> None:
    td = Path(tempfile.mkdtemp())
    time_dir = td / "151.000_2026-06-04_12-00-00" / "DMR"
    time_dir.mkdir(parents=True)
    (time_dir / "slot0_common_file.wav").write_bytes(b"")
    wav = time_dir / "slot0_202_to_203_AES256_k51_4[+].wav"
    samples: list[int] = []
    for i in range(4000):
        amp = 9000 if (i // 200) % 2 == 0 else 1500
        samples.append(amp if i % 50 < 25 else -amp)
    _write_wav(wav, samples)
    entry = parse_intercept_audio_file(wav, td)
    assert entry is not None
    assert entry.correspondent_id == "202"
    assert entry.group_code == "T-T"
    assert entry.call_mode == "tt"
    assert entry.peer_correspondent_id == "203"
    assert entry.has_key is True
    assert entry.has_message is True
