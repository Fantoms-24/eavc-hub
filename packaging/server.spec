# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata, collect_all

block_cipher = None

hiddenimports = []
hiddenimports += collect_submodules("flask_login")

_numpy_datas, _numpy_binaries, _numpy_hiddenimports = collect_all("numpy")
hiddenimports += _numpy_hiddenimports

hiddenimports += [
    "web_portal.app_perf",
    "web_portal.app_runtime_caches",
    "web_portal.positions",
    "web_portal.lib.wsgi_server",
    "waitress",
]
hiddenimports += collect_submodules("web_portal.webapp")

# PyInstaller передаёт в spec переменную specpath (директория spec-файла).
# Spec лежит в packaging/, корень проекта — на уровень выше.
project_dir = Path(globals().get("specpath", os.getcwd())).resolve().parent

a = Analysis(
    [str(project_dir / "server_main.py")],
    pathex=[str(project_dir)],
    binaries=_numpy_binaries,
    datas=[
        (str(project_dir / "templates"), "templates"),
        (str(project_dir / "static"), "static"),
        (str(project_dir / "config" / "server_config.example.json"), "."),
    ] + _numpy_datas + copy_metadata("werkzeug") + copy_metadata("flask") + copy_metadata("numpy"),
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'tkinter.*'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Иконка exe: файл icon.ico лежит в packaging/ (рядом со spec-файлами).
_icon_path = project_dir / "packaging" / "icon.ico"
_exe_icon = str(_icon_path) if _icon_path.is_file() else None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EAVC - SERVER",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    icon=_exe_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="EAVC - SERVER",
)

