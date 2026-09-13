"""Безопасное хранение и публикация пакетов обновления HUB на SERVER.

Пакет — ZIP от сборки PyInstaller ``onedir``.  Сам файл кладётся оператором
в ``Update/`` рядом с SERVER.exe; в БД рабочие файлы пакета не попадают.
Опубликованный манифест пишется атомарно и содержит SHA-256, поэтому HUB
никогда не применяет недокачанный или подменённый ZIP.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MANIFEST_NAME = "current.json"
_REV_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MAX_TITLE_LEN = 160
_MAX_NOTES_LEN = 2_000
_MAX_UNPACKED_BYTES = 20 * 1024 * 1024 * 1024


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _safe_package_name(value: str) -> str:
    name = Path(str(value or "").strip()).name
    if not name or name != str(value or "").strip() or not name.lower().endswith(".zip"):
        raise ValueError("Выберите ZIP-файл из папки Update")
    return name


def _validate_zip(package_path: Path) -> None:
    """Проверяет структуру ZIP до публикации, не распаковывая его."""
    try:
        with zipfile.ZipFile(package_path) as archive:
            names = [info.filename.replace("\\", "/") for info in archive.infolist()]
            if not names:
                raise ValueError("ZIP-пакет пуст")
            for name in names:
                p = Path(name)
                if p.is_absolute() or ".." in p.parts:
                    raise ValueError("ZIP содержит недопустимый путь")
            package_roots = []
            for name in names:
                if name == "EAVC - HUB.exe":
                    package_roots.append("")
                elif name.endswith("/EAVC - HUB.exe"):
                    package_roots.append(name[: -len("EAVC - HUB.exe")])
            valid_root = next(
                (
                    root
                    for root in package_roots
                    if (
                        any(name.startswith(f"{root}_internal/") for name in names)
                        and f"{root}EAVC Updater.exe" in names
                    )
                ),
                None,
            )
            if valid_root is None:
                raise ValueError(
                    "Нужен полный пакет HUB: EAVC - HUB.exe, _internal и EAVC Updater.exe в одной папке"
                )
    except zipfile.BadZipFile as exc:
        raise ValueError("Файл не является корректным ZIP-пакетом") from exc


def _zip_unpacked_bytes(package_path: Path) -> int:
    """Размер распаковки для проверки свободного места на HUB."""
    try:
        with zipfile.ZipFile(package_path) as archive:
            total = sum(max(0, int(info.file_size)) for info in archive.infolist())
            if total > _MAX_UNPACKED_BYTES:
                raise ValueError("Распакованный пакет HUB превышает 20 ГиБ")
            return total
    except zipfile.BadZipFile as exc:
        raise ValueError("Файл не является корректным ZIP-пакетом") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as src:
        while chunk := src.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def list_release_packages(directory: Path) -> list[dict[str, Any]]:
    base = Path(directory).resolve()
    base.mkdir(parents=True, exist_ok=True)
    packages: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            stat = path.stat()
            _validate_zip(path)
            packages.append(
                {
                    "name": path.name,
                    "size_bytes": int(stat.st_size),
                    "unpacked_bytes": _zip_unpacked_bytes(path),
                    "modified_at": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "valid": True,
                }
            )
        except Exception as exc:
            packages.append({"name": path.name, "valid": False, "error": str(exc)})
    return packages


def _manifest_path(directory: Path) -> Path:
    return Path(directory).resolve() / MANIFEST_NAME


def read_current_release(directory: Path) -> dict[str, Any]:
    path = _manifest_path(directory)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    try:
        package = _safe_package_name(str(raw.get("package") or ""))
        revision = str(raw.get("revision") or "").strip()
        checksum = str(raw.get("sha256") or "").strip().lower()
        size_bytes = max(0, int(raw.get("size_bytes") or 0))
        unpacked_bytes = max(0, int(raw.get("unpacked_bytes") or 0))
        if not _REV_RE.fullmatch(revision) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            return {}
        package_path = Path(directory).resolve() / package
        if not package_path.is_file():
            return {}
    except Exception:
        return {}
    return {
        "revision": revision,
        "title": str(raw.get("title") or "").strip(),
        "notes": str(raw.get("notes") or "").strip(),
        "package": package,
        "sha256": checksum,
        "size_bytes": size_bytes,
        "unpacked_bytes": unpacked_bytes,
        "published_at": str(raw.get("published_at") or "").strip(),
    }


def publish_release(
    directory: Path,
    *,
    package: str,
    revision: str,
    title: str,
    notes: str,
) -> dict[str, Any]:
    """Проверяет ZIP и атомарно публикует его как текущую версию."""
    base = Path(directory).resolve()
    base.mkdir(parents=True, exist_ok=True)
    package_name = _safe_package_name(package)
    version = str(revision or "").strip()
    if not _REV_RE.fullmatch(version):
        raise ValueError("Версия: буквы, цифры, точка, дефис и подчёркивание; до 64 символов")
    clean_title = str(title or "").strip()
    clean_notes = str(notes or "").strip()
    if not clean_title:
        raise ValueError("Укажите название обновления")
    if len(clean_title) > _MAX_TITLE_LEN or len(clean_notes) > _MAX_NOTES_LEN:
        raise ValueError("Название или описание слишком длинные")
    package_path = (base / package_name).resolve()
    if package_path.parent != base or not package_path.is_file():
        raise ValueError("Пакет не найден в папке Update")
    _validate_zip(package_path)
    manifest = {
        "revision": version,
        "title": clean_title,
        "notes": clean_notes,
        "package": package_name,
        "sha256": sha256_file(package_path),
        "size_bytes": int(package_path.stat().st_size),
        "unpacked_bytes": _zip_unpacked_bytes(package_path),
        "published_at": _utc_now(),
    }
    target = _manifest_path(base)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)
    return manifest


def release_package_path(directory: Path, package: str) -> Path:
    base = Path(directory).resolve()
    package_name = _safe_package_name(package)
    result = (base / package_name).resolve()
    if result.parent != base or not result.is_file():
        raise FileNotFoundError("Пакет обновления не найден")
    return result


def release_signature(release: dict[str, Any], sync_key: str) -> str:
    """HMAC манифеста: HUB проверяет, что его опубликовал именно SERVER."""
    body = json.dumps(release or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hmac.new(
        str(sync_key or "").encode("utf-8"), body.encode("utf-8"), hashlib.sha256
    ).hexdigest()
