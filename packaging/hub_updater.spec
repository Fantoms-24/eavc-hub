# -*- mode: python ; coding: utf-8 -*-
"""Минимальный отдельный updater: его нельзя блокировать заменой HUB.exe."""

from pathlib import Path

# ``specpath`` может быть рабочей директорией; ``SPEC`` — путь к spec-файлу.
project_dir = Path(globals().get("SPEC") or Path.cwd()).resolve().parent.parent

a = Analysis(
    [str(project_dir / "hub_updater_main.py")],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="EAVC Updater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon=str(project_dir / "packaging" / "icon.ico"),
)
