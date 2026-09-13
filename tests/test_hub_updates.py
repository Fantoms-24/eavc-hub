from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from web_portal.lib.hub_updates import (
    publish_release,
    read_current_release,
    release_signature,
)


def _hub_package(path: Path, *, wrapped: bool = False) -> None:
    prefix = "EAVC - HUB/" if wrapped else ""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{prefix}EAVC - HUB.exe", b"hub-binary")
        archive.writestr(f"{prefix}_internal/python.dll", b"runtime")
        archive.writestr(f"{prefix}EAVC Updater.exe", b"updater-binary")


def test_publish_release_writes_checked_manifest(tmp_path: Path) -> None:
    package = tmp_path / "hub-2.1.zip"
    _hub_package(package, wrapped=True)

    release = publish_release(
        tmp_path,
        package=package.name,
        revision="2.1.0",
        title="Исправление синхронизации",
        notes="Пилотный выпуск",
    )

    restored = read_current_release(tmp_path)
    assert restored["revision"] == "2.1.0"
    assert restored["sha256"] == release["sha256"]
    assert restored["unpacked_bytes"] > 0
    assert release_signature(restored, "test-key") != release_signature(restored, "other-key")


def test_publish_release_rejects_incomplete_package(tmp_path: Path) -> None:
    package = tmp_path / "broken.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("EAVC - HUB.exe", b"not enough")

    with pytest.raises(ValueError, match="полный пакет"):
        publish_release(
            tmp_path,
            package=package.name,
            revision="2.1.0",
            title="Broken",
            notes="",
        )


def test_publish_release_rejects_mixed_package_roots(tmp_path: Path) -> None:
    package = tmp_path / "mixed.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("EAVC - HUB.exe", b"hub")
        archive.writestr("other/_internal/runtime.dll", b"runtime")
        archive.writestr("EAVC Updater.exe", b"updater")

    with pytest.raises(ValueError, match="одной папке"):
        publish_release(
            tmp_path,
            package=package.name,
            revision="2.1.0",
            title="Broken",
            notes="",
        )


def test_malformed_current_manifest_is_not_served(tmp_path: Path) -> None:
    (tmp_path / "current.json").write_text(
        json.dumps({"revision": "2.1", "sha256": "x" * 64, "size_bytes": "bad"}),
        encoding="utf-8",
    )
    assert read_current_release(tmp_path) == {}
