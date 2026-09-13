"""Таймаут и валидация путей для аудио API."""

from __future__ import annotations

import tempfile
from pathlib import Path

from web_portal.lib.safe_paths import probe_audio_file, probe_path


def test_probe_path_local_dir() -> None:
    td = Path(tempfile.mkdtemp())
    r = probe_path(td, timeout_sec=2.0)
    assert r.ok
    assert r.exists
    assert r.is_dir
    assert not r.timed_out


def test_probe_audio_file_rejects_traversal() -> None:
    td = Path(tempfile.mkdtemp())
    r = probe_audio_file(str(td), "../secret.wav", timeout_sec=2.0)
    assert not r.ok
    assert "Недопустимый" in (r.error or "")


def test_probe_audio_file_local_wav() -> None:
    td = Path(tempfile.mkdtemp())
    wav = td / "slot0_1_to_G2_AES256_k1_1.wav"
    wav.write_bytes(b"RIFF")
    r = probe_audio_file(str(td), wav.name, timeout_sec=2.0)
    assert r.ok
    assert r.exists
    assert r.is_file
