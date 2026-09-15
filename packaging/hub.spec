# -*- mode: python ; coding: utf-8 -*-

import os
import atexit
import shutil
import sys
import tempfile
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata, collect_all

block_cipher = None

# The repository folder may have any name (for example ``Copy``), while the
# application imports itself as ``web_portal``.  Give PyInstaller an explicit
# package alias so it never picks up a stale sibling folder named web_portal.
project_dir = Path(globals().get("SPEC") or os.getcwd()).resolve().parent.parent
_alias_root = Path(tempfile.mkdtemp(prefix="eavc-pyi-"))
_alias_pkg = _alias_root / "web_portal"
_alias_pkg.mkdir()
for _source in project_dir.glob("*.py"):
    shutil.copy2(_source, _alias_pkg / _source.name)
for _package_name in ("application", "lib", "webapp"):
    shutil.copytree(
        project_dir / _package_name,
        _alias_pkg / _package_name,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
_entry_script = _alias_root / "hub_main.py"
shutil.copy2(project_dir / "hub_main.py", _entry_script)
sys.path.insert(0, str(_alias_root))

def _cleanup_alias():
    shutil.rmtree(_alias_root, ignore_errors=True)

atexit.register(_cleanup_alias)

hiddenimports = []
hiddenimports += collect_submodules("flask_login")
hiddenimports += collect_submodules("telethon")

# ai_vector_recall → numpy (косинусный поиск по эмбеддингам)
_numpy_datas, _numpy_binaries, _numpy_hiddenimports = collect_all("numpy")
hiddenimports += _numpy_hiddenimports

hiddenimports += [
    "web_portal.app_perf",
    "web_portal.app_runtime_caches",
    "web_portal.positions",
    "web_portal.lib.wsgi_server",
    "web_portal.lib.telegram_user_service",
    "web_portal.lib.word_push",
    "waitress",
    "telethon",
]
hiddenimports += collect_submodules("web_portal.webapp")

a = Analysis(
    [str(_entry_script)],
    pathex=[str(_alias_root)],
    binaries=_numpy_binaries,
    datas=[
        (str(project_dir / "templates"), "templates"),
        (str(project_dir / "static"), "static"),
        (str(project_dir / "config" / "hub_config.example.json"), "."),
        (str(project_dir / "config" / "word_push_config.example.json"), "."),
    ] + _numpy_datas + copy_metadata("werkzeug") + copy_metadata("flask") + copy_metadata("numpy"),
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        # Exclude heavy ML/ASR stacks from HUB build.
        # They are optional in runtime and dramatically increase size/time.
        "torch",
        "torchaudio",
        "torchvision",
        "whisper",
        "openai_whisper",
        "transformers",
        "sentencepiece",
        "librosa",
        "soundfile",
        "_soundfile_data",
        "jiwer",
        # Scientific stack accidentally pulled from fat .venv-build (~200MB).
        # Compact HUB (like compact-2026-09-14) does not need these.
        "scipy",
        "sklearn",
        "scikit_learn",
        "scikit-learn",
        "llvmlite",
        "numba",
        "pandas",
        "matplotlib",
        "cv2",
        "opencv",
        "opencv-python",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Иконка exe: файл icon.ico лежит в packaging/ (рядом со spec-файлами).
# Если файла нет — сборка идёт без иконки.
_icon_path = project_dir / "packaging" / "icon.ico"
_exe_icon = str(_icon_path) if _icon_path.is_file() else None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EAVC - HUB",
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
    name="EAVC - HUB",
)
