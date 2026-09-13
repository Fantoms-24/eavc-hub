# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

block_cipher = None
# Spec лежит в packaging/, корень проекта — на уровень выше.
project_dir = Path(globals().get("specpath", os.getcwd())).resolve().parent

a = Analysis(
    [str(project_dir / "telegram_receiver_main.py")],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[
        (str(project_dir / "config" / "telegram_receiver_config.example.json"), "."),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "tkinter.*"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TG_RECEIVER",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TG_RECEIVER",
)
