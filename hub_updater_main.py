"""Независимый Windows-updater для сборки HUB (PyInstaller onedir).

Его нельзя заменять работающим HUB.exe, поэтому updater запускается отдельным
EXE, ждёт штатного завершения HUB и только потом меняет ``EAVC - HUB.exe`` и
``_internal``. Рабочая папка ``data-hub`` и конфигурация не затрагиваются.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib import request as urlrequest


APP_EXE = "EAVC - HUB.exe"
APP_INTERNAL = "_internal"


def _write_status(data_dir: Path, payload: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / "update_status.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok and code.value == 259)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return False


def _zip_root(archive: zipfile.ZipFile) -> str:
    names = [info.filename.replace("\\", "/") for info in archive.infolist()]
    for name in names:
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("Недопустимый путь внутри ZIP")
    for name in names:
        if name == APP_EXE:
            return ""
    roots = {name.split("/", 1)[0] for name in names if "/" in name}
    for root in roots:
        if f"{root}/{APP_EXE}" in names:
            return f"{root}/"
    raise ValueError("В ZIP нет EAVC - HUB.exe")


def _extract_package(package: Path, extract_to: Path) -> None:
    with zipfile.ZipFile(package) as archive:
        root = _zip_root(archive)
        for info in archive.infolist():
            source = info.filename.replace("\\", "/")
            if source.endswith("/"):
                continue
            if root and not source.startswith(root):
                continue
            relative = source[len(root) :] if root else source
            if not relative:
                continue
            destination = (extract_to / relative).resolve()
            if destination != extract_to and extract_to not in destination.parents:
                raise ValueError("Недопустимый путь распаковки")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, destination.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    if not (extract_to / APP_EXE).is_file() or not (extract_to / APP_INTERNAL).is_dir():
        raise ValueError("Пакет не содержит полный набор HUB")


def _move_to_backup(source: Path, backup: Path) -> None:
    if source.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists():
            if backup.is_dir():
                shutil.rmtree(backup)
            else:
                backup.unlink()
        shutil.move(str(source), str(backup))


def _wait_for_healthy_hub(proc: subprocess.Popen, port: int, timeout_sec: int = 45) -> None:
    """Подтверждает, что новый HUB действительно принял HTTP-запрос /health."""
    deadline = time.monotonic() + timeout_sec
    last_error = ""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("Новый HUB завершился до проверки готовности")
        try:
            with urlrequest.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                data = json.loads((response.read() or b"{}").decode("utf-8"))
            if isinstance(data, dict) and data.get("ok") is True:
                return
            last_error = "health вернул некорректный ответ"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.75)
    raise RuntimeError(f"Новый HUB не прошёл проверку /health: {last_error}")


def apply_update(args: argparse.Namespace) -> int:
    install_dir = Path(args.install_dir).resolve()
    data_dir = Path(args.data_dir).resolve()
    package = Path(args.package).resolve()
    revision = str(args.revision or "").strip()
    # Служебные ZIP и резервная копия лежат на том же диске, что и программа:
    # замена файлов остаётся атомарной в пределах тома и не трогает data-hub.
    state_dir = install_dir / ".eavc-update"
    _write_status(data_dir, {"state": "waiting", "revision": revision})
    deadline = time.monotonic() + max(15, min(int(args.wait_sec), 300))
    while _pid_is_running(int(args.parent_pid)) and time.monotonic() < deadline:
        time.sleep(0.5)
    if _pid_is_running(int(args.parent_pid)):
        _write_status(data_dir, {"state": "failed", "revision": revision, "error": "HUB не завершился вовремя"})
        return 2
    if not package.is_file():
        _write_status(data_dir, {"state": "failed", "revision": revision, "error": "Пакет обновления не найден"})
        return 3
    extract_dir = state_dir / f"extract-{revision}"
    rollback_dir = state_dir / f"rollback-{revision}"
    new_proc: subprocess.Popen | None = None
    try:
        shutil.rmtree(extract_dir, ignore_errors=True)
        extract_dir.mkdir(parents=True, exist_ok=True)
        _write_status(data_dir, {"state": "installing", "revision": revision})
        _extract_package(package, extract_dir)
        _move_to_backup(install_dir / APP_EXE, rollback_dir / APP_EXE)
        _move_to_backup(install_dir / APP_INTERNAL, rollback_dir / APP_INTERNAL)
        shutil.move(str(extract_dir / APP_EXE), str(install_dir / APP_EXE))
        shutil.move(str(extract_dir / APP_INTERNAL), str(install_dir / APP_INTERNAL))
        _write_status(data_dir, {"state": "health_check", "revision": revision})
        new_proc = subprocess.Popen([str(install_dir / APP_EXE)], cwd=str(install_dir))
        _wait_for_healthy_hub(new_proc, int(args.port))
        (data_dir / "hub_release.json").write_text(
            json.dumps({"revision": revision}, ensure_ascii=False), encoding="utf-8"
        )
        _write_status(data_dir, {"state": "completed", "revision": revision})
        return 0
    except Exception as exc:
        try:
            if new_proc is not None and new_proc.poll() is None:
                new_proc.terminate()
                try:
                    new_proc.wait(timeout=5)
                except Exception:
                    new_proc.kill()
                    new_proc.wait(timeout=5)
            for name in (APP_EXE, APP_INTERNAL):
                target = install_dir / name
                backup = rollback_dir / name
                if target.exists():
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                if backup.exists():
                    shutil.move(str(backup), str(target))
            if (install_dir / APP_EXE).is_file():
                subprocess.Popen([str(install_dir / APP_EXE)], cwd=str(install_dir))
        finally:
            _write_status(data_dir, {"state": "rolled_back", "revision": revision, "error": str(exc)})
        return 4
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-pid", required=True, type=int)
    parser.add_argument("--install-dir", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--wait-sec", default=90, type=int)
    parser.add_argument("--port", default=5000, type=int)
    return apply_update(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
