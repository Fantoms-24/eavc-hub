from __future__ import annotations

import struct
import tempfile
import wave
from pathlib import Path

from web_portal.lib.intercept_audio_bundle import (
    _parse_bundle_wav_name,
    probe_bundle_layout,
    scan_bundle_intercept_audio_files,
)


def _write_wav(path: Path, samples: list[int], rate: int = 8000) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(struct.pack(f"{len(samples)}h", *samples))


def _speech_samples() -> list[int]:
    out: list[int] = []
    for i in range(4000):
        amp = 9000 if (i // 200) % 2 == 0 else 1500
        out.append(amp if i % 50 < 25 else -amp)
    return out


def _make_ct_bundle_tree(root: Path) -> None:
    freq = root / "fr{149.9750}"
    freq.mkdir(parents=True)
    _write_wav(
        freq / "2026-06-05_07-42-09_id-101__0_CT_Group_TO_2047519_FR_4489_pe_0__47.wav",
        _speech_samples(),
    )
    _write_wav(
        freq / "2026-06-05_07-42-09_id-102__1_CT_Group_TO_2047519_FR_4490_pe_0__48.wav",
        _speech_samples(),
    )


def _make_legacy_bundle_tree(root: Path) -> None:
    group = root / "154.0130" / "Group TO_2047519"
    group.mkdir(parents=True)
    _write_wav(group / "FR_4489_2025-06-05_11-40-53_0[+].wav", _speech_samples())


def test_parse_ct_bundle_wav_name() -> None:
    meta = _parse_bundle_wav_name(
        "2026-06-05_07-42-09_id-101__0_CT_Group_TO_2047519_FR_4489_pe_0__47.wav"
    )
    assert meta
    assert meta["correspondent_id"] == "4489"
    assert meta["group_code"] == "2047519"
    assert meta["date"] == "2026-06-05"
    assert meta["time"] == "07-42-09"


def test_probe_ct_bundle_layout() -> None:
    td = Path(tempfile.mkdtemp())
    _make_ct_bundle_tree(td)
    assert probe_bundle_layout(td)


def test_scan_ct_bundle_fr_folder() -> None:
    td = Path(tempfile.mkdtemp())
    _make_ct_bundle_tree(td)
    entries = scan_bundle_intercept_audio_files(
        td, limit=50, use_cache=False, newest_first=True
    )
    assert len(entries) == 2
    assert entries[0].frequency == "149.9750"
    assert entries[0].group_code == "2047519"
    assert entries[0].recorded_at.startswith("2026-06-05 07:42:09")
    ids = {e.correspondent_id for e in entries}
    assert "4489" in ids
    assert "4490" in ids


def test_scan_legacy_group_folder() -> None:
    td = Path(tempfile.mkdtemp())
    _make_legacy_bundle_tree(td)
    entries = scan_bundle_intercept_audio_files(td, limit=50, use_cache=False)
    assert len(entries) == 1
    assert entries[0].correspondent_id == "4489"
