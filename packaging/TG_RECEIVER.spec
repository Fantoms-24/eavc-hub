# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

# Spec лежит в packaging/, корень проекта — на уровень выше.
project_dir = Path(globals().get("specpath", os.getcwd())).resolve().parent

a = Analysis(
    [str(project_dir / 'telegram_receiver_main.py')],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[(str(project_dir / 'config' / 'telegram_receiver_config.example.json'), '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TG_RECEIVER',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
